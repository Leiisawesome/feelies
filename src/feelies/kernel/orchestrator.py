"""System orchestrator — the operating system of the quant platform.

Owns the macro state machine and coordinates all layers through the
deterministic micro-state pipeline.  Enforces the single-threaded,
sequential tick processing loop.

The orchestrator contains NO business logic.  It is a coordinator
that calls each layer in the deterministic order defined by the
micro-state machine.

System invariants enforced here (Section V):
  Inv-1: No order submission outside G5/G6.
         (Structurally guaranteed — micro loop only runs in TRADING_MODES,
          and ExecutionBackend determines what "submit" means per mode.)
  Inv-2: Micro loop must not advance past M0 outside {G4, G5, G6}.
         (Enforced by _run_pipeline gating on TRADING_MODES.)
  Inv-3: R4 (LOCKED) forbids transitions to G6 without passing G2.
         (Structurally guaranteed — G8 → G2 → G6.  run_live() also
          asserts risk level is NORMAL.)
  Inv-4: Every order terminally resolved before shutdown.
         (Enforced via OrderState SM tracking in _active_orders.)
  Inv-5: Replay in G4 reproduces identical state transitions.
         (order_id derived deterministically, not from uuid4.)

Key architectural invariants:
  - Backtest/live parity (platform inv 9): same _process_tick() in all modes
  - Deterministic replay (platform inv 5): micro-state transitions identical
  - No silent transitions: every state change logged via the bus
  - Fail-safe default (platform inv 11): risk breach → lockdown,
    mid-tick exception → DEGRADED
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from feelies.alpha.registry import AlphaRegistry

from feelies.bus.event_bus import EventBus
from feelies.core.clock import Clock
from feelies.core.config import Configuration
from feelies.core.errors import ConfigurationError
from feelies.core.events import (
    Alert,
    AlertSeverity,
    Event,
    KillSwitchActivation,
    MetricEvent,
    MetricType,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    PositionUpdate,
    RegimeState,
    RiskAction,
    RiskVerdict,
    Signal,
    SignalDirection,
    Side,
    StateTransition,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.core.state_machine import StateMachine, TransitionRecord
from feelies.execution.backend import ExecutionBackend
from feelies.execution.intent import (
    IntentTranslator,
    OrderIntent,
    SignalPositionTranslator,
    TradingIntent,
)
from feelies.execution.order_state import OrderState, create_order_state_machine
from feelies.features.engine import FeatureEngine
from feelies.ingestion.data_integrity import DataHealth
from feelies.ingestion.normalizer import MarketDataNormalizer
from feelies.kernel.macro import (
    TRADING_MODES,
    MacroState,
    create_macro_state_machine,
)
from feelies.kernel.micro import MicroState, create_micro_state_machine
from feelies.monitoring.alerting import AlertManager
from feelies.monitoring.kill_switch import KillSwitch
from feelies.monitoring.telemetry import MetricCollector
from feelies.portfolio.position_store import PositionStore
from feelies.risk.engine import RiskEngine
from feelies.risk.escalation import RiskLevel, create_risk_escalation_machine
from feelies.risk.position_sizer import BudgetBasedSizer, PositionSizer
from feelies.services.regime_engine import RegimeEngine
from feelies.signals.engine import SignalEngine
from feelies.storage.event_log import EventLog
from feelies.storage.feature_snapshot import FeatureSnapshotMeta, FeatureSnapshotStore
from feelies.storage.trade_journal import TradeJournal, TradeRecord

_TERMINAL_ORDER_STATES: frozenset[OrderState] = frozenset({
    OrderState.FILLED,
    OrderState.CANCELLED,
    OrderState.REJECTED,
    OrderState.EXPIRED,
})


class Orchestrator:
    """Central coordinator for the deterministic tick-processing pipeline.

    Lifecycle:
      1. __init__   — wire up all components
      2. boot()     — G0 → G1 → G2
      3. run_*()    — G2 → {G3|G4|G5|G6} → pipeline → G2
      4. shutdown() — → G9

    The orchestrator never inspects ``backend.mode`` to branch logic.
    Mode-specific behavior is confined to ExecutionBackend (platform inv 9).
    """

    def __init__(
        self,
        clock: Clock,
        bus: EventBus,
        backend: ExecutionBackend,
        feature_engine: FeatureEngine,
        signal_engine: SignalEngine,
        risk_engine: RiskEngine,
        position_store: PositionStore,
        event_log: EventLog,
        metric_collector: MetricCollector,
        normalizer: MarketDataNormalizer | None = None,
        alert_manager: AlertManager | None = None,
        kill_switch: KillSwitch | None = None,
        trade_journal: TradeJournal | None = None,
        feature_snapshots: FeatureSnapshotStore | None = None,
        regime_engine: RegimeEngine | None = None,
        intent_translator: IntentTranslator | None = None,
        position_sizer: PositionSizer | None = None,
        alpha_registry: "AlphaRegistry | None" = None,
        account_equity: Decimal = Decimal("100000"),
    ) -> None:
        self._clock = clock
        self._bus = bus
        self._backend = backend
        self._feature_engine = feature_engine
        self._signal_engine = signal_engine
        self._risk_engine = risk_engine
        self._positions = position_store
        self._event_log = event_log
        self._metrics = metric_collector
        self._normalizer = normalizer
        self._alert_manager = alert_manager
        self._kill_switch = kill_switch
        self._trade_journal = trade_journal
        self._feature_snapshots = feature_snapshots
        self._regime_engine = regime_engine
        self._intent_translator: IntentTranslator = (
            intent_translator if intent_translator is not None
            else SignalPositionTranslator()
        )
        self._position_sizer: PositionSizer = (
            position_sizer if position_sizer is not None
            else BudgetBasedSizer(regime_engine=regime_engine)
        )
        self._alpha_registry = alpha_registry
        self._account_equity = account_equity
        self._seq = SequenceGenerator()

        self._config: Configuration | None = None

        # Per-order lifecycle tracking for Inv-4 enforcement.
        # Maps order_id -> (OrderState SM, Side, OrderRequest).
        self._active_orders: dict[str, tuple[StateMachine[OrderState], Side, OrderRequest]] = {}

        # When True, market events arriving from the data source are
        # already present in the event log (replay mode).  Prevents
        # re-appending identical events during backtest replay.
        self._events_prelogged = False

        self._macro = create_macro_state_machine(clock)
        self._micro = create_micro_state_machine(clock)
        self._risk_escalation = create_risk_escalation_machine(clock)

        self._macro.on_transition(self._emit_state_transition)
        self._micro.on_transition(self._emit_state_transition)
        self._risk_escalation.on_transition(self._emit_state_transition)

        # Wire MetricCollector to receive MetricEvents from the bus.
        self._bus.subscribe(MetricEvent, self._on_metric_event)

        # Wire AlertManager to receive Alert events from the bus.
        if self._alert_manager is not None:
            self._bus.subscribe(Alert, self._on_alert_event)

    # ── Public state accessors ──────────────────────────────────────

    @property
    def macro_state(self) -> MacroState:
        return self._macro.state

    @property
    def micro_state(self) -> MicroState:
        return self._micro.state

    @property
    def risk_level(self) -> RiskLevel:
        return self._risk_escalation.state

    # ── Lifecycle: boot / run / shutdown ────────────────────────────

    def boot(self, config: Configuration) -> None:
        """G0 → G1 → G2  (happy path).

        Guard: CONFIG_VALIDATED requires all dependencies resolved.
        Guard: DATA_INTEGRITY_OK requires all streams verified.
        """
        try:
            config.validate()
            self._config = config
            self._macro.transition(
                MacroState.DATA_SYNC,
                trigger="CONFIG_VALIDATED",
            )
        except ConfigurationError as exc:
            self._macro.transition(
                MacroState.SHUTDOWN,
                trigger=f"CONFIG_ERROR:{exc}",
            )
            return

        if self._verify_data_integrity():
            self._macro.transition(
                MacroState.READY,
                trigger="DATA_INTEGRITY_OK",
            )
            self._restore_feature_snapshots()
        else:
            self._macro.transition(
                MacroState.DEGRADED,
                trigger="DATA_INTEGRITY_FAIL",
            )

    def run_backtest(self) -> None:
        """G2 → G4 → pipeline → G2.

        Guard: backtest config valid.
        """
        self._macro.assert_state(MacroState.READY)
        self._micro.reset(trigger="session_start:backtest")
        self._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")

        self._events_prelogged = True
        try:
            self._run_pipeline()
            if self._macro.state == MacroState.BACKTEST_MODE:
                self._macro.transition(
                    MacroState.READY,
                    trigger="BACKTEST_COMPLETE",
                )
        except Exception as exc:
            if self._macro.state == MacroState.BACKTEST_MODE:
                self._macro.transition(
                    MacroState.DEGRADED,
                    trigger=f"BACKTEST_INTEGRITY_FAIL:{type(exc).__name__}",
                )
            raise
        finally:
            self._events_prelogged = False

    def run_paper(self) -> None:
        """G2 → G5 → pipeline.

        Guard: broker sim connected.
        Post-pipeline: if macro is still G5, the data feed terminated
        unexpectedly — transition to DEGRADED.
        """
        self._macro.assert_state(MacroState.READY)
        self._micro.reset(trigger="session_start:paper")
        self._macro.transition(
            MacroState.PAPER_TRADING_MODE,
            trigger="CMD_PAPER_DEPLOY",
        )
        try:
            self._run_pipeline()
        except Exception as exc:
            if self._macro.state == MacroState.PAPER_TRADING_MODE:
                self._macro.transition(
                    MacroState.DEGRADED,
                    trigger=f"PAPER_PIPELINE_FAIL:{type(exc).__name__}",
                )
            raise
        if self._macro.state == MacroState.PAPER_TRADING_MODE:
            self._macro.transition(
                MacroState.DEGRADED,
                trigger="DATA_DRIFT_DETECTED:feed_terminated",
            )

    def run_live(self) -> None:
        """G2 → G6 → pipeline.

        Guard: human approval + risk audit pass.
        Inv-3: R4 (LOCKED) forbids this — must pass through G2 first,
        which is structurally guaranteed (G8 → G2 → G6).
        Post-pipeline: if macro is still G6, the data feed terminated
        unexpectedly — transition to DEGRADED.
        """
        self._macro.assert_state(MacroState.READY)
        if self._risk_escalation.state != RiskLevel.NORMAL:
            raise RuntimeError(
                f"Cannot enter LIVE: risk level is {self._risk_escalation.state.name}, "
                f"must be NORMAL"
            )
        self._micro.reset(trigger="session_start:live")
        self._macro.transition(
            MacroState.LIVE_TRADING_MODE,
            trigger="CMD_LIVE_DEPLOY",
        )
        try:
            self._run_pipeline()
        except Exception as exc:
            if self._macro.state == MacroState.LIVE_TRADING_MODE:
                self._macro.transition(
                    MacroState.DEGRADED,
                    trigger=f"LIVE_PIPELINE_FAIL:{type(exc).__name__}",
                )
            raise
        if self._macro.state == MacroState.LIVE_TRADING_MODE:
            self._macro.transition(
                MacroState.DEGRADED,
                trigger="DATA_DRIFT_DETECTED:feed_terminated",
            )

    def run_research(self, job: Callable[[], None]) -> None:
        """G2 → G3 → job() → G2.

        Research mode does not run the tick pipeline.  The caller
        provides a job (backtest variant, data exploration, etc.)
        that executes within the RESEARCH_MODE macro state.
        """
        self._macro.assert_state(MacroState.READY)
        self._macro.transition(MacroState.RESEARCH_MODE, trigger="CMD_RESEARCH")
        try:
            job()
            if self._macro.state == MacroState.RESEARCH_MODE:
                self._macro.transition(
                    MacroState.READY,
                    trigger="JOB_COMPLETE",
                )
        except Exception as exc:
            if self._macro.state == MacroState.RESEARCH_MODE:
                self._macro.transition(
                    MacroState.DEGRADED,
                    trigger=f"CRITICAL_ERROR:{type(exc).__name__}",
                )
            raise

    def halt(self) -> None:
        """CMD_STOP: any trading mode → G2."""
        if self._macro.state in TRADING_MODES:
            self._macro.transition(MacroState.READY, trigger="CMD_STOP")

    def recover_from_degraded(self) -> bool:
        """G7 → G2 on recovery validation.  Returns True if successful."""
        self._macro.assert_state(MacroState.DEGRADED)
        if self._verify_data_integrity():
            self._macro.transition(
                MacroState.READY,
                trigger="RECOVERY_VALIDATED",
            )
            return True
        return False

    def unlock_from_lockdown(self, *, audit_token: str) -> None:
        """G8 → G2.  Human-authorized only.

        Guard: positions = 0, audit logged (Inv-4 for lockdown recovery).

        Transition ordering: macro first, then risk.  If the macro
        transition succeeded but risk failed (both are structurally
        valid, so failure is near-impossible), macro at READY with
        risk at LOCKED is fail-safe — run_live() guard blocks entry,
        and paper would re-lock on first FORCE_FLATTEN.  The reverse
        (risk at NORMAL, macro at RISK_LOCKDOWN) would break the
        retry path because the next unlock_from_lockdown attempt
        would try R4→R0 from R0, raising IllegalTransition.
        """
        self._macro.assert_state(MacroState.RISK_LOCKDOWN)

        exposure = self._positions.total_exposure()
        if exposure != Decimal("0"):
            raise RuntimeError(
                f"Cannot unlock: total exposure is {exposure}, must be 0 "
                f"(FORCED_FLATTEN_COMPLETE guard)"
            )

        self._macro.transition(
            MacroState.READY,
            trigger=f"FORCED_FLATTEN_COMPLETE:audit:{audit_token}",
        )
        self._risk_escalation.transition(
            RiskLevel.NORMAL,
            trigger=f"human_override_audit:{audit_token}",
        )

    def reset_risk_escalation(self, *, audit_token: str) -> None:
        """Human-authorized reset of risk escalation from any intermediate level.

        Used when _escalate_risk() was interrupted (callback exception)
        and the risk SM is stranded at WARNING, BREACH_DETECTED, or
        FORCED_FLATTEN while macro has recovered to DEGRADED or READY.

        Invariant 11: loosening safety controls requires human
        re-authorization — enforced via mandatory audit_token.
        """
        if self._risk_escalation.state == RiskLevel.NORMAL:
            return
        if self._risk_escalation.state == RiskLevel.LOCKED:
            raise RuntimeError(
                "Risk is LOCKED — use unlock_from_lockdown() instead"
            )
        if self._macro.state in TRADING_MODES:
            raise RuntimeError(
                "Cannot reset risk during active trading — halt first"
            )
        self._risk_escalation.reset(
            trigger=f"human_risk_reset:{audit_token}",
        )

    def shutdown(self) -> None:
        """→ G9 (terminal).

        Inv-4: all orders must be terminally resolved before shutdown.
        Pending orders are surfaced as a WARNING alert but do not
        block shutdown — the operator investigates post-mortem.
        """
        self._checkpoint_feature_snapshots()
        pending = [
            oid for oid, (sm, _, _) in self._active_orders.items()
            if sm.state not in _TERMINAL_ORDER_STATES
        ]
        if pending:
            self._bus.publish(Alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id="",
                sequence=self._seq.next(),
                severity=AlertSeverity.WARNING,
                layer="kernel",
                alert_name="pending_orders_at_shutdown",
                message=(
                    f"Inv-4 violation: {len(pending)} order(s) not terminally "
                    f"resolved at shutdown"
                ),
                context={"order_ids": pending},
            ))

        if self._macro.can_transition(MacroState.SHUTDOWN):
            self._macro.transition(MacroState.SHUTDOWN, trigger="CMD_SHUTDOWN")
        self._metrics.flush()

    # ── Pipeline: the deterministic tick loop ───────────────────────

    def _run_pipeline(self) -> None:
        """Execute the deterministic micro-state loop over all market events.

        Inv-2: breaks when macro state leaves TRADING_MODES.

        Dispatches by event type: NBBOQuote drives the full signal
        pipeline; Trade events are logged and published for
        observability but do not trigger signal evaluation.
        """
        for event in self._backend.market_data.events():
            if self._macro.state not in TRADING_MODES:
                break
            if isinstance(event, NBBOQuote):
                self._process_tick(event)
            elif isinstance(event, Trade):
                self._process_trade(event)

    def _process_trade(self, trade: Trade) -> None:
        """Log, publish, and forward a trade event to the feature engine.

        Trades update feature state (e.g., volume clustering, trade
        arrival rate) but do not trigger signal evaluation.  Updated
        feature values feed into the next quote-driven tick.
        """
        if not self._events_prelogged:
            self._event_log.append(trade)
        self._bus.publish(trade)

        process_trade_fn = getattr(self._feature_engine, "process_trade", None)
        if process_trade_fn is not None:
            process_trade_fn(trade)

    def _process_tick(self, quote: NBBOQuote) -> None:
        """Process a single tick through the full micro-state pipeline.

        This method is IDENTICAL in G4, G5, and G6.  The only
        mode-specific behavior is inside ExecutionBackend (platform inv 9).

        Micro-state sequence (formal spec Section II):
          M0 → M1 → M2 → M3 → M4 → M5 →
            (risk fail)         → [G8, pipeline aborts]
            (pass, no order)    → M10 → M0
            (pass, order)       → M6 →
              (check_order fail)  → M10 → M0
              (check_order pass)  → M7 → M8 → M9 → M10 → M0

        Exception handling: if any step throws, the micro SM is reset
        to M0 and macro transitions to DEGRADED.  This prevents the
        micro SM from being stranded mid-pipeline, which would make
        the next tick's M0→M1 transition illegal (platform inv 11:
        errors resolve to reduced exposure, never undefined state).
        """
        cid = quote.correlation_id
        try:
            self._process_tick_inner(quote)
        except Exception as exc:
            self._handle_tick_failure(cid, exc)

    def _handle_tick_failure(self, cid: str, original: Exception) -> None:
        """Recover micro SM and degrade macro after a tick-processing failure.

        The handler itself must not throw — if reset() or the macro
        transition fails, we still degrade to the safest reachable
        state.  The original exception's type name is captured in the
        trigger for provenance (invariant 13).
        """
        exc_name = type(original).__name__

        try:
            self._micro.reset(
                trigger=f"pipeline_abort:{exc_name}",
                correlation_id=cid,
            )
        except Exception:
            pass

        try:
            if (
                self._macro.state in TRADING_MODES
                and self._macro.can_transition(MacroState.DEGRADED)
            ):
                self._macro.transition(
                    MacroState.DEGRADED,
                    trigger=f"EXECUTION_DRIFT_DETECTED:{exc_name}",
                    correlation_id=cid,
                )
        except Exception:
            pass

    def _process_tick_inner(self, quote: NBBOQuote) -> None:
        """Core tick-processing logic.  Separated from _process_tick
        so the exception handler has a clean boundary.
        """
        cid = quote.correlation_id
        t_wall_start = time.perf_counter_ns()
        self._tick_timings: dict[str, int] = {}

        # ── Kill switch gate (W-2) ─────────────────────────────
        if self._kill_switch is not None and self._kill_switch.is_active:
            if self._macro.state in TRADING_MODES:
                if self._macro.can_transition(MacroState.DEGRADED):
                    self._macro.transition(
                        MacroState.DEGRADED,
                        trigger="KILL_SWITCH_ACTIVE",
                        correlation_id=cid,
                    )
            return

        # ── Runtime data integrity check (W-6) ─────────────────
        if self._normalizer is not None:
            symbol_health = self._normalizer.health(quote.symbol)
            if symbol_health == DataHealth.CORRUPTED:
                if self._macro.can_transition(MacroState.DEGRADED):
                    self._macro.transition(
                        MacroState.DEGRADED,
                        trigger=f"DATA_CORRUPTED:{quote.symbol}",
                        correlation_id=cid,
                    )
                return

        # ── M0 → M1: MARKET_EVENT_RECEIVED ─────────────────────
        self._micro.transition(
            MicroState.MARKET_EVENT_RECEIVED,
            trigger="tick_arrived",
            correlation_id=cid,
        )
        if not self._events_prelogged:
            self._event_log.append(quote)
        self._bus.publish(quote)

        # ── M1 → M2: STATE_UPDATE ──────────────────────────────
        self._micro.transition(
            MicroState.STATE_UPDATE,
            trigger="event_logged",
            correlation_id=cid,
        )
        self._update_regime(quote, cid)

        # ── M2 → M3: FEATURE_COMPUTE ───────────────────────────
        self._micro.transition(
            MicroState.FEATURE_COMPUTE,
            trigger="state_updated",
            correlation_id=cid,
        )
        t0 = time.perf_counter_ns()
        features = self._feature_engine.update(quote)
        self._tick_timings["feature_compute_ns"] = time.perf_counter_ns() - t0
        self._bus.publish(features)

        # ── M3 → M4: SIGNAL_EVALUATE ───────────────────────────
        self._micro.transition(
            MicroState.SIGNAL_EVALUATE,
            trigger="features_computed",
            correlation_id=cid,
        )
        t0 = time.perf_counter_ns()
        signal = self._signal_engine.evaluate(features)
        self._tick_timings["signal_evaluate_ns"] = time.perf_counter_ns() - t0

        if signal is None:
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="no_signal_this_tick",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        self._bus.publish(signal)

        # ── Position sizing: compute target quantity from risk budget ──
        target_qty = self._compute_target_quantity(signal, quote)

        # ── Intent translation: Signal x Position → OrderIntent ──
        current_position = self._positions.get(signal.symbol)
        intent = self._intent_translator.translate(signal, current_position, target_qty)

        if intent.intent == TradingIntent.NO_ACTION:
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="intent_no_action",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        # ── M4 → M5: RISK_CHECK ────────────────────────────────
        self._micro.transition(
            MicroState.RISK_CHECK,
            trigger="signal_evaluated",
            correlation_id=cid,
        )
        t0 = time.perf_counter_ns()
        verdict = self._risk_engine.check_signal(signal, self._positions)
        self._tick_timings["risk_check_ns"] = time.perf_counter_ns() - t0
        self._bus.publish(verdict)

        # ── M5 branch: risk fail → cross-machine to G8 ─────────
        if verdict.action == RiskAction.FORCE_FLATTEN:
            if self._macro.can_transition(MacroState.RISK_LOCKDOWN):
                self._escalate_risk(cid)
                self._micro.reset(
                    trigger="pipeline_abort:risk_lockdown",
                    correlation_id=cid,
                )
                return
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="risk_force_flatten_simulated",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        # ── M5 branch: risk rejected → M10 ─────────────────────
        if verdict.action == RiskAction.REJECT:
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="risk_reject_no_order",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        # ── M5 → M6: risk pass, order warranted ────────────────
        if verdict.action not in (RiskAction.ALLOW, RiskAction.SCALE_DOWN):
            raise ValueError(
                f"Unhandled RiskAction at order gate: {verdict.action!r}. "
                f"Fail-safe: aborting order path."
            )

        self._micro.transition(
            MicroState.ORDER_DECISION,
            trigger="risk_pass_order_warranted",
            correlation_id=cid,
        )
        order = self._build_order_from_intent(intent, verdict, cid)

        # ── M6: Pre-submission risk check on concrete order ─────
        order_verdict = self._risk_engine.check_order(order, self._positions)
        self._bus.publish(order_verdict)

        if order_verdict.action == RiskAction.FORCE_FLATTEN:
            if self._macro.can_transition(MacroState.RISK_LOCKDOWN):
                self._escalate_risk(cid)
                self._micro.reset(
                    trigger="pipeline_abort:check_order_lockdown",
                    correlation_id=cid,
                )
                return
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="check_order_force_flatten_simulated",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        if order_verdict.action == RiskAction.REJECT:
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger=f"check_order_rejected:{order_verdict.reason}",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        if order_verdict.action == RiskAction.SCALE_DOWN:
            scaled_qty = max(1, round(order.quantity * order_verdict.scaling_factor))
            if scaled_qty != order.quantity:
                order = replace(order, quantity=scaled_qty)

        # Exhaustiveness guard (Inv-11): mirror M5's guard.
        # Unknown RiskActions at the check_order gate must never
        # fall through to order submission.
        if order_verdict.action not in (RiskAction.ALLOW, RiskAction.SCALE_DOWN):
            raise ValueError(
                f"Unhandled RiskAction at check_order gate: "
                f"{order_verdict.action!r}. "
                f"Fail-safe: aborting order path."
            )

        # ── Track order lifecycle (Inv-4) ───────────────────────
        self._track_order(order.order_id, order.side, order)

        # ── M6 → M7: ORDER_SUBMIT ──────────────────────────────
        self._micro.transition(
            MicroState.ORDER_SUBMIT,
            trigger="order_constructed",
            correlation_id=cid,
        )
        self._transition_order(order.order_id, OrderState.SUBMITTED, "submitted")
        self._backend.order_router.submit(order)
        self._bus.publish(order)

        # ── M7 → M8: ORDER_ACK ─────────────────────────────────
        self._micro.transition(
            MicroState.ORDER_ACK,
            trigger="order_submitted",
            correlation_id=cid,
        )
        acks = self._backend.order_router.poll_acks()
        for ack in acks:
            self._bus.publish(ack)
            self._apply_ack_to_order(ack)

        # ── M8 → M9: POSITION_UPDATE ───────────────────────────
        self._micro.transition(
            MicroState.POSITION_UPDATE,
            trigger="order_acknowledged",
            correlation_id=cid,
        )
        self._reconcile_fills(acks, cid)

        # ── M9 → M10: LOG_AND_METRICS ──────────────────────────
        self._micro.transition(
            MicroState.LOG_AND_METRICS,
            trigger="position_updated",
            correlation_id=cid,
        )
        self._finalize_tick(t_wall_start, cid)

    # ── Helpers ─────────────────────────────────────────────────────

    def _finalize_tick(self, t_wall_start_ns: int, correlation_id: str) -> None:
        """Emit tick latency and per-segment timing metrics, then M10 → M0."""
        latency_ns = time.perf_counter_ns() - t_wall_start_ns
        now_ns = self._clock.now_ns()

        self._bus.publish(MetricEvent(
            timestamp_ns=now_ns,
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            layer="kernel",
            name="tick_to_decision_latency_ns",
            value=float(latency_ns),
            metric_type=MetricType.HISTOGRAM,
        ))

        timings = getattr(self, "_tick_timings", {})
        for name, value in timings.items():
            self._bus.publish(MetricEvent(
                timestamp_ns=now_ns,
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                layer="kernel",
                name=name,
                value=float(value),
                metric_type=MetricType.HISTOGRAM,
            ))
        self._micro.transition(
            MicroState.WAITING_FOR_MARKET_EVENT,
            trigger="tick_complete",
            correlation_id=correlation_id,
        )

    def _update_regime(self, quote: NBBOQuote, correlation_id: str) -> None:
        """Update platform-level RegimeEngine and publish RegimeState event.

        Called at M2 (STATE_UPDATE) — single-writer point for regime
        state.  Downstream consumers (feature code, risk engine,
        position sizer) read cached state; they never update.
        """
        if self._regime_engine is None:
            return
        posteriors = self._regime_engine.posterior(quote)
        dominant_idx = max(range(len(posteriors)), key=lambda i: posteriors[i])
        state_names = tuple(self._regime_engine.state_names)
        self._bus.publish(RegimeState(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            symbol=quote.symbol,
            engine_name=type(self._regime_engine).__name__,
            state_names=state_names,
            posteriors=tuple(posteriors),
            dominant_state=dominant_idx,
            dominant_name=state_names[dominant_idx] if dominant_idx < len(state_names) else "unknown",
        ))

    def _escalate_risk(self, correlation_id: str) -> None:
        """Escalate through R0 → R1 → R2 → R3 → R4 → macro G8.

        Monotonically tightens safety (platform inv 11).  Once R1
        (WARNING) is entered, de-escalation is impossible without
        completing the full cycle to R4 and human unlock.

        At R3 (FORCED_FLATTEN) we attempt to close all non-zero
        positions via emergency market orders before transitioning
        to R4 (LOCKED).
        """
        level = self._risk_escalation.state

        if level == RiskLevel.NORMAL:
            self._risk_escalation.transition(
                RiskLevel.WARNING,
                trigger="risk_threshold_approaching",
                correlation_id=correlation_id,
            )
            level = RiskLevel.WARNING

        if level == RiskLevel.WARNING:
            self._risk_escalation.transition(
                RiskLevel.BREACH_DETECTED,
                trigger="risk_breach_confirmed",
                correlation_id=correlation_id,
            )
            level = RiskLevel.BREACH_DETECTED

        if level == RiskLevel.BREACH_DETECTED:
            self._risk_escalation.transition(
                RiskLevel.FORCED_FLATTEN,
                trigger="forced_flatten_initiated",
                correlation_id=correlation_id,
            )
            level = RiskLevel.FORCED_FLATTEN

        if level == RiskLevel.FORCED_FLATTEN:
            self._emergency_flatten_all(correlation_id)
            self._risk_escalation.transition(
                RiskLevel.LOCKED,
                trigger="positions_zero_flatten_complete",
                correlation_id=correlation_id,
            )

        if self._kill_switch is not None:
            self._kill_switch.activate(
                reason="risk_escalation_lockdown",
                activated_by="orchestrator",
            )
            self._bus.publish(KillSwitchActivation(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                reason="risk_escalation_lockdown",
                activated_by="orchestrator",
            ))

        self._macro.transition(
            MacroState.RISK_LOCKDOWN,
            trigger="RISK_BREACH",
            correlation_id=correlation_id,
        )

    def _emergency_flatten_all(self, correlation_id: str) -> None:
        """Submit market orders to flatten all non-zero positions.

        Emergency path -- bypasses the micro SM (which will be reset
        immediately after).  Individual order failures are logged but
        do not prevent the escalation to LOCKED (Inv-11: fail-safe).
        """
        positions = self._positions.all_positions()
        for symbol, pos in positions.items():
            if pos.quantity == 0:
                continue
            side = Side.SELL if pos.quantity > 0 else Side.BUY
            qty = abs(pos.quantity)
            seq = self._seq.next()
            order_id = hashlib.sha256(
                f"emergency_flatten:{correlation_id}:{symbol}:{seq}".encode()
            ).hexdigest()[:16]

            order = OrderRequest(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=correlation_id,
                sequence=seq,
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=qty,
                strategy_id="emergency_flatten",
            )

            try:
                self._track_order(order_id, side, order)
                self._transition_order(order_id, OrderState.SUBMITTED, "emergency_flatten")
                self._backend.order_router.submit(order)
                self._bus.publish(order)
                acks = self._backend.order_router.poll_acks()
                for ack in acks:
                    self._bus.publish(ack)
                    self._apply_ack_to_order(ack)
                self._reconcile_fills(acks, correlation_id)
            except Exception:
                logger.exception(
                    "Emergency flatten failed for %s (qty=%d) -- "
                    "position may remain open at LOCKED",
                    symbol, pos.quantity,
                )

    def _compute_target_quantity(
        self,
        signal: Signal,
        quote: NBBOQuote,
    ) -> int | None:
        """Use PositionSizer + AlphaRegistry to compute target quantity.

        Returns None if the registry is not available, letting the
        IntentTranslator fall back to its default.
        """
        if self._alpha_registry is None:
            return None

        try:
            alpha = self._alpha_registry.get(signal.strategy_id)
        except KeyError:
            return None

        risk_budget = alpha.manifest.risk_budget
        mid_price = (quote.bid + quote.ask) / Decimal(2)
        if mid_price <= 0:
            return 0

        return self._position_sizer.compute_target_quantity(
            signal=signal,
            risk_budget=risk_budget,
            symbol_price=mid_price,
            account_equity=self._account_equity,
        )

    def _build_order_from_intent(
        self,
        intent: OrderIntent,
        verdict: RiskVerdict,
        correlation_id: str,
    ) -> OrderRequest:
        """Construct an OrderRequest from an OrderIntent.

        order_id is derived from correlation_id + sequence via SHA-256
        so that replay of identical events produces identical order IDs
        (invariant 5).  uuid4 is forbidden here.

        The intent's ``target_quantity`` is the pre-computed quantity
        from the IntentTranslator (which may include position sizer
        output).  ``verdict.scaling_factor`` is applied on top for
        risk-driven scaling.
        """
        side = self._side_from_intent(intent)
        seq = self._seq.next()
        order_id = hashlib.sha256(
            f"{correlation_id}:{seq}".encode()
        ).hexdigest()[:16]

        quantity = max(1, round(intent.target_quantity * verdict.scaling_factor))

        return OrderRequest(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            sequence=seq,
            order_id=order_id,
            symbol=intent.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            strategy_id=intent.strategy_id,
        )

    @staticmethod
    def _side_from_intent(intent: OrderIntent) -> Side:
        """Derive order Side from TradingIntent."""
        if intent.intent in (
            TradingIntent.ENTRY_LONG,
            TradingIntent.REVERSE_SHORT_TO_LONG,
        ):
            return Side.BUY

        if intent.intent in (
            TradingIntent.ENTRY_SHORT,
            TradingIntent.REVERSE_LONG_TO_SHORT,
        ):
            return Side.SELL

        if intent.intent == TradingIntent.EXIT:
            return Side.SELL if intent.current_quantity > 0 else Side.BUY

        if intent.intent == TradingIntent.SCALE_UP:
            return Side.BUY if intent.current_quantity >= 0 else Side.SELL

        raise ValueError(
            f"Cannot determine Side for intent {intent.intent!r}. "
            f"Fail-safe: aborting order construction."
        )

    # ── Order lifecycle tracking (Inv-4) ────────────────────────────

    def cancel_order(self, order_id: str, *, reason: str = "operator") -> bool:
        """Request cancellation of an active order.

        Transitions the order SM: ACKNOWLEDGED → CANCEL_REQUESTED.
        Only orders in ACKNOWLEDGED state can be cancel-requested;
        SUBMITTED orders have not yet been confirmed by the broker
        so cancellation is premature, and PARTIALLY_FILLED orders
        have restricted transitions per the order SM spec.

        Returns True if the cancel request was accepted, False if the
        order is in a state that doesn't allow cancel requests.
        Terminal orders (FILLED, CANCELLED, REJECTED, EXPIRED) are
        no-ops that return False.
        """
        if order_id not in self._active_orders:
            return False
        sm = self._active_orders[order_id][0]
        if not sm.can_transition(OrderState.CANCEL_REQUESTED):
            return False
        sm.transition(
            OrderState.CANCEL_REQUESTED,
            trigger=f"cancel_requested:{reason}",
        )
        return True

    def _track_order(self, order_id: str, side: Side, order: OrderRequest) -> None:
        """Create an OrderState SM for a new order."""
        sm = create_order_state_machine(order_id, self._clock)
        sm.on_transition(self._emit_state_transition)
        self._active_orders[order_id] = (sm, side, order)

    def _transition_order(
        self,
        order_id: str,
        target: OrderState,
        trigger: str,
    ) -> None:
        """Transition an order's state machine."""
        if order_id in self._active_orders:
            sm = self._active_orders[order_id][0]
            sm.transition(target, trigger=trigger)

    def _apply_ack_to_order(self, ack: OrderAck) -> None:
        """Update an order's SM based on a broker acknowledgement.

        Uses typed ``OrderAckStatus`` enum — exhaustive matching ensures
        every status is handled explicitly (invariant 7, hard rule 2).
        When a valid status cannot be applied because the order SM is
        in an incompatible state, an alert is emitted instead of
        silently dropping the ack (invariant 13: full provenance).
        """
        if ack.order_id not in self._active_orders:
            self._bus.publish(Alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=ack.correlation_id,
                sequence=self._seq.next(),
                severity=AlertSeverity.WARNING,
                layer="kernel",
                alert_name="ack_for_unknown_order",
                message=f"Ack for unknown order_id={ack.order_id}, status={ack.status.name}",
                context={"order_id": ack.order_id, "status": ack.status.name},
            ))
            return
        sm = self._active_orders[ack.order_id][0]

        if ack.status == OrderAckStatus.REJECTED:
            sm.transition(OrderState.REJECTED, trigger=f"broker_reject:{ack.reason}")
            return

        if ack.status == OrderAckStatus.ACKNOWLEDGED:
            if sm.state == OrderState.SUBMITTED:
                sm.transition(OrderState.ACKNOWLEDGED, trigger="broker_ack")
            return

        # Ensure ACKNOWLEDGED before any fill/cancel/expiry transition.
        if sm.state == OrderState.SUBMITTED:
            sm.transition(OrderState.ACKNOWLEDGED, trigger="broker_ack")

        if ack.status == OrderAckStatus.FILLED:
            sm.transition(OrderState.FILLED, trigger="fill_complete")
        elif ack.status == OrderAckStatus.PARTIALLY_FILLED:
            if sm.can_transition(OrderState.PARTIALLY_FILLED):
                sm.transition(OrderState.PARTIALLY_FILLED, trigger="partial_fill")
            else:
                self._emit_ack_drop_alert(ack, sm)
        elif ack.status == OrderAckStatus.CANCELLED:
            if sm.can_transition(OrderState.CANCELLED):
                sm.transition(OrderState.CANCELLED, trigger="broker_cancel")
            else:
                self._emit_ack_drop_alert(ack, sm)
        elif ack.status == OrderAckStatus.EXPIRED:
            if sm.can_transition(OrderState.EXPIRED):
                sm.transition(OrderState.EXPIRED, trigger="order_expired")
            else:
                self._emit_ack_drop_alert(ack, sm)
        else:
            raise ValueError(
                f"Unhandled OrderAckStatus: {ack.status!r}. "
                f"Fail-safe: all enum members must be explicitly handled."
            )

    def _emit_ack_drop_alert(self, ack: OrderAck, sm: StateMachine[OrderState]) -> None:
        """Emit an alert when a valid broker ack cannot be applied to the order SM."""
        self._bus.publish(Alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=ack.correlation_id,
            sequence=self._seq.next(),
            severity=AlertSeverity.WARNING,
            layer="kernel",
            alert_name="ack_inapplicable_to_order_state",
            message=(
                f"Ack status={ack.status.name} cannot be applied to order "
                f"{ack.order_id} in state {sm.state.name}"
            ),
            context={
                "order_id": ack.order_id,
                "ack_status": ack.status.name,
                "order_state": sm.state.name,
            },
        ))

    # ── Fill reconciliation ─────────────────────────────────────────

    def _reconcile_fills(
        self,
        acks: list[OrderAck],
        correlation_id: str,
    ) -> None:
        """Update positions from fill acknowledgements.

        Determines sign of quantity_delta from the original order's
        Side: BUY adds to position, SELL subtracts.
        Writes TradeRecords to the trade journal for post-trade forensics.

        Inv-11 fail-safe: fills for unknown order IDs are rejected
        (not applied) and surfaced via alert.  Defaulting to BUY
        would risk increasing exposure from an untracked sell order.
        """
        for ack in acks:
            if ack.fill_price is None or ack.filled_quantity <= 0:
                continue

            if ack.order_id not in self._active_orders:
                self._bus.publish(Alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=correlation_id,
                    sequence=self._seq.next(),
                    severity=AlertSeverity.WARNING,
                    layer="kernel",
                    alert_name="fill_for_unknown_order",
                    message=(
                        f"Fill for unknown order_id={ack.order_id}, "
                        f"symbol={ack.symbol}, qty={ack.filled_quantity}, "
                        f"price={ack.fill_price}. "
                        f"Rejected: cannot determine side (Inv-11 fail-safe)."
                    ),
                    context={
                        "order_id": ack.order_id,
                        "symbol": ack.symbol,
                        "filled_quantity": ack.filled_quantity,
                        "fill_price": str(ack.fill_price),
                    },
                ))
                continue

            _, side, order = self._active_orders[ack.order_id]
            signed_qty = ack.filled_quantity
            if side == Side.SELL:
                signed_qty = -signed_qty

            prev_realized = self._positions.get(ack.symbol).realized_pnl
            position = self._positions.update(
                ack.symbol,
                signed_qty,
                ack.fill_price,
            )
            self._bus.publish(PositionUpdate(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                symbol=ack.symbol,
                quantity=position.quantity,
                avg_price=position.avg_entry_price,
                realized_pnl=position.realized_pnl,
                unrealized_pnl=position.unrealized_pnl,
                slippage_bps=ack.slippage_bps,
            ))

            if self._trade_journal is not None:
                self._trade_journal.record(TradeRecord(
                    order_id=ack.order_id,
                    symbol=ack.symbol,
                    strategy_id=order.strategy_id,
                    side=side,
                    requested_quantity=order.quantity,
                    filled_quantity=ack.filled_quantity,
                    fill_price=ack.fill_price,
                    signal_timestamp_ns=order.timestamp_ns,
                    submit_timestamp_ns=order.timestamp_ns,
                    fill_timestamp_ns=ack.timestamp_ns,
                    slippage_bps=ack.slippage_bps,
                    fees=ack.fees,
                    realized_pnl=position.realized_pnl - prev_realized,
                    correlation_id=order.correlation_id,
                ))

        self._prune_terminal_orders()

    def _prune_terminal_orders(self) -> None:
        """Remove terminally-resolved orders from _active_orders.

        Prevents unbounded memory growth in long-running live sessions.
        Orders in FILLED, CANCELLED, REJECTED, or EXPIRED states have
        completed their lifecycle and can be safely discarded.
        """
        terminal_ids = [
            oid for oid, (sm, _, _) in self._active_orders.items()
            if sm.state in _TERMINAL_ORDER_STATES
        ]
        for oid in terminal_ids:
            del self._active_orders[oid]

    # ── Observability ───────────────────────────────────────────────

    def _emit_state_transition(self, record: TransitionRecord) -> None:
        """Emit a StateTransition event for every state machine change."""
        self._bus.publish(StateTransition(
            timestamp_ns=record.timestamp_ns,
            correlation_id=record.correlation_id,
            sequence=self._seq.next(),
            machine_name=record.machine_name,
            from_state=record.from_state,
            to_state=record.to_state,
            trigger=record.trigger,
            metadata=record.metadata,
        ))

    def _on_metric_event(self, event: Event) -> None:
        """Forward MetricEvents from the bus to the MetricCollector."""
        if isinstance(event, MetricEvent):
            self._metrics.record(event)

    def _on_alert_event(self, event: Event) -> None:
        """Forward Alert events from the bus to the AlertManager."""
        if isinstance(event, Alert) and self._alert_manager is not None:
            self._alert_manager.emit(event)

    # ── Configuration and data integrity ────────────────────────────

    def _verify_data_integrity(self) -> bool:
        """Verify data integrity for all configured symbols.

        If a normalizer is available, checks that every configured
        symbol is tracked and reports HEALTHY.  Without a normalizer
        (e.g., backtest with pre-validated data), returns True.
        """
        if self._normalizer is None:
            return True
        if self._config is None:
            return True
        health = self._normalizer.all_health()
        for symbol in self._config.symbols:
            if symbol not in health:
                return False
            if health[symbol] != DataHealth.HEALTHY:
                return False
        return True

    # ── Feature snapshot management ─────────────────────────────────

    def _restore_feature_snapshots(self) -> None:
        """Restore feature engine state from snapshots for warm-start.

        Best-effort: if a snapshot is missing, corrupt, or version-
        incompatible, the feature engine cold-starts for that symbol.
        Snapshot failures never block boot.
        """
        if self._feature_snapshots is None or self._config is None:
            return
        version = self._feature_engine.version
        for symbol in self._config.symbols:
            result = self._feature_snapshots.load(symbol, version)
            if result is None:
                continue
            _, state = result
            try:
                self._feature_engine.restore(symbol, state)
            except Exception:
                self._feature_engine.reset(symbol)

    def _checkpoint_feature_snapshots(self) -> None:
        """Checkpoint feature engine state for all configured symbols.

        Best-effort: snapshot failures do not block shutdown.
        """
        if self._feature_snapshots is None or self._config is None:
            return
        version = self._feature_engine.version
        for symbol in self._config.symbols:
            try:
                state, event_count = self._feature_engine.checkpoint(symbol)
                checksum = hashlib.sha256(state).hexdigest()
                meta = FeatureSnapshotMeta(
                    symbol=symbol,
                    feature_version=version,
                    event_count=event_count,
                    last_sequence=0,
                    last_timestamp_ns=self._clock.now_ns(),
                    checksum=checksum,
                )
                self._feature_snapshots.save(meta, state)
            except Exception:
                logger.warning(
                    "Feature snapshot checkpoint failed for %s -- "
                    "next boot will cold-start this symbol",
                    symbol,
                    exc_info=True,
                )
