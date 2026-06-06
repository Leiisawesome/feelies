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
import itertools
import logging
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

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
from feelies.alpha.cost_arithmetic import MIN_MARGIN_RATIO

from feelies.bus.event_bus import EventBus
from feelies.core.clock import Clock
from feelies.core.config import Configuration
from feelies.core.errors import (
    ConfigurationError,
    OrchestratorPipelineAbortError,
    SessionEntryBlockedError,
)
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
    SymbolHalted,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.core.state_machine import StateMachine, TransitionRecord
from feelies.execution.backend import ExecutionBackend
from feelies.execution.cost_model import estimate_round_trip_cost_bps
from feelies.execution.min_cost_policy import (
    MinCostPolicyConfig,
    MinimumCostExecutionPolicy,
)
from feelies.execution.intent import (
    IntentTranslator,
    OrderIntent,
    SignalPositionTranslator,
    TradingIntent,
)
from feelies.execution.order_state import OrderState, create_order_state_machine
from feelies.execution.trading_session import TradingSessionBounds
from feelies.execution.regulatory.borrow_availability import (
    BorrowTier,
    build_borrow_table,
    htb_fee_applies,
    is_short_sale_intent,
)
from feelies.ingestion.data_integrity import (
    DataHealth,
    HaltSignal,
    classify_halt_status,
)
from feelies.ingestion.idle_tick import IdleTick
from feelies.ingestion.normalizer import MarketDataNormalizer
from feelies.kernel.macro import (
    TRADING_MODES,
    MacroState,
    create_macro_state_machine,
)
from feelies.kernel.micro import MicroState, create_micro_state_machine
from feelies.kernel.signal_order_trace import SignalOrderTraceRow
from feelies.monitoring.alerting import AlertManager
from feelies.monitoring.kill_switch import KillSwitch
from feelies.monitoring.paper_session_recorder import PaperSessionRecorder
from feelies.monitoring.telemetry import MetricCollector
from feelies.portfolio.position_store import PositionStore
from feelies.risk.engine import RiskEngine
from feelies.risk.escalation import RiskLevel, create_risk_escalation_machine
from feelies.risk.position_sizer import BudgetBasedSizer, PositionSizer
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.registry import SensorRegistry
from feelies.services.regime_engine import RegimeEngine, regime_posterior_entropy_nats
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

# Stable correlation id for boot-time macro transitions (audit replay).
_PLATFORM_BOOT_CORRELATION_ID = "platform_boot"
_ORCHESTRATOR_SHUTDOWN_CORRELATION_ID = "orchestrator_shutdown"


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
        new_qty = pos.quantity + self._adj
        mark = self.latest_mark(pos.symbol)
        unrealized = Decimal("0")
        if new_qty != 0:
            if mark is not None and mark > 0:
                unrealized = (mark - pos.avg_entry_price) * new_qty
            else:
                unrealized = pos.unrealized_pnl
        return Position(
            symbol=pos.symbol,
            quantity=new_qty,
            avg_entry_price=pos.avg_entry_price,
            realized_pnl=pos.realized_pnl,
            unrealized_pnl=unrealized,
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
        mark = self.latest_mark(self._symbol)
        if mark is None or mark <= 0:
            mark = pos.avg_entry_price
        old_contrib = abs(pos.quantity) * mark
        new_contrib = abs(pos.quantity + self._adj) * mark
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

# BT-5: intents that open or increase exposure (a "new entry").  These are
# suppressed during the post-halt resolution blackout; EXIT and NO_ACTION
# are always permitted (existing positions may always be unwound).
_ENTRY_OPENING_INTENTS: frozenset[TradingIntent] = frozenset({
    TradingIntent.ENTRY_LONG,
    TradingIntent.ENTRY_SHORT,
    TradingIntent.SCALE_UP,
    TradingIntent.REVERSE_LONG_TO_SHORT,
    TradingIntent.REVERSE_SHORT_TO_LONG,
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
      * **PORTFOLIO alphas** (``_on_bus_sized_intent`` + ``_flush_pending_sized_intents``).
        Each ``SizedPositionIntent`` is buffered on the bus, then drained after the
        ``CROSS_SECTIONAL`` bookend: ``RiskEngine.check_sized_intent`` runs under
        micro ``RISK_CHECK`` through ``LOG_AND_METRICS`` (M5–M10) before ``FEATURE_COMPUTE``,
        preserving position updates before the standalone-SIGNAL M4 drain.  Multiple intents
        on the same quote walk ``LOG_AND_METRICS → RISK_CHECK`` between legs.

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
        signal_order_trace_sink: list[SignalOrderTraceRow] | None = None,
        regime_calibration_quotes: Sequence[NBBOQuote] | None = None,
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
        self._signal_order_trace_sink: list[SignalOrderTraceRow] | None = (
            signal_order_trace_sink
        )
        self._paper_session_recorder: PaperSessionRecorder | None = None
        self._quote_tick_in_flight: bool = False
        self._tick_quote_for_trace: NBBOQuote | None = None
        # Last quote that completed M1 with tracing enabled — survives the
        # per-tick ``_tick_quote_for_trace = None`` reset so Trade-driven
        # horizon ticks (which can publish Signals between quotes) still have
        # an anchor row for ``SignalOrderTraceRow`` and so buffer evictions
        # can attribute ``signal_buffer_cleared_unprocessed_at_tick_boundary``.
        self._last_quote_context_for_signal_trace: NBBOQuote | None = None
        self._signal_order_trace_seen_sequences: set[int] = set()
        # Signal sequences first observed while no quote tick is in-flight.
        # These are the only buffered Signals eligible to carry across the
        # next quote boundary (trade-driven/inter-quote HorizonTicks).  Once
        # they reach M4, eligibility is retired so they cannot be processed
        # again on later ticks.
        self._carryover_signal_sequences: set[int] = set()
        # Per-(symbol, engine_name) cache of the most recently
        # observed RegimeState; used as ``prev`` argument to the
        # detector on the next tick.  Cleared by
        # ``_reset_regime_session_state`` at every session_start (along
        # with the hazard detector's suppression set) so a stale prev
        # from a previous session never pairs with a fresh curr — that
        # pairing would otherwise compute a "decay" across the session
        # gap and leak a spurious RegimeHazardSpike (see §20.3.1).
        # The regime engine itself is intentionally NOT reset: its
        # per-symbol HMM posterior is the very state we want to carry
        # across sessions (calibration is done once at boot).
        self._last_regime_state: dict[tuple[str, str], RegimeState] = {}

        self._stop_loss_per_share: float = 0.0
        self._trail_activate_per_share: float = 0.0
        self._stop_loss_pct: float = 0.0
        self._trail_activate_pct: float = 0.0
        self._trail_pct: float = 0.5
        self._peak_pnl_per_share: dict[str, float] = {}
        self._min_order_shares: int = 1
        # Audit F-H-14: default 1.0 (round-trip breakeven) matches
        # ``PlatformConfig.signal_min_edge_cost_ratio``.  0 = gate disabled.
        self._signal_min_edge_cost_ratio: float = 1.0
        # Audit F-H-13: ``"one_way"`` keeps the legacy edge-vs-RT-cost
        # comparison; ``"round_trip"`` (the new default) multiplies the
        # disclosed one-way edge by 2 inside the gate so both sides
        # share the round-trip basis explicitly.
        self._signal_edge_cost_basis: str = "round_trip"
        # B5: reversal edge guard multiplier.  The entry leg of a REVERSE
        # intent is suppressed (flatten-only) unless the signal edge clears
        # this multiple of the combined exit+entry round-trip cost.  0.0
        # disables the guard (legacy flip-on-every-signal behaviour).
        self._reversal_min_edge_cost_multiplier: float = 1.5
        # Audit F-M-22: dedicated threshold for the realized-vs-disclosed
        # cost alert, decoupled from MIN_MARGIN_RATIO.
        self._realized_cost_alert_ratio: float = 1.5
        self._regime_calibration_max_quotes: int | None = None
        self._regime_calibration_quotes: tuple[NBBOQuote, ...] | None = (
            tuple(regime_calibration_quotes)
            if regime_calibration_quotes is not None
            else None
        )

        self._config: Configuration | None = None

        # Per-order lifecycle tracking for Inv-4 enforcement.
        # Maps order_id -> (OrderState SM, Side, OrderRequest).
        self._active_orders: dict[str, tuple[StateMachine[OrderState], Side, OrderRequest]] = {}
        # Maps order_id -> TradingIntent.name at submission time so fill
        # reconciliation can stamp each ``TradeRecord.trading_intent``
        # without re-deriving the intent from fill order (Task 4).  Pruned
        # alongside ``_active_orders``.
        self._order_trading_intent: dict[str, str] = {}
        # Router acks that were drained while waiting for a different
        # order family.  The order-router queue is global, so targeted
        # pollers must buffer unrelated acks instead of stealing them.
        self._deferred_router_acks: list[OrderAck] = []

        # When True, market events arriving from the data source are
        # already present in the event log (replay mode).  Prevents
        # re-appending identical events during backtest replay.
        self._events_prelogged = False
        # When tick-failure recovery cannot transition macro to DEGRADED,
        # stop consuming market events (fail-safe — avoids trading in an
        # unknown macro/micro pairing).
        self._pipeline_abort_requested = False

        # ── BT-5: LULD halt modeling ─────────────────────────────────
        # Symbols currently halted (no fills, entry or exit).  Driven from
        # the Trade tape's halt-on / halt-off condition codes.  The blackout
        # map records, per symbol, the event-time ns until which new ENTRY
        # fills remain suppressed after a resume.  Codes / blackout cached
        # from config in boot(); empty codes ⇒ halt modeling is inert.
        self._halted_symbols: set[str] = set()
        self._halt_blackout_until_ns: dict[str, int] = {}
        self._halt_on_codes: frozenset[int] = frozenset()
        self._halt_off_codes: frozenset[int] = frozenset()
        self._halt_blackout_ns: int = 0

        # ── BT-6: Reg-SHO / SSR short-sale restriction ───────────────
        # Symbols currently SSR-active (sticky for the session): seeded from
        # the daily SSR list at boot, then added to when the Trade tape's
        # SSR-trigger condition codes fire intraday.  Under SSR (refuse_short
        # mode) a short ENTRY fill is refused.  Empty codes + list ⇒ inert.
        self._ssr_active: set[str] = set()
        self._ssr_codes: frozenset[int] = frozenset()
        self._ssr_mode: str = "refuse_short"

        # ── BT-7: static borrow-availability table ────────────────────
        # Per-symbol locate tier (available / hard / unavailable).  Omitted
        # symbols default to AVAILABLE.  Cached from config in boot().
        self._borrow_tier: dict[str, BorrowTier] = {}

        # ── BT-8: MOC strategy routing ────────────────────────────────
        # Set of strategy_ids whose entries route as MOC orders, and a
        # flag indicating whether MOC session bounds were successfully
        # resolved at boot().  Defaulted to empty/False here so configs
        # without ``moc_strategy_ids`` (and tests using minimal configs)
        # do not raise AttributeError on the entry-order path.
        self._moc_strategy_ids: frozenset[str] = frozenset()
        self._moc_bounds_configured: bool = False

        # BT-16: RTH entry-fill suppression + close buying-power phase flip.
        self._trading_session_bounds: TradingSessionBounds | None = None
        self._rth_close_bp_flipped: bool = False

        # When True, entry/exit orders use LIMIT at BBO instead of
        # MARKET.  Stop-loss exits always use MARKET (fail-safe).
        # Set from config via boot().
        self._use_passive_entries = False
        # Optional per-order routing policy (set in boot() when
        # config.execution_mode == "minimum_cost").  When non-None,
        # the order constructor consults the policy for each candidate
        # order and picks LIMIT or MARKET accordingly; otherwise the
        # static ``_use_passive_entries`` flag governs.
        self._min_cost_policy: MinimumCostExecutionPolicy | None = None

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
        self._pending_sized_intents: deque[SizedPositionIntent] = deque()
        self._consumed_by_portfolio_ids: frozenset[str] | None = None
        self._warned_multi_standalone_signals: bool = False
        self._bus.subscribe(Signal, self._on_bus_signal)

        # ── PR-2b-iv: bus-driven SizedPositionIntent subscriber ─────────
        # Phase-4 ``CompositionEngine`` publishes one
        # ``SizedPositionIntent`` per registered PORTFOLIO alpha at every
        # horizon boundary (a synchronous side-effect of scheduler-driven
        # ``bus.publish(HorizonTick)`` during ``_dispatch_sensor_layer``).
        # Pre-PR-2b-iv nothing
        # translated those intents into ``OrderRequest`` events: PORTFOLIO
        # alphas were hooked into the bus end-to-end for SizedPositionIntent
        # but the production order pipeline simply ignored them.
        #
        # ``_on_bus_sized_intent`` **buffers** each
        # ``SizedPositionIntent``; :meth:`_flush_pending_sized_intents`
        # drains the queue after the ``CROSS_SECTIONAL`` bookend (still
        # before ``FEATURE_COMPUTE``) so M5 → M10 transitions record
        # PORTFOLIO execution on the same micro SM.  This preserves the
        # causal order vs standalone SIGNAL alphas (positions updated before
        # M4).  PR-2b-iii ``depends_on_signals`` skip-rule still prevents
        # double-trading.
        self._bus.subscribe(SizedPositionIntent, self._on_bus_sized_intent)

        # ── Audit R1: hazard-exit submission dedup ────────────────────
        # ``_active_orders`` is pruned on FILLED (so memory doesn't
        # grow unboundedly in long-running live sessions), but that
        # also means it cannot serve as a long-lived idempotency set
        # for the hazard handler — a duplicate publish AFTER the fill
        # would re-submit.  Track every hazard ``order_id`` we have
        # ever forwarded to the router in this run; the controller's
        # SHA-256 ``order_id`` derivation is collision-free per
        # ``(correlation_id, trigger_ts_ns, symbol, reason)`` so this
        # set never grows past one entry per (episode, symbol, reason).
        self._hazard_submitted_order_ids: set[str] = set()

        # ── Audit R1: bus-driven hazard-exit OrderRequest subscriber ──
        # ``HazardExitController`` publishes ``OrderRequest`` events
        # with ``source_layer="RISK"`` and ``reason in {"HAZARD_SPIKE",
        # "HARD_EXIT_AGE"}`` directly on the bus (no router call —
        # see risk/hazard_exit.py:_emit_exit).  Pre-fix, no production
        # subscriber routed those orders to ``backend.order_router``,
        # so the entire hazard-exit subsystem was effectively inert
        # in any orchestrator-composed deployment (the only subscriber
        # was the metrics collector).  ``_on_bus_hazard_order`` filters
        # to *exactly* the controller's signature and runs the same
        # submit → poll_acks → reconcile_fills flow used by
        # ``_emergency_flatten_all`` (which also bypasses ``check_order``
        # by design — Inv-11 fail-safe: an exit-direction order may
        # never *increase* exposure, so the per-symbol cap and gross
        # exposure cap cannot be breached by it).  Per-leg attribution
        # lands in ``_reconcile_fills`` exactly as for SIGNAL-driven
        # exits.  The subscriber is registered unconditionally; in
        # deployments without a hazard detector the bus simply never
        # sees a hazard-tagged ``OrderRequest`` so this handler is a
        # no-op (Inv-A: pre-R1 baselines bit-identical).
        self._bus.subscribe(OrderRequest, self._on_bus_hazard_order)

    # ── Optional SIGNAL → order diagnostic sink ─────────────────────

    def _append_signal_order_trace(
        self,
        quote: NBBOQuote,
        signal: Signal,
        *,
        outcome: Literal["ORDER_SUBMITTED", "NO_ORDER"],
        reasons: tuple[str, ...],
        trading_intent: str | None = None,
    ) -> None:
        sink = self._signal_order_trace_sink
        if sink is None:
            return
        sink.append(
            SignalOrderTraceRow(
                quote_timestamp_ns=quote.timestamp_ns,
                quote_correlation_id=quote.correlation_id,
                quote_sequence=quote.sequence,
                signal_sequence=signal.sequence,
                signal_timestamp_ns=int(signal.timestamp_ns),
                strategy_id=signal.strategy_id,
                symbol=signal.symbol,
                signal_direction=signal.direction.name,
                trading_intent=(
                    trading_intent if trading_intent is not None else "—"
                ),
                outcome=outcome,
                reasons=reasons,
            )
        )
        self._signal_order_trace_seen_sequences.add(signal.sequence)

    def _trace_buffered_signals_arbitration(
        self,
        quote: NBBOQuote,
        buf_snapshot: list[Signal],
        bus_selected: Signal | None,
        stop_signal: Signal | None,
    ) -> None:
        if self._signal_order_trace_sink is None or not buf_snapshot:
            return
        if stop_signal is not None:
            for s in buf_snapshot:
                self._append_signal_order_trace(
                    quote,
                    s,
                    outcome="NO_ORDER",
                    reasons=("superseded_by_inline_stop_exit",),
                )
            return
        if bus_selected is None:
            for s in buf_snapshot:
                self._append_signal_order_trace(
                    quote,
                    s,
                    outcome="NO_ORDER",
                    reasons=(
                        "arbitration_returned_none_dead_zone_or_conflict",
                    ),
                )
            return
        for s in buf_snapshot:
            if s is bus_selected:
                continue
            self._append_signal_order_trace(
                quote,
                s,
                outcome="NO_ORDER",
                reasons=(
                    "not_selected_in_arbitration_winner_is:"
                    f"{bus_selected.strategy_id}",
                ),
            )

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

    @property
    def trade_journal(self) -> TradeJournal | None:
        return self._trade_journal

    @property
    def position_store(self) -> PositionStore:
        return self._positions

    @property
    def account_equity(self) -> Decimal:
        return self._account_equity

    @property
    def metric_collector(self) -> MetricCollector:
        return self._metrics

    @property
    def kill_switch(self) -> KillSwitch | None:
        return self._kill_switch

    @property
    def alpha_registry(self) -> AlphaRegistry | None:
        return self._alpha_registry

    def set_paper_session_recorder(
        self, recorder: PaperSessionRecorder | None,
    ) -> None:
        """Attach a forensic session recorder (PAPER mode only)."""
        self._paper_session_recorder = recorder

    def _require_safe_session_entry(self) -> None:
        """Fail closed before operational macro modes (Inv-11).

        Applies to ``run_research``, ``run_backtest``, ``run_paper``, and
        ``run_live`` — kill switch and risk escalation must both allow entry.
        """
        if self._kill_switch is not None and self._kill_switch.is_active:
            raise SessionEntryBlockedError(
                "Cannot start session: kill switch is active — "
                "reset with operator audit first",
            )
        if self._risk_escalation.state != RiskLevel.NORMAL:
            raise SessionEntryBlockedError(
                f"Cannot start session: risk escalation is "
                f"{self._risk_escalation.state.name}, must be NORMAL — "
                "use reset_risk_escalation() or unlock_from_lockdown()",
            )

    def _bind_router_position_qty_for_rth(self) -> None:
        """BT-16: wire signed live position qty into the router's RTH gate.

        The router-side :class:`RthEntryFillGate` defaults ``current_qty``
        to 0 when unbound, which would mis-classify exit fills as new
        entries and suppress them after RTH close (violating Inv-11 for
        the execution layer).  Binding is a no-op when RTH gating is
        disabled (``_trading_session_bounds is None``) or when the
        backend's router does not expose ``bind_position_qty``
        (e.g. live broker routers without the hook).
        """
        if self._trading_session_bounds is None:
            return
        router = getattr(self._backend, "order_router", None)
        bind = getattr(router, "bind_position_qty", None)
        if not callable(bind):
            return
        bind(lambda sym: self._positions.get(sym).quantity)

    def _maybe_flip_buying_power_at_rth_close(self, quote: NBBOQuote) -> None:
        """BT-16: flip risk-engine buying-power phase at RTH close.

        Once-per-session: the first quote with
        ``exchange_timestamp_ns >= rth_close_ns`` transitions the risk
        engine to :attr:`BuyingPowerPhase.OVERNIGHT` so the 2× overnight
        multiplier is applied to any exits that linger past the close.
        Compared against ``exchange_timestamp_ns`` rather than
        ``timestamp_ns`` so the flip aligns with the exchange-time RTH
        close used by router-side entry gating
        (``BacktestOrderRouter`` / ``PassiveLimitOrderRouter`` and
        :class:`TradingSessionBounds`).  No-op when RTH gating is
        disabled, the flip has already fired this session, or the risk
        engine does not expose ``set_buying_power_phase``.
        """
        if self._rth_close_bp_flipped:
            return
        bounds = self._trading_session_bounds
        if bounds is None:
            return
        if quote.exchange_timestamp_ns < bounds.rth_close_ns:
            return
        set_phase = getattr(self._risk_engine, "set_buying_power_phase", None)
        if not callable(set_phase):
            self._rth_close_bp_flipped = True
            return
        from feelies.risk.buying_power import BuyingPowerPhase

        set_phase(BuyingPowerPhase.OVERNIGHT)
        self._rth_close_bp_flipped = True

    def _reset_buying_power_phase_for_session(self) -> None:
        """BT-16: reset the once-per-session RTH-close BP flip state.

        Clears the latch that gates :meth:`_maybe_flip_buying_power_at_rth_close`
        and forces the risk engine back onto
        :attr:`BuyingPowerPhase.INTRADAY` so a new session always opens
        on the 4× intraday cap — even when the same orchestrator
        instance is reused across runs and the previous run left the
        engine flipped to ``OVERNIGHT`` after crossing the close.
        """
        self._rth_close_bp_flipped = False
        set_phase = getattr(self._risk_engine, "set_buying_power_phase", None)
        if callable(set_phase):
            from feelies.risk.buying_power import BuyingPowerPhase

            set_phase(BuyingPowerPhase.INTRADAY)

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
            # Percentage-based stops override the per-share fields when set.
            # The actual per-share threshold can only be derived at fill time
            # (it depends on entry price), so we cache the pct and convert in
            # ``_check_stop_exit`` against the position's ``avg_entry_price``.
            if hasattr(config, "stop_loss_pct"):
                self._stop_loss_pct = config.stop_loss_pct
            if hasattr(config, "trail_activate_pct"):
                self._trail_activate_pct = config.trail_activate_pct
            if hasattr(config, "trail_pct"):
                self._trail_pct = config.trail_pct
            # BT-5: cache halt-detection config (empty codes ⇒ inert).
            if hasattr(config, "halt_on_condition_codes"):
                self._halt_on_codes = frozenset(config.halt_on_condition_codes)
            if hasattr(config, "halt_off_condition_codes"):
                self._halt_off_codes = frozenset(config.halt_off_condition_codes)
            if hasattr(config, "halt_resolution_blackout_seconds"):
                self._halt_blackout_ns = (
                    int(config.halt_resolution_blackout_seconds) * 1_000_000_000
                )
            # BT-6: seed the daily SSR list + cache the intraday trigger codes.
            if hasattr(config, "ssr_active_symbols"):
                self._ssr_active = {
                    s.upper() for s in config.ssr_active_symbols
                }
            if hasattr(config, "ssr_trigger_condition_codes"):
                self._ssr_codes = frozenset(config.ssr_trigger_condition_codes)
            if hasattr(config, "ssr_mode"):
                self._ssr_mode = config.ssr_mode
            if hasattr(config, "borrow_availability"):
                self._borrow_tier = build_borrow_table(config.borrow_availability)
            if hasattr(config, "moc_strategy_ids"):
                self._moc_strategy_ids = frozenset(config.moc_strategy_ids)
                if config.moc_strategy_ids:
                    from feelies.execution.moc_session import (
                        build_moc_bounds_from_platform,
                    )

                    _event_cal = getattr(config, "event_calendar_path", None)
                    cal_path = (
                        str(_event_cal) if _event_cal is not None else None
                    )
                    self._moc_bounds_configured = (
                        build_moc_bounds_from_platform(
                            moc_session_date=getattr(
                                config, "moc_session_date", None,
                            ),
                            event_calendar_path=cal_path,
                            moc_cutoff_et=getattr(
                                config, "moc_cutoff_et", "15:50",
                            ),
                            official_close_et=getattr(
                                config, "official_close_et", "16:00",
                            ),
                            early_close_dates=getattr(
                                config, "early_close_dates", (),
                            ),
                            early_close_moc_cutoff_et=getattr(
                                config, "early_close_moc_cutoff_et", "12:50",
                            ),
                            early_close_official_close_et=getattr(
                                config, "early_close_official_close_et", "13:00",
                            ),
                        )
                        is not None
                    )
            if getattr(config, "rth_session_gating_enabled", False):
                from feelies.execution.trading_session import (
                    build_trading_session_from_platform,
                )

                _event_cal = getattr(config, "event_calendar_path", None)
                cal_path = (
                    str(_event_cal) if _event_cal is not None else None
                )
                self._trading_session_bounds = build_trading_session_from_platform(
                    rth_session_gating_enabled=True,
                    rth_session_date=(
                        getattr(config, "rth_session_date", None)
                        or getattr(config, "moc_session_date", None)
                    ),
                    event_calendar_path=cal_path,
                    rth_open_et=getattr(config, "rth_open_et", "09:30"),
                    rth_close_et=getattr(config, "rth_close_et", "16:00"),
                    early_close_dates=getattr(config, "early_close_dates", ()),
                    early_close_rth_close_et=getattr(
                        config, "early_close_rth_close_et", "13:00",
                    ),
                    market_holiday_dates=getattr(
                        config, "market_holiday_dates", (),
                    ),
                    no_entry_first_seconds=getattr(
                        config, "no_entry_first_seconds", 0,
                    ),
                )
            if hasattr(config, "execution_mode"):
                # passive_limit and minimum_cost both wire through the
                # passive-limit backend.  The static flag tells the
                # rest of the orchestrator (resting-fill reconciliation,
                # duplicate-passive-order guard) to expect resting
                # orders.  ``minimum_cost`` additionally constructs a
                # per-order policy that may override the choice on a
                # per-order basis.
                self._use_passive_entries = config.execution_mode in (
                    "passive_limit", "minimum_cost",
                )
                if (
                    config.execution_mode == "minimum_cost"
                    and self._cost_model is not None
                ):
                    self._min_cost_policy = MinimumCostExecutionPolicy(
                        cost_model=self._cost_model,
                        config=MinCostPolicyConfig(
                            prefer_passive_bias_bps=Decimal(
                                str(getattr(
                                    config, "cost_min_passive_bias_bps", 0.0,
                                ))
                            ),
                            small_order_aggressive_threshold_shares=int(
                                getattr(
                                    config,
                                    "cost_min_small_order_threshold_shares",
                                    0,
                                )
                            ),
                            min_half_spread_for_passive=Decimal(
                                str(getattr(
                                    config,
                                    "cost_min_half_spread_threshold",
                                    0.0,
                                ))
                            ),
                            allow_passive_short_entry=bool(
                                getattr(
                                    config,
                                    "cost_min_allow_passive_short_entry",
                                    True,
                                )
                            ),
                            market_impact_factor=Decimal(str(getattr(
                                config, "cost_market_impact_factor", 0.5,
                            ))),
                            max_impact_half_spreads=Decimal(str(getattr(
                                config, "cost_max_impact_half_spreads", 10.0,
                            ))),
                            passive_non_fill_probability=Decimal(str(getattr(
                                config,
                                "cost_min_passive_non_fill_probability",
                                0.30,
                            ))),
                        ),
                    )
            if hasattr(config, "platform_min_order_shares"):
                self._min_order_shares = config.platform_min_order_shares
            if hasattr(config, "signal_min_edge_cost_ratio"):
                self._signal_min_edge_cost_ratio = config.signal_min_edge_cost_ratio
            if hasattr(config, "reversal_min_edge_cost_multiplier"):
                self._reversal_min_edge_cost_multiplier = (
                    config.reversal_min_edge_cost_multiplier
                )
            if hasattr(config, "signal_edge_cost_basis"):
                self._signal_edge_cost_basis = config.signal_edge_cost_basis
            if hasattr(config, "realized_cost_alert_ratio"):
                self._realized_cost_alert_ratio = config.realized_cost_alert_ratio
            if hasattr(config, "regime_calibration_max_quotes"):
                self._regime_calibration_max_quotes = (
                    config.regime_calibration_max_quotes
                )
            self._macro.transition(
                MacroState.DATA_SYNC,
                trigger="CONFIG_VALIDATED",
                correlation_id=_PLATFORM_BOOT_CORRELATION_ID,
            )
        except ConfigurationError as exc:
            self._macro.transition(
                MacroState.SHUTDOWN,
                trigger=f"CONFIG_ERROR:{exc}",
                correlation_id=_PLATFORM_BOOT_CORRELATION_ID,
            )
            return

        if self._verify_data_integrity():
            self._macro.transition(
                MacroState.READY,
                trigger="DATA_INTEGRITY_OK",
                correlation_id=_PLATFORM_BOOT_CORRELATION_ID,
            )
            self._restore_feature_snapshots()
            self._calibrate_regime_engine()
            self._pending_sized_intents.clear()
        else:
            self._macro.transition(
                MacroState.DEGRADED,
                trigger="DATA_INTEGRITY_FAIL",
                correlation_id=_PLATFORM_BOOT_CORRELATION_ID,
            )

    def run_backtest(self) -> None:
        """G2 → G4 → pipeline → G2.

        Guard: backtest config valid; kill switch inactive; risk NORMAL.
        """
        self._macro.assert_state(MacroState.READY)
        self._require_safe_session_entry()
        self._pipeline_abort_requested = False
        self._micro.reset(trigger="session_start:backtest")
        self._reset_buying_power_phase_for_session()
        self._bind_router_position_qty_for_rth()
        self._pending_sized_intents.clear()
        self._consumed_by_portfolio_ids = None
        self._reset_regime_session_state()
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
        Normal completion (feed iterator exhausted without exception)
        returns macro to **READY** — same hub state as ``run_backtest``.
        Exceptions during the pipeline transition to **DEGRADED** and
        re-raise.
        """
        self._macro.assert_state(MacroState.READY)
        self._require_safe_session_entry()
        self._pipeline_abort_requested = False
        self._micro.reset(trigger="session_start:paper")
        self._reset_buying_power_phase_for_session()
        self._bind_router_position_qty_for_rth()
        self._pending_sized_intents.clear()
        self._consumed_by_portfolio_ids = None
        self._reset_regime_session_state()
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
                MacroState.READY,
                trigger="SESSION_FEED_COMPLETE",
            )

    def run_live(self) -> None:
        """G2 → G6 → pipeline.

        Guard: human approval + risk audit pass; kill switch inactive.
        Inv-3: R4 (LOCKED) forbids this — must pass through G2 first,
        which is structurally guaranteed (G8 → G2 → G6).
        Normal completion (feed iterator exhausted without exception)
        returns macro to **READY**. Exceptions transition to **DEGRADED**.
        """
        self._macro.assert_state(MacroState.READY)
        self._require_safe_session_entry()
        self._pipeline_abort_requested = False
        self._micro.reset(trigger="session_start:live")
        self._reset_buying_power_phase_for_session()
        self._bind_router_position_qty_for_rth()
        self._pending_sized_intents.clear()
        self._reset_regime_session_state()
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
                MacroState.READY,
                trigger="SESSION_FEED_COMPLETE",
            )

    def run_research(self, job: Callable[[], None]) -> None:
        """G2 → G3 → job() → G2.

        Research mode does not run the tick pipeline.  The caller
        provides a job (backtest variant, data exploration, etc.)
        that executes within the RESEARCH_MODE macro state.
        """
        self._macro.assert_state(MacroState.READY)
        self._require_safe_session_entry()
        self._pipeline_abort_requested = False
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
        """CMD_STOP: any trading mode → G2.

        Resets the micro state machine so the next session starts from a
        defined WAITING baseline (audit remediation — avoids stranded
        mid-pipeline micro states after an operator halt).
        """
        if self._macro.state in TRADING_MODES:
            self._macro.transition(MacroState.READY, trigger="CMD_STOP")
            self._micro.reset(trigger="halt:operator_stop")
            self._pending_sized_intents.clear()

    def recover_from_degraded(self) -> bool:
        """G7 → G2 on recovery validation.  Returns True if successful."""
        self._macro.assert_state(MacroState.DEGRADED)
        if self._kill_switch is not None and self._kill_switch.is_active:
            logger.warning(
                "recover_from_degraded: refused — kill switch is still active",
            )
            return False
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
        risk at LOCKED is fail-safe — session-entry guard blocks
        ``run_*`` until resolved.  The reverse
        (risk at NORMAL, macro at RISK_LOCKDOWN) would break the
        retry path because the next unlock_from_lockdown attempt
        would try R4→R0 from R0, raising IllegalTransition.

        When ``_escalate_risk`` activated the kill switch, this method
        also resets it with the same audit token so ticks do not
        immediately re-enter DEGRADED on kill-switch polling.
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
        # Risk escalation activates the kill switch in `_escalate_risk`.
        # Clearing it here keeps macro/risk/kill-switch semantics coherent
        # so the next quote tick does not immediately re-enter DEGRADED.
        if self._kill_switch is not None and self._kill_switch.is_active:
            self._kill_switch.reset(
                operator="unlock_from_lockdown",
                audit_token=audit_token,
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

        ``CANCEL_REQUESTED`` orders (e.g. abandoned when no router cancel
        API existed in an older build) are transitioned to ``CANCELLED``
        best-effort before the pending-order scan so shutdown reflects
        local operator intent.

        Allowed from **RISK_LOCKDOWN** via ``CMD_SHUTDOWN`` so operators
        can tear down the process without a prior unlock when needed.
        """
        # Final fill drain (Inv-9 paper/live) — picks up any broker
        # ack that landed between the last quote and the operator's
        # halt() so the CANCEL_REQUESTED resolution + pending-orders
        # scan below act on the freshest order state.  Defensive
        # ``_backend is not None`` for partially-constructed test
        # orchestrators; production paths always have a backend.
        if self._backend is not None:
            # BT-8: terminate MOC orders that never received a
            # closing-auction print so they don't survive shutdown
            # as ACKNOWLEDGED-but-never-filled (Inv-4 hygiene).
            expire_moc = getattr(
                self._backend.order_router, "expire_pending_moc", None,
            )
            if expire_moc is not None:
                expire_moc()
            self._drain_async_fills(correlation_id="shutdown")
        self._checkpoint_feature_snapshots()
        # Resolve operator cancel intent when no broker ack will arrive
        # (e.g. mid backtest router has no cancel_order API).
        for oid, (sm, _, order) in list(self._active_orders.items()):
            if sm.state != OrderState.CANCEL_REQUESTED:
                continue
            if sm.can_transition(OrderState.CANCELLED):
                sm.transition(
                    OrderState.CANCELLED,
                    trigger="shutdown_resolve_cancel_requested",
                    correlation_id=order.correlation_id,
                )
        self._prune_terminal_orders()

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
            self._macro.transition(
                MacroState.SHUTDOWN,
                trigger="CMD_SHUTDOWN",
                correlation_id=_ORCHESTRATOR_SHUTDOWN_CORRELATION_ID,
            )
        self._metrics.flush()

    # ── Pipeline: the deterministic tick loop ───────────────────────

    def _run_pipeline(self) -> None:
        """Execute the deterministic micro-state loop over all market events.

        Inv-2: breaks when macro state leaves TRADING_MODES.

        Dispatches by event type: NBBOQuote drives the full signal
        pipeline; Trade events are logged and published for
        observability but do not trigger signal evaluation;
        :class:`IdleTick` triggers the async fill drain only (no
        micro-SM transition, no bus publish, no EventLog append) so
        broker-pushed fills from :class:`IBOrderRouter` are reconciled
        when the live feed is between frames (Inv-9 paper/live;
        BACKTEST feeds never emit ``IdleTick`` — Inv-A preserved).
        """
        for event in self._backend.market_data.events():
            if self._pipeline_abort_requested:
                break
            if self._macro.state not in TRADING_MODES:
                break
            if isinstance(event, NBBOQuote):
                self._process_tick(event)
            elif isinstance(event, Trade):
                self._process_trade(event)
            elif isinstance(event, IdleTick):
                if self._paper_session_recorder is not None:
                    self._paper_session_recorder.record_idle_tick()
                self._drain_async_fills(
                    correlation_id=f"idle:{event.timestamp_ns}",
                )

        if self._pipeline_abort_requested:
            raise OrchestratorPipelineAbortError(
                "Tick failure recovery could not transition macro to DEGRADED "
                "(transition callback raised); pipeline aborted fail-safe."
            )

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
        # BT-5: detect halt-on / resume from the trade tape before the
        # data-health gate so a halt is registered even when the symbol's
        # quote feed is otherwise quiet.
        self._update_halt_state(trade)
        # BT-6: detect an intraday SSR trigger from the same tape.
        self._update_ssr_state(trade)

        if self._data_health_blocks_trading(trade.symbol, trade.correlation_id):
            return

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

    def _maybe_transition_cross_sectional_bookend(self, correlation_id: str) -> None:
        """Record ``MicroState.CROSS_SECTIONAL`` after the bus composition chain.

        ``UniverseSynchronizer`` / ``CompositionEngine`` run synchronously
        inside the ``HorizonTick`` handler stack (``_dispatch_sensor_layer``).
        This transition is a forensic bookend only — it does not re-invoke
        composition.  It is emitted when a **registered PORTFOLIO alpha**
        exists **or** a :class:`~feelies.composition.engine.CompositionEngine`
        is attached (test / partial deployments), and the micro SM can legally
        enter ``CROSS_SECTIONAL`` from the current horizon state (typically
        ``HORIZON_AGGREGATE`` or ``SIGNAL_GATE``).
        """
        registry_portfolio = (
            self._alpha_registry is not None
            and self._alpha_registry.has_portfolio_alphas()
        )
        if not registry_portfolio and self._composition_engine is None:
            return
        if not self._micro.can_transition(MicroState.CROSS_SECTIONAL):
            return
        self._micro.transition(
            MicroState.CROSS_SECTIONAL,
            trigger="composition_pipeline_bookend",
            correlation_id=correlation_id,
        )

    def _flush_pending_sized_intents(
        self,
        *,
        correlation_id: str,
    ) -> None:
        """Drain horizon-buffered PORTFOLIO intents under micro M5–M10 before M3."""
        if not self._pending_sized_intents:
            return
        first_intent = True
        while self._pending_sized_intents:
            intent = self._pending_sized_intents.popleft()
            if first_intent:
                first_intent = False
                if self._micro.state is MicroState.CROSS_SECTIONAL:
                    self._micro.transition(
                        MicroState.RISK_CHECK,
                        trigger="portfolio_sized_intent",
                        correlation_id=correlation_id,
                    )
                elif self._micro.can_transition(MicroState.RISK_CHECK):
                    self._micro.transition(
                        MicroState.RISK_CHECK,
                        trigger="portfolio_sized_intent_resume",
                        correlation_id=correlation_id,
                    )
                else:
                    logger.warning(
                        "orchestrator: portfolio flush blocked at micro state "
                        "%s — submitting without SM transitions",
                        self._micro.state.name,
                    )
                    self._submit_portfolio_leg_without_micro_walk(
                        intent, correlation_id,
                    )
                    while self._pending_sized_intents:
                        nxt = self._pending_sized_intents.popleft()
                        self._submit_portfolio_leg_without_micro_walk(
                            nxt, correlation_id,
                        )
                    return
            else:
                self._micro.transition(
                    MicroState.RISK_CHECK,
                    trigger="portfolio_sized_intent_next",
                    correlation_id=correlation_id,
                )

            sized = self._risk_engine.check_sized_intent(intent, self._positions)
            if sized.requires_global_risk_escalation:
                self._escalate_risk(correlation_id)
                self._micro.transition(
                    MicroState.LOG_AND_METRICS,
                    trigger="portfolio_intent_risk_escalation",
                    correlation_id=correlation_id,
                )
                continue
            orders: list[OrderRequest] = list(sized.orders)
            if not orders:
                self._micro.transition(
                    MicroState.LOG_AND_METRICS,
                    trigger="portfolio_intent_no_orders",
                    correlation_id=correlation_id,
                )
                continue

            orders = self._filter_portfolio_orders_for_pending_conflicts(
                orders,
                intent=intent,
                correlation_id=correlation_id,
            )
            if not orders:
                self._micro.transition(
                    MicroState.LOG_AND_METRICS,
                    trigger="portfolio_intent_all_legs_skipped_pending",
                    correlation_id=correlation_id,
                )
                continue

            self._micro.transition(
                MicroState.ORDER_DECISION,
                trigger="portfolio_orders_ready",
                correlation_id=correlation_id,
            )
            self._micro.transition(
                MicroState.ORDER_SUBMIT,
                trigger="portfolio_batch_submitted",
                correlation_id=correlation_id,
            )
            for order in orders:
                self._track_order(order.order_id, order.side, order)
                self._transition_order(
                    order.order_id, OrderState.SUBMITTED, "submitted",
                )
                self._backend.order_router.submit(order)
                self._bus.publish(order)

            self._micro.transition(
                MicroState.ORDER_ACK,
                trigger="portfolio_poll_acks",
                correlation_id=correlation_id,
            )
            expected_order_ids = {o.order_id for o in orders}
            acks = self._poll_order_router_acks(expected_order_ids)
            for ack in acks:
                self._bus.publish(ack)
                self._apply_ack_to_order(ack)

            self._micro.transition(
                MicroState.POSITION_UPDATE,
                trigger="portfolio_reconcile",
                correlation_id=correlation_id,
            )
            self._reconcile_fills(acks, correlation_id)

            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="portfolio_leg_complete",
                correlation_id=correlation_id,
            )

    def _submit_portfolio_leg_without_micro_walk(
        self,
        intent: SizedPositionIntent,
        correlation_id: str,
    ) -> None:
        """Fail-safe submit when micro cannot enter ``RISK_CHECK`` (should be rare)."""
        sized = self._risk_engine.check_sized_intent(intent, self._positions)
        if sized.requires_global_risk_escalation:
            self._escalate_risk(correlation_id)
            return
        orders: list[OrderRequest] = list(sized.orders)
        if not orders:
            return
        orders = self._filter_portfolio_orders_for_pending_conflicts(
            orders,
            intent=intent,
            correlation_id=correlation_id,
        )
        if not orders:
            return
        for order in orders:
            self._track_order(order.order_id, order.side, order)
            self._transition_order(
                order.order_id, OrderState.SUBMITTED, "submitted",
            )
            self._backend.order_router.submit(order)
            self._bus.publish(order)
        acks = self._poll_order_router_acks({o.order_id for o in orders})
        for ack in acks:
            self._bus.publish(ack)
            self._apply_ack_to_order(ack)
        self._reconcile_fills(acks, correlation_id)
    def _process_tick(self, quote: NBBOQuote) -> None:
        """Process a single tick through the full micro-state pipeline.

        This method is IDENTICAL in G4, G5, and G6.  The only
        mode-specific behavior is inside ExecutionBackend (platform inv 9).

        Micro-state sequence (formal spec Section II):
          M0 → M1 → M2 → M3 → M4 → M5 →
            (lockdown FORCE_FLATTEN) → M10 → M0  (via ``_finalize_tick``)
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
        self._quote_tick_in_flight = True
        try:
            self._process_tick_inner(quote)
        except Exception as exc:
            self._handle_tick_failure(cid, exc)
        finally:
            self._quote_tick_in_flight = False

    def _handle_tick_failure(self, cid: str, original: Exception) -> None:
        """Recover micro SM and degrade macro after a tick-processing failure.

        The handler itself must not throw — if reset() or the macro
        transition fails, we still degrade to the safest reachable
        state.  The original exception's type name is captured in the
        trigger for provenance (invariant 13).

        If the macro ``DEGRADED`` transition raises (e.g. subscriber
        veto), ``_pipeline_abort_requested`` is set and :meth:`_run_pipeline`
        raises :class:`~feelies.core.errors.OrchestratorPipelineAbortError`
        so callers do not treat the loop as normally exhausted.
        """
        exc_name = type(original).__name__

        try:
            self._micro.reset(
                trigger=f"pipeline_abort:{exc_name}",
                correlation_id=cid,
            )
            self._pending_sized_intents.clear()
            self._bus.publish(MetricEvent(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=cid,
                sequence=self._seq.next(),
                layer="kernel",
                name="tick_aborted_micro_reset",
                value=1.0,
                metric_type=MetricType.COUNTER,
            ))
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
            self._pipeline_abort_requested = True

    def _process_tick_inner(self, quote: NBBOQuote) -> None:
        """Core tick-processing logic.  Separated from _process_tick
        so the exception handler has a clean boundary.
        """
        cid = quote.correlation_id
        t_wall_start = time.perf_counter_ns()
        self._tick_timings: dict[str, int] = {}

        # PR-2b-iii (H1 fix): partition the inter-tick Signal buffer into
        # *fresh* and *stale* before ``bus.publish(quote)`` triggers
        # HorizonSignalEngine subscribers for this tick.
        #
        # Prior policy (unconditional clear) silently dropped trade-path
        # Signals whose triggering horizon boundary was first crossed by a
        # Trade event rather than a quote.  Those Signals are valid and must
        # reach M4 on the next quote tick, provided the alpha's
        # ``horizon_seconds`` window has not yet elapsed.
        #
        # Staleness rules (evaluated against this quote's timestamp_ns):
        #   • sequence not marked carry-over          → STALE (quote-path
        #     leftovers / M4 republish rows must never leak forward)
        #   • horizon_seconds > 0 and age > horizon  → STALE (evict + trace)
        #   • horizon_seconds == 0 (non-horizon)      → STALE (no carry-over
        #     guarantee; preserves historical behaviour for legacy producers)
        #   • carry-over + horizon_seconds > 0 and age ≤ horizon  → FRESH
        if self._signal_buffer:
            _now_ns = quote.timestamp_ns
            fresh: list[Signal] = []
            stale: list[Signal] = []
            for sig in self._signal_buffer:
                if (
                    sig.sequence in self._carryover_signal_sequences
                    and
                    sig.horizon_seconds > 0
                    and (_now_ns - sig.timestamp_ns)
                    <= sig.horizon_seconds * 1_000_000_000
                ):
                    fresh.append(sig)
                else:
                    stale.append(sig)
                    self._carryover_signal_sequences.discard(sig.sequence)
            if self._signal_order_trace_sink is not None and stale:
                anchor = self._last_quote_context_for_signal_trace
                if anchor is not None:
                    for pending in stale:
                        if pending.sequence in self._signal_order_trace_seen_sequences:
                            continue
                        self._append_signal_order_trace(
                            anchor,
                            pending,
                            outcome="NO_ORDER",
                            reasons=(
                                "signal_buffer_cleared_unprocessed_at_tick_boundary",
                            ),
                        )
            self._signal_buffer.clear()
            self._signal_buffer.extend(fresh)
        self._tick_quote_for_trace = None

        # ── Kill switch gate (W-2) ─────────────────────────────
        if self._kill_switch is not None and self._kill_switch.is_active:
            if self._macro.state in TRADING_MODES:
                if self._macro.can_transition(MacroState.DEGRADED):
                    self._macro.transition(
                        MacroState.DEGRADED,
                        trigger="KILL_SWITCH_ACTIVE",
                        correlation_id=cid,
                    )
            self._bus.publish(MetricEvent(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=cid,
                sequence=self._seq.next(),
                layer="kernel",
                name="tick_suppressed_kill_switch",
                value=1.0,
                metric_type=MetricType.COUNTER,
            ))
            return

        # ── Runtime data integrity check (W-6) ─────────────────
        if self._data_health_blocks_trading(quote.symbol, cid):
            return

        # ── BT-5: LULD halt gate ───────────────────────────────
        # While a symbol is halted there are no fills (entry or exit):
        # skip the quote entirely so the router never sees ``on_quote``
        # (no resting/deferred fills) and the mark freezes at its last
        # value (existing positions are held).  Resting passive orders
        # were cancelled at halt-on (see ``_update_halt_state``).
        if quote.symbol in self._halted_symbols:
            return

        # ── M0 → M1: MARKET_EVENT_RECEIVED ─────────────────────
        self._micro.transition(
            MicroState.MARKET_EVENT_RECEIVED,
            trigger="tick_arrived",
            correlation_id=cid,
        )
        if not self._events_prelogged:
            self._event_log.append(quote)
        if self._signal_order_trace_sink is not None:
            self._tick_quote_for_trace = quote
            self._last_quote_context_for_signal_trace = quote
        self._bus.publish(quote)

        # ── Mark-to-market feed ─────────────────────────────────
        # Push the latest mid to both the aggregate and per-strategy
        # position books so ``total_exposure`` and ``unrealized_pnl``
        # reflect live prices, not cost basis.  The risk engine uses
        # these for the gross-exposure cap and drawdown guard.
        mid = (quote.bid + quote.ask) / Decimal("2")
        if mid > 0:
            # Audit F-H-03: pass BBO so unrealized PnL marks at the
            # realistic liquidation price (bid for longs, ask for
            # shorts) rather than mid.  The drawdown guard reads
            # unrealized PnL, so this removes a half-spread × |qty|
            # optimistic bias that delayed the gate.
            self._positions.update_mark(
                quote.symbol, mid, bid=quote.bid, ask=quote.ask,
            )
            # Advance the risk engine's drawdown high-water mark from
            # the freshly updated marks so peak equity reflects open
            # appreciation between order checks.  Without this, the HWM
            # only ratchets when ``check_signal`` / ``check_order`` run,
            # which biases drawdown verdicts to be order-arrival
            # dependent (BasicRiskEngine.refresh_high_water_mark).  The
            # capability is optional on the ``RiskEngine`` protocol so
            # legacy stubs without the hook are silently skipped.
            refresh_hwm = getattr(
                self._risk_engine, "refresh_high_water_mark", None,
            )
            if callable(refresh_hwm):
                refresh_hwm(self._positions)
            if self._strategy_positions is not None:
                self._strategy_positions.update_mark(
                    quote.symbol, mid, bid=quote.bid, ask=quote.ask,
                )
        # BT-16: drive the RTH-close buying-power flip purely from the
        # quote's exchange timestamp so it always aligns with router-side
        # entry gating, even on ticks that fail the mid guard (zeroed or
        # invalid BBO).  Otherwise the engine could remain on intraday
        # buying power past the close while the router already treats
        # the session as closed — inconsistent risk vs execution.
        self._maybe_flip_buying_power_at_rth_close(quote)

        # ── Quote-driven router ack drain ────────────────────────
        # bus.publish(quote) triggered on_quote() on the router, which
        # may emit fills/cancels for resting limits (passive entries)
        # or deferred aggressive / MARKET acks when ``latency_ns > 0``
        # (market-mode BacktestOrderRouter).  Drain pending router acks
        # before evaluating signals so the position store is current.
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
        self._maybe_transition_cross_sectional_bookend(cid)
        self._flush_pending_sized_intents(correlation_id=cid)

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
        buf_snapshot = list(self._signal_buffer)
        signal: Signal | None = None
        if buf_snapshot:
            t0 = time.perf_counter_ns()
            signal = self._select_bus_signal()
            self._tick_timings["signal_evaluate_ns"] = time.perf_counter_ns() - t0

        stop_signal = self._check_stop_exit(quote)
        self._trace_buffered_signals_arbitration(
            quote, buf_snapshot, signal, stop_signal,
        )
        if buf_snapshot:
            for buffered in buf_snapshot:
                self._carryover_signal_sequences.discard(buffered.sequence)
            self._signal_buffer.clear()

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
            reasons_no: list[str] = [
                "intent_translator_no_action",
                f"intent_enum={intent.intent.name}",
                f"current_position_qty={intent.current_quantity}",
            ]
            if target_qty == 0:
                reasons_no.insert(0, "position_sizer_returned_zero_target_quantity")
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=tuple(reasons_no),
                trading_intent=intent.intent.name,
            )
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
        # Macro RISK_LOCKDOWN exists only from PAPER/LIVE (`macro.py`).
        # BACKTEST_MODE cannot transition there — `can_transition` is false
        # and we simulate flatten without global lockdown (replay parity).
        if verdict.action == RiskAction.FORCE_FLATTEN:
            if self._macro.can_transition(MacroState.RISK_LOCKDOWN):
                self._append_signal_order_trace(
                    quote,
                    signal,
                    outcome="NO_ORDER",
                    reasons=(
                        "risk_check_signal_force_flatten_lockdown",
                        verdict.reason,
                    ),
                    trading_intent=intent.intent.name,
                )
                self._escalate_risk(cid)
                self._micro.reset(
                    trigger="pipeline_abort:risk_lockdown",
                    correlation_id=cid,
                )
                return
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=(
                    "risk_check_signal_force_flatten_simulated",
                    verdict.reason,
                ),
                trading_intent=intent.intent.name,
            )
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="risk_force_flatten_simulated",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        # ── M5 branch: risk rejected → M10 ─────────────────────
        if verdict.action == RiskAction.REJECT:
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=("risk_check_signal_reject", verdict.reason),
                trading_intent=intent.intent.name,
            )
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

        # BT-5: post-halt resolution blackout — suppress new ENTRY-opening
        # orders for ``halt_resolution_blackout_seconds`` after a resume so
        # the reopening-auction print can stabilize.  Exits (and NO_ACTION)
        # are always permitted — an existing position may always unwind.
        if (
            intent.intent in _ENTRY_OPENING_INTENTS
            and self._in_halt_blackout(intent.symbol, quote.timestamp_ns)
        ):
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=(
                    "halt_resolution_blackout",
                    f"symbol={intent.symbol}",
                ),
                trading_intent=intent.intent.name,
            )
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="halt_resolution_blackout",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        # BT-6: Reg-SHO / SSR conservative refuse-short.  Under an active
        # short-sale restriction, an order that opens or increases SHORT
        # exposure (a short sale) is refused; the entry retries next horizon
        # boundary.  Buys, covers, and long-side exits are unaffected.
        if self._ssr_blocks_intent(intent):
            self._emit_ssr_suppression_alert(intent, cid)
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=("ssr_suppressed", f"symbol={intent.symbol}"),
                trading_intent=intent.intent.name,
            )
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="ssr_suppressed",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        # BT-7: short-locate gate — refuse short sales when borrow is
        # unavailable.  ``hard`` tier still fills but routes HTB fees via
        # ``OrderRequest.is_short``; ``available`` short entries omit HTB.
        if self._borrow_blocks_intent(intent):
            self._emit_locate_unavailable_alert(intent, cid)
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=("locate_unavailable", f"symbol={intent.symbol}"),
                trading_intent=intent.intent.name,
            )
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="locate_unavailable",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        # H2/H3/H7: REVERSE intents decompose into EXIT(MARKET) +
        # ENTRY(LIMIT) — aggressive close guarantees fill, passive
        # entry saves spread.
        if intent.intent in (
            TradingIntent.REVERSE_LONG_TO_SHORT,
            TradingIntent.REVERSE_SHORT_TO_LONG,
        ):
            self._execute_reverse(intent, verdict, cid, quote, t_wall_start)
            return

        order, order_build_reason = self._try_build_order_from_intent(
            intent, verdict, cid, quote,
        )
        if order is None:
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=(
                    "order_request_build_failed",
                    order_build_reason or "unknown",
                ),
                trading_intent=intent.intent.name,
            )
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
                self._append_signal_order_trace(
                    quote,
                    signal,
                    outcome="NO_ORDER",
                    reasons=(
                        "risk_check_order_force_flatten_lockdown",
                        order_verdict.reason,
                    ),
                    trading_intent=intent.intent.name,
                )
                self._escalate_risk(cid)
                self._micro.reset(
                    trigger="pipeline_abort:check_order_lockdown",
                    correlation_id=cid,
                )
                return
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=(
                    "risk_check_order_force_flatten_simulated",
                    order_verdict.reason,
                ),
                trading_intent=intent.intent.name,
            )
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="check_order_force_flatten_simulated",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        if order_verdict.action == RiskAction.REJECT:
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=("risk_check_order_reject", order_verdict.reason),
                trading_intent=intent.intent.name,
            )
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger=f"check_order_rejected:{order_verdict.reason}",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        if order_verdict.action == RiskAction.SCALE_DOWN:
            # H2: ``check_signal`` and ``check_order`` can both emit
            # ``SCALE_DOWN``.  Compose them as the tightest cap on the
            # original target quantity, rather than multiplying an
            # already-scaled order and shrinking it twice.
            scaled_qty = self._compose_scaled_quantity(
                intent.target_quantity,
                verdict.scaling_factor,
                order_verdict.scaling_factor,
            )
            if scaled_qty <= 0:
                self._append_signal_order_trace(
                    quote,
                    signal,
                    outcome="NO_ORDER",
                    reasons=(
                        "risk_check_order_scale_down_to_zero_quantity",
                        order_verdict.reason,
                    ),
                    trading_intent=intent.intent.name,
                )
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
        #    exists.  EXIT is allowed to race in only when no identical
        #    exit is already pending, which prevents stop-exit pile-ups
        #    from overshooting the book.  REVERSE intents handled by
        #    _execute_reverse() and never reach this guard.
        #
        # The ``_use_passive_entries`` clause was removed because
        # broker fills in PAPER / LIVE mode arrive asynchronously
        # regardless of execution_mode.  A pending IB ack on the
        # same symbol must block a duplicate SIGNAL submit; the
        # ``__stop_exit__`` / ``TradingIntent.EXIT`` carve-out
        # preserves Inv-11 (exits always race in).
        if self._has_pending_order_for_symbol(order.symbol):
            if (
                intent.intent != TradingIntent.EXIT
                or self._has_pending_exit_for_symbol(order.symbol)
            ):
                self._append_signal_order_trace(
                    quote,
                    signal,
                    outcome="NO_ORDER",
                    reasons=(
                        "resting_order_guard_blocked_duplicate_passive_order",
                        f"symbol={order.symbol}",
                    ),
                    trading_intent=intent.intent.name,
                )
                self._micro.transition(
                    MicroState.LOG_AND_METRICS,
                    trigger="resting_order_pending",
                    correlation_id=cid,
                )
                self._finalize_tick(t_wall_start, cid)
                return

        # ── Track order lifecycle (Inv-4) ───────────────────────
        self._track_order(
            order.order_id, order.side, order,
            trading_intent=intent.intent.name,
        )

        # ── M6 → M7: ORDER_SUBMIT ──────────────────────────────
        self._micro.transition(
            MicroState.ORDER_SUBMIT,
            trigger="order_constructed",
            correlation_id=cid,
        )
        self._transition_order(
            order.order_id,
            OrderState.SUBMITTED,
            "submitted",
            correlation_id=cid,
        )
        try:
            self._backend.order_router.submit(order)
        except Exception as exc:
            self._reject_order_after_submit_failure(order, exc)
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=(
                    "order_router_submit_raised",
                    type(exc).__name__,
                    repr(exc),
                ),
                trading_intent=intent.intent.name,
            )
            self._micro.transition(
                MicroState.ORDER_ACK,
                trigger="order_submit_failed_no_router_ack",
                correlation_id=cid,
            )
            self._micro.transition(
                MicroState.POSITION_UPDATE,
                trigger="order_submit_failed_no_fills",
                correlation_id=cid,
            )
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="order_submit_failed",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        self._bus.publish(order)
        self._append_signal_order_trace(
            quote,
            signal,
            outcome="ORDER_SUBMITTED",
            reasons=(
                f"order_id={order.order_id}",
                f"quantity={order.quantity}",
                f"order_type={order.order_type.name}",
            ),
            trading_intent=intent.intent.name,
        )

        # ── M7 → M8: ORDER_ACK ─────────────────────────────────
        self._micro.transition(
            MicroState.ORDER_ACK,
            trigger="order_submitted",
            correlation_id=cid,
        )
        acks = self._poll_order_router_acks({order.order_id})
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

        if self._paper_session_recorder is not None:
            self._paper_session_recorder.record_timing(
                kind="tick_process",
                duration_ns=latency_ns,
                correlation_id=correlation_id,
            )

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

    def _emit_signal_edge_gate_suppression_alert(
        self,
        signal: Signal,
        symbol: str,
        correlation_id: str,
        *,
        detail: str,
    ) -> None:
        """Surface B4 edge-vs-cost suppressions (Inv-13 provenance)."""
        self._bus.publish(Alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            severity=AlertSeverity.WARNING,
            layer="kernel",
            alert_name="signal_edge_below_min_edge_cost_ratio_gate",
            message=(
                f"Order suppressed: signal.edge_estimate_bps below "
                f"{self._signal_min_edge_cost_ratio}× round-trip cost "
                f"({detail}; strategy_id={signal.strategy_id!r}, "
                f"symbol={symbol!r})."
            ),
            context={
                "detail": detail,
                "strategy_id": signal.strategy_id,
                "symbol": symbol,
                "edge_estimate_bps": signal.edge_estimate_bps,
                "signal_min_edge_cost_ratio": self._signal_min_edge_cost_ratio,
            },
        ))

    def _signal_passes_edge_cost_gate(
        self,
        signal: Signal,
        *,
        symbol: str,
        entry_side: Side,
        quantity: int,
        quote: NBBOQuote,
        is_taker_entry: bool,
        is_short_entry: bool,
        correlation_id: str,
        detail: str,
    ) -> bool:
        """Return True when B4 edge estimate clears model round-trip cost."""
        if self._signal_min_edge_cost_ratio <= 0 or self._cost_model is None:
            return True
        round_trip_cost_bps = self._round_trip_cost_bps(
            symbol=symbol,
            entry_side=entry_side,
            quantity=quantity,
            quote=quote,
            is_taker_entry=is_taker_entry,
            is_short_entry=is_short_entry,
        )
        edge_bps_basis = signal.edge_estimate_bps
        if self._signal_edge_cost_basis == "round_trip":
            edge_bps_basis = edge_bps_basis * 2.0
        if edge_bps_basis < (
            self._signal_min_edge_cost_ratio * round_trip_cost_bps
        ):
            self._emit_signal_edge_gate_suppression_alert(
                signal,
                symbol,
                correlation_id,
                detail=detail,
            )
            return False
        return True

    def _round_trip_cost_bps(
        self,
        *,
        symbol: str,
        entry_side: Side,
        quantity: int,
        quote: NBBOQuote,
        is_taker_entry: bool,
        is_short_entry: bool,
    ) -> float:
        """Model round-trip (entry + taker exit) cost in bps for one leg.

        Shared by the B4 entry edge gate (:meth:`_signal_passes_edge_cost_gate`)
        and the B5 reversal edge gate
        (:meth:`_reversal_passes_combined_edge_gate`) so both price legs with
        an identical cost-model call.  Callers guarantee
        ``self._cost_model is not None`` before invoking.
        """
        assert self._cost_model is not None
        gate_price = (quote.bid + quote.ask) / Decimal("2")
        gate_spread = (quote.ask - quote.bid) / Decimal("2")
        return estimate_round_trip_cost_bps(
            self._cost_model,
            symbol=symbol,
            entry_side=entry_side,
            quantity=quantity,
            mid_price=gate_price,
            half_spread=gate_spread,
            is_taker=is_taker_entry,
            is_taker_exit=True,
            is_short_entry=is_short_entry,
            bid_size=quote.bid_size,
            ask_size=quote.ask_size,
            market_impact_factor=Decimal(str(getattr(
                self._config, "cost_market_impact_factor", 0.5,
            ))) if self._config else None,
            max_impact_half_spreads=Decimal(str(getattr(
                self._config, "cost_max_impact_half_spreads", 10.0,
            ))) if self._config else None,
        )

    def _reversal_passes_combined_edge_gate(
        self,
        *,
        edge_estimate_bps: float,
        symbol: str,
        exit_side: Side,
        exit_qty: int,
        entry_side: Side,
        entry_qty: int,
        quote: NBBOQuote,
        is_short_entry: bool,
    ) -> tuple[float, float, bool]:
        """B5 reversal edge guard — price the cost of flipping the book.

        A reversal first *crystallises* the existing opposite position
        (exit leg) before re-establishing the new direction (entry leg).
        That zero-crossing cost is paid immediately and is independent of
        the new signal's edge.  The guard asks whether the raw signal edge
        on the new direction clears the combined round-trip cost of both
        legs::

            edge_estimate_bps
                > (exit_roundtrip_cost_bps + entry_roundtrip_cost_bps)
                  * reversal_min_edge_cost_multiplier

        Returns ``(combined_cost_bps, required_bps, passes)``.  The guard is
        a no-op (returns ``(0.0, 0.0, True)``) when the multiplier is 0 or
        when no cost model is wired — fail-safe: an unknown cost model
        disables the guard rather than crashing or blocking the flip.
        """
        if (
            self._reversal_min_edge_cost_multiplier <= 0
            or self._cost_model is None
        ):
            return 0.0, 0.0, True
        # Exit leg: aggressive MARKET close of the existing position (taker,
        # never a short — closing a long is a plain sell, covering a short
        # is a plain buy).
        exit_roundtrip_cost_bps = self._round_trip_cost_bps(
            symbol=symbol,
            entry_side=exit_side,
            quantity=exit_qty,
            quote=quote,
            is_taker_entry=True,
            is_short_entry=False,
        )
        # Entry leg: same side as the exit (both close-then-open in the new
        # direction); taker assumption mirrors the B4 entry gate.
        entry_roundtrip_cost_bps = self._round_trip_cost_bps(
            symbol=symbol,
            entry_side=entry_side,
            quantity=entry_qty,
            quote=quote,
            is_taker_entry=(
                not self._use_passive_entries
                or self._min_cost_policy is not None
            ),
            is_short_entry=is_short_entry,
        )
        combined_cost_bps = exit_roundtrip_cost_bps + entry_roundtrip_cost_bps
        required_bps = (
            combined_cost_bps * self._reversal_min_edge_cost_multiplier
        )
        passes = edge_estimate_bps > required_bps
        return combined_cost_bps, required_bps, passes

    def _calibrate_regime_engine(self) -> None:
        """Calibrate regime emission parameters from a *prefix* of the log.

        Full-event-log calibration leaks future spread statistics into
        boot-time parameters.  When ``regime_calibration_max_quotes`` is
        ``None`` (platform default), calibration from the trading log is
        skipped entirely — use explicit positive integers for a causal
        warmup prefix only.
        """
        if self._regime_engine is None:
            return
        calibrate_fn = getattr(self._regime_engine, "calibrate", None)
        if calibrate_fn is None:
            return
        if getattr(self._regime_engine, "calibrated", False):
            return

        max_q = self._regime_calibration_max_quotes
        if max_q is None:
            # Uncalibrated regime engines fall through to placeholder
            # emission params that barely discriminate ``compression``
            # vs ``normal`` vs ``vol_breakout``, silently making every
            # ``P(<state>)`` gate near-equal.  Emit a CRITICAL alert so
            # operators see this on the bus instead of buried in a log
            # line (matches the calibrate-fail path below).
            logger.warning(
                "Regime calibration skipped — regime_calibration_max_quotes "
                "is unset.  Engine will run with placeholder emission "
                "parameters; downstream P(state) gates will be near-uniform."
            )
            self._bus.publish(Alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id="regime_calibration",
                sequence=self._seq.next(),
                severity=AlertSeverity.WARNING,
                layer="kernel",
                alert_name="regime_calibration_unset",
                message=(
                    "RegimeEngine has no calibration prefix configured "
                    "(regime_calibration_max_quotes is None). Posteriors "
                    "will use placeholder emission parameters; configure a "
                    "positive integer for a causal warmup prefix."
                ),
                context={},
            ))
            return

        precomputed = self._regime_calibration_quotes
        if precomputed is not None:
            quotes = list(precomputed)
        else:
            quote_stream = (
                event for event in self._event_log.replay()
                if isinstance(event, NBBOQuote)
            )
            quotes = list(itertools.islice(quote_stream, max_q))
        if not quotes:
            logger.info(
                "Regime calibration skipped — no quotes in event log"
            )
            return

        prefix_n = len(quotes)
        # Exact total only when the prefix exhausts the quote stream; otherwise
        # counting the suffix is O(full log) at boot — report a lower bound.
        exact_total = (
            precomputed is not None or prefix_n < max_q
        )

        ok = calibrate_fn(quotes)
        if ok:
            if exact_total:
                logger.info(
                    "Regime engine calibrated from %d quotes "
                    "(prefix cap=%d, total_log=%d)",
                    prefix_n,
                    max_q,
                    prefix_n,
                )
            else:
                logger.info(
                    "Regime engine calibrated from %d quotes "
                    "(prefix cap=%d; NBBO quote count ≥ %d — suffix not scanned)",
                    prefix_n,
                    max_q,
                    max_q,
                )
        else:
            logger.warning(
                "Regime calibration failed (insufficient data in prefix: "
                "%d quotes, cap=%d) — using default emission parameters",
                prefix_n,
                max_q,
            )
            self._bus.publish(Alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id="regime_calibration",
                sequence=self._seq.next(),
                severity=AlertSeverity.CRITICAL,
                layer="kernel",
                alert_name="regime_calibration_failed",
                message=(
                    f"Regime engine calibrate() returned False "
                    f"(prefix_quotes={prefix_n}, cap={max_q}). "
                    "Posteriors may discriminate poorly until operators "
                    "raise regime_calibration_max_quotes or supply cleaner data."
                ),
                context=(
                    {
                        "prefix_quote_count": prefix_n,
                        "cap": max_q,
                        "total_quotes_in_log": prefix_n,
                    }
                    if exact_total
                    else {
                        "prefix_quote_count": prefix_n,
                        "cap": max_q,
                        "total_quotes_in_log_at_least": max_q,
                    }
                ),
            ))

    def _update_regime(self, quote: NBBOQuote, correlation_id: str) -> None:
        """Update platform-level RegimeEngine and publish RegimeState event.

        Called at M2 (STATE_UPDATE) — single-writer point for regime
        state.  Downstream consumers (feature code, risk engine,
        position sizer) read cached state; they never update.
        """
        if self._regime_engine is None:
            return
        posteriors = self._regime_engine.posterior(quote)
        # Ties: lowest index wins (stable, deterministic replay).
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
            posterior_entropy_nats=regime_posterior_entropy_nats(posteriors),
        )
        self._bus.publish(regime_state)
        self._maybe_publish_hazard_spike(regime_state, correlation_id)

    def _reset_regime_session_state(self) -> None:
        """Clear hazard-detection state that must not span sessions.

        Called from every ``run_*`` entry point alongside ``_micro.reset``.
        Two structures are cleared:

        * ``self._last_regime_state`` — the prev-pointer dict feeding
          :class:`RegimeHazardDetector`.  Without this clear, a
          ``RegimeState`` from session N-1 would pair with the first
          ``RegimeState`` of session N, the detector would compute a
          "decay" across the session gap, and a spurious
          :class:`RegimeHazardSpike` could be emitted (§20.3.1).
        * ``self._regime_hazard_detector._suppressed`` (via
          ``reset()``) — without this clear, suppression keys from
          session N-1 would silence legitimate spikes early in
          session N for the same ``(symbol, engine_name,
          departing_state)`` triple.

        The :class:`RegimeEngine` itself is intentionally NOT reset:
        its per-symbol HMM posterior is the carry-over we want
        (boot-time calibration is the only place that wipes it).
        """
        self._last_regime_state.clear()
        if self._regime_hazard_detector is not None:
            self._regime_hazard_detector.reset()

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
            failures, residual = self._emergency_flatten_all(correlation_id)
            flatten_clean = not failures and not residual
            self._risk_escalation.transition(
                RiskLevel.LOCKED,
                trigger=(
                    "positions_zero_flatten_complete"
                    if flatten_clean
                    else "emergency_flatten_incomplete_residual_exposure"
                ),
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

    def _emergency_flatten_all(
        self,
        correlation_id: str,
    ) -> tuple[dict[str, str], dict[str, int]]:
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

        Returns ``(failures, residual_qty_by_symbol)`` so risk escalation
        can record an honest transition trigger when exposure remains.
        """
        positions = self._positions.all_positions()
        failures: dict[str, str] = {}
        # Iterate in lexicographic symbol order so the emitted
        # OrderRequest stream is bit-identical across replays even
        # when the position store's insertion order differs (Inv-5).
        for symbol in sorted(positions):
            pos = positions[symbol]
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
                self._transition_order(
                    order_id,
                    OrderState.SUBMITTED,
                    "emergency_flatten",
                    correlation_id=correlation_id,
                )
                try:
                    self._backend.order_router.submit(order)
                except Exception as submit_exc:
                    failures[symbol] = f"submit_exception: {submit_exc!r}"
                    self._reject_order_after_submit_failure(order, submit_exc)
                    continue

                self._bus.publish(order)
                acks = self._poll_order_router_acks({order_id})
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
                if order_id in self._active_orders:
                    self._force_order_terminal_after_pipeline_error(
                        order,
                        exc,
                        context="emergency_flatten",
                    )

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
        return failures, residual

    def _check_stop_exit(self, quote: NBBOQuote) -> Signal | None:
        """Check stop-loss and trailing stop for open positions.

        Returns a synthetic FLAT Signal if a stop triggers, None otherwise.
        Also updates peak unrealized P&L tracking for trailing stops.

        Percentage-based thresholds (``stop_loss_pct``,
        ``trail_activate_pct``) take precedence over per-share fields when
        non-zero, converted against ``avg_entry_price`` at check time so a
        single config value applies across the universe regardless of
        per-symbol price level.
        """
        if (
            self._stop_loss_per_share <= 0
            and self._trail_activate_per_share <= 0
            and self._stop_loss_pct <= 0
            and self._trail_activate_pct <= 0
        ):
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

        # Percentage thresholds override per-share fields when set.
        stop_threshold = (
            entry * self._stop_loss_pct
            if self._stop_loss_pct > 0
            else self._stop_loss_per_share
        )
        trail_activate_threshold = (
            entry * self._trail_activate_pct
            if self._trail_activate_pct > 0
            else self._trail_activate_per_share
        )

        triggered = False

        if stop_threshold > 0 and unrealized_per_share < -stop_threshold:
            triggered = True

        if (trail_activate_threshold > 0
                and peak >= trail_activate_threshold
                and unrealized_per_share < peak * self._trail_pct):
            triggered = True

        if not triggered:
            return None

        return Signal(
            timestamp_ns=quote.timestamp_ns,
            correlation_id=quote.correlation_id,
            sequence=self._signal_seq.next(),
            source_layer="SIGNAL",
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
        if exit_verdict.action == RiskAction.FORCE_FLATTEN:
            if self._macro.can_transition(MacroState.RISK_LOCKDOWN):
                # Same global halt as standalone SIGNAL/order gates — drawdown
                # breach must not strand the book without emergency flatten.
                self._escalate_risk(cid)
                self._micro.transition(
                    MicroState.LOG_AND_METRICS,
                    trigger="reverse_exit_force_flatten_escalation",
                    correlation_id=cid,
                )
                self._finalize_tick(t_wall_start, cid)
                return
            # BACKTEST_MODE: simulate without global lockdown (replay parity).
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="reverse_exit_force_flatten_simulated",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        if exit_verdict.action == RiskAction.REJECT:
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="reverse_exit_rejected",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        # SCALE_DOWN on the exit verdict is intentionally a no-op here:
        # the exit OrderRequest was built above with the full
        # ``close_qty`` and that's what submits.  The scaling factor only
        # governs the entry leg (computed from the outer signal-level
        # ``verdict`` below).  Exits must always close the entire
        # existing position; a partial close would leave the wrong-
        # direction residual on the book during a reverse.

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
        # B5: replaced signal carrying the combined reversal cost estimate
        # (Task 3).  Stays at the original signal (cost 0.0) when no entry
        # leg is warranted or the guard is disabled.
        reverse_signal: Signal = intent.signal

        # Signed adjustment: the exit leg removes close_qty from position.
        exit_signed_adj = -close_qty if exit_side == Side.SELL else close_qty
        post_exit_positions = _PostExitPositionView(
            self._positions, intent.symbol, exit_signed_adj,
        )

        if entry_qty >= self._min_order_shares:
            entry_side = exit_side  # same direction for both legs
            short_sale = intent.intent == TradingIntent.REVERSE_LONG_TO_SHORT
            tier = self._borrow_tier_for(intent.symbol)
            is_short = htb_fee_applies(tier, short_sale)

            # B5: reversal combined-edge guard.  Flipping the book first
            # crystallises the existing opposite position (exit leg); the
            # round-trip cost of *both* legs is paid immediately and is
            # independent of the new signal's edge.  Suppress the entry
            # (flatten-only) unless the raw edge clears the combined cost.
            # Inv-11: the exit leg below still always submits.
            (
                reversal_cost_bps,
                reversal_required_bps,
                reversal_edge_passes,
            ) = self._reversal_passes_combined_edge_gate(
                edge_estimate_bps=intent.signal.edge_estimate_bps,
                symbol=intent.symbol,
                exit_side=exit_side,
                exit_qty=close_qty,
                entry_side=entry_side,
                entry_qty=entry_qty,
                quote=quote,
                is_short_entry=is_short,
            )
            # Task 3: expose the combined estimate on the signal so trace
            # sinks / alerts can read it without recomputing.
            reverse_signal = replace(
                intent.signal,
                reversal_cost_estimate_bps=reversal_cost_bps,
            )

            if not reversal_edge_passes:
                edge_bps = intent.signal.edge_estimate_bps
                deficit_bps = reversal_required_bps - edge_bps
                self._bus.publish(Alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=cid,
                    sequence=self._seq.next(),
                    severity=AlertSeverity.WARNING,
                    layer="kernel",
                    alert_name="reversal_edge_insufficient",
                    message=(
                        f"Reversal entry suppressed (flatten-only): "
                        f"edge_bps={edge_bps:.4f} below required "
                        f"{reversal_required_bps:.4f} "
                        f"({self._reversal_min_edge_cost_multiplier}× combined "
                        f"round-trip cost {reversal_cost_bps:.4f}); "
                        f"deficit={deficit_bps:.4f} bps "
                        f"(symbol={intent.symbol!r}, "
                        f"strategy_id={intent.strategy_id!r})."
                    ),
                    context={
                        "edge_bps": edge_bps,
                        "required_bps": reversal_required_bps,
                        "deficit_bps": deficit_bps,
                        "symbol": intent.symbol,
                        "strategy_id": intent.strategy_id,
                        "order_id": exit_order.order_id,
                    },
                ))

            # B4: edge vs cost gate for the entry leg.  Short-circuited when
            # the B5 reversal guard already suppressed the flip.
            entry_passes_edge_gate = (
                reversal_edge_passes
                and self._signal_passes_edge_cost_gate(
                    intent.signal,
                    symbol=intent.symbol,
                    entry_side=entry_side,
                    quantity=entry_qty,
                    quote=quote,
                    is_taker_entry=(
                        not self._use_passive_entries
                        or self._min_cost_policy is not None
                    ),
                    is_short_entry=is_short,
                    correlation_id=cid,
                    detail="reverse_entry_leg_suppressed",
                )
            )

            if entry_passes_edge_gate:
                seq_entry = self._seq.next()
                entry_order_id = hashlib.sha256(
                    f"{cid}:{seq_entry}:entry".encode()
                ).hexdigest()[:16]

                order_type = OrderType.MARKET
                limit_price: Decimal | None = None
                entry_is_moc = (
                    intent.strategy_id in self._moc_strategy_ids
                    and self._moc_bounds_configured
                )
                if entry_is_moc:
                    order_type = OrderType.MARKET
                    limit_price = None
                elif self._use_passive_entries:
                    use_passive = True
                    if self._min_cost_policy is not None:
                        decision = self._min_cost_policy.decide(
                            symbol=intent.symbol,
                            side=entry_side,
                            quantity=entry_qty,
                            mid_price=(quote.bid + quote.ask) / Decimal("2"),
                            half_spread=(quote.ask - quote.bid) / Decimal("2"),
                            is_short=is_short,
                            force_aggressive=False,
                            bid_size=quote.bid_size,
                            ask_size=quote.ask_size,
                            edge_bps=intent.signal.edge_estimate_bps,
                        )
                        use_passive = decision == "passive"
                    if use_passive:
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
                    is_moc=entry_is_moc,
                    g12_disclosed_cost_total_bps=(
                        intent.signal.disclosed_cost_total_bps
                    ),
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
                    scaled = self._compose_scaled_quantity(
                        entry_qty_raw,
                        verdict.scaling_factor,
                        entry_rv.scaling_factor,
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

        # Submit EXIT leg.  The exit (flatten) leg carries the REVERSE_*
        # intent — it is the leg the reversal report keys on (Task 5).  The
        # entry leg below is stamped with its resulting ENTRY_* intent so it
        # is not double-counted as a separate reversal attempt.
        self._track_order(
            exit_order.order_id, exit_order.side, exit_order,
            trading_intent=intent.intent.name,
        )
        self._transition_order(
            exit_order.order_id,
            OrderState.SUBMITTED,
            "submitted",
            correlation_id=cid,
        )
        try:
            self._backend.order_router.submit(exit_order)
        except Exception as exc:
            self._reject_order_after_submit_failure(exit_order, exc)
            self._micro.transition(
                MicroState.ORDER_ACK,
                trigger="reverse_exit_submit_failed",
                correlation_id=cid,
            )
            acks = self._poll_order_router_acks({exit_order.order_id})
            for ack in acks:
                self._bus.publish(ack)
                self._apply_ack_to_order(ack)
            self._micro.transition(
                MicroState.POSITION_UPDATE,
                trigger="reverse_acks_after_failed_exit_submit",
                correlation_id=cid,
            )
            self._reconcile_fills(acks, cid)
            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="reverse_aborted_exit_submit_failed",
                correlation_id=cid,
            )
            self._finalize_tick(t_wall_start, cid)
            return

        self._bus.publish(exit_order)

        entry_submitted_ok = False
        if entry_order is not None:
            entry_intent_name = (
                TradingIntent.ENTRY_SHORT.name
                if intent.intent == TradingIntent.REVERSE_LONG_TO_SHORT
                else TradingIntent.ENTRY_LONG.name
            )
            self._track_order(
                entry_order.order_id, entry_order.side, entry_order,
                trading_intent=entry_intent_name,
            )
            self._transition_order(
                entry_order.order_id,
                OrderState.SUBMITTED,
                "submitted",
                correlation_id=cid,
            )
            try:
                self._backend.order_router.submit(entry_order)
            except Exception as exc:
                self._reject_order_after_submit_failure(entry_order, exc)
            else:
                self._bus.publish(entry_order)
                entry_submitted_ok = True

        # ── M7 → M8: ORDER_ACK ────────────────────────────────────
        self._micro.transition(
            MicroState.ORDER_ACK,
            trigger="reverse_orders_submitted",
            correlation_id=cid,
        )
        expected_order_ids = {exit_order.order_id}
        if entry_order is not None and entry_submitted_ok:
            expected_order_ids.add(entry_order.order_id)
        acks = self._poll_order_router_acks(expected_order_ids)
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

        if self._signal_order_trace_sink is not None:
            leg = (
                "exit_plus_entry"
                if entry_order is not None and entry_submitted_ok
                else "exit_only"
            )
            self._append_signal_order_trace(
                quote,
                reverse_signal,
                outcome="ORDER_SUBMITTED",
                reasons=(
                    f"reverse_{leg}_submitted",
                    f"exit_order_id={exit_order.order_id}",
                ),
                trading_intent=intent.intent.name,
            )

        # ── M9 → M10: LOG_AND_METRICS ─────────────────────────────
        self._micro.transition(
            MicroState.LOG_AND_METRICS,
            trigger="reverse_position_updated",
            correlation_id=cid,
        )
        self._finalize_tick(t_wall_start, cid)

    def _try_build_order_from_intent(
        self,
        intent: OrderIntent,
        verdict: RiskVerdict,
        correlation_id: str,
        quote: NBBOQuote | None = None,
    ) -> tuple[OrderRequest | None, str | None]:
        """Like :meth:`_build_order_from_intent` but returns a failure token."""
        side = self._side_from_intent(intent)
        seq = self._seq.next()
        order_id = hashlib.sha256(
            f"{correlation_id}:{seq}".encode()
        ).hexdigest()[:16]

        quantity = round(intent.target_quantity * verdict.scaling_factor)
        if quantity <= 0:
            return None, "rounded_quantity_after_risk_scaling_le_zero"

        # F2: Exits and stop-losses bypass min_order_shares — you must be
        # able to close any position regardless of size (Inv-11 fail-safe).
        is_exit_or_stop = (
            intent.intent == TradingIntent.EXIT
            or intent.signal.strategy_id == "__stop_exit__"
        )
        if not is_exit_or_stop and quantity < self._min_order_shares:
            return None, "quantity_below_platform_min_order_shares"

        # BT-7: HTB fee flag — only ``hard``-tier short sales carry
        # ``OrderRequest.is_short``; ``available`` omits HTB even when
        # cost_htb_borrow_annual_bps is configured.
        short_sale = is_short_sale_intent(intent)
        tier = self._borrow_tier_for(intent.symbol)
        is_short = htb_fee_applies(tier, short_sale)

        if (
            not is_exit_or_stop
            and quote is not None
            and not self._signal_passes_edge_cost_gate(
                intent.signal,
                symbol=intent.symbol,
                entry_side=side,
                quantity=quantity,
                quote=quote,
                is_taker_entry=(
                    not self._use_passive_entries
                    or self._min_cost_policy is not None
                ),
                is_short_entry=is_short,
                correlation_id=correlation_id,
                detail="standalone_intent_suppressed",
            )
        ):
            return None, "signal_edge_below_min_edge_cost_ratio_gate"

        order_type = OrderType.MARKET
        limit_price: Decimal | None = None
        is_moc = (
            intent.strategy_id in self._moc_strategy_ids
            and self._moc_bounds_configured
            and not is_exit_or_stop
        )

        if is_moc:
            order_type = OrderType.MARKET
            limit_price = None
        elif self._use_passive_entries and quote is not None:
            is_stop_exit = intent.signal.strategy_id == "__stop_exit__"
            if not is_stop_exit:
                # Default: post passive at the near BBO.  When the
                # minimum-cost policy is wired, let it override on a
                # per-order basis.  Stop-loss / forced-flatten always
                # short-circuit to MARKET above (is_stop_exit branch),
                # so the policy is consulted only on tradeable orders
                # where either route is safe.
                use_passive = True
                if self._min_cost_policy is not None:
                    decision = self._min_cost_policy.decide(
                        symbol=intent.symbol,
                        side=side,
                        quantity=quantity,
                        mid_price=(quote.bid + quote.ask) / Decimal("2"),
                        half_spread=(quote.ask - quote.bid) / Decimal("2"),
                        is_short=is_short,
                        force_aggressive=is_exit_or_stop,
                        bid_size=quote.bid_size,
                        ask_size=quote.ask_size,
                        edge_bps=intent.signal.edge_estimate_bps,
                    )
                    use_passive = decision == "passive"
                if use_passive:
                    order_type = OrderType.LIMIT
                    limit_price = quote.bid if side == Side.BUY else quote.ask

        return (
            OrderRequest(
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
                is_moc=is_moc,
                g12_disclosed_cost_total_bps=(
                    intent.signal.disclosed_cost_total_bps
                ),
            ),
            None,
        )

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
        order, _reason = self._try_build_order_from_intent(
            intent, verdict, correlation_id, quote,
        )
        return order

    @staticmethod
    def _compose_scaled_quantity(base_quantity: int, *factors: float) -> int:
        """Apply the tightest risk cap exactly once to ``base_quantity``."""
        capped = min(max(0.0, min(1.0, factor)) for factor in factors)
        return round(base_quantity * capped)

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

        Valid kernel transitions into ``CANCEL_REQUESTED`` follow the
        ``OrderState`` table (typically from ``ACKNOWLEDGED`` or
        ``PARTIALLY_FILLED``).

        When ``order_router.cancel_order`` exists it is invoked and the
        resulting acks are reconciled.  Routers without cancel support
        emit ``cancel_order_router_unsupported`` and immediately resolve
        the SM to ``CANCELLED`` (no broker ack is possible in backtest).

        Returns True if the SM accepted ``CANCEL_REQUESTED``, False when
        the order is missing or cannot cancel from its current state.
        """
        if order_id not in self._active_orders:
            return False
        sm = self._active_orders[order_id][0]
        if not sm.can_transition(OrderState.CANCEL_REQUESTED):
            return False
        order = self._active_orders[order_id][2]
        sm.transition(
            OrderState.CANCEL_REQUESTED,
            trigger=f"cancel_requested:{reason}",
            correlation_id=order.correlation_id,
        )
        cancel_fn = getattr(self._backend.order_router, "cancel_order", None)
        if cancel_fn is None:
            self._bus.publish(Alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=order.correlation_id,
                sequence=self._seq.next(),
                severity=AlertSeverity.WARNING,
                layer="kernel",
                alert_name="cancel_order_router_unsupported",
                message=(
                    f"cancel_order requested for {order_id!r} but "
                    f"{type(self._backend.order_router).__name__} has no "
                    "cancel_order(...) — resolving SM to CANCELLED locally "
                    "(Inv-4 shutdown hygiene)."
                ),
                context={"order_id": order_id},
            ))
            sm2 = self._active_orders[order_id][0]
            if sm2.can_transition(OrderState.CANCELLED):
                sm2.transition(
                    OrderState.CANCELLED,
                    trigger="cancel_router_unsupported_local_terminal",
                    correlation_id=order.correlation_id,
                )
            self._prune_terminal_orders()
            return True
        accepted = cancel_fn(order_id)
        acks = self._poll_order_router_acks({order_id})
        for ack in acks:
            self._bus.publish(ack)
            self._apply_ack_to_order(ack)
        self._reconcile_fills(acks, order.correlation_id)
        # Only resolve locally when the router rejected the cancel
        # (e.g. unknown id, or backtest non-MOC paths with no resting
        # interest).  When the router accepted the cancel (True), the
        # terminal ack may arrive asynchronously on a later poll — for
        # IB the cancel is fire-and-forget — so forcing CANCELLED here
        # would desync kernel state from a still-live broker order.
        if not accepted and order_id in self._active_orders:
            sm_post = self._active_orders[order_id][0]
            if sm_post.state == OrderState.CANCEL_REQUESTED:
                if sm_post.can_transition(OrderState.CANCELLED):
                    sm_post.transition(
                        OrderState.CANCELLED,
                        trigger="cancel_no_broker_ack_local_terminal",
                        correlation_id=order.correlation_id,
                    )
        self._prune_terminal_orders()
        return True

    def _has_pending_order_for_symbol(self, symbol: str) -> bool:
        """True if any non-terminal order exists for this symbol."""
        return any(
            order.symbol == symbol and sm.state not in _TERMINAL_ORDER_STATES
            for sm, _, order in self._active_orders.values()
        )

    def _filter_portfolio_orders_for_pending_conflicts(
        self,
        orders: list[OrderRequest],
        *,
        intent: SizedPositionIntent,
        correlation_id: str,
    ) -> list[OrderRequest]:
        """Drop PORTFOLIO legs that would duplicate an in-flight order.

        Paper/live IB acks land asynchronously; backtest fills are
        synchronous so this filter is usually a no-op there.  PORTFOLIO
        has no native supersede-pending semantics — a later boundary's
        leg is dropped rather than cancel-replaced.  Hazard-exit orders
        bypass this path via :meth:`_on_bus_hazard_order` (Inv-11).
        """
        filtered: list[OrderRequest] = []
        for order in orders:
            if self._has_pending_order_for_symbol(order.symbol):
                self._bus.publish(Alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=correlation_id,
                    sequence=self._seq.next(),
                    severity=AlertSeverity.WARNING,
                    layer="kernel",
                    alert_name="portfolio_leg_skipped_pending_order",
                    message=(
                        f"PORTFOLIO leg skipped: pending order on "
                        f"{order.symbol!r} (order_id={order.order_id!r}, "
                        f"strategy={intent.strategy_id!r})"
                    ),
                    context={
                        "order_id": order.order_id,
                        "symbol": order.symbol,
                        "strategy_id": intent.strategy_id,
                    },
                ))
                continue
            filtered.append(order)
        return filtered

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
        cancel_order_ids = {
            order_id
            for order_id, (sm, _, order) in self._active_orders.items()
            if order.symbol == symbol and sm.state not in _TERMINAL_ORDER_STATES
        }
        cancel_acks = self._poll_order_router_acks(cancel_order_ids)
        if cancel_acks:
            for ack in cancel_acks:
                self._bus.publish(ack)
                self._apply_ack_to_order(ack)
            self._reconcile_fills(cancel_acks, cid)

    def _poll_order_router_acks(
        self,
        expected_order_ids: set[str] | None = None,
    ) -> list[OrderAck]:
        """Drain router acks, buffering unrelated ones for the next caller.

        The execution backend exposes a single pending-ack queue shared by
        immediate submit/cancel acks and quote-driven fills from previously
        resting orders.  Callers that just submitted a specific order family
        must not steal unrelated pending acks and reconcile them under the
        wrong correlation lineage.
        """
        polled = self._backend.order_router.poll_acks()
        if self._deferred_router_acks:
            all_acks = [*self._deferred_router_acks, *polled]
            self._deferred_router_acks.clear()
        else:
            all_acks = polled

        if expected_order_ids is None:
            return all_acks

        matched: list[OrderAck] = []
        deferred: list[OrderAck] = []
        for ack in all_acks:
            if ack.order_id in expected_order_ids:
                matched.append(ack)
            else:
                deferred.append(ack)
        self._deferred_router_acks.extend(deferred)
        return matched

    def _reject_order_after_submit_failure(
        self,
        order: OrderRequest,
        exc: BaseException,
    ) -> None:
        """Transition a tracked order to REJECTED when ``submit`` raises (Inv-11)."""
        self._bus.publish(Alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=order.correlation_id,
            sequence=self._seq.next(),
            severity=AlertSeverity.WARNING,
            layer="kernel",
            alert_name="order_submit_failed",
            message=(
                f"order_router.submit raised for order_id={order.order_id!r} "
                f"symbol={order.symbol!r}: {exc!r}"
            ),
            context={
                "order_id": order.order_id,
                "symbol": order.symbol,
                "exc_type": type(exc).__name__,
            },
        ))
        oid = order.order_id
        if oid not in self._active_orders:
            return
        sm = self._active_orders[oid][0]
        if sm.can_transition(OrderState.REJECTED):
            sm.transition(
                OrderState.REJECTED,
                trigger=f"submit_failed:{type(exc).__name__}",
                correlation_id=order.correlation_id,
            )
        self._prune_terminal_orders()

    def _force_order_terminal_after_pipeline_error(
        self,
        order: OrderRequest,
        exc: BaseException,
        *,
        context: str,
    ) -> None:
        """Best-effort terminal resolution after an unexpected pipeline failure.

        Used when ``submit`` succeeded but a later step (poll/apply/reconcile)
        raised — the order must not remain stuck in a non-terminal SM state
        (Inv-4 / operator hygiene).
        """
        self._bus.publish(Alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=order.correlation_id,
            sequence=self._seq.next(),
            severity=AlertSeverity.WARNING,
            layer="kernel",
            alert_name="order_pipeline_exception",
            message=(
                f"{context}: pipeline failed after submit for "
                f"order_id={order.order_id!r} symbol={order.symbol!r}: {exc!r}"
            ),
            context={
                "order_id": order.order_id,
                "symbol": order.symbol,
                "context": context,
                "exc_type": type(exc).__name__,
            },
        ))
        oid = order.order_id
        if oid not in self._active_orders:
            return
        sm = self._active_orders[oid][0]
        if sm.state in _TERMINAL_ORDER_STATES:
            self._prune_terminal_orders()
            return
        trigger_base = f"{context}_pipeline_abort:{type(exc).__name__}"
        for target in (
            OrderState.REJECTED,
            OrderState.CANCELLED,
            OrderState.EXPIRED,
        ):
            if sm.can_transition(target):
                sm.transition(
                    target,
                    trigger=trigger_base,
                    correlation_id=order.correlation_id,
                )
                self._prune_terminal_orders()
                return
        logger.critical(
            "orchestrator: could not force terminal order state for %s "
            "(current=%s) after %s — manual reconciliation required",
            oid,
            sm.state.name,
            context,
        )

    def _drain_async_fills(self, correlation_id: str) -> None:
        """Drain pending router acks and reconcile fills.

        The single source of truth for async fill processing. Called from
        three triggers:

        * Tick start (via :meth:`_reconcile_resting_fills`) — quote-driven
          fills from :class:`BacktestOrderRouter` /
          :class:`PassiveLimitOrderRouter` / :class:`IBOrderRouter` (the
          latter pushes asynchronously, so this is the dominant path for
          paper trading).
        * :class:`IdleTick` — live WS feed idle; no signal pipeline runs
          (paper/live trading only).
        * Shutdown — final drain so a fill between the last quote and the
          operator's halt is not dropped.

        Does NOT transition the micro SM and does NOT touch the macro SM.
        Routes through :meth:`_poll_order_router_acks` so the deferred-ack
        buffer (``_deferred_router_acks``) is honoured.
        """
        t0 = time.perf_counter_ns()
        acks = self._poll_order_router_acks()
        if acks:
            for ack in acks:
                self._bus.publish(ack)
                self._apply_ack_to_order(ack)
            self._reconcile_fills(acks, correlation_id)
        if self._paper_session_recorder is not None:
            self._paper_session_recorder.record_timing(
                kind="drain_async_fills",
                duration_ns=time.perf_counter_ns() - t0,
                correlation_id=correlation_id,
                extra={"ack_count": len(acks)},
            )

    def _reconcile_resting_fills(self, cid: str) -> None:
        """Poll and reconcile quote-driven router acknowledgements.

        Tick-start trigger; delegates to :meth:`_drain_async_fills` so the
        body is shared with the idle-tick and shutdown drain paths.  The
        trigger name is kept distinct from ``_drain_async_fills`` so
        metric / log attribution stays greppable.
        """
        self._drain_async_fills(cid)

    def _track_order(
        self,
        order_id: str,
        side: Side,
        order: OrderRequest,
        *,
        trading_intent: str = "",
    ) -> None:
        """Create an OrderState SM for a new order.

        ``trading_intent`` (``TradingIntent.name``) is recorded so the fill
        reconciliation path can stamp ``TradeRecord.trading_intent`` (Task 4).
        """
        sm = create_order_state_machine(order_id, self._clock)
        sm.on_transition(self._emit_state_transition)
        self._active_orders[order_id] = (sm, side, order)
        if trading_intent:
            self._order_trading_intent[order_id] = trading_intent

    def _transition_order(
        self,
        order_id: str,
        target: OrderState,
        trigger: str,
        *,
        correlation_id: str = "",
    ) -> None:
        """Transition an order's state machine."""
        if order_id in self._active_orders:
            sm = self._active_orders[order_id][0]
            sm.transition(
                target,
                trigger=trigger,
                correlation_id=correlation_id,
            )

    def _apply_ack_to_order(self, ack: OrderAck) -> None:
        """Update an order's SM based on a broker acknowledgement.

        Uses typed ``OrderAckStatus`` enum — exhaustive matching ensures
        every status is handled explicitly (invariant 7, hard rule 2).
        When a valid status cannot be applied because the order SM is
        in an incompatible state, an alert is emitted instead of
        silently dropping the ack (invariant 13: full provenance).
        """
        cid = ack.correlation_id
        if ack.order_id not in self._active_orders:
            self._bus.publish(Alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=cid,
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
            if sm.can_transition(OrderState.REJECTED):
                sm.transition(
                    OrderState.REJECTED,
                    trigger=f"broker_reject:{ack.reason}",
                    correlation_id=cid,
                )
            else:
                self._emit_ack_drop_alert(ack, sm)
            return

        if ack.status == OrderAckStatus.ACKNOWLEDGED:
            if sm.state == OrderState.SUBMITTED:
                sm.transition(
                    OrderState.ACKNOWLEDGED,
                    trigger="broker_ack",
                    correlation_id=cid,
                )
            return

        # Ensure ACKNOWLEDGED before any fill/cancel/expiry transition.
        if sm.state == OrderState.SUBMITTED:
            sm.transition(
                OrderState.ACKNOWLEDGED,
                trigger="broker_ack",
                correlation_id=cid,
            )

        if ack.status == OrderAckStatus.FILLED:
            if sm.state == OrderState.FILLED:
                self._bus.publish(Alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=cid,
                    sequence=self._seq.next(),
                    severity=AlertSeverity.WARNING,
                    layer="kernel",
                    alert_name="duplicate_terminal_fill_ack",
                    message=(
                        f"Ignoring duplicate FILLED ack for order_id={ack.order_id} "
                        "(already terminal FILLED)."
                    ),
                    context={"order_id": ack.order_id},
                ))
                return
            if sm.can_transition(OrderState.FILLED):
                sm.transition(
                    OrderState.FILLED,
                    trigger="fill_complete",
                    correlation_id=cid,
                )
            else:
                self._emit_ack_drop_alert(ack, sm)
            return

        if ack.status == OrderAckStatus.PARTIALLY_FILLED:
            if sm.can_transition(OrderState.PARTIALLY_FILLED):
                sm.transition(
                    OrderState.PARTIALLY_FILLED,
                    trigger="partial_fill",
                    correlation_id=cid,
                )
            else:
                self._emit_ack_drop_alert(ack, sm)
            return

        if ack.status == OrderAckStatus.CANCELLED:
            if sm.can_transition(OrderState.CANCELLED):
                sm.transition(
                    OrderState.CANCELLED,
                    trigger="broker_cancel",
                    correlation_id=cid,
                )
            else:
                self._emit_ack_drop_alert(ack, sm)
            return

        if ack.status == OrderAckStatus.EXPIRED:
            if sm.can_transition(OrderState.EXPIRED):
                sm.transition(
                    OrderState.EXPIRED,
                    trigger="order_expired",
                    correlation_id=cid,
                )
            else:
                self._emit_ack_drop_alert(ack, sm)
            return

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

        Position mutations require ``status ∈ {FILLED, PARTIALLY_FILLED}``
        with positive ``filled_quantity`` and a non-null ``fill_price``.
        """
        for ack in acks:
            # F7: debit cancel/expiry fees even when there is no fill.
            if ack.status in (
                OrderAckStatus.CANCELLED, OrderAckStatus.EXPIRED,
            ) and ack.fees and ack.fees > 0:
                self._positions.debit_fees(ack.symbol, ack.fees)
                if (
                    self._strategy_positions is not None
                    and ack.order_id in self._active_orders
                ):
                    strategy_id = self._active_orders[ack.order_id][2].strategy_id
                    if strategy_id:
                        self._strategy_positions.debit_fees(
                            strategy_id,
                            ack.symbol,
                            ack.fees,
                        )
                fee_position = self._positions.get(ack.symbol)
                self._bus.publish(PositionUpdate(
                    timestamp_ns=ack.timestamp_ns,
                    correlation_id=correlation_id,
                    sequence=self._seq.next(),
                    symbol=ack.symbol,
                    quantity=fee_position.quantity,
                    avg_price=fee_position.avg_entry_price,
                    realized_pnl=fee_position.realized_pnl,
                    unrealized_pnl=fee_position.unrealized_pnl,
                    cumulative_fees=fee_position.cumulative_fees,
                    cost_bps=ack.cost_bps,
                ))

            if ack.status in (
                OrderAckStatus.FILLED,
                OrderAckStatus.PARTIALLY_FILLED,
            ):
                if ack.fill_price is None or ack.filled_quantity <= 0:
                    self._bus.publish(Alert(
                        timestamp_ns=self._clock.now_ns(),
                        correlation_id=correlation_id,
                        sequence=self._seq.next(),
                        severity=AlertSeverity.WARNING,
                        layer="kernel",
                        alert_name="fill_ack_missing_price_or_quantity",
                        message=(
                            f"{ack.status.name} ack missing economics "
                            f"(order_id={ack.order_id!r}, symbol={ack.symbol!r}, "
                            f"filled_quantity={ack.filled_quantity}, "
                            f"fill_price={ack.fill_price!r})."
                        ),
                        context={
                            "order_id": ack.order_id,
                            "symbol": ack.symbol,
                            "status": ack.status.name,
                            "filled_quantity": ack.filled_quantity,
                            "fill_price": str(ack.fill_price),
                        },
                    ))
                    continue
            else:
                fill_like = (
                    ack.fill_price is not None and ack.filled_quantity > 0
                )
                if fill_like:
                    self._bus.publish(Alert(
                        timestamp_ns=self._clock.now_ns(),
                        correlation_id=correlation_id,
                        sequence=self._seq.next(),
                        severity=AlertSeverity.WARNING,
                        layer="kernel",
                        alert_name="fill_payload_inconsistent_with_ack_status",
                        message=(
                            f"Ignoring fill-like payload on {ack.status.name} ack "
                            f"(order_id={ack.order_id!r}, symbol={ack.symbol!r})."
                        ),
                        context={
                            "order_id": ack.order_id,
                            "symbol": ack.symbol,
                            "status": ack.status.name,
                            "filled_quantity": ack.filled_quantity,
                            "fill_price": str(ack.fill_price),
                        },
                    ))
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

            prev_position = self._positions.get(ack.symbol)
            prev_realized = prev_position.realized_pnl
            prev_qty = prev_position.quantity
            position = self._positions.update(
                ack.symbol,
                signed_qty,
                ack.fill_price,
                fees=ack.fees,
                timestamp_ns=ack.timestamp_ns,
            )

            if position.quantity == 0:
                self._peak_pnl_per_share.pop(ack.symbol, None)

            # BT-4: feed the PDT round-trip counter (duck-typed; no-op
            # when the risk engine carries no PDT constraint).  Pure
            # bookkeeping — emits nothing, so replay stays bit-identical.
            record_fill = getattr(self._risk_engine, "record_fill", None)
            if callable(record_fill):
                record_fill(
                    ack.symbol, prev_qty, position.quantity, ack.timestamp_ns,
                )

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
                            timestamp_ns=ack.timestamp_ns,
                        )
                else:
                    # No attribution record (emergency flatten, stop
                    # exit, or attribution failure).  Distribute the
                    # fill proportionally across all strategy positions
                    # for this symbol to keep strategy and global stores
                    # in sync.
                    self._distribute_fill_to_strategies(
                        ack.symbol,
                        signed_qty,
                        ack.fill_price,
                        ack.fees,
                        ack.timestamp_ns,
                    )
            self._bus.publish(PositionUpdate(
                timestamp_ns=ack.timestamp_ns,
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

            disclosed = order.g12_disclosed_cost_total_bps
            alert_ratio = self._realized_cost_alert_ratio
            if disclosed > 0 and float(ack.cost_bps) > disclosed * alert_ratio:
                self._bus.publish(Alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=correlation_id,
                    sequence=self._seq.next(),
                    severity=AlertSeverity.WARNING,
                    layer="kernel",
                    alert_name="g12_realized_cost_exceeds_disclosure",
                    message=(
                        f"Fill cost_bps={float(ack.cost_bps):.4f} exceeds "
                        f"{alert_ratio}× G12 disclosed one-way "
                        f"cost_total_bps={disclosed:.4f} "
                        f"(strategy_id={order.strategy_id!r}, "
                        f"symbol={ack.symbol!r}, order_id={ack.order_id!r})"
                    ),
                    context={
                        "strategy_id": order.strategy_id,
                        "symbol": ack.symbol,
                        "order_id": ack.order_id,
                        "realized_cost_bps": float(ack.cost_bps),
                        "g12_disclosed_cost_total_bps": disclosed,
                        "alert_ratio": alert_ratio,
                    },
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
                    trading_intent=self._order_trading_intent.get(
                        ack.order_id, "",
                    ),
                ))

        self._prune_terminal_orders()

    def _distribute_fill_to_strategies(
        self,
        symbol: str,
        signed_qty: int,
        fill_price: Decimal,
        fees: Decimal,
        timestamp_ns: int,
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
        remainder_sid: str | None = None
        for (sid, _q), alloc_qty in zip(strategy_qtys, floors, strict=True):
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
                timestamp_ns=timestamp_ns,
            )
            remainder_sid = sid

        # Assign any rounding remainder to the last non-zero allocation.
        if fee_remainder != Decimal("0") and remainder_sid is not None:
            self._strategy_positions.debit_fees(
                remainder_sid,
                symbol,
                fee_remainder,
            )

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
            self._order_trading_intent.pop(oid, None)

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
        q = self._tick_quote_for_trace
        if event.layer != "SIGNAL":
            if self._signal_order_trace_sink is not None and q is not None:
                self._append_signal_order_trace(
                    q,
                    event,
                    outcome="NO_ORDER",
                    reasons=(
                        "filtered_bus_signal_pipeline_wrong_layer",
                        f"layer={event.layer!r}",
                    ),
                )
            return
        if event.strategy_id == "__stop_exit__":
            if self._signal_order_trace_sink is not None and q is not None:
                self._append_signal_order_trace(
                    q,
                    event,
                    outcome="NO_ORDER",
                    reasons=("filtered_stop_exit_routed_inline_only",),
                )
            return
        if self._is_consumed_by_portfolio(event.strategy_id):
            if self._signal_order_trace_sink is not None and q is not None:
                self._append_signal_order_trace(
                    q,
                    event,
                    outcome="NO_ORDER",
                    reasons=(
                        "filtered_alpha_consumed_by_portfolio_composition",
                    ),
                )
            return
        self._signal_buffer.append(event)
        if not self._quote_tick_in_flight:
            self._carryover_signal_sequences.add(event.sequence)

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
                "orchestrator: %d standalone SIGNAL candidate(s) from %d "
                "alpha id(s) fired on the same tick (%s); arbitrating via "
                "%s.  Prefer a PORTFOLIO alpha listing these ids in "
                "depends_on_signals for full multi-alpha aggregation.",
                len(buf),
                len(ids),
                ids,
                type(self._signal_arbitrator).__name__,
            )
        return self._signal_arbitrator.arbitrate(buf)

    # ── PR-2b-iv: bus-driven SizedPositionIntent handler ────────────

    def _on_bus_sized_intent(self, event: Event) -> None:
        """Buffer or immediately execute ``SizedPositionIntent`` (Inv-9 parity).

        During ``_process_tick`` (``_quote_tick_in_flight``), intents are
        queued and drained by :meth:`_flush_pending_sized_intents` after the
        ``CROSS_SECTIONAL`` bookend so M5–M10 record PORTFOLIO execution.
        Out-of-tick bus publishes (unit tests, diagnostics) execute
        immediately without micro transitions — micro stays at ``WAITING``.
        """
        if not isinstance(event, SizedPositionIntent):
            return
        if self._quote_tick_in_flight:
            self._pending_sized_intents.append(event)
        else:
            self._submit_portfolio_leg_without_micro_walk(event, event.correlation_id)

    # ── Audit R1: bus-driven hazard-exit OrderRequest handler ────────

    _HAZARD_EXIT_REASONS: frozenset[str] = frozenset(
        {"HAZARD_SPIKE", "HARD_EXIT_AGE"}
    )

    def _on_bus_hazard_order(self, event: Event) -> None:
        """Route hazard-exit ``OrderRequest`` events to the execution backend.

        ``HazardExitController._emit_exit`` publishes an
        ``OrderRequest`` (with ``source_layer="RISK"`` and ``reason in
        {"HAZARD_SPIKE", "HARD_EXIT_AGE"}``) but does NOT call any
        router itself.  Pre-R1 there was no production subscriber that
        bridged these orders to ``backend.order_router.submit``, so
        every hazard exit was silently inert in any composed
        deployment.  This handler closes that gap.

        Filtering is intentionally tight: only orders matching the
        controller's exact signature are submitted from here.  Orders
        published by ``_on_bus_sized_intent`` (PORTFOLIO leg fan-out),
        ``_emergency_flatten_all``, ``_execute_reverse``, and the
        normal SIGNAL walk all reach the router via their direct
        ``self._backend.order_router.submit`` calls upstream of their
        ``self._bus.publish(order)``; this handler must NOT
        double-submit them when their published copy reaches the bus.

        Inv-11 (fail-safe): hazard exits are exit-direction-only by
        construction in ``HazardExitController`` (the order side is
        always opposite the position sign) so they cannot increase
        exposure.  A defensive ``check_order`` runs for audit parity;
        ``REJECT`` verdicts are logged and the order is still submitted
        (mirroring emergency flatten).  See ``risk/engine.py`` for the
        formal sole-gatekeeper carve-outs.
        """
        if not isinstance(event, OrderRequest):
            return
        if event.source_layer != "RISK":
            return
        if event.reason not in self._HAZARD_EXIT_REASONS:
            return
        # Idempotency guard against a duplicate publish of the same
        # hazard order_id (e.g. a misconfigured second subscriber
        # echoing onto the bus, or a controller bug bypassing its
        # own episode-suppression).  ``_active_orders`` is pruned on
        # terminal states so it can't serve as a long-lived dedup
        # set; ``_hazard_submitted_order_ids`` is hazard-only and
        # never pruned (one entry per episode-symbol-reason —
        # bounded by trading volume per session).
        if event.order_id in self._hazard_submitted_order_ids:
            return
        self._hazard_submitted_order_ids.add(event.order_id)
        hv = self._risk_engine.check_order(event, self._positions)
        # Do not broadcast FORCE_FLATTEN: downstream subscribers may treat it as
        # a global lockdown trigger while this handler still submits the exit
        # (Inv-11 fail-safe).  REJECT / ALLOW are fine for audit parity.
        if hv.action != RiskAction.FORCE_FLATTEN:
            self._bus.publish(hv)
        if hv.action == RiskAction.REJECT:
            self._bus.publish(Alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=event.correlation_id,
                sequence=self._seq.next(),
                severity=AlertSeverity.WARNING,
                layer="kernel",
                alert_name="hazard_exit_defensive_check_order_reject",
                message=(
                    "Defensive check_order returned REJECT on a hazard exit "
                    f"(strategy_id={event.strategy_id!r}, symbol={event.symbol!r}, "
                    f"reason={hv.reason!r}) — submitting anyway (Inv-11 exit "
                    "fail-safe)."
                ),
                context={
                    "order_id": event.order_id,
                    "risk_reason": hv.reason,
                },
            ))
        self._track_order(event.order_id, event.side, event)
        self._transition_order(
            event.order_id,
            OrderState.SUBMITTED,
            event.reason,
            correlation_id=event.correlation_id,
        )
        try:
            self._backend.order_router.submit(event)
        except Exception as exc:  # noqa: BLE001 — fail-safe: never raise from bus
            logger.exception(
                "Hazard exit order submission failed for %s "
                "(strategy_id=%s, reason=%s, order_id=%s); position "
                "remains open and will be retried on the next spike.",
                event.symbol, event.strategy_id, event.reason,
                event.order_id,
            )
            self._reject_order_after_submit_failure(event, exc)
            return
        acks = self._poll_order_router_acks({event.order_id})
        for ack in acks:
            self._bus.publish(ack)
            self._apply_ack_to_order(ack)
        self._reconcile_fills(acks, event.correlation_id)

    # ── Configuration and data integrity ────────────────────────────

    # ── BT-5: LULD halt modeling ────────────────────────────────────

    def _update_halt_state(self, trade: Trade) -> None:
        """Register halt-on / resume edges from the Trade tape (BT-5).

        On halt-on for a symbol not already halted: mark it halted, cancel
        any resting orders (Inv-11), and emit ``SymbolHalted``.  On resume:
        clear the halt, open the entry blackout window, and emit the resume
        ``SymbolHalted``.  Inert when no halt codes are configured.
        """
        if not self._halt_on_codes and not self._halt_off_codes:
            return
        status = classify_halt_status(
            trade.conditions, self._halt_on_codes, self._halt_off_codes,
        )
        if status is None:
            return
        symbol = trade.symbol
        if status is HaltSignal.HALT_ON:
            if symbol not in self._halted_symbols:
                self._halted_symbols.add(symbol)
                self._halt_blackout_until_ns.pop(symbol, None)
                self._cancel_resting_for_symbol(symbol, trade.correlation_id)
                self._emit_symbol_halted(
                    symbol,
                    halted=True,
                    reason="LULD_HALT",
                    ts=trade.timestamp_ns,
                    correlation_id=trade.correlation_id,
                    blackout_until_ns=0,
                )
        elif symbol in self._halted_symbols:
            self._halted_symbols.discard(symbol)
            deadline = trade.timestamp_ns + self._halt_blackout_ns
            self._halt_blackout_until_ns[symbol] = deadline
            self._emit_symbol_halted(
                symbol,
                halted=False,
                reason="LULD_RESUME",
                ts=trade.timestamp_ns,
                correlation_id=trade.correlation_id,
                blackout_until_ns=deadline,
            )

    def _in_halt_blackout(self, symbol: str, now_ns: int) -> bool:
        """True while a symbol is inside its post-resume entry blackout."""
        deadline = self._halt_blackout_until_ns.get(symbol)
        return deadline is not None and now_ns < deadline

    def _emit_symbol_halted(
        self,
        symbol: str,
        *,
        halted: bool,
        reason: str,
        ts: int,
        correlation_id: str,
        blackout_until_ns: int,
    ) -> None:
        """Publish the forensic ``SymbolHalted`` marker."""
        self._bus.publish(SymbolHalted(
            timestamp_ns=ts,
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            source_layer="kernel",
            symbol=symbol,
            halted=halted,
            reason=reason,
            blackout_until_ns=blackout_until_ns,
        ))

    # ── BT-6: Reg-SHO / SSR short-sale restriction ──────────────────

    def _update_ssr_state(self, trade: Trade) -> None:
        """Flip a symbol SSR-active when the tape's trigger codes fire (BT-6).

        SSR is sticky for the session — once active it never clears intraday —
        so this only ever adds.  Inert when no trigger codes are configured.
        """
        if not self._ssr_codes:
            return
        if not (set(trade.conditions) & self._ssr_codes):
            return
        symbol = trade.symbol.upper()
        if symbol in self._ssr_active:
            return
        self._ssr_active.add(symbol)
        self._bus.publish(Alert(
            timestamp_ns=trade.timestamp_ns,
            correlation_id=trade.correlation_id,
            sequence=self._seq.next(),
            severity=AlertSeverity.INFO,
            layer="kernel",
            alert_name="ssr_triggered",
            message=f"SSR became active intraday for {symbol} (Reg-SHO 201).",
            context={"symbol": symbol},
        ))

    # ── BT-7: static borrow-availability ────────────────────────────

    def _borrow_tier_for(self, symbol: str) -> BorrowTier:
        """Locate tier for ``symbol``; omitted symbols default to AVAILABLE."""
        return self._borrow_tier.get(symbol.upper(), BorrowTier.AVAILABLE)

    def _borrow_blocks_intent(self, intent: OrderIntent) -> bool:
        """True when locate is unavailable and this intent is a short sale."""
        return (
            self._borrow_tier_for(intent.symbol) == BorrowTier.UNAVAILABLE
            and is_short_sale_intent(intent)
        )

    def _emit_locate_unavailable_alert(
        self, intent: OrderIntent, correlation_id: str,
    ) -> None:
        """Publish the forensic marker for a refused short entry (no locate)."""
        self._bus.publish(Alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            severity=AlertSeverity.WARNING,
            layer="kernel",
            alert_name="locate_unavailable",
            message=(
                f"No borrow locate for {intent.symbol!r}: refused short entry "
                f"({intent.intent.name}); retries next boundary."
            ),
            context={"symbol": intent.symbol, "intent": intent.intent.name},
        ))

    def _ssr_blocks_intent(self, intent: OrderIntent) -> bool:
        """True when SSR (refuse_short) must refuse this short-opening order."""
        if intent.symbol.upper() not in self._ssr_active:
            return False
        return is_short_sale_intent(intent)

    def _emit_ssr_suppression_alert(
        self, intent: OrderIntent, correlation_id: str,
    ) -> None:
        """Publish the forensic marker for a refused SSR short entry."""
        self._bus.publish(Alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            severity=AlertSeverity.WARNING,
            layer="kernel",
            alert_name="ssr_short_suppressed",
            message=(
                f"SSR active for {intent.symbol!r}: refused short entry "
                f"({intent.intent.name}); retries next boundary (Reg-SHO 201)."
            ),
            context={"symbol": intent.symbol, "intent": intent.intent.name},
        ))

    def _data_health_blocks_trading(self, symbol: str, correlation_id: str) -> bool:
        """Return True when the Massive normalizer forbids consuming this symbol.

        CORRUPTED always halts trading for the symbol when a normalizer is wired.
        GAP_DETECTED does the same only when ``PlatformConfig.degrade_on_data_gap``
        is enabled (strict paper/live policy).

        HALTED (BT-5) blocks the tick without escalating macro — LULD halts
        are recoverable and ``DataHealth.HALTED → HEALTHY`` is the resume
        path.  This sits alongside the orchestrator-side ``_halted_symbols``
        edge tracker (which retains the cancel-resting + post-halt blackout
        side effects) so the normalizer's view is *also* load-bearing here:
        if the two ever drift, the more conservative gate wins (audit M1).
        """
        if self._normalizer is None:
            return False
        health = self._normalizer.health(symbol)
        cfg_syms = (
            {s.upper() for s in self._config.symbols}
            if self._config is not None
            else frozenset()
        )
        if getattr(self._config, "strict_normalizer_symbol_coverage", False):
            if symbol.upper() in cfg_syms:
                tracked = {k.upper() for k in self._normalizer.all_health()}
                if symbol.upper() not in tracked:
                    if self._macro.can_transition(MacroState.DEGRADED):
                        self._macro.transition(
                            MacroState.DEGRADED,
                            trigger=f"DATA_SYMBOL_UNTRACKED:{symbol}",
                            correlation_id=correlation_id,
                        )
                    return True
        if health == DataHealth.CORRUPTED:
            # Force-flatten the affected symbol before transitioning macro.
            # CORRUPTED is terminal — leaving an open position to mark at
            # the last-known quote would carry stale risk through DEGRADED.
            self._force_flatten_symbol_on_degrade(
                symbol, correlation_id, reason="DATA_CORRUPTED",
            )
            if self._macro.can_transition(MacroState.DEGRADED):
                self._macro.transition(
                    MacroState.DEGRADED,
                    trigger=f"DATA_CORRUPTED:{symbol}",
                    correlation_id=correlation_id,
                )
            return True
        if health == DataHealth.HALTED:
            # Recoverable halt — block fills for this symbol but do NOT
            # escalate macro (a real LULD pause is expected to resume).
            # Side effects (cancel resting, blackout window) live in the
            # orchestrator's ``_update_halt_state`` edge detector; this
            # gate provides defense-in-depth in case that detector and
            # the normalizer ever disagree.
            return True
        degrade_gap = getattr(self._config, "degrade_on_data_gap", False)
        if degrade_gap and health == DataHealth.GAP_DETECTED:
            # GAP_DETECTED can recover to HEALTHY, but the macro DEGRADED
            # transition is sticky (requires explicit operator command).
            # Unwind the affected symbol at the last-known mark so the
            # book doesn't carry stale exposure through the gap window.
            self._force_flatten_symbol_on_degrade(
                symbol, correlation_id, reason="DATA_GAP_DETECTED",
            )
            if self._macro.can_transition(MacroState.DEGRADED):
                self._macro.transition(
                    MacroState.DEGRADED,
                    trigger=f"DATA_GAP_DETECTED:{symbol}",
                    correlation_id=correlation_id,
                )
            return True
        return False

    def _force_flatten_symbol_on_degrade(
        self,
        symbol: str,
        correlation_id: str,
        *,
        reason: str,
    ) -> None:
        """Submit a MARKET flatten for ``symbol`` before macro DEGRADED.

        Best-effort: any submit exception is logged and surfaced via
        WARNING alert but does not raise, so a single broken symbol
        cannot block the DEGRADED transition (Inv-11 fail-safe).  The
        order_id is content-addressed on ``(reason, symbol, sequence)``
        so replays produce bit-identical IDs.
        """
        pos = self._positions.get(symbol)
        if pos.quantity == 0:
            return
        side = Side.SELL if pos.quantity > 0 else Side.BUY
        qty = abs(pos.quantity)
        seq = self._seq.next()
        order_id = hashlib.sha256(
            f"degrade_flatten:{reason}:{symbol}:{seq}".encode()
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
            strategy_id="degrade_flatten",
            reason=reason,
        )
        try:
            self._track_order(order_id, side, order)
            self._transition_order(
                order_id,
                OrderState.SUBMITTED,
                f"degrade_flatten:{reason}",
                correlation_id=correlation_id,
            )
            self._backend.order_router.submit(order)
            self._bus.publish(order)
            acks = self._poll_order_router_acks({order_id})
            for ack in acks:
                self._bus.publish(ack)
                self._apply_ack_to_order(ack)
            self._reconcile_fills(acks, correlation_id)
        except Exception as exc:  # noqa: BLE001 — fail-safe; never raise
            logger.exception(
                "Force-flatten on %s failed for symbol=%s (qty=%d, side=%s); "
                "position remains open and will require manual intervention.",
                reason, symbol, qty, side.name,
            )
            self._bus.publish(Alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                severity=AlertSeverity.CRITICAL,
                layer="kernel",
                alert_name="degrade_flatten_failed",
                message=(
                    f"Force-flatten on {reason} failed for symbol={symbol!r} "
                    f"(qty={qty}, side={side.name}). Position remains open."
                ),
                context={
                    "symbol": symbol,
                    "reason": reason,
                    "exception": repr(exc),
                },
            ))


    def _verify_data_integrity(self) -> bool:
        """Verify data integrity for all configured symbols.

        If a normalizer is available, checks that every configured
        symbol is tracked and reports HEALTHY.

        Without a normalizer (cached replay / offline logs), optional
        ``PlatformConfig.require_healthy_disk_cache_manifests`` enforces
        per-day ``ingestion_health`` rows supplied by the ingest/replay path.
        """
        if self._config is None:
            return True

        if self._normalizer is not None:
            health = self._normalizer.all_health()
            for symbol in self._config.symbols:
                if symbol not in health or health[symbol] != DataHealth.HEALTHY:
                    return False
            return True

        if getattr(self._config, "require_healthy_disk_cache_manifests", False):
            rows = getattr(self._config, "disk_cache_ingestion_health_rows", ()) or ()
            if not rows:
                logger.warning(
                    "require_healthy_disk_cache_manifests=True but "
                    "disk_cache_ingestion_health_rows is empty — integrity fail"
                )
                return False
            for sym, day, h in rows:
                if h != "HEALTHY":
                    logger.warning(
                        "disk cache ingestion_health=%s for %s/%s — integrity fail",
                        h,
                        sym,
                        day,
                    )
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
