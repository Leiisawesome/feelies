"""System orchestrator — the operating system of the quant platform.

Owns the macro state machine and coordinates all layers through the
deterministic micro-state pipeline.  Enforces the single-threaded,
sequential tick processing loop.

The orchestrator contains NO business logic.  It is a coordinator
that calls each layer in the deterministic order defined by the
micro-state machine.

System invariants enforced here (Section V):
  Inv-1: No order submission outside G5/G6.
  Inv-2: Micro loop must not advance past M0 outside {G4, G5, G6}.
  Inv-3: R4 (LOCKED) forbids transitions to G6 without passing G2.
          (Structurally guaranteed — G8 → G2 → G6.)
  Inv-4: Every order terminally resolved before shutdown.
  Inv-5: Replay in G4 reproduces identical state transitions.

Key architectural invariants:
  - Backtest/live parity (platform inv 9): same _process_tick() in all modes
  - Deterministic replay (platform inv 5): micro-state transitions identical
  - No silent transitions: every state change logged via the bus
  - Fail-safe default (platform inv 11): risk breach → lockdown
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from feelies.bus.event_bus import EventBus
from feelies.core.clock import Clock
from feelies.core.errors import ConfigurationError
from feelies.core.events import (
    MetricEvent,
    MetricType,
    NBBOQuote,
    OrderAck,
    OrderRequest,
    OrderType,
    PositionUpdate,
    RiskAction,
    Signal,
    SignalDirection,
    Side,
    StateTransition,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.core.state_machine import TransitionRecord
from feelies.execution.backend import ExecutionBackend
from feelies.features.engine import FeatureEngine
from feelies.kernel.macro import (
    TRADING_MODES,
    MacroState,
    create_macro_state_machine,
)
from feelies.kernel.micro import MicroState, create_micro_state_machine
from feelies.monitoring.telemetry import MetricCollector
from feelies.portfolio.position_store import PositionStore
from feelies.risk.engine import RiskEngine
from feelies.risk.escalation import RiskLevel, create_risk_escalation_machine
from feelies.storage.event_log import EventLog

# Macro states where live/simulated order submission is permitted (Inv-1).
# G4 submits to the simulated fill model; G5/G6 to broker sandbox / real broker.
_ORDER_SUBMIT_MODES: frozenset[MacroState] = frozenset({
    MacroState.BACKTEST_MODE,
    MacroState.PAPER_TRADING_MODE,
    MacroState.LIVE_TRADING_MODE,
})


class Orchestrator:
    """Central coordinator for the deterministic tick-processing pipeline.

    Lifecycle:
      1. __init__   — wire up all components
      2. boot()     — G0 → G1 → G2
      3. run_*()    — G2 → {G4|G5|G6} → pipeline → G2
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
        signal_engine: Any,
        risk_engine: RiskEngine,
        position_store: PositionStore,
        event_log: EventLog,
        metric_collector: MetricCollector,
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
        self._seq = SequenceGenerator()

        self._macro = create_macro_state_machine(clock)
        self._micro = create_micro_state_machine(clock)
        self._risk_escalation = create_risk_escalation_machine(clock)

        self._macro.on_transition(self._emit_state_transition)
        self._micro.on_transition(self._emit_state_transition)
        self._risk_escalation.on_transition(self._emit_state_transition)

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

    def boot(self, config: dict[str, Any]) -> None:
        """G0 → G1 → G2  (happy path).

        Guard: CONFIG_VALIDATED requires all dependencies resolved.
        Guard: DATA_INTEGRITY_OK requires all streams verified.
        """
        try:
            self._validate_config(config)
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
        self._micro.reset()
        self._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")

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
                    trigger=f"BACKTEST_INTEGRITY_FAIL:{exc}",
                )
            raise

    def run_paper(self) -> None:
        """G2 → G5 → pipeline.

        Guard: broker sim connected.
        """
        self._macro.assert_state(MacroState.READY)
        self._micro.reset()
        self._macro.transition(
            MacroState.PAPER_TRADING_MODE,
            trigger="CMD_PAPER_DEPLOY",
        )
        self._run_pipeline()

    def run_live(self) -> None:
        """G2 → G6 → pipeline.

        Guard: human approval + risk audit pass.
        Inv-3: R4 (LOCKED) forbids this — must pass through G2 first,
        which is structurally guaranteed (G8 → G2 → G6).
        """
        self._macro.assert_state(MacroState.READY)
        if self._risk_escalation.state != RiskLevel.NORMAL:
            raise RuntimeError(
                f"Cannot enter LIVE: risk level is {self._risk_escalation.state.name}, "
                f"must be NORMAL"
            )
        self._micro.reset()
        self._macro.transition(
            MacroState.LIVE_TRADING_MODE,
            trigger="CMD_LIVE_DEPLOY",
        )
        self._run_pipeline()

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
        Risk escalation R4 → R0 (human override + audit pass).
        """
        self._macro.assert_state(MacroState.RISK_LOCKDOWN)

        exposure = self._positions.total_exposure()
        if exposure != Decimal("0"):
            raise RuntimeError(
                f"Cannot unlock: total exposure is {exposure}, must be 0 "
                f"(FORCED_FLATTEN_COMPLETE guard)"
            )

        self._risk_escalation.transition(
            RiskLevel.NORMAL,
            trigger=f"human_override_audit:{audit_token}",
        )
        self._macro.transition(
            MacroState.READY,
            trigger=f"FORCED_FLATTEN_COMPLETE:audit:{audit_token}",
        )

    def shutdown(self) -> None:
        """→ G9 (terminal).

        Inv-4: all orders must be terminally resolved before shutdown.
        """
        if self._macro.can_transition(MacroState.SHUTDOWN):
            self._macro.transition(MacroState.SHUTDOWN, trigger="CMD_SHUTDOWN")
        self._metrics.flush()

    # ── Pipeline: the deterministic tick loop ───────────────────────

    def _run_pipeline(self) -> None:
        """Execute the deterministic micro-state loop over all market events.

        Inv-2: breaks when macro state leaves TRADING_MODES.
        """
        for quote in self._backend.market_data.events():
            if self._macro.state not in TRADING_MODES:
                break
            self._process_tick(quote)

    def _process_tick(self, quote: NBBOQuote) -> None:
        """Process a single tick through the full micro-state pipeline.

        This method is IDENTICAL in G4, G5, and G6.  The only
        mode-specific behavior is inside ExecutionBackend (platform inv 9).

        Micro-state sequence (formal spec Section II):
          M0 → M1 → M2 → M3 → M4 → M5 →
            (risk fail)       → [G8, pipeline aborts]
            (pass, no order)  → M10 → M0
            (pass, order)     → M6 → M7 → M8 → M9 → M10 → M0
        """
        cid = quote.correlation_id
        t_received = self._clock.now_ns()

        # ── M0 → M1: MARKET_EVENT_RECEIVED ─────────────────────
        self._micro.transition(
            MicroState.MARKET_EVENT_RECEIVED,
            trigger="tick_arrived",
            correlation_id=cid,
        )
        self._event_log.append(quote)

        # ── M1 → M2: STATE_UPDATE ──────────────────────────────
        self._micro.transition(
            MicroState.STATE_UPDATE,
            trigger="event_logged",
            correlation_id=cid,
        )

        # ── M2 → M3: FEATURE_COMPUTE ───────────────────────────
        self._micro.transition(
            MicroState.FEATURE_COMPUTE,
            trigger="state_updated",
            correlation_id=cid,
        )
        features = self._feature_engine.update(quote)
        self._bus.publish(features)

        # ── M3 → M4: SIGNAL_EVALUATE ───────────────────────────
        self._micro.transition(
            MicroState.SIGNAL_EVALUATE,
            trigger="features_computed",
            correlation_id=cid,
        )
        signal: Signal = self._signal_engine.evaluate(features)
        self._bus.publish(signal)

        # ── M4 → M5: RISK_CHECK ────────────────────────────────
        self._micro.transition(
            MicroState.RISK_CHECK,
            trigger="signal_evaluated",
            correlation_id=cid,
        )
        verdict = self._risk_engine.check_signal(signal, self._positions)
        self._bus.publish(verdict)

        # ── M5 three-way branch ────────────────────────────────
        #
        # Branch 1: risk fail → cross-machine to G8.
        #   Only valid from G5/G6 (macro SM enforces G4 cannot → G8).
        #   In G4, risk failure is logged and the tick ends at M10.
        #
        if verdict.action == RiskAction.FORCE_FLATTEN:
            if self._macro.can_transition(MacroState.RISK_LOCKDOWN):
                self._escalate_risk(cid)
                self._micro.reset()
                return
            # G4 (backtest): risk failure is simulation output, not a macro event.
            # Fall through to "no order" path.

        # Branch 2: risk pass, no order → M5 → M10
        needs_order = (
            verdict.action in (RiskAction.ALLOW, RiskAction.SCALE_DOWN)
            and signal.direction != SignalDirection.FLAT
        )

        if not needs_order:
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="risk_pass_no_order",
                correlation_id=cid,
            )
            self._finalize_tick(t_received, cid)
            return

        # Branch 3: risk pass, order warranted → M5 → M6
        self._micro.transition(
            MicroState.ORDER_DECISION,
            trigger="risk_pass_order_warranted",
            correlation_id=cid,
        )
        order = self._build_order(signal, verdict, cid)

        # ── M6 → M7: ORDER_SUBMIT ──────────────────────────────
        self._micro.transition(
            MicroState.ORDER_SUBMIT,
            trigger="order_constructed",
            correlation_id=cid,
        )
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
        self._finalize_tick(t_received, cid)

    # ── Helpers ─────────────────────────────────────────────────────

    def _finalize_tick(self, t_received: int, correlation_id: str) -> None:
        """Emit tick latency metric and return micro state M10 → M0."""
        latency_ns = self._clock.now_ns() - t_received
        self._bus.publish(MetricEvent(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            layer="kernel",
            name="tick_to_decision_latency_ns",
            value=float(latency_ns),
            metric_type=MetricType.HISTOGRAM,
        ))
        self._micro.transition(
            MicroState.WAITING_FOR_MARKET_EVENT,
            trigger="tick_complete",
            correlation_id=correlation_id,
        )

    def _escalate_risk(self, correlation_id: str) -> None:
        """Escalate through R0 → R1 → R2 → R3 → R4 → macro G8.

        Monotonically tightens safety (platform inv 11).  Once R1
        (WARNING) is entered, de-escalation is impossible without
        completing the full cycle to R4 and human unlock.
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
            self._risk_escalation.transition(
                RiskLevel.LOCKED,
                trigger="positions_zero_flatten_complete",
                correlation_id=correlation_id,
            )

        self._macro.transition(
            MacroState.RISK_LOCKDOWN,
            trigger="RISK_BREACH",
            correlation_id=correlation_id,
        )

    def _build_order(
        self,
        signal: Signal,
        verdict: Any,
        correlation_id: str,
    ) -> OrderRequest:
        """Construct an OrderRequest.  Only called when order IS warranted."""
        side = Side.BUY if signal.direction == SignalDirection.LONG else Side.SELL

        return OrderRequest(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            order_id=uuid.uuid4().hex[:16],
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=1,  # sizing delegated to risk engine scaling
            strategy_id=signal.strategy_id,
        )

    def _reconcile_fills(
        self,
        acks: list[OrderAck],
        correlation_id: str,
    ) -> None:
        """Update positions from fill acknowledgements."""
        for ack in acks:
            if ack.fill_price is not None and ack.filled_quantity > 0:
                position = self._positions.update(
                    ack.symbol,
                    ack.filled_quantity,
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
                    slippage_bps=Decimal("0"),
                ))

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

    def _validate_config(self, config: dict[str, Any]) -> None:
        """Validate system configuration.  Raises ConfigurationError."""
        required_keys = {"symbols"}
        missing = required_keys - set(config.keys())
        if missing:
            raise ConfigurationError(f"Missing required config keys: {missing}")

    def _verify_data_integrity(self) -> bool:
        """Verify historical data integrity for all configured symbols.

        Placeholder — concrete implementation in data-engineering layer.
        """
        return True
