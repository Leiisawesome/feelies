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
    from feelies.alpha.fill_attribution import FillAttributionLedger
    from feelies.alpha.registry import AlphaRegistry
    from feelies.composition.engine import CompositionEngine
    from feelies.monitoring.horizon_metrics import HorizonMetricsCollector
    from feelies.portfolio.cross_sectional_tracker import CrossSectionalTracker
    from feelies.portfolio.strategy_position_store import StrategyPositionStore
    from feelies.risk.hazard_exit import HazardExitController

from feelies.alpha.arbitration import EdgeWeightedArbitrator, SignalArbitrator

from feelies.bus.event_bus import EventBus
from feelies.core.clock import Clock
from feelies.core.config import Configuration
from feelies.core.errors import ConfigurationError
from feelies.core.events import (
    Alert,
    AlertSeverity,
    Event,
    HorizonTick,
    KillSwitchActivation,
    MetricEvent,
    MetricType,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    PositionUpdate,
    RegimeHazardSpike,
    RegimeState,
    RiskAction,
    RiskVerdict,
    Signal,
    SignalDirection,
    Side,
    SizedPositionIntent,
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
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.registry import SensorRegistry
from feelies.services.regime_engine import RegimeEngine
from feelies.services.regime_hazard_detector import RegimeHazardDetector
from feelies.signals.horizon_engine import HorizonSignalEngine
from feelies.storage.event_log import EventLog
from feelies.storage.feature_snapshot import FeatureSnapshotMeta, FeatureSnapshotStore
from feelies.storage.trade_journal import TradeJournal, TradeRecord

# Avoid a hard execution-layer import at module level: imported lazily in boot()
# or via TYPE_CHECKING to preserve the layer boundary.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from feelies.execution.cost_model import CostModel
    from feelies.portfolio.position_store import Position

class _PostExitPositionView:
    """Position view that simulates a pending exit fill for risk checking.

    Used by ``_execute_reverse()`` so the entry leg's ``check_order()``
    sees the post-exit position rather than the stale pre-exit snapshot.
    Without this, the risk engine computes an incorrectly favorable
    ``post_fill_qty`` for the entry leg (e.g. 0 instead of the actual
    new-entry quantity), allowing entries that should be rejected.

    Only ``get``, ``all_positions``, and ``total_exposure`` are needed
    by the risk engine — mutating methods raise ``RuntimeError``.
    """

    __slots__ = ("_inner", "_symbol", "_adj")

    def __init__(
        self,
        inner: PositionStore,
        symbol: str,
        quantity_adjustment: int,
    ) -> None:
        self._inner = inner
        self._symbol = symbol
        self._adj = quantity_adjustment

    def _adjusted(self, pos: "Position") -> "Position":
        from feelies.portfolio.position_store import Position
        return Position(
            symbol=pos.symbol,
            quantity=pos.quantity + self._adj,
            avg_entry_price=pos.avg_entry_price,
            realized_pnl=pos.realized_pnl,
            unrealized_pnl=pos.unrealized_pnl,
            cumulative_fees=pos.cumulative_fees,
        )

    def get(self, symbol: str) -> "Position":
        pos = self._inner.get(symbol)
        if symbol == self._symbol:
            return self._adjusted(pos)
        return pos

    def all_positions(self) -> "dict[str, Position]":
        result = dict(self._inner.all_positions())
        if self._symbol in result:
            result[self._symbol] = self._adjusted(result[self._symbol])
        return result

    def total_exposure(self) -> Decimal:
        total = self._inner.total_exposure()
        pos = self._inner.get(self._symbol)
        old_contrib = abs(pos.quantity) * pos.avg_entry_price
        new_contrib = abs(pos.quantity + self._adj) * pos.avg_entry_price
        return total - old_contrib + new_contrib

    def update(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("_PostExitPositionView is read-only")

    def debit_fees(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("_PostExitPositionView is read-only")

    def update_mark(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("_PostExitPositionView is read-only")

    # ----- Phase-4 PositionStore Protocol shims --------------------------
    # These delegate to the inner store unmodified.  The post-exit view
    # only adjusts ``quantity`` for the in-flight reverse leg; the mark
    # price and open-timestamp shadow maps are unaffected by the simulated
    # exit and must therefore reflect the underlying store.
    def latest_mark(self, symbol: str) -> Decimal | None:
        return self._inner.latest_mark(symbol)

    def opened_at_ns(self, symbol: str) -> int | None:
        return self._inner.opened_at_ns(symbol)


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

    Workstream D.2 has retired the per-tick legacy alpha pipeline:

      * PR-2b-ii deleted :class:`CompositeFeatureEngine`,
        :class:`CompositeSignalEngine`, :class:`MultiAlphaEvaluator`,
        and the :class:`feelies.features.engine.FeatureEngine` /
        :class:`feelies.signals.engine.SignalEngine` Protocols.
      * PR-2b-iii added the bus-driven ``Signal`` subscriber
        (``_on_bus_signal``) — the first production-reachable
        Signal → Order path in the platform.
      * PR-2b-iv (this commit) (1) added the bus-driven
        ``SizedPositionIntent`` subscriber (``_on_bus_sized_intent``) so
        PORTFOLIO alphas finally submit orders end-to-end via
        ``RiskEngine.check_sized_intent``, and (2) deleted the surviving
        scaffolding: ``feature_engine`` / ``signal_engine`` ctor params,
        the per-tick :class:`feelies.core.events.FeatureVector` event,
        :meth:`AlphaModule.evaluate`, the legacy gated single-alpha
        branch in :py:meth:`_process_tick_inner`, and the orphan
        multi-alpha helpers ``_build_net_order`` / ``_compute_contributions``.

    Two production Signal / Intent → Order paths now coexist on the bus:

      * **Standalone SIGNAL alphas** (``_on_bus_signal``).  Buffer
        ``Signal(layer="SIGNAL")`` events per tick after filtering out
        SIGNAL alphas referenced by any registered PORTFOLIO's
        ``depends_on_signals`` (those flow through CompositionEngine and
        emerge as SizedPositionIntent, not OrderRequest).  Drain the
        first buffered signal at M4 ``SIGNAL_EVALUATE`` and run it
        through the per-tick risk → order → fill walk.
      * **PORTFOLIO alphas** (``_on_bus_sized_intent``).  Translate every
        ``SizedPositionIntent`` into per-leg ``OrderRequest`` events via
        :meth:`RiskEngine.check_sized_intent` (Inv-11 per-leg veto;
        Inv-5 deterministic order_id).  Runs *outside* the per-tick
        micro-SM walk: PORTFOLIO orders dispatch as a synchronous
        side-effect of the M3 ``CROSS_SECTIONAL`` ``bus.publish(intent)``
        and do NOT advance the SIGNAL-reserved M5 → M10 walk.

    Concurrency / coexistence rules:

      * The micro-SM permits at most one Signal → Order walk per tick.
        When more than one standalone SIGNAL alpha fires on the same
        tick the orchestrator picks the first arrival
        (HorizonSignalEngine's deterministic registration-order
        dispatch) and emits a once-per-process WARNING hinting that
        the operator should aggregate via a PORTFOLIO alpha.
      * Standalone SIGNAL and PORTFOLIO can coexist on the same tick:
        the SIGNAL-bus subscriber's ``depends_on_signals`` skip-rule
        prevents double-trading when the same Signal feeds both paths.
      * Stop-loss exits computed inline by ``_check_stop_exit`` always
        override (Inv-11: position safety beats alpha conviction).

    The micro-state transitions ``FEATURE_COMPUTE`` (M3) and
    ``SIGNAL_EVALUATE`` (M4) still fire unconditionally so the SM stays
    on its legal path; M3's body is now empty (Phase-3 SIGNAL/PORTFOLIO
    outputs are produced via the bus-driven HorizonAggregator →
    HorizonSignalEngine → CompositionEngine chain attached upstream of
    the orchestrator); M4's body either dispatches a buffered Signal or
    finalises with no order.
    """

    def __init__(
        self,
        clock: Clock,
        bus: EventBus,
        backend: ExecutionBackend,
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
        regime_engine_registry_name: str | None = None,
        intent_translator: IntentTranslator | None = None,
        position_sizer: PositionSizer | None = None,
        alpha_registry: "AlphaRegistry | None" = None,
        account_equity: Decimal = Decimal("100000"),
        fill_ledger: "FillAttributionLedger | None" = None,
        strategy_positions: "StrategyPositionStore | None" = None,
        cost_model: "CostModel | None" = None,
        sensor_registry: SensorRegistry | None = None,
        horizon_scheduler: HorizonScheduler | None = None,
        horizon_signal_engine: HorizonSignalEngine | None = None,
        sensor_sequence_generator: SequenceGenerator | None = None,
        horizon_sequence_generator: SequenceGenerator | None = None,
        snapshot_sequence_generator: SequenceGenerator | None = None,
        signal_sequence_generator: SequenceGenerator | None = None,
        regime_hazard_detector: RegimeHazardDetector | None = None,
        hazard_sequence_generator: SequenceGenerator | None = None,
        composition_engine: "CompositionEngine | None" = None,
        cross_sectional_tracker: "CrossSectionalTracker | None" = None,
        composition_metrics_collector: "HorizonMetricsCollector | None" = None,
        hazard_exit_controller: "HazardExitController | None" = None,
        signal_arbitrator: SignalArbitrator | None = None,
    ) -> None:
        self._clock = clock
        self._bus = bus
        self._backend = backend
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
        # Bus-visible name must match alpha YAML ``regime_gate.regime_engine``
        # (registry key, e.g. ``hmm_3state_fractional``), not the Python class
        # name — otherwise HorizonSignalEngine's regime cache lookup misses and
        # every ``P(...)`` gate raises UnknownIdentifierError.
        self._regime_engine_registry_name = regime_engine_registry_name
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
        self._fill_ledger = fill_ledger
        self._strategy_positions = strategy_positions
        self._cost_model: "CostModel | None" = cost_model
        self._seq = SequenceGenerator()

        # ── Phase-2 (three-layer architecture) ─────────────────────────
        # Sensor / scheduler / aggregator are optional; when None the
        # orchestrator takes the legacy bit-identical path through the
        # micro-state machine (Inv-A in the implementation plan).
        self._sensor_registry = sensor_registry
        self._horizon_scheduler = horizon_scheduler
        self._horizon_signal_engine = horizon_signal_engine
        # Per-event-family sequence generators (C1).  These are
        # *separate* from ``self._seq`` (kernel-owned) so adding
        # sensors / signals cannot perturb existing event sequence
        # numbers.  Each generator is owned by exactly one event family:
        #
        #   _seq          → kernel-emitted bus events (RiskVerdict,
        #                   PositionUpdate, MetricEvent, OrderRequest
        #                   for the per-tick walk, etc.)
        #   _sensor_seq   → SensorReading
        #   _horizon_seq  → HorizonTick
        #   _snapshot_seq → HorizonFeatureSnapshot (P2-β)
        #   _signal_seq   → Signal(layer='SIGNAL') (P3-α)
        #
        # The bootstrap layer constructs the registry/scheduler/
        # horizon_signal_engine with the same SequenceGenerator
        # instances it passes here, so tests that verify Inv-A (legacy
        # parity) can introspect a single canonical reference.  When
        # sensors / SIGNAL alphas are disabled these counters simply
        # never advance.
        self._sensor_seq = sensor_sequence_generator or SequenceGenerator()
        self._horizon_seq = horizon_sequence_generator or SequenceGenerator()
        self._snapshot_seq = snapshot_sequence_generator or SequenceGenerator()
        self._signal_seq = signal_sequence_generator or SequenceGenerator()
        # P3.1: optional hazard detector + dedicated _hazard_seq
        # generator (Inv-A / C1 isolation: enabling hazard exits must
        # not perturb pre-existing event sequence numbers).  Caller
        # passes None when no alpha declares hazard_exit.enabled, in
        # which case the orchestrator never publishes
        # RegimeHazardSpike events and the counter stays at zero.
        self._regime_hazard_detector = regime_hazard_detector
        self._hazard_seq = hazard_sequence_generator or SequenceGenerator()
        # ── Phase-4 PORTFOLIO / composition layer (optional) ─────────
        # All four are ``None`` for default deployments — Inv-A:
        # SIGNAL-only deployments without a PORTFOLIO alpha take the
        # short path and the composition pipeline is never wired up.
        # When wired by bootstrap, the
        # subscriptions are already installed; the orchestrator holds
        # references purely for introspection (tests, forensics,
        # operator ``stats()`` queries).
        self._composition_engine = composition_engine
        self._cross_sectional_tracker = cross_sectional_tracker
        self._composition_metrics_collector = composition_metrics_collector
        self._hazard_exit_controller = hazard_exit_controller
        self._signal_arbitrator: SignalArbitrator = (
            signal_arbitrator
            if signal_arbitrator is not None
            else EdgeWeightedArbitrator()
        )
        # Per-(symbol, engine_name) cache of the most recently
        # observed RegimeState; used as ``prev`` argument to the
        # detector on the next tick.  Cleared on session boundary
        # alongside the regime engine itself.
        self._last_regime_state: dict[tuple[str, str], RegimeState] = {}

        self._stop_loss_per_share: float = 0.0
        self._trail_activate_per_share: float = 0.0
        self._trail_pct: float = 0.5
        self._peak_pnl_per_share: dict[str, float] = {}
        self._min_order_shares: int = 1
        self._signal_min_edge_cost_ratio: float = 0.0  # 0 = gate disabled

        self._config: Configuration | None = None

        # Per-order lifecycle tracking for Inv-4 enforcement.
        # Maps order_id -> (OrderState SM, Side, OrderRequest).
        self._active_orders: dict[str, tuple[StateMachine[OrderState], Side, OrderRequest]] = {}

        # When True, market events arriving from the data source are
        # already present in the event log (replay mode).  Prevents
        # re-appending identical events during backtest replay.
        self._events_prelogged = False

        # When True, entry/exit orders use LIMIT at BBO instead of
        # MARKET.  Stop-loss exits always use MARKET (fail-safe).
        # Set from config via boot().
        self._use_passive_entries = False

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

        # ── PR-2b-iii: bus-driven Signal subscriber ────────────────────
        # Phase-3 ``HorizonSignalEngine`` publishes ``Signal(layer="SIGNAL")``
        # events on the bus when an alpha's regime gate is ON at a horizon
        # boundary.  ``_on_bus_signal`` buffers SIGNAL-layer Signals per
        # tick (after filtering out alphas that any registered PORTFOLIO
        # consumes via ``depends_on_signals``); the M4 ``SIGNAL_EVALUATE``
        # drain consumes the buffer and walks the existing risk → order →
        # fill pipeline once per tick (the micro SM only supports one
        # Signal → Order walk per tick; multiple standalone candidates on
        # the same tick are filtered by ``EdgeWeightedArbitrator`` before
        # this walk — full cross-alpha aggregation belongs in a PORTFOLIO
        # alpha).  PR-2b-iv (this commit) deleted the
        # legacy ``signal_engine`` ctor scaffolding, so this is now the
        # sole standalone-SIGNAL → Order path.
        self._signal_buffer: list[Signal] = []
        self._consumed_by_portfolio_ids: frozenset[str] | None = None
        self._warned_multi_standalone_signals: bool = False
        self._bus.subscribe(Signal, self._on_bus_signal)

        # ── PR-2b-iv: bus-driven SizedPositionIntent subscriber ─────────
        # Phase-4 ``CompositionEngine`` publishes one
        # ``SizedPositionIntent`` per registered PORTFOLIO alpha at every
        # horizon boundary (a side-effect of ``bus.publish(quote)`` while
        # the micro-SM is in CROSS_SECTIONAL).  Pre-PR-2b-iv nothing
        # translated those intents into ``OrderRequest`` events: PORTFOLIO
        # alphas were hooked into the bus end-to-end for SizedPositionIntent
        # but the production order pipeline simply ignored them.
        #
        # ``_on_bus_sized_intent`` calls
        # :meth:`RiskEngine.check_sized_intent` (which translates
        # ``TargetPosition`` deltas into per-leg ``OrderRequest`` tuples
        # under per-leg veto semantics; Inv-11) and submits each surviving
        # order to ``backend.order_router``, polling synchronous acks and
        # reconciling fills into the position store.
        #
        # The handler runs *outside* the per-tick micro-SM walk: PORTFOLIO
        # orders are bus-dispatched at CROSS_SECTIONAL (M3) and do NOT
        # drive the M5 → M10 transitions, which remain reserved for the
        # at-most-one SIGNAL-driven order per tick.  This sidesteps the
        # SM's single-walk-per-tick limit and lets PORTFOLIO + standalone
        # SIGNAL coexist on the same tick (PR-2b-iii's
        # ``depends_on_signals`` skip-rule prevents double-trading when a
        # SIGNAL alpha is consumed by a PORTFOLIO alpha).
        self._bus.subscribe(SizedPositionIntent, self._on_bus_sized_intent)

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
            if hasattr(config, "stop_loss_per_share"):
                self._stop_loss_per_share = config.stop_loss_per_share
            if hasattr(config, "trail_activate_per_share"):
                self._trail_activate_per_share = config.trail_activate_per_share
            if hasattr(config, "trail_pct"):
                self._trail_pct = config.trail_pct
            if hasattr(config, "execution_mode"):
                self._use_passive_entries = (
                    config.execution_mode == "passive_limit"
                )
            if hasattr(config, "platform_min_order_shares"):
                self._min_order_shares = config.platform_min_order_shares
            if hasattr(config, "signal_min_edge_cost_ratio"):
                self._signal_min_edge_cost_ratio = config.signal_min_edge_cost_ratio
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
            self._calibrate_regime_engine()
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

        Also forwarded to the order router (D10) when the router
        supports ``on_trade()`` — enables volume-based queue aging
        for passive limit order fills.
        """
        self._process_trade_inner(trade)

    def _process_trade_inner(self, trade: Trade) -> None:
        """Trade-path body (split out for Phase-2 sensor wiring, C3).

        The trade path does *not* drive the micro-state machine
        (trades are out-of-band w.r.t. the quote-driven pipeline), so
        we do not transition through SENSOR_UPDATE / HORIZON_CHECK
        for trades.  We *do* however invoke the sensor registry (via
        the bus) and the horizon scheduler (manually) so trade-only
        sensors and any time-bucket boundaries crossed by the trade
        timestamp are observed.
        """
        if not self._events_prelogged:
            self._event_log.append(trade)
        self._bus.publish(trade)

        router_on_trade = getattr(self._backend.order_router, "on_trade", None)
        if router_on_trade is not None:
            router_on_trade(trade)

        # P2-α: drive the scheduler from the trade path too (C3).  No
        # micro-state walk; trade ticks just produce HorizonTicks if
        # they cross a boundary.  Sensor registry runs through the
        # bus subscription on ``self._bus.publish(trade)`` above.
        if self._horizon_scheduler is not None:
            for tick in self._horizon_scheduler.on_event(trade):
                self._bus.publish(tick)

    def _dispatch_sensor_layer(self, event: NBBOQuote, cid: str) -> None:
        """Quote-path Phase-2 dispatch: sensors + scheduler + aggregator.

        Walks the new micro-states (SENSOR_UPDATE → HORIZON_CHECK
        → HORIZON_AGGREGATE) only when the sensor stack is wired.  The
        sensor registry has already received the quote via its bus
        subscription on ``self._bus.publish(quote)`` in the caller, so
        SENSOR_UPDATE here is a bookkeeping transition; the
        observability gain is that the micro SM exposes the explicit
        Phase-2 stage to forensics consumers.

        When the registry is empty *and* no scheduler is configured,
        this method returns immediately and the caller transitions
        STATE_UPDATE → FEATURE_COMPUTE directly — preserving the
        legacy execution path bit-for-bit (Inv-A).
        """
        registry_active = (
            self._sensor_registry is not None
            and not self._sensor_registry.is_empty()
        )
        scheduler_active = self._horizon_scheduler is not None
        if not registry_active and not scheduler_active:
            return

        # M2 → SENSOR_UPDATE.  Sensors already ran via the bus
        # subscription; this transition is the authoritative record
        # in the micro SM that the sensor stage completed.
        self._micro.transition(
            MicroState.SENSOR_UPDATE,
            trigger="state_updated",
            correlation_id=cid,
        )
        # SENSOR_UPDATE → HORIZON_CHECK.
        self._micro.transition(
            MicroState.HORIZON_CHECK,
            trigger="sensors_dispatched",
            correlation_id=cid,
        )

        ticks: tuple[HorizonTick, ...] = ()
        if scheduler_active:
            assert self._horizon_scheduler is not None
            ticks = self._horizon_scheduler.on_event(event)
            for tick in ticks:
                self._bus.publish(tick)

        if ticks:
            # HORIZON_CHECK → HORIZON_AGGREGATE.  In P2-α the
            # aggregator does not yet exist; the transition is purely
            # bookkeeping.  P2-β wires a real aggregator on the bus
            # (subscribed to HorizonTick + SensorReading), so this
            # transition window is where ``HorizonFeatureSnapshot``
            # events will materialise.
            self._micro.transition(
                MicroState.HORIZON_AGGREGATE,
                trigger="horizon_tick_emitted",
                correlation_id=cid,
            )
            # HORIZON_AGGREGATE → SIGNAL_GATE (P3-α).  Only fires when
            # at least one SIGNAL alpha is registered with the
            # :class:`HorizonSignalEngine`.  Without it we transition
            # straight to FEATURE_COMPUTE through the caller's per-tick
            # path, preserving the Phase-2 bit-identical sequence (Inv-A).
            #
            # The signal engine has already executed via its
            # :class:`HorizonFeatureSnapshot` bus subscription by the
            # time this transition fires; the SM transition is the
            # authoritative record that the SIGNAL stage completed
            # (mirrors the SENSOR_UPDATE bookkeeping pattern).
            if (
                self._horizon_signal_engine is not None
                and not self._horizon_signal_engine.is_empty
            ):
                self._micro.transition(
                    MicroState.SIGNAL_GATE,
                    trigger="horizon_signal_dispatched",
                    correlation_id=cid,
                )

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
            logger.critical(
                "orchestrator: micro SM reset failed during tick-failure recovery "
                "— orchestrator state is unknown",
                exc_info=True,
            )

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
            logger.critical(
                "orchestrator: macro SM DEGRADED transition failed during tick-failure recovery "
                "— orchestrator state is unknown",
                exc_info=True,
            )

    def _process_tick_inner(self, quote: NBBOQuote) -> None:
        """Core tick-processing logic.  Separated from _process_tick
        so the exception handler has a clean boundary.
        """
        cid = quote.correlation_id
        t_wall_start = time.perf_counter_ns()
        self._tick_timings: dict[str, int] = {}

        # PR-2b-iii: clear last tick's bus-fed Signal buffer before
        # ``bus.publish(quote)`` triggers HorizonSignalEngine subscribers
        # for the new tick.  Without this, Signals that fired during a
        # prior tick (and were never drained — e.g., when the kill switch
        # short-circuited the pipeline) would leak into the new tick's
        # M4 drain and translate into ghost orders.
        self._signal_buffer.clear()

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

        # ── Mark-to-market feed ─────────────────────────────────
        # Push the latest mid to both the aggregate and per-strategy
        # position books so ``total_exposure`` and ``unrealized_pnl``
        # reflect live prices, not cost basis.  The risk engine uses
        # these for the gross-exposure cap and drawdown guard.
        mid = (quote.bid + quote.ask) / Decimal("2")
        if mid > 0:
            self._positions.update_mark(quote.symbol, mid)
            if self._strategy_positions is not None:
                self._strategy_positions.update_mark(quote.symbol, mid)

        # ── Resting order fill check ─────────────────────────────
        # bus.publish(quote) triggered on_quote() on the router,
        # which evaluated fill conditions for any resting limit
        # orders.  Pick up those fills before evaluating signals so
        # the position store is current.
        if self._use_passive_entries:
            self._reconcile_resting_fills(cid)

        # ── M1 → M2: STATE_UPDATE ──────────────────────────────
        self._micro.transition(
            MicroState.STATE_UPDATE,
            trigger="event_logged",
            correlation_id=cid,
        )
        self._update_regime(quote, cid)

        # ── (P2-α) Optional sensor + scheduler pass ────────────
        # ``_dispatch_sensor_layer`` is a no-op when no sensor
        # registry / scheduler is configured (Inv-A: legacy path is
        # bit-identical).  When configured it walks the new
        # SENSOR_UPDATE → HORIZON_CHECK [ → HORIZON_AGGREGATE ]
        # micro-states and publishes any HorizonTick events emitted
        # by the scheduler.
        self._dispatch_sensor_layer(quote, cid)

        # ── M2 (or HORIZON_*) → M3: FEATURE_COMPUTE ────────────
        # Workstream D.2 PR-2b-iv: legacy ``feature_engine`` is gone.
        # The micro-SM still visits M3 to preserve the legal path
        # FEATURE_COMPUTE → SIGNAL_EVALUATE → LOG_AND_METRICS, but the
        # body is now empty — Phase-3 SIGNAL/PORTFOLIO outputs are
        # produced via the bus-driven ``HorizonAggregator`` →
        # ``HorizonSignalEngine`` → ``CompositionEngine`` chain attached
        # upstream of the orchestrator (see ``_dispatch_sensor_layer``).
        self._micro.transition(
            MicroState.FEATURE_COMPUTE,
            trigger="state_updated",
            correlation_id=cid,
        )

        # ── M3 → M4: SIGNAL_EVALUATE ───────────────────────────
        self._micro.transition(
            MicroState.SIGNAL_EVALUATE,
            trigger="features_computed",
            correlation_id=cid,
        )

        # Workstream D.2 PR-2b-iv: the legacy ``signal_engine`` ctor
        # scaffolding is gone; the per-tick risk → order → fill walk is
        # now driven exclusively by the PR-2b-iii bus-driven Signal
        # subscriber.  ``HorizonSignalEngine`` publishes
        # ``Signal(layer="SIGNAL")`` events as a side-effect of
        # ``bus.publish(quote)`` at M1 (synchronous bus dispatch);
        # ``_on_bus_signal`` buffers them after filtering out
        # PORTFOLIO-consumed alphas (those flow through
        # ``CompositionEngine`` and emerge as ``SizedPositionIntent``,
        # not ``OrderRequest``, handled by ``_on_bus_sized_intent``).
        #
        # The micro SM only supports one Signal-driven walk per tick;
        # the standalone-SIGNAL case resolves multiple buffered Signals
        # via :class:`~feelies.alpha.arbitration.EdgeWeightedArbitrator`
        # (injectable ``signal_arbitrator`` ctor param).  Stop-loss exits
        # computed inline by ``_check_stop_exit`` always override (Inv-11:
        # position safety beats alpha conviction).
        signal: "Signal | None" = None
        if self._signal_buffer:
            t0 = time.perf_counter_ns()
            signal = self._select_bus_signal()
            self._tick_timings["signal_evaluate_ns"] = time.perf_counter_ns() - t0

        stop_signal = self._check_stop_exit(quote)
        if stop_signal is not None:
            signal = stop_signal

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

        # H2/H3/H7: REVERSE intents decompose into EXIT(MARKET) +
        # ENTRY(LIMIT) — aggressive close guarantees fill, passive
        # entry saves spread.
        if intent.intent in (
            TradingIntent.REVERSE_LONG_TO_SHORT,
            TradingIntent.REVERSE_SHORT_TO_LONG,
        ):
            self._execute_reverse(intent, verdict, cid, quote, t_wall_start)
            return

        order = self._build_order_from_intent(intent, verdict, cid, quote)
        if order is None:
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="risk_scale_down_to_zero",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

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
            scaled_qty = round(order.quantity * order_verdict.scaling_factor)
            if scaled_qty <= 0:
                self._micro.transition(
                    MicroState.LOG_AND_METRICS,
                    trigger="check_order_scale_down_to_zero",
                    correlation_id=cid,
                )
                self._finalize_tick(t_wall_start, cid)
                return
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

        # ── Guard: suppress duplicate orders while a resting order
        #    exists.  EXIT allowed only when no exit already resting
        #    (prevents the duplicate-exit pile-up bug).  Stop-loss
        #    always passes.  REVERSE intents handled by
        #    _execute_reverse() and never reach this guard.
        if (
            self._use_passive_entries
            and intent.signal.strategy_id != "__stop_exit__"
            and self._has_pending_order_for_symbol(order.symbol)
        ):
            if intent.intent != TradingIntent.EXIT or self._has_pending_exit_for_symbol(order.symbol):
                self._micro.transition(
                    MicroState.LOG_AND_METRICS,
                    trigger="resting_order_pending",
                    correlation_id=cid,
                )
                self._finalize_tick(t_wall_start, cid)
                return

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

    def _calibrate_regime_engine(self) -> None:
        """Calibrate regime engine emission parameters from event log data.

        Pre-scans quotes in the event log and calls ``calibrate()`` if
        the engine supports it and hasn't already been calibrated (e.g.,
        via restored checkpoint).  Backtest mode has the full dataset
        available; live/paper would use previous-day data.
        """
        if self._regime_engine is None:
            return
        calibrate_fn = getattr(self._regime_engine, "calibrate", None)
        if calibrate_fn is None:
            return
        if getattr(self._regime_engine, "calibrated", False):
            return

        quotes = [
            event for event in self._event_log.replay()
            if isinstance(event, NBBOQuote)
        ]
        if not quotes:
            logger.info(
                "Regime calibration skipped — no quotes in event log"
            )
            return

        ok = calibrate_fn(quotes)
        if ok:
            logger.info(
                "Regime engine calibrated from %d quotes", len(quotes),
            )
        else:
            logger.warning(
                "Regime calibration failed (insufficient data: %d quotes) "
                "— using default emission parameters",
                len(quotes),
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
        engine_name = (
            self._regime_engine_registry_name
            if self._regime_engine_registry_name is not None
            else type(self._regime_engine).__name__
        )
        regime_state = RegimeState(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            symbol=quote.symbol,
            engine_name=engine_name,
            state_names=state_names,
            posteriors=tuple(posteriors),
            dominant_state=dominant_idx,
            dominant_name=state_names[dominant_idx] if dominant_idx < len(state_names) else "unknown",
        )
        self._bus.publish(regime_state)
        self._maybe_publish_hazard_spike(regime_state, correlation_id)

    def _maybe_publish_hazard_spike(
        self,
        regime_state: RegimeState,
        correlation_id: str,
    ) -> None:
        """Detect and publish a RegimeHazardSpike if the detector is wired.

        Pure function of two consecutive RegimeState events from the
        same (symbol, engine_name) channel (§20.3.1, §20.7.3).
        Sequence numbers are drawn from the dedicated _hazard_seq
        generator so enabling hazard exits never perturbs LEGACY or
        SIGNAL parity hashes (Inv-A / C1).
        """
        if self._regime_hazard_detector is None:
            return
        key = (regime_state.symbol, regime_state.engine_name)
        prev = self._last_regime_state.get(key)
        self._last_regime_state[key] = regime_state
        spike = self._regime_hazard_detector.detect(prev, regime_state)
        if spike is None:
            return
        self._bus.publish(RegimeHazardSpike(
            timestamp_ns=spike.timestamp_ns,
            correlation_id=correlation_id,
            sequence=self._hazard_seq.next(),
            symbol=spike.symbol,
            engine_name=spike.engine_name,
            departing_state=spike.departing_state,
            departing_posterior_prev=spike.departing_posterior_prev,
            departing_posterior_now=spike.departing_posterior_now,
            incoming_state=spike.incoming_state,
            hazard_score=spike.hazard_score,
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
        immediately after).  Individual order failures are captured
        rather than silently swallowed; we still proceed through the
        loop so one broken symbol can't block flattening the rest
        (Inv-11: fail-safe).

        After the flatten loop, residual exposure is checked.  If any
        positions remain open — whether from submit exceptions, partial
        fills, or rejected acks — a CRITICAL alert is emitted listing
        every failed symbol so the operator sees exactly which legs
        need manual intervention before LOCKED traps them.
        """
        positions = self._positions.all_positions()
        failures: dict[str, str] = {}
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
                # A reject / zero-fill ack still leaves the position open.
                # Surface it as a failure so the residual alert sees it.
                non_fill_acks = [
                    a for a in acks
                    if a.order_id == order_id
                    and (a.filled_quantity or 0) == 0
                    and a.status in (OrderAckStatus.REJECTED, OrderAckStatus.CANCELLED)
                ]
                if non_fill_acks:
                    failures[symbol] = (
                        f"{non_fill_acks[0].status.name}: "
                        f"{non_fill_acks[0].reason or 'no reason'}"
                    )
            except Exception as exc:
                logger.exception(
                    "Emergency flatten failed for %s (qty=%d) -- "
                    "position may remain open at LOCKED",
                    symbol, pos.quantity,
                )
                failures[symbol] = f"submit_exception: {exc!r}"

        residual = {
            sym: p.quantity
            for sym, p in self._positions.all_positions().items()
            if p.quantity != 0
        }
        if residual or failures:
            msg = (
                f"Emergency flatten incomplete — residual positions: "
                f"{residual}, total_exposure={self._positions.total_exposure()}, "
                f"failures={failures}"
            )
            logger.critical(msg)
            self._bus.publish(Alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                severity=AlertSeverity.CRITICAL,
                layer="kernel",
                alert_name="emergency_flatten_incomplete",
                message=msg,
            ))

    def _check_stop_exit(self, quote: NBBOQuote) -> Signal | None:
        """Check stop-loss and trailing stop for open positions.

        Returns a synthetic FLAT Signal if a stop triggers, None otherwise.
        Also updates peak unrealized P&L tracking for trailing stops.
        """
        if self._stop_loss_per_share <= 0 and self._trail_activate_per_share <= 0:
            return None

        pos = self._positions.get(quote.symbol)
        if pos.quantity == 0:
            self._peak_pnl_per_share.pop(quote.symbol, None)
            return None

        mid = float((quote.bid + quote.ask) / Decimal(2))
        entry = float(pos.avg_entry_price)
        if entry <= 0:
            return None

        sign = 1.0 if pos.quantity > 0 else -1.0
        unrealized_per_share = (mid - entry) * sign

        peak = self._peak_pnl_per_share.get(quote.symbol, unrealized_per_share)
        if unrealized_per_share > peak:
            peak = unrealized_per_share
        self._peak_pnl_per_share[quote.symbol] = peak

        triggered = False

        if self._stop_loss_per_share > 0 and unrealized_per_share < -self._stop_loss_per_share:
            triggered = True

        if (self._trail_activate_per_share > 0
                and peak >= self._trail_activate_per_share
                and unrealized_per_share < peak * self._trail_pct):
            triggered = True

        if not triggered:
            return None

        return Signal(
            timestamp_ns=quote.timestamp_ns,
            correlation_id=quote.correlation_id,
            sequence=quote.sequence,
            symbol=quote.symbol,
            strategy_id="__stop_exit__",
            direction=SignalDirection.FLAT,
            strength=0.0,
            edge_estimate_bps=0.0,
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

        target = self._position_sizer.compute_target_quantity(
            signal=signal,
            risk_budget=risk_budget,
            symbol_price=mid_price,
            account_equity=self._account_equity,
        )

        # H1: Clamp up to min_order_shares to avoid the dead zone where
        # the sizer produces a positive quantity below the gate threshold.
        # "Trade the minimum viable size, or don't trade at all."
        # The risk engine will reject or scale down if the clamped size
        # exceeds the alpha's budget.
        if 0 < target < self._min_order_shares:
            target = self._min_order_shares

        return target

    def _execute_reverse(
        self,
        intent: OrderIntent,
        verdict: RiskVerdict,
        cid: str,
        quote: NBBOQuote,
        t_wall_start: int,
    ) -> None:
        """Execute a REVERSE intent as EXIT(MARKET) + ENTRY(LIMIT).

        H2/H3/H7: Decomposes reversals so the closing leg is aggressive
        (guaranteed fill) and the entry leg is passive (spread savings).
        Prevents position-trapping where a combined passive order sits
        in the queue while the position is stuck in the wrong direction.

        The EXIT leg is always MARKET and bypasses min_order_shares
        (you must be able to close any position).  The ENTRY leg uses
        the normal passive/active mode and is subject to all gates.
        """
        close_qty = abs(intent.current_quantity)
        entry_qty_raw = intent.target_quantity - close_qty

        # ── Cancel any resting orders for this symbol ──────────────
        self._cancel_resting_for_symbol(intent.symbol, cid)

        # ── EXIT leg: aggressive MARKET close ──────────────────────
        exit_side = Side.SELL if intent.current_quantity > 0 else Side.BUY
        seq_exit = self._seq.next()
        exit_order_id = hashlib.sha256(
            f"{cid}:{seq_exit}:exit".encode()
        ).hexdigest()[:16]

        exit_order = OrderRequest(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=cid,
            sequence=seq_exit,
            order_id=exit_order_id,
            symbol=intent.symbol,
            side=exit_side,
            order_type=OrderType.MARKET,
            quantity=close_qty,
            strategy_id=intent.strategy_id,
            is_short=False,
        )

        # Risk check exit (should always pass — reduces exposure).
        exit_verdict = self._risk_engine.check_order(
            exit_order, self._positions,
        )
        self._bus.publish(exit_verdict)
        if exit_verdict.action in (RiskAction.REJECT, RiskAction.FORCE_FLATTEN):
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="reverse_exit_rejected",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        # ── ENTRY leg: passive LIMIT (or MARKET if passive disabled) ─
        #
        # Risk-check the entry leg against a POST-EXIT position view.
        # The exit hasn't filled yet (both legs submit in the same tick),
        # so self._positions still reflects the pre-exit state.  Without
        # the adjustment, check_order computes post_fill_qty from the
        # stale position, producing an incorrectly favorable result
        # (e.g. 0 instead of the actual new-entry quantity).
        entry_order: OrderRequest | None = None
        entry_qty = round(entry_qty_raw * verdict.scaling_factor)

        # Signed adjustment: the exit leg removes close_qty from position.
        exit_signed_adj = -close_qty if exit_side == Side.SELL else close_qty
        post_exit_positions = _PostExitPositionView(
            self._positions, intent.symbol, exit_signed_adj,
        )

        if entry_qty >= self._min_order_shares:
            entry_side = exit_side  # same direction for both legs
            is_short = (
                intent.intent == TradingIntent.REVERSE_LONG_TO_SHORT
            )

            # B4: edge vs cost gate for the entry leg.
            entry_passes_edge_gate = True
            if (
                self._signal_min_edge_cost_ratio > 0
                and self._cost_model is not None
            ):
                gate_price = (quote.bid + quote.ask) / Decimal("2")
                gate_spread = (quote.ask - quote.bid) / Decimal("2")
                is_taker_gate = not self._use_passive_entries
                cost = self._cost_model.compute(
                    intent.symbol, entry_side, entry_qty, gate_price,
                    gate_spread, is_taker=is_taker_gate,
                )
                round_trip_cost_bps = float(cost.cost_bps) * 2
                if intent.signal.edge_estimate_bps < (
                    self._signal_min_edge_cost_ratio * round_trip_cost_bps
                ):
                    entry_passes_edge_gate = False

            if entry_passes_edge_gate:
                seq_entry = self._seq.next()
                entry_order_id = hashlib.sha256(
                    f"{cid}:{seq_entry}:entry".encode()
                ).hexdigest()[:16]

                order_type = OrderType.MARKET
                limit_price: Decimal | None = None
                if self._use_passive_entries:
                    order_type = OrderType.LIMIT
                    limit_price = (
                        quote.bid if entry_side == Side.BUY else quote.ask
                    )

                entry_order = OrderRequest(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=cid,
                    sequence=seq_entry,
                    order_id=entry_order_id,
                    symbol=intent.symbol,
                    side=entry_side,
                    order_type=order_type,
                    quantity=entry_qty,
                    limit_price=limit_price,
                    strategy_id=intent.strategy_id,
                    is_short=is_short,
                )

                # Risk check entry leg against post-exit position view.
                entry_rv = self._risk_engine.check_order(
                    entry_order, post_exit_positions,
                )
                self._bus.publish(entry_rv)
                if entry_rv.action in (
                    RiskAction.REJECT, RiskAction.FORCE_FLATTEN,
                ):
                    entry_order = None
                elif entry_rv.action == RiskAction.SCALE_DOWN:
                    scaled = round(
                        entry_order.quantity * entry_rv.scaling_factor,
                    )
                    if scaled < self._min_order_shares:
                        entry_order = None
                    elif scaled != entry_order.quantity:
                        entry_order = replace(
                            entry_order, quantity=scaled,
                        )

        # ── M6 → M7: ORDER_SUBMIT ─────────────────────────────────
        self._micro.transition(
            MicroState.ORDER_SUBMIT,
            trigger="reverse_orders_constructed",
            correlation_id=cid,
        )

        # Submit EXIT leg.
        self._track_order(exit_order.order_id, exit_order.side, exit_order)
        self._transition_order(
            exit_order.order_id, OrderState.SUBMITTED, "submitted",
        )
        self._backend.order_router.submit(exit_order)
        self._bus.publish(exit_order)

        # Submit ENTRY leg (if valid).
        if entry_order is not None:
            self._track_order(
                entry_order.order_id, entry_order.side, entry_order,
            )
            self._transition_order(
                entry_order.order_id, OrderState.SUBMITTED, "submitted",
            )
            self._backend.order_router.submit(entry_order)
            self._bus.publish(entry_order)

        # ── M7 → M8: ORDER_ACK ────────────────────────────────────
        self._micro.transition(
            MicroState.ORDER_ACK,
            trigger="reverse_orders_submitted",
            correlation_id=cid,
        )
        acks = self._backend.order_router.poll_acks()
        for ack in acks:
            self._bus.publish(ack)
            self._apply_ack_to_order(ack)

        # ── M8 → M9: POSITION_UPDATE ──────────────────────────────
        self._micro.transition(
            MicroState.POSITION_UPDATE,
            trigger="reverse_acks_received",
            correlation_id=cid,
        )
        self._reconcile_fills(acks, cid)

        # ── M9 → M10: LOG_AND_METRICS ─────────────────────────────
        self._micro.transition(
            MicroState.LOG_AND_METRICS,
            trigger="reverse_position_updated",
            correlation_id=cid,
        )
        self._finalize_tick(t_wall_start, cid)

    def _build_order_from_intent(
        self,
        intent: OrderIntent,
        verdict: RiskVerdict,
        correlation_id: str,
        quote: NBBOQuote | None = None,
    ) -> OrderRequest | None:
        """Construct an OrderRequest from an OrderIntent.

        order_id is derived from correlation_id + sequence via SHA-256
        so that replay of identical events produces identical order IDs
        (invariant 5).  uuid4 is forbidden here.

        The intent's ``target_quantity`` is the pre-computed quantity
        from the IntentTranslator (which may include position sizer
        output).  ``verdict.scaling_factor`` is applied on top for
        risk-driven scaling.

        When ``_use_passive_entries`` is set and ``quote`` is provided,
        entry/exit orders use LIMIT at the near BBO.  Stop-loss exits
        always use MARKET (invariant 11: fail-safe).
        """
        side = self._side_from_intent(intent)
        seq = self._seq.next()
        order_id = hashlib.sha256(
            f"{correlation_id}:{seq}".encode()
        ).hexdigest()[:16]

        quantity = round(intent.target_quantity * verdict.scaling_factor)
        if quantity <= 0:
            return None

        # F2: Exits and stop-losses bypass min_order_shares — you must be
        # able to close any position regardless of size (Inv-11 fail-safe).
        is_exit_or_stop = (
            intent.intent == TradingIntent.EXIT
            or intent.signal.strategy_id == "__stop_exit__"
        )
        if not is_exit_or_stop and quantity < self._min_order_shares:
            return None

        # B4: signal edge vs round-trip cost gate.
        # Skip exits and stop-losses (always allow for safety) and when
        # the gate is disabled (ratio == 0) or no cost model / quote.
        if (
            not is_exit_or_stop
            and self._signal_min_edge_cost_ratio > 0
            and self._cost_model is not None
            and quote is not None
        ):
            gate_price = (quote.bid + quote.ask) / Decimal("2")
            gate_spread = (quote.ask - quote.bid) / Decimal("2")
            # F4: Use maker cost when passive entries are enabled —
            # taker assumption overestimates cost for passive strategies.
            is_taker_gate = not self._use_passive_entries
            cost = self._cost_model.compute(
                intent.symbol, side, quantity, gate_price, gate_spread,
                is_taker=is_taker_gate,
            )
            round_trip_cost_bps = float(cost.cost_bps) * 2
            if intent.signal.edge_estimate_bps < (
                self._signal_min_edge_cost_ratio * round_trip_cost_bps
            ):
                return None

        # Determine if this is a short-entry sell (for HTB fee routing).
        is_short = intent.intent in (
            TradingIntent.ENTRY_SHORT,
            TradingIntent.REVERSE_LONG_TO_SHORT,
        ) or (
            intent.intent == TradingIntent.SCALE_UP
            and intent.current_quantity < 0
        )

        order_type = OrderType.MARKET
        limit_price: Decimal | None = None

        if self._use_passive_entries and quote is not None:
            is_stop_exit = intent.signal.strategy_id == "__stop_exit__"
            if not is_stop_exit:
                order_type = OrderType.LIMIT
                limit_price = quote.bid if side == Side.BUY else quote.ask

        return OrderRequest(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            sequence=seq,
            order_id=order_id,
            symbol=intent.symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            strategy_id=intent.strategy_id,
            is_short=is_short,
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

    def _has_pending_order_for_symbol(self, symbol: str) -> bool:
        """True if any non-terminal order exists for this symbol."""
        return any(
            order.symbol == symbol and sm.state not in _TERMINAL_ORDER_STATES
            for sm, _, order in self._active_orders.values()
        )

    def _has_pending_exit_for_symbol(self, symbol: str) -> bool:
        """True if a non-terminal order would close the current position.

        Prevents duplicate exit orders from piling up when the alpha
        keeps emitting FLAT while a prior EXIT is still resting.
        """
        pos = self._positions.get(symbol)
        if pos.quantity == 0:
            return False
        exit_side = Side.SELL if pos.quantity > 0 else Side.BUY
        return any(
            order.symbol == symbol
            and sm.state not in _TERMINAL_ORDER_STATES
            and side == exit_side
            for sm, side, order in self._active_orders.values()
        )

    def _cancel_resting_for_symbol(self, symbol: str, cid: str) -> None:
        """Cancel all non-terminal resting orders for a symbol.

        Calls the router's cancel_order (if available), then polls and
        reconciles the resulting cancel acks so the position store and
        order SMs are current before new legs are submitted.
        """
        cancel_fn = getattr(self._backend.order_router, "cancel_order", None)
        if cancel_fn is None:
            return
        for order_id, (sm, _, order) in list(self._active_orders.items()):
            if order.symbol == symbol and sm.state not in _TERMINAL_ORDER_STATES:
                cancel_fn(order_id)
        cancel_acks = self._backend.order_router.poll_acks()
        if cancel_acks:
            for ack in cancel_acks:
                self._bus.publish(ack)
                self._apply_ack_to_order(ack)
            self._reconcile_fills(cancel_acks, cid)

    def _reconcile_resting_fills(self, cid: str) -> None:
        """Poll and reconcile fills from resting orders.

        Called at tick start (after the quote triggers on_quote on the
        router) to process fills from limit orders posted on previous
        ticks.  Uses the same reconciliation path as normal fills.
        """
        acks = self._backend.order_router.poll_acks()
        if not acks:
            return
        for ack in acks:
            self._bus.publish(ack)
            self._apply_ack_to_order(ack)
        self._reconcile_fills(acks, cid)

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
            # F7: debit cancel/expiry fees even when there is no fill.
            if ack.status in (
                OrderAckStatus.CANCELLED, OrderAckStatus.EXPIRED,
            ) and ack.fees and ack.fees > 0:
                self._positions.debit_fees(ack.symbol, ack.fees)

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
                fees=ack.fees,
            )

            if position.quantity == 0:
                self._peak_pnl_per_share.pop(ack.symbol, None)

            # ── Per-alpha fill attribution (multi-alpha mode) ──
            if (
                self._fill_ledger is not None
                and self._strategy_positions is not None
            ):
                try:
                    alpha_allocs = self._fill_ledger.allocate_fill(
                        ack.order_id,
                        ack.filled_quantity,
                        ack.fill_price,
                        total_fees=ack.fees,
                    )
                except Exception:
                    logger.exception(
                        "Fill attribution failed for order %s — "
                        "falling back to proportional distribution",
                        ack.order_id,
                    )
                    alpha_allocs = []

                if alpha_allocs:
                    for (
                        strat_id, sym, alpha_signed, price, alloc_fees
                    ) in alpha_allocs:
                        self._strategy_positions.update(
                            strat_id, sym, alpha_signed, price,
                            fees=alloc_fees,
                        )
                else:
                    # No attribution record (emergency flatten, stop
                    # exit, or attribution failure).  Distribute the
                    # fill proportionally across all strategy positions
                    # for this symbol to keep strategy and global stores
                    # in sync.
                    self._distribute_fill_to_strategies(
                        ack.symbol, signed_qty, ack.fill_price, ack.fees,
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
                cumulative_fees=position.cumulative_fees,
                cost_bps=ack.cost_bps,
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
                    cost_bps=ack.cost_bps,
                    fees=ack.fees,
                    realized_pnl=position.realized_pnl - prev_realized,
                    correlation_id=order.correlation_id,
                ))

        self._prune_terminal_orders()

    def _distribute_fill_to_strategies(
        self,
        symbol: str,
        signed_qty: int,
        fill_price: Decimal,
        fees: Decimal,
    ) -> None:
        """Distribute a fill proportionally across per-alpha strategy positions.

        Used when no fill-attribution record exists (emergency flatten,
        stop exit, or attribution failure).  Distributes ``signed_qty``
        proportionally to each strategy's current quantity for this
        symbol, keeping global and strategy position stores in sync.

        Uses largest-remainder rounding so the sum of per-alpha deltas
        equals ``signed_qty`` exactly.
        """
        if self._strategy_positions is None:
            return

        strategy_ids = list(self._strategy_positions.strategy_ids())
        if not strategy_ids:
            return

        # Collect each strategy's current quantity for this symbol.
        strategy_qtys: list[tuple[str, int]] = []
        total_abs = 0
        for sid in strategy_ids:
            q = self._strategy_positions.get(sid, symbol).quantity
            if q != 0:
                strategy_qtys.append((sid, q))
                total_abs += abs(q)

        if total_abs == 0:
            return

        # Proportional allocation via largest-remainder.
        abs_fill = abs(signed_qty)
        exact = [abs_fill * abs(q) / total_abs for _, q in strategy_qtys]
        floors = [int(e) for e in exact]
        remainders = [e - f for e, f in zip(exact, floors)]
        deficit = abs_fill - sum(floors)
        indices = sorted(range(len(remainders)), key=lambda i: -remainders[i])
        for i in range(deficit):
            floors[indices[i]] += 1

        # Apply each allocation with the sign matching the fill direction.
        fee_remainder = fees
        for idx, ((sid, q), alloc_qty) in enumerate(
            zip(strategy_qtys, floors, strict=True),
        ):
            if alloc_qty == 0:
                continue
            # Sign: same as the overall fill direction.
            alloc_sign = 1 if signed_qty > 0 else -1
            alloc_fees = Decimal("0")
            if total_abs > 0:
                alloc_fees = (fees * alloc_qty / abs_fill).quantize(
                    Decimal("0.01"),
                )
            fee_remainder -= alloc_fees
            self._strategy_positions.update(
                sid, symbol, alloc_sign * alloc_qty, fill_price,
                fees=alloc_fees,
            )

        # Assign any rounding remainder to the last allocation.
        if fee_remainder != Decimal("0") and strategy_qtys:
            last_sid = strategy_qtys[-1][0]
            last_pos = self._strategy_positions.get(last_sid, symbol)
            last_pos.cumulative_fees += fee_remainder

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

    # ── PR-2b-iii: bus-driven Signal handler ────────────────────────

    def _on_bus_signal(self, event: Event) -> None:
        """Buffer a SIGNAL-layer ``Signal`` for the current tick's M4 drain.

        Filtered for safety / correctness:

        * ``layer != "SIGNAL"`` — Phase-4 PORTFOLIO emits
          ``SizedPositionIntent`` events, not Signals; if a future PR
          starts publishing ``Signal(layer="PORTFOLIO")`` it should not
          enter the per-tick legacy order pipeline (PR-2b-iv will wire
          PORTFOLIO intents through ``RiskEngine.check_sized_intent``).
        * ``strategy_id == "__stop_exit__"`` — synthetic stop-loss signals
          are computed inline at M4 by ``_check_stop_exit`` and merged
          there; routing them through the bus would require the producer
          to mint sequence numbers from the right generator and would
          double-fire.
        * ``alpha_id`` listed in any registered PORTFOLIO's
          ``depends_on_signals`` — these Signals are aggregated by
          ``CompositionEngine`` into ``SizedPositionIntent`` events.
          Translating them into ``OrderRequest`` events here as well
          would double-trade (Inv-11 fail-safe: prefer no order over
          duplicate orders).

        The buffer is cleared at the start of every ``_process_tick_inner``
        call; Signals published in response to the same tick's
        ``bus.publish(quote)`` arrive synchronously before M4 and are
        drained there.
        """
        if not isinstance(event, Signal):
            return
        if event.layer != "SIGNAL":
            return
        if event.strategy_id == "__stop_exit__":
            return
        if self._is_consumed_by_portfolio(event.strategy_id):
            return
        self._signal_buffer.append(event)

    def _is_consumed_by_portfolio(self, alpha_id: str) -> bool:
        """True iff any PORTFOLIO alpha lists ``alpha_id`` in ``depends_on_signals``.

        Lazily computes the union of every registered PORTFOLIO module's
        ``depends_on_signals`` on first call, then caches it as a
        ``frozenset``.  Alphas are registered at bootstrap and never
        added at runtime (registry is sealed before ``boot()``), so the
        cache is invalidation-free.
        """
        if self._consumed_by_portfolio_ids is None:
            consumed: set[str] = set()
            if self._alpha_registry is not None:
                portfolio_alphas_fn = getattr(
                    self._alpha_registry, "portfolio_alphas", None,
                )
                if portfolio_alphas_fn is not None:
                    for module in portfolio_alphas_fn():
                        deps = getattr(module, "depends_on_signals", ())
                        consumed.update(deps)
            self._consumed_by_portfolio_ids = frozenset(consumed)
        return alpha_id in self._consumed_by_portfolio_ids

    def _select_bus_signal(self) -> Signal | None:
        """Pick one Signal from this tick's bus buffer (deterministic).

        The micro-state machine permits at most one ``RISK_CHECK →
        ORDER_DECISION → ORDER_SUBMIT → … → LOG_AND_METRICS`` walk per
        tick (``_MICRO_TRANSITIONS`` in ``feelies.kernel.micro``).  When
        more than one standalone SIGNAL alpha fires on the same tick,
        candidates are passed to ``self._signal_arbitrator`` (default
        :class:`~feelies.alpha.arbitration.EdgeWeightedArbitrator`: FLAT
        privileged, else highest ``edge_estimate_bps * strength``; below
        dead-zone yields ``None``).  Ties break by earliest bus arrival
        (buffer order).  Emits a once-per-process WARNING when multiple
        candidates appear, recommending a PORTFOLIO alpha for explicit
        cross-sectional aggregation.

        Returns ``None`` when the buffer is empty or the arbitrator
        suppresses all candidates.
        """
        if not self._signal_buffer:
            return None
        buf = self._signal_buffer
        if len(buf) > 1 and not self._warned_multi_standalone_signals:
            self._warned_multi_standalone_signals = True
            ids = sorted({s.strategy_id for s in buf})
            logger.warning(
                "orchestrator: %d standalone SIGNAL alphas fired on the "
                "same tick (%s); arbitrating via %s.  Prefer a PORTFOLIO "
                "alpha listing these ids in depends_on_signals for full "
                "multi-alpha aggregation.",
                len(buf),
                ids,
                type(self._signal_arbitrator).__name__,
            )
        return self._signal_arbitrator.arbitrate(buf)

    # ── PR-2b-iv: bus-driven SizedPositionIntent handler ────────────

    def _on_bus_sized_intent(self, event: Event) -> None:
        """Translate a Phase-4 ``SizedPositionIntent`` to per-leg orders.

        Workflow (synchronous side-effect of
        ``bus.publish(intent)`` in ``CompositionEngine``):

        1. Filter the bus event for ``SizedPositionIntent``.
        2. Call :meth:`RiskEngine.check_sized_intent`.  The risk engine
           translates each non-zero ``TargetPosition`` delta into one
           ``OrderRequest`` under per-leg veto semantics (Inv-11: a
           breaching leg is dropped silently — the rest of the intent
           proceeds; degenerate intents trivially yield ``()``).  Symbol
           iteration is lexicographically sorted and ``order_id`` is a
           SHA-256 of ``(intent.correlation_id, intent.sequence, symbol)``
           so per-leg orders are bit-identical across replays (Inv-5).
        3. For every surviving order, track it, mark it submitted, publish
           it on the bus, hand it to ``backend.order_router.submit``, then
           drain ``poll_acks`` and reconcile fills into the position
           store.  This mirrors the ``_execute_reverse`` pattern minus the
           micro-SM transitions: PORTFOLIO orders dispatch at M3
           CROSS_SECTIONAL (the bus callback fires while the micro-SM is
           still *entering* CROSS_SECTIONAL) and do NOT advance the
           SIGNAL-reserved M5 → M10 walk.

        Consequences for SIGNAL/PORTFOLIO coexistence on a single tick:

        * The PR-2b-iii ``depends_on_signals`` skip-rule prevents the
          SIGNAL-bus subscriber from also translating Signals consumed by
          PORTFOLIO alphas — so each strategy_id contributes orders
          through exactly one path, never both (Inv-11 fail-safe: prefer
          no order over duplicate orders).
        * Standalone SIGNAL alphas continue to drive the per-tick
          M5 → M10 walk; PORTFOLIO alphas dispatch their orders here.
          Both can fire on the same tick without contention.

        The risk engine's contract guarantees ``check_sized_intent`` does
        not raise (Inv-11); this handler treats the empty tuple as
        "hold all current positions" and exits silently.
        """
        if not isinstance(event, SizedPositionIntent):
            return
        orders = self._risk_engine.check_sized_intent(event, self._positions)
        if not orders:
            return
        for order in orders:
            self._track_order(order.order_id, order.side, order)
            self._transition_order(
                order.order_id, OrderState.SUBMITTED, "submitted",
            )
            self._backend.order_router.submit(order)
            self._bus.publish(order)
        acks = self._backend.order_router.poll_acks()
        for ack in acks:
            self._bus.publish(ack)
            self._apply_ack_to_order(ack)
        self._reconcile_fills(acks, event.correlation_id)

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

    _REGIME_SNAPSHOT_KEY = "__regime__"
    _REGIME_VERSION_PREFIX = "regime:"

    def _restore_feature_snapshots(self) -> None:
        """Restore regime-engine state from snapshots for warm-start.

        Best-effort: if a snapshot is missing, corrupt, or version-
        incompatible, the regime engine cold-starts.  Snapshot failures
        never block boot.

        Workstream D.2 PR-2b-iv: the legacy per-tick ``feature_engine``
        plumbing was deleted; the feature-snapshot store now persists
        only the regime-engine slot.  Phase-3 deployments rely on
        deterministic cold-start replay for everything else (Inv-5,
        separate ``_seq`` generators per event family).
        """
        if self._feature_snapshots is None:
            return
        self._restore_regime_snapshot()

    def _restore_regime_snapshot(self) -> None:
        if self._feature_snapshots is None or self._regime_engine is None:
            return
        regime_version = (
            self._REGIME_VERSION_PREFIX
            + type(self._regime_engine).__name__
        )
        result = self._feature_snapshots.load(
            self._REGIME_SNAPSHOT_KEY, regime_version,
        )
        if result is None:
            return
        _, data = result
        try:
            self._regime_engine.restore(data)
        except Exception:
            logger.warning(
                "Regime snapshot restore failed -- cold-starting regime engine",
                exc_info=True,
            )

    def _checkpoint_feature_snapshots(self) -> None:
        """Checkpoint regime-engine state.

        Best-effort: snapshot failures do not block shutdown.

        Workstream D.2 PR-2b-iv: with the legacy ``feature_engine``
        deleted, the only writer to the feature-snapshot store is the
        regime engine.  See :meth:`_restore_feature_snapshots` for the
        symmetric warm-start guard.
        """
        if self._feature_snapshots is None:
            return
        self._checkpoint_regime_snapshot()

    def _checkpoint_regime_snapshot(self) -> None:
        if self._feature_snapshots is None or self._regime_engine is None:
            return
        regime_version = (
            self._REGIME_VERSION_PREFIX
            + type(self._regime_engine).__name__
        )
        try:
            data = self._regime_engine.checkpoint()
            checksum = hashlib.sha256(data).hexdigest()
            meta = FeatureSnapshotMeta(
                symbol=self._REGIME_SNAPSHOT_KEY,
                feature_version=regime_version,
                event_count=0,
                last_sequence=0,
                last_timestamp_ns=self._clock.now_ns(),
                checksum=checksum,
            )
            self._feature_snapshots.save(meta, data)
        except Exception:
            logger.warning(
                "Regime snapshot checkpoint failed -- "
                "next boot will cold-start regime engine",
                exc_info=True,
            )
