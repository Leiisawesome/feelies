"""Coordinate deterministic platform state and tick processing.

Domain calculations remain in their owning layers. The orchestrator enforces
trading-mode gates, deterministic order IDs and replay transitions, terminal
order resolution before shutdown, and fail-safe degradation or lockdown. All
modes share the same tick pipeline and publish every state transition.
"""

from __future__ import annotations

import hashlib
import itertools
import logging
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Mapping

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from feelies.alpha.fill_attribution import FillAttributionLedger
    from feelies.alpha.registry import AlphaRegistry
    from feelies.composition.engine import CompositionEngine
    from feelies.monitoring.horizon_metrics import HorizonMetricsCollector
    from feelies.portfolio.cross_sectional_tracker import CrossSectionalTracker
    from feelies.portfolio.strategy_position_store import StrategyPositionStore
    from feelies.risk.exit_composer import ExitComposer
    from feelies.risk.hazard_exit import HazardExitController

from feelies.alpha.arbitration import (
    EdgeWeightedArbitrator,
    SignalArbitrator,
    StandaloneArbitrationCollision,
    collision_is_harmless_flat_gate_close,
    is_redundant_gate_close_flat,
    standalone_signal_actionable_for_strategy,
)

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
    TrendMechanism,
)
from feelies.core.identifiers import SequenceGenerator, derive_order_id
from feelies.core.state_machine import StateMachine, TransitionRecord
from feelies.execution.backend import ExecutionBackend
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
from feelies.execution.portfolio_netter import (
    DesiredTargetBook,
    NetDivergence,
    PortfolioNetter,
    standing_target_from_desired,
)
from feelies.execution.position_manager import (
    DesiredPosition,
    ExecStyle,
    MarketContext,
    PlanDivergence,
    PlanLeg,
    PositionManager,
    PositionManagerConfig,
    PositionPlan,
    compare_plan_to_intent,
    desired_from_signal,
    entry_edge_clears_cost,
    order_intent_from_plan,
    reversal_edge_gate,
    round_trip_cost_bps,
)
from feelies.execution.trading_session import TradingSessionBounds
from feelies.execution.regulatory.borrow_availability import (
    BorrowTier,
    build_borrow_table,
    htb_fee_applies,
    is_short_sale_intent,
    parse_borrow_tier,
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
from feelies.portfolio.lot_ledger import LotLedger
from feelies.risk.engine import RiskEngine
from feelies.risk.escalation import RiskLevel, create_risk_escalation_machine
from feelies.risk.exit_composer import EXIT_COMPOSER_EXIT_REASONS
from feelies.risk.hazard_exit import HAZARD_EXIT_REASONS, HAZARD_EXIT_SOURCE_LAYER
from feelies.risk.edge_weighted_sizer import (
    EdgeWeightedSizer,
    SizeDivergence,
    apply_tilt,
)
from feelies.risk.position_sizer import BudgetBasedSizer, PositionSizer
from feelies.risk.post_exit_position_view import PostExitPositionView
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.registry import SensorRegistry
from feelies.services.regime_engine import RegimeEngine, regime_posterior_entropy_nats
from feelies.services.regime_hazard_detector import RegimeHazardDetector
from feelies.signals.horizon_engine import HorizonSignalEngine
from feelies.storage.event_log import EventLog
from feelies.storage.feature_snapshot import FeatureSnapshotMeta, FeatureSnapshotStore
from feelies.storage.trade_journal import TradeJournal, TradeRecord

if TYPE_CHECKING:
    from feelies.execution.cost_model import CostModel
    from feelies.portfolio.position_store import Position

# Stable correlation IDs for lifecycle transitions.
_PLATFORM_BOOT_CORRELATION_ID = "platform_boot"
_ORCHESTRATOR_SHUTDOWN_CORRELATION_ID = "orchestrator_shutdown"


_TERMINAL_ORDER_STATES: frozenset[OrderState] = frozenset(
    {
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
    }
)

# Exposure-increasing intents are blocked after a halt; exits remain allowed.
_ENTRY_OPENING_INTENTS: frozenset[TradingIntent] = frozenset(
    {
        TradingIntent.ENTRY_LONG,
        TradingIntent.ENTRY_SHORT,
        TradingIntent.SCALE_UP,
        TradingIntent.REVERSE_LONG_TO_SHORT,
        TradingIntent.REVERSE_SHORT_TO_LONG,
    }
)

# Synthetic strategies whose exits must always cross at MARKET — a
# guaranteed close (stop-loss, end-of-day flatten) is never left to a
# passive non-fill (Inv-11).
_FORCED_MARKET_EXIT_STRATEGIES: frozenset[str] = frozenset(
    {
        "__stop_exit__",
        "__session_flat__",
    }
)

# Stop exits receive panic-fill pricing; scheduled session flats do not.
_FORCED_EXIT_PANIC_REASON: Mapping[str, str] = MappingProxyType(
    {
        "__stop_exit__": "STOP_EXIT",
    }
)

# Reducing forced-exit reasons routed through the non-vetoable RISK-layer bridge
# (:meth:`Orchestrator._on_bus_hazard_order`).  Both authors — the hazard
# controller and the exit composer — stamp ``source_layer="RISK"`` and one of
# these reasons; the union keeps the bridge's membership test a single source of
# truth so adding a reason to either writer automatically extends what routes,
# and a mandated exit never silently drops (Inv-11 fail-safe).
_RISK_FORCED_EXIT_REASONS: frozenset[str] = HAZARD_EXIT_REASONS | EXIT_COMPOSER_EXIT_REASONS


def _int_to_direction(sign: int) -> SignalDirection:
    """Map a signed direction (+1 / -1 / 0) to a ``SignalDirection``."""
    if sign > 0:
        return SignalDirection.LONG
    if sign < 0:
        return SignalDirection.SHORT
    return SignalDirection.FLAT


class Orchestrator:
    """Central coordinator for the deterministic tick-processing pipeline.

    ``boot`` wires configuration, ``run_*`` drives the one shared tick path,
    and ``shutdown`` drains outstanding acknowledgements before G9. Execution
    mode differences remain confined to :class:`ExecutionBackend`.

    Standalone ``Signal`` and portfolio ``SizedPositionIntent`` events arrive
    on the bus. Portfolio intents are drained first; one arbitrated standalone
    signal may then walk M4–M10. Signals consumed by a portfolio are filtered
    from the standalone path to prevent double trading. Forced exits override
    alpha conviction and always retain fail-safe priority.
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
        exit_composer: "ExitComposer | None" = None,
        signal_arbitrator: SignalArbitrator | None = None,
        edge_calibration_factors: Mapping[str, float] | None = None,
        signal_order_trace_sink: list[SignalOrderTraceRow] | None = None,
        regime_calibration_quotes: Sequence[NBBOQuote] | None = None,
        position_manager: "PositionManager | None" = None,
        position_manager_shadow_sink: "list[PlanDivergence] | None" = None,
        position_manager_drive: bool = False,
        position_manager_enable_trim: bool = False,
        position_manager_trim_edge_gate_multiplier: float = 0.0,
        position_manager_urgency_exec: bool = False,
        net_shadow_sink: "list[NetDivergence] | None" = None,
        net_shadow_portfolio_max_abs_qty: int | None = None,
        size_shadow_sizer: "EdgeWeightedSizer | None" = None,
        size_shadow_sink: "list[SizeDivergence] | None" = None,
        thread_safe_sequences: bool = True,
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
        # Signal gates use the alpha-YAML registry key, not the Python class name.
        self._regime_engine_registry_name = regime_engine_registry_name
        self._intent_translator: IntentTranslator = (
            intent_translator if intent_translator is not None else SignalPositionTranslator()
        )
        self._position_sizer: PositionSizer = (
            position_sizer
            if position_sizer is not None
            else BudgetBasedSizer(regime_engine=regime_engine)
        )
        # Shadow the planner without affecting orders, events, or journals.
        self._position_manager = position_manager
        self._position_manager_shadow_sink = position_manager_shadow_sink
        # When enabled, the planner supplies the live OrderIntent.
        self._position_manager_drive = position_manager_drive
        # Allow cost-aware partial reductions when a same-direction target shrinks.
        self._position_manager_enable_trim = position_manager_enable_trim
        # Suppress trims while forward edge clears this cost multiple; 0 disables.
        self._position_manager_trim_edge_gate_multiplier = (
            position_manager_trim_edge_gate_multiplier
        )
        # Post discretionary trims passively; unfilled residuals later cross at MARKET.
        self._position_manager_urgency_exec = position_manager_urgency_exec
        # Shadow the budget-weighted portfolio target against the arbitrated winner.
        self._desired_target_book = DesiredTargetBook()
        self._net_portfolio_max_abs_qty: int | None = net_shadow_portfolio_max_abs_qty
        self._portfolio_netter = PortfolioNetter(
            self._desired_target_book,
            portfolio_max_abs_qty=self._net_portfolio_max_abs_qty,
        )
        self._net_shadow_sink = net_shadow_sink
        # Shadow edge/vol/inventory sizing without affecting live orders.
        self._size_shadow_sizer = size_shadow_sizer
        self._size_shadow_sink = size_shadow_sink
        # Expire shadow targets at the same horizon as the live signal buffer.
        self._net_staleness_k: float = 1.0
        # Horizon-zero targets last one tick; evict these keys on the next update.
        self._net_shadow_transient_keys: set[tuple[str, str]] = set()
        # Drive from the portfolio net target when enabled.
        self._enable_portfolio_netting: bool = False
        self._alpha_registry = alpha_registry
        self._account_equity = account_equity
        self._fill_ledger = fill_ledger
        self._strategy_positions = strategy_positions
        self._cost_model: "CostModel | None" = cost_model
        self._market_context = MarketContext()
        # BACKTEST bootstrap passes thread_safe_sequences=False (single-
        # threaded replay); paper/live keep the lock.
        _seq_kw = {"thread_safe": thread_safe_sequences}
        self._seq = SequenceGenerator(**_seq_kw)

        # Optional sensor and horizon components; None keeps the short tick path.
        self._sensor_registry = sensor_registry
        self._horizon_scheduler = horizon_scheduler
        self._horizon_signal_engine = horizon_signal_engine
        # Separate sequence families prevent optional stages from shifting kernel
        # event IDs. Bootstrap shares these exact generators with each producer.
        self._sensor_seq = sensor_sequence_generator or SequenceGenerator(**_seq_kw)
        self._horizon_seq = horizon_sequence_generator or SequenceGenerator(**_seq_kw)
        self._snapshot_seq = snapshot_sequence_generator or SequenceGenerator(**_seq_kw)
        self._signal_seq = signal_sequence_generator or SequenceGenerator(**_seq_kw)
        # Hazard events use an isolated sequence so exits cannot shift other IDs.
        self._regime_hazard_detector = regime_hazard_detector
        self._hazard_seq = hazard_sequence_generator or SequenceGenerator(**_seq_kw)
        # Bootstrap wires optional composition components to the bus; these
        # references support orchestration and inspection.
        self._composition_engine = composition_engine
        self._cross_sectional_tracker = cross_sectional_tracker
        self._composition_metrics_collector = composition_metrics_collector
        self._hazard_exit_controller = hazard_exit_controller
        # Stage-0 exit composer (risk layer): actuates decoupled alphas' unwind
        # from ``SafetyStateChange``.  It self-subscribes to the bus in bootstrap;
        # the orchestrator holds the reference for lifecycle/inspection symmetry
        # with ``_hazard_exit_controller``.  Its emitted flatten ``OrderRequest``
        # routes through ``_on_bus_hazard_order`` like any RISK-layer forced exit.
        self._exit_composer = exit_composer
        self._signal_arbitrator: SignalArbitrator = (
            signal_arbitrator if signal_arbitrator is not None else EdgeWeightedArbitrator()
        )
        self._signal_order_trace_sink: list[SignalOrderTraceRow] | None = signal_order_trace_sink
        self._paper_session_recorder: PaperSessionRecorder | None = None
        self._quote_tick_in_flight: bool = False
        self._tick_quote_for_trace: NBBOQuote | None = None
        # Preserve the last quote so inter-quote signals can produce trace rows.
        self._last_quote_context_for_signal_trace: NBBOQuote | None = None
        self._signal_order_trace_seen_sequences: set[int] = set()
        # Only inter-quote signals may cross one quote boundary; M4 consumes them.
        self._carryover_signal_sequences: set[int] = set()
        # Reset session-local hazard history while retaining the regime engine's
        # calibrated posterior across sessions.
        self._last_regime_state: dict[tuple[str, str], RegimeState] = {}
        # Symbols for which ``_update_regime`` has published at least one
        # ``RegimeState`` on the bus this session.  The trade path drives
        # the horizon scheduler without a micro-SM walk and without calling
        # ``_update_regime`` (regime engines require NBBO quotes).  Emitting
        # ``HorizonTick``s before the first quote-driven publish leaves
        # ``HorizonSignalEngine`` with an empty regime cache, so ``P(...)``
        # gates fail safe with a cold-start WARNING.  Trade-path ticks are
        # deferred until this set contains the symbol (see
        # ``_process_trade_inner``); quote-path ticks are unaffected because
        # M2 publishes RegimeState before the scheduler runs.
        self._regime_bus_published_symbols: set[str] = set()

        self._stop_loss_per_share: float = 0.0
        self._trail_activate_per_share: float = 0.0
        self._stop_loss_pct: float = 0.0
        self._trail_activate_pct: float = 0.0
        self._trail_pct: float = 0.5
        self._peak_pnl_per_share: dict[str, float] = {}
        # Optional EOD flatten blocks entries and closes positions near RTH close.
        self._session_flatten_enabled: bool = False
        self._session_flatten_seconds_before_close: int = 0
        self._min_order_shares: int = 1
        # Minimum edge-to-round-trip-cost ratio; 0 disables the gate.
        self._signal_min_edge_cost_ratio: float = 1.0
        # Convert disclosed one-way edge to a round-trip basis when configured.
        self._signal_edge_cost_basis: str = "round_trip"
        # Fixed per-alpha realization factors shrink disclosed edge toward observed edge.
        self._edge_calibration_factors: dict[str, float] = (
            dict(edge_calibration_factors) if edge_calibration_factors else {}
        )
        # Require reversal entry edge to clear combined exit and entry cost.
        self._reversal_min_edge_cost_multiplier: float = 1.5
        # Alert when realized cost exceeds disclosed cost by this ratio.
        self._realized_cost_alert_ratio: float = 1.5
        # Optional lockdown after repeated realized-cost overruns.
        self._realized_cost_escalation_enabled: bool = False
        self._realized_cost_escalation_streak: int = 3
        # Per-strategy consecutive realized-cost-overrun streak counter.
        self._realized_cost_breach_streak: dict[str, int] = {}
        self._regime_calibration_max_quotes: int | None = None
        self._regime_calibration_quotes: tuple[NBBOQuote, ...] | None = (
            tuple(regime_calibration_quotes) if regime_calibration_quotes is not None else None
        )

        self._config: Configuration | None = None

        # Active order state machines keyed by order ID.
        self._active_orders: dict[str, tuple[StateMachine[OrderState], Side, OrderRequest]] = {}
        # Submission-time intent used to stamp TradeRecord attribution.
        self._order_trading_intent: dict[str, str] = {}
        # Latest signal mechanism per strategy and symbol, used only for fills.
        self._last_signal_mechanism: dict[tuple[str, str], tuple[TrendMechanism | None, int]] = {}
        # Passive reductions that require MARKET fallback on unfilled residuals.
        self._working_exit_fallback: dict[str, tuple[str, Side, int]] = {}
        self._order_filled_qty: dict[str, int] = {}
        # FIFO lot attribution; never feeds decisions.
        self._lot_ledger = LotLedger()
        # Acks buffered by targeted pollers so unrelated order families are not lost.
        self._deferred_router_acks: list[OrderAck] = []

        # When True, market events arriving from the data source are
        # already present in the event log (replay mode).  Prevents
        # re-appending identical events during backtest replay.
        self._events_prelogged = False
        # When tick-failure recovery cannot transition macro to DEGRADED,
        # stop consuming market events (fail-safe — avoids trading in an
        # unknown macro/micro pairing).
        self._pipeline_abort_requested = False

        # LULD state and post-resume entry blackout; empty codes disable modeling.
        self._halted_symbols: set[str] = set()
        self._halt_blackout_until_ns: dict[str, int] = {}
        self._halt_on_codes: frozenset[int] = frozenset()
        self._halt_off_codes: frozenset[int] = frozenset()
        self._halt_blackout_ns: int = 0

        # Session-sticky SSR symbols; empty inputs disable the restriction.
        self._ssr_active: set[str] = set()
        self._ssr_codes: frozenset[int] = frozenset()
        self._ssr_mode: str = "refuse_short"

        # Static locate tiers; omitted symbols use the configured default.
        self._borrow_tier: dict[str, BorrowTier] = {}
        # AVAILABLE is optimistic; use hard or unavailable for conservative universes.
        self._borrow_default_tier: BorrowTier = BorrowTier.AVAILABLE

        # Strategies routed to MOC once session bounds resolve.
        self._moc_strategy_ids: frozenset[str] = frozenset()
        self._moc_bounds_configured: bool = False

        # RTH entry suppression and close buying-power transition.
        self._trading_session_bounds: TradingSessionBounds | None = None
        self._rth_close_bp_flipped: bool = False
        # NY session date the BP flip is currently armed for.  Tracked so a
        # multi-day replay re-arms the flip (and reopens on the intraday cap)
        # at each new session date instead of latching OVERNIGHT after day 1.
        self._rth_bp_session_date: date | None = None

        # Static passive routing; forced exits always use MARKET.
        self._use_passive_entries = False
        # Optional per-order policy overrides the static route in minimum-cost mode.
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

        # Buffer standalone signals for one arbitrated M4 order walk. Signals
        # consumed by a PORTFOLIO alpha are excluded to prevent double trading.
        self._signal_buffer: list[Signal] = []
        self._alpha_symbols_with_fills: set[tuple[str, str]] = set()
        self._arbitration_collisions: list[StandaloneArbitrationCollision] = []
        self._pending_sized_intents: deque[SizedPositionIntent] = deque()
        self._consumed_by_portfolio_ids: frozenset[str] | None = None
        self._warned_multi_standalone_signals: bool = False
        self._logged_harmless_arbitration_collision: bool = False
        self._bus.subscribe(Signal, self._on_bus_signal)

        # Drain PORTFOLIO intents after CROSS_SECTIONAL and before the standalone
        # M4 walk, so portfolio fills update positions first.
        self._bus.subscribe(SizedPositionIntent, self._on_bus_sized_intent)

        # Hazard IDs remain deduplicated after terminal orders leave _active_orders.
        self._hazard_submitted_order_ids: set[str] = set()

        # Route only controller-authored hazard exits. The handler submits,
        # acknowledges, and reconciles without republishing the bus order.
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
                trading_intent=(trading_intent if trading_intent is not None else "—"),
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
                if not self._standalone_signal_actionable_for_strategy_ownership(s):
                    continue
                self._append_signal_order_trace(
                    quote,
                    s,
                    outcome="NO_ORDER",
                    reasons=("arbitration_returned_none_dead_zone_or_conflict",),
                )
            return
        for s in buf_snapshot:
            if s is bus_selected:
                continue
            if not self._standalone_signal_actionable_for_strategy_ownership(s):
                continue
            self._append_signal_order_trace(
                quote,
                s,
                outcome="NO_ORDER",
                reasons=(f"not_selected_in_arbitration_winner_is:{bus_selected.strategy_id}",),
            )

    # ── Public state accessors ──────────────────────────────────────

    @property
    def macro_state(self) -> MacroState:
        return self._macro.state

    @property
    def micro_state(self) -> MicroState:
        return self._micro.state

    @property
    def arbitration_collisions(self) -> tuple[StandaloneArbitrationCollision, ...]:
        """Post-filter standalone-SIGNAL ticks with 2+ candidates (forensics)."""
        return tuple(self._arbitration_collisions)

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
    def lot_ledger(self) -> LotLedger:
        """FIFO open-lot ledger for age, provenance, and realized PnL."""
        return self._lot_ledger

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
        self,
        recorder: PaperSessionRecorder | None,
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
                "Cannot start session: kill switch is active — reset with operator audit first",
            )
        if self._risk_escalation.state != RiskLevel.NORMAL:
            raise SessionEntryBlockedError(
                f"Cannot start session: risk escalation is "
                f"{self._risk_escalation.state.name}, must be NORMAL — "
                "use reset_risk_escalation() or unlock_from_lockdown()",
            )

    def _bind_router_position_qty_for_rth(self) -> None:
        """Provide live signed positions to the router's RTH gate.

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
        """Switch risk buying-power limits at RTH close.

        Once-per-session-date: the first quote with
        ``exchange_timestamp_ns >= rth_close_ns`` transitions the risk
        engine to :attr:`BuyingPowerPhase.OVERNIGHT` so the 2× overnight
        multiplier is applied to any exits that linger past the close.
        Compared against ``exchange_timestamp_ns`` rather than
        ``timestamp_ns`` so the flip aligns with the exchange-time RTH
        close used by router-side entry gating
        (``BacktestOrderRouter`` / ``PassiveLimitOrderRouter`` and
        :class:`TradingSessionBounds`).

        Multi-day replays run as a single booted session whose quotes span
        several NY dates (``resolve_for_timestamp`` recomputes the close per
        quote).  When the resolved session date advances, re-arm the flip and
        reopen the day on the intraday cap — otherwise the day-1 OVERNIGHT flip
        latches for the whole run and days 2+ trade their entire RTH session
        under the 2× overnight multiplier.

        No-op when RTH gating is disabled or the risk engine does not expose
        ``set_buying_power_phase``.
        """
        bounds = self._trading_session_bounds
        if bounds is None:
            return
        effective = bounds.resolve_for_timestamp(quote.exchange_timestamp_ns)
        set_phase = getattr(self._risk_engine, "set_buying_power_phase", None)

        # New NY session date → reopen on the intraday cap and re-arm the flip.
        if effective.session_date != self._rth_bp_session_date:
            self._rth_bp_session_date = effective.session_date
            if self._rth_close_bp_flipped:
                self._rth_close_bp_flipped = False
                if callable(set_phase):
                    from feelies.risk.buying_power import BuyingPowerPhase

                    set_phase(BuyingPowerPhase.INTRADAY)

        if self._rth_close_bp_flipped:
            return
        if quote.exchange_timestamp_ns < effective.rth_close_ns:
            return
        if not callable(set_phase):
            self._rth_close_bp_flipped = True
            return
        from feelies.risk.buying_power import BuyingPowerPhase

        set_phase(BuyingPowerPhase.OVERNIGHT)
        self._rth_close_bp_flipped = True

    def _reset_buying_power_phase_for_session(self) -> None:
        """Reset the RTH-close buying-power state at session start.

        Clears the latch (and the armed session date) that gate
        :meth:`_maybe_flip_buying_power_at_rth_close` and forces the risk
        engine back onto :attr:`BuyingPowerPhase.INTRADAY` so a new session
        always opens on the 4× intraday cap — even when the same orchestrator
        instance is reused across runs and the previous run left the engine
        flipped to ``OVERNIGHT`` after crossing the close.
        """
        self._rth_close_bp_flipped = False
        self._rth_bp_session_date = None
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
            market_impact_factor = Decimal(str(getattr(config, "cost_market_impact_factor", 0.5)))
            max_impact_half_spreads = Decimal(
                str(getattr(config, "cost_max_impact_half_spreads", 10.0))
            )
            within_l1_impact_factor = Decimal(
                str(getattr(config, "cost_within_l1_impact_factor", 0.0))
            )
            permanent_impact_coefficient = Decimal(
                str(getattr(config, "cost_permanent_impact_coefficient", 0.0))
            )
            self._market_context = MarketContext(
                market_impact_factor=market_impact_factor,
                max_impact_half_spreads=max_impact_half_spreads,
                within_l1_impact_factor=within_l1_impact_factor,
                permanent_impact_coefficient=permanent_impact_coefficient,
            )
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
            # Session-flatten configuration.
            if hasattr(config, "session_flatten_enabled"):
                self._session_flatten_enabled = config.session_flatten_enabled
            if hasattr(config, "session_flatten_seconds_before_close"):
                self._session_flatten_seconds_before_close = int(
                    config.session_flatten_seconds_before_close
                )
            # Cross-alpha netting reuses the platform per-symbol cap.
            if hasattr(config, "enable_portfolio_netting"):
                self._enable_portfolio_netting = config.enable_portfolio_netting
            if hasattr(config, "net_staleness_k"):
                self._net_staleness_k = float(config.net_staleness_k)
            if hasattr(config, "risk_max_position_per_symbol"):
                cap = config.risk_max_position_per_symbol
                self._net_portfolio_max_abs_qty = int(cap) if cap and cap > 0 else None
                self._portfolio_netter = PortfolioNetter(
                    self._desired_target_book,
                    portfolio_max_abs_qty=self._net_portfolio_max_abs_qty,
                )
            # Empty condition-code sets disable halt detection.
            if hasattr(config, "halt_on_condition_codes"):
                self._halt_on_codes = frozenset(config.halt_on_condition_codes)
            if hasattr(config, "halt_off_condition_codes"):
                self._halt_off_codes = frozenset(config.halt_off_condition_codes)
            if hasattr(config, "halt_resolution_blackout_seconds"):
                self._halt_blackout_ns = (
                    int(config.halt_resolution_blackout_seconds) * 1_000_000_000
                )
            # Seed daily SSR state and intraday trigger codes.
            if hasattr(config, "ssr_active_symbols"):
                self._ssr_active = {s.upper() for s in config.ssr_active_symbols}
            if hasattr(config, "ssr_trigger_condition_codes"):
                self._ssr_codes = frozenset(config.ssr_trigger_condition_codes)
            if hasattr(config, "ssr_mode"):
                self._ssr_mode = config.ssr_mode
            if hasattr(config, "borrow_availability"):
                self._borrow_tier = build_borrow_table(config.borrow_availability)
            if hasattr(config, "borrow_default_tier"):
                self._borrow_default_tier = parse_borrow_tier(config.borrow_default_tier)
                if (
                    self._borrow_default_tier != BorrowTier.AVAILABLE
                    and getattr(config, "cost_htb_borrow_annual_bps", 0.0) == 0.0
                ):
                    logger.warning(
                        "borrow_default_tier=%s but cost_htb_borrow_annual_bps=0 — "
                        "short-side borrow cost is not modelled; set "
                        "cost_htb_borrow_annual_bps for HARD-to-borrow names.",
                        self._borrow_default_tier.value,
                    )
            if hasattr(config, "moc_strategy_ids"):
                self._moc_strategy_ids = frozenset(config.moc_strategy_ids)
                if config.moc_strategy_ids:
                    from feelies.execution.moc_session import (
                        build_moc_bounds_from_platform,
                    )

                    _event_cal = getattr(config, "event_calendar_path", None)
                    cal_path = str(_event_cal) if _event_cal is not None else None
                    self._moc_bounds_configured = (
                        build_moc_bounds_from_platform(
                            moc_session_date=getattr(
                                config,
                                "moc_session_date",
                                None,
                            ),
                            event_calendar_path=cal_path,
                            moc_cutoff_et=getattr(
                                config,
                                "moc_cutoff_et",
                                "15:50",
                            ),
                            official_close_et=getattr(
                                config,
                                "official_close_et",
                                "16:00",
                            ),
                            early_close_dates=getattr(
                                config,
                                "early_close_dates",
                                (),
                            ),
                            early_close_moc_cutoff_et=getattr(
                                config,
                                "early_close_moc_cutoff_et",
                                "12:50",
                            ),
                            early_close_official_close_et=getattr(
                                config,
                                "early_close_official_close_et",
                                "13:00",
                            ),
                        )
                        is not None
                    )
            if getattr(config, "rth_session_gating_enabled", False):
                from feelies.execution.trading_session import (
                    build_trading_session_from_platform,
                )

                _event_cal = getattr(config, "event_calendar_path", None)
                cal_path = str(_event_cal) if _event_cal is not None else None
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
                        config,
                        "early_close_rth_close_et",
                        "13:00",
                    ),
                    market_holiday_dates=getattr(
                        config,
                        "market_holiday_dates",
                        (),
                    ),
                    no_entry_first_seconds=getattr(
                        config,
                        "no_entry_first_seconds",
                        0,
                    ),
                )
            if hasattr(config, "execution_mode"):
                # Both modes use the passive backend; minimum_cost may override per order.
                self._use_passive_entries = config.execution_mode in (
                    "passive_limit",
                    "minimum_cost",
                )
                if config.execution_mode == "minimum_cost" and self._cost_model is not None:
                    self._min_cost_policy = MinimumCostExecutionPolicy(
                        cost_model=self._cost_model,
                        config=MinCostPolicyConfig(
                            prefer_passive_bias_bps=Decimal(
                                str(
                                    getattr(
                                        config,
                                        "cost_min_passive_bias_bps",
                                        0.0,
                                    )
                                )
                            ),
                            small_order_aggressive_threshold_shares=int(
                                getattr(
                                    config,
                                    "cost_min_small_order_threshold_shares",
                                    0,
                                )
                            ),
                            min_half_spread_for_passive=Decimal(
                                str(
                                    getattr(
                                        config,
                                        "cost_min_half_spread_threshold",
                                        0.0,
                                    )
                                )
                            ),
                            allow_passive_short_entry=bool(
                                getattr(
                                    config,
                                    "cost_min_allow_passive_short_entry",
                                    True,
                                )
                            ),
                            market_impact_factor=market_impact_factor,
                            max_impact_half_spreads=max_impact_half_spreads,
                            within_l1_impact_factor=within_l1_impact_factor,
                            permanent_impact_coefficient=permanent_impact_coefficient,
                            passive_non_fill_probability=Decimal(
                                str(
                                    getattr(
                                        config,
                                        "cost_min_passive_non_fill_probability",
                                        0.30,
                                    )
                                )
                            ),
                        ),
                    )
            if hasattr(config, "platform_min_order_shares"):
                self._min_order_shares = config.platform_min_order_shares
            if hasattr(config, "signal_min_edge_cost_ratio"):
                self._signal_min_edge_cost_ratio = config.signal_min_edge_cost_ratio
            if hasattr(config, "reversal_min_edge_cost_multiplier"):
                self._reversal_min_edge_cost_multiplier = config.reversal_min_edge_cost_multiplier
            if hasattr(config, "signal_edge_cost_basis"):
                self._signal_edge_cost_basis = config.signal_edge_cost_basis
            if hasattr(config, "realized_cost_alert_ratio"):
                self._realized_cost_alert_ratio = config.realized_cost_alert_ratio
            if hasattr(config, "realized_cost_escalation_enabled"):
                self._realized_cost_escalation_enabled = config.realized_cost_escalation_enabled
            if hasattr(config, "realized_cost_escalation_streak"):
                self._realized_cost_escalation_streak = config.realized_cost_escalation_streak
            if hasattr(config, "regime_calibration_max_quotes"):
                self._regime_calibration_max_quotes = config.regime_calibration_max_quotes
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
        self._run_deployment_session(
            mode=MacroState.PAPER_TRADING_MODE,
            session_name="paper",
            command_trigger="CMD_PAPER_DEPLOY",
            failure_trigger_prefix="PAPER_PIPELINE_FAIL",
            reset_portfolio_consumption=True,
        )

    def run_live(self) -> None:
        """G2 → G6 → pipeline.

        Guard: human approval and risk review; kill switch inactive.
        Inv-3: R4 (LOCKED) forbids this — must pass through G2 first,
        which is structurally guaranteed (G8 → G2 → G6).
        Normal completion (feed iterator exhausted without exception)
        returns macro to **READY**. Exceptions transition to **DEGRADED**.
        """
        self._run_deployment_session(
            mode=MacroState.LIVE_TRADING_MODE,
            session_name="live",
            command_trigger="CMD_LIVE_DEPLOY",
            failure_trigger_prefix="LIVE_PIPELINE_FAIL",
            reset_portfolio_consumption=False,
        )

    def _run_deployment_session(
        self,
        *,
        mode: MacroState,
        session_name: str,
        command_trigger: str,
        failure_trigger_prefix: str,
        reset_portfolio_consumption: bool,
    ) -> None:
        self._macro.assert_state(MacroState.READY)
        self._require_safe_session_entry()
        self._pipeline_abort_requested = False
        self._micro.reset(trigger=f"session_start:{session_name}")
        self._reset_buying_power_phase_for_session()
        self._bind_router_position_qty_for_rth()
        self._pending_sized_intents.clear()
        if reset_portfolio_consumption:
            self._consumed_by_portfolio_ids = None
        self._reset_regime_session_state()
        self._macro.transition(mode, trigger=command_trigger)
        try:
            self._run_pipeline()
        except Exception as exc:
            if self._macro.state == mode:
                self._macro.transition(
                    MacroState.DEGRADED,
                    trigger=f"{failure_trigger_prefix}:{type(exc).__name__}",
                )
            raise
        if self._macro.state == mode:
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
        defined WAITING baseline instead of a stranded pipeline state.
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
        """Reset interrupted risk escalation with human authorization.

        ``audit_token`` is mandatory. Resetting from ``FORCED_FLATTEN`` also
        requires a flat book; earlier escalation levels do not.
        """
        if self._risk_escalation.state == RiskLevel.NORMAL:
            return
        if self._risk_escalation.state == RiskLevel.LOCKED:
            raise RuntimeError("Risk is LOCKED — use unlock_from_lockdown() instead")
        if self._macro.state in TRADING_MODES:
            raise RuntimeError("Cannot reset risk during active trading — halt first")
        if self._risk_escalation.state == RiskLevel.FORCED_FLATTEN:
            exposure = self._positions.total_exposure()
            if exposure != Decimal("0"):
                raise RuntimeError(
                    f"Cannot reset risk from FORCED_FLATTEN: total exposure is "
                    f"{exposure}, must be 0 — the emergency flatten this level "
                    f"implies may not have completed. Close positions first, or "
                    f"drive the SM to LOCKED and use unlock_from_lockdown() instead."
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
        # Drain late broker acknowledgements before resolving pending orders.
        if self._backend is not None:
            # Expire MOC orders that received no closing-auction print.
            expire_moc = getattr(
                self._backend.order_router,
                "expire_pending_moc",
                None,
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
            oid
            for oid, (sm, _, _) in self._active_orders.items()
            if sm.state not in _TERMINAL_ORDER_STATES
        ]
        if pending:
            self._bus.publish(
                Alert(
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
                )
            )

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
        """Process one trade through the sensor-aware path.

        The trade path does *not* drive the micro-state machine
        (trades are out-of-band w.r.t. the quote-driven pipeline), so
        we do not transition through SENSOR_UPDATE / HORIZON_CHECK
        for trades.  We *do* however invoke the sensor registry (via
        the bus) and the horizon scheduler (manually) so trade-only
        sensors and any time-bucket boundaries crossed by the trade
        timestamp are observed.
        """
        # Update halt state before applying the data-health gate.
        self._update_halt_state(trade)
        # Update intraday SSR state from the trade tape.
        self._update_ssr_state(trade)

        trade_block_reason = self._data_health_blocks_trading(trade.symbol, trade.correlation_id)
        if trade_block_reason is not None:
            # Drop corrupt or gapped data. Halt prints remain observable, but
            # never reach the router or scheduler.
            if (
                self._normalizer is not None
                and self._normalizer.health(trade.symbol) == DataHealth.HALTED
            ):
                if not self._events_prelogged:
                    self._event_log.append(trade)
                self._bus.publish(trade)
            elif self._normalizer is not None:
                # Report rejected data that never reaches the event log.
                self._publish_rejected_event_alert(
                    trade,
                    trade.correlation_id,
                    trade_block_reason,
                )
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
        #
        # Defer until a quote has published RegimeState for this symbol
        # (Inv-11): regime engines update only on NBBO, so a trade at
        # RTH open that crosses boundary 0 would otherwise emit snapshots
        # into an empty HorizonSignalEngine regime cache.  Skipping
        # ``on_event`` (not discarding its ticks) keeps the scheduler's
        # last-boundary cursor unadvanced so the first quote still emits.
        if self._horizon_scheduler is not None and self._trade_path_may_emit_horizon_ticks(
            trade.symbol
        ):
            for tick in self._horizon_scheduler.on_event(trade):
                self._bus.publish(tick)

    def _dispatch_sensor_layer(self, event: NBBOQuote, cid: str) -> None:
        """Record sensor stages and publish horizon ticks for a quote."""
        registry_active = (
            self._sensor_registry is not None and not self._sensor_registry.is_empty()
        )
        scheduler_active = self._horizon_scheduler is not None
        if not registry_active and not scheduler_active:
            return

        # Sensors already ran synchronously through the bus subscription.
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
            # Aggregation already ran synchronously when the tick was published.
            self._micro.transition(
                MicroState.HORIZON_AGGREGATE,
                trigger="horizon_tick_emitted",
                correlation_id=cid,
            )
            # Record SIGNAL_GATE only when a signal engine consumed the snapshot.
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
            self._alpha_registry is not None and self._alpha_registry.has_portfolio_alphas()
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
                        intent,
                        correlation_id,
                    )
                    while self._pending_sized_intents:
                        nxt = self._pending_sized_intents.popleft()
                        self._submit_portfolio_leg_without_micro_walk(
                            nxt,
                            correlation_id,
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
                    order.order_id,
                    OrderState.SUBMITTED,
                    "submitted",
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
            self._publish_and_apply_order_acks(acks)

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
                order.order_id,
                OrderState.SUBMITTED,
                "submitted",
            )
            self._backend.order_router.submit(order)
            self._bus.publish(order)
        acks = self._poll_order_router_acks({o.order_id for o in orders})
        self._publish_and_apply_order_acks(acks)
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
            self._micro.bind_timing_sink(None)

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
            self._bus.publish(
                MetricEvent(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=cid,
                    sequence=self._seq.next(),
                    layer="kernel",
                    name="tick_aborted_micro_reset",
                    value=1.0,
                    metric_type=MetricType.COUNTER,
                )
            )
        except Exception:
            logger.critical(
                "orchestrator: micro SM reset failed during tick-failure recovery "
                "— orchestrator state is unknown",
                exc_info=True,
            )

        try:
            if self._macro.state in TRADING_MODES and self._macro.can_transition(
                MacroState.DEGRADED
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
        self._micro.bind_timing_sink(self._tick_timings)

        # Carry inter-quote signals to the next quote only while their horizon is
        # live. Quote-path leftovers and horizon-zero signals expire immediately.
        if self._signal_buffer:
            _now_ns = quote.timestamp_ns
            fresh: list[Signal] = []
            stale: list[Signal] = []
            for sig in self._signal_buffer:
                if (
                    sig.sequence in self._carryover_signal_sequences
                    and sig.horizon_seconds > 0
                    and (_now_ns - sig.timestamp_ns) <= sig.horizon_seconds * 1_000_000_000
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
                            reasons=("signal_buffer_cleared_unprocessed_at_tick_boundary",),
                        )
            self._signal_buffer.clear()
            self._signal_buffer.extend(fresh)
        self._tick_quote_for_trace = None

        # Kill switch gate.
        if self._kill_switch is not None and self._kill_switch.is_active:
            if self._macro.state in TRADING_MODES:
                if self._macro.can_transition(MacroState.DEGRADED):
                    self._macro.transition(
                        MacroState.DEGRADED,
                        trigger="KILL_SWITCH_ACTIVE",
                        correlation_id=cid,
                    )
            self._bus.publish(
                MetricEvent(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=cid,
                    sequence=self._seq.next(),
                    layer="kernel",
                    name="tick_suppressed_kill_switch",
                    value=1.0,
                    metric_type=MetricType.COUNTER,
                )
            )
            return

        # Runtime data integrity check.
        quote_block_reason = self._data_health_blocks_trading(quote.symbol, cid)
        if quote_block_reason is not None:
            # Report rejected quotes because none reach the event log.
            if self._normalizer is not None:
                self._publish_rejected_event_alert(quote, cid, quote_block_reason)
            return

        # Halted symbols neither mark nor fill.
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
        # Sensor fan-out (+ router on_quote) runs synchronously inside
        # publish; time the call for hot-path attribution.
        t_pub = time.perf_counter_ns()
        self._bus.publish(quote)
        self._tick_timings["sensor_fanout_ns"] = time.perf_counter_ns() - t_pub

        # Mark aggregate and strategy books for exposure and drawdown checks.
        mid = (quote.bid + quote.ask) / Decimal("2")
        if mid > 0:
            # Mark liquidation at bid for longs and ask for shorts.
            self._positions.update_mark(
                quote.symbol,
                mid,
                bid=quote.bid,
                ask=quote.ask,
            )
            # Refresh peak equity on every mark; minimal test doubles may omit the hook.
            refresh_hwm = getattr(
                self._risk_engine,
                "refresh_high_water_mark",
                None,
            )
            if callable(refresh_hwm):
                refresh_hwm(self._positions)
            if self._strategy_positions is not None:
                self._strategy_positions.update_mark(
                    quote.symbol,
                    mid,
                    bid=quote.bid,
                    ask=quote.ask,
                )
        # Use exchange time so risk and routing cross the RTH close together.
        self._maybe_flip_buying_power_at_rth_close(quote)

        # Reconcile quote-triggered fills and cancels before evaluating signals.
        self._reconcile_resting_fills(cid)

        # ── M1 → M2: STATE_UPDATE ──────────────────────────────
        self._micro.transition(
            MicroState.STATE_UPDATE,
            trigger="event_logged",
            correlation_id=cid,
        )
        self._update_regime(quote, cid)

        # Optional sensor and horizon stages.
        self._dispatch_sensor_layer(quote, cid)
        self._maybe_transition_cross_sectional_bookend(cid)
        self._flush_pending_sized_intents(correlation_id=cid)

        # FEATURE_COMPUTE is a state-machine bookend; bus subscribers did the work.
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

        # Select one standalone signal for the single M4 order walk. PORTFOLIO
        # inputs execute through SizedPositionIntent, while forced exits override.
        # position safety beats alpha conviction).
        buf_snapshot = list(self._signal_buffer)
        signal: Signal | None = None
        if buf_snapshot:
            t0 = time.perf_counter_ns()
            signal = self._select_bus_signal()
            self._tick_timings["signal_evaluate_ns"] = time.perf_counter_ns() - t0

        stop_signal = self._check_stop_exit(quote)
        self._trace_buffered_signals_arbitration(
            quote,
            buf_snapshot,
            signal,
            stop_signal,
        )
        # Update standing targets and record winner-versus-net divergence.
        self._record_net_shadow(buf_snapshot, signal, quote)
        if buf_snapshot:
            for buffered in buf_snapshot:
                self._carryover_signal_sequences.discard(buffered.sequence)
            self._signal_buffer.clear()

        # Flat-by-close overrides alpha conviction; a simultaneous stop also flattens.
        session_flat_signal = self._check_session_flat(quote)
        if session_flat_signal is not None:
            signal = session_flat_signal

        if stop_signal is not None:
            signal = stop_signal

        if signal is None:
            self._finalize_tick(t_wall_start, cid, "no_signal_this_tick")
            return

        # Alpha signals are already published upstream; publish only synthetic exits here.
        if signal.strategy_id in _FORCED_MARKET_EXIT_STRATEGIES:
            self._bus.publish(signal)

        # ── Position sizing: compute target quantity from risk budget ──
        target_qty = self._compute_target_quantity(signal, quote)
        self._record_size_shadow(signal, quote)

        # ── Decision: Signal × Position → OrderIntent ──────────────────
        # Use the planner when driving; otherwise translate the signal directly.
        current_position = self._positions.get(signal.symbol)
        # Only discretionary trims override the builder's execution style.
        exec_style_override: ExecStyle | None = None
        if self._position_manager is not None and self._position_manager_drive:
            # With portfolio netting, the winner selects the symbol and the
            # budget-weighted net target selects its position.
            # Forced exits bypass alpha netting and always target flat.
            decision_signal = signal
            if (
                self._enable_portfolio_netting
                and signal.strategy_id not in _FORCED_MARKET_EXIT_STRATEGIES
            ):
                net_desired = self._portfolio_netter.net(
                    signal.symbol,
                    int(quote.timestamp_ns),
                )
                plan = self._plan_for_signal(
                    signal,
                    current_position,
                    target_qty,
                    quote,
                    desired=net_desired,
                )
                decision_signal = replace(
                    signal,
                    direction=_int_to_direction(net_desired.direction),
                )
            else:
                plan = self._plan_for_signal(
                    signal,
                    current_position,
                    target_qty,
                    quote,
                )
            intent = order_intent_from_plan(
                plan,
                signal=decision_signal,
                current=current_position,
            )
            if plan.primary_leg is PlanLeg.TRIM and plan.orders:
                exec_style_override = plan.orders[0].style
        else:
            intent = self._intent_translator.translate(
                signal,
                current_position,
                target_qty,
            )
            # Shadow planning is observational and does not affect execution.
            self._record_position_manager_shadow(
                signal,
                current_position,
                target_qty,
                intent,
                quote,
            )

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
            self._finalize_tick(t_wall_start, cid, "intent_no_action")
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

        # Shared exposure and drawdown checks cannot block reductions. Preserve a
        # reachable FORCE_FLATTEN because lockdown performs the uniform close.
        is_reducing_intent = intent.intent == TradingIntent.EXIT
        preserves_escalation = verdict.action == RiskAction.FORCE_FLATTEN and (
            self._macro.can_transition(MacroState.RISK_LOCKDOWN)
        )
        if is_reducing_intent and verdict.action != RiskAction.ALLOW and not preserves_escalation:
            verdict = replace(verdict, action=RiskAction.ALLOW, scaling_factor=1.0)

        # ── M5 branch: risk fail → cross-machine to G8 ─────────
        # Backtests simulate flatten because RISK_LOCKDOWN exists only in PAPER/LIVE.
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
            self._finalize_tick(t_wall_start, cid, "risk_force_flatten_simulated")
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
            self._finalize_tick(t_wall_start, cid, "risk_reject_no_order")
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

        # Block new entries after a halt; exits remain available.
        if intent.intent in _ENTRY_OPENING_INTENTS and self._in_halt_blackout(
            intent.symbol, quote.timestamp_ns
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
            self._finalize_tick(t_wall_start, cid, "halt_resolution_blackout")
            return

        # Refuse new entries inside the session-flatten window.
        if intent.intent in _ENTRY_OPENING_INTENTS and self._in_session_flatten_window(quote):
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=(
                    "session_flatten_window",
                    f"symbol={intent.symbol}",
                ),
                trading_intent=intent.intent.name,
            )
            self._finalize_tick(t_wall_start, cid, "session_flatten_window")
            return

        # Under SSR, refuse new short exposure but permit buys and covers.
        if self._ssr_blocks_intent(intent):
            self._emit_ssr_suppression_alert(intent, cid)
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=("ssr_suppressed", f"symbol={intent.symbol}"),
                trading_intent=intent.intent.name,
            )
            self._finalize_tick(t_wall_start, cid, "ssr_suppressed")
            return

        # Reject unavailable locates; hard-to-borrow entries carry fees.
        if self._borrow_blocks_intent(intent):
            self._emit_locate_unavailable_alert(intent, cid)
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=("locate_unavailable", f"symbol={intent.symbol}"),
                trading_intent=intent.intent.name,
            )
            self._finalize_tick(t_wall_start, cid, "locate_unavailable")
            return

        # Reversals close at market before opening through the entry policy.
        if intent.intent in (
            TradingIntent.REVERSE_LONG_TO_SHORT,
            TradingIntent.REVERSE_SHORT_TO_LONG,
        ):
            self._execute_reverse(intent, verdict, cid, quote, t_wall_start)
            return

        order, order_build_reason = self._try_build_order_from_intent(
            intent,
            verdict,
            cid,
            quote,
            exec_style=exec_style_override,
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
            self._finalize_tick(t_wall_start, cid, "risk_scale_down_to_zero")
            return

        # ── M6: Pre-submission risk check on concrete order ─────
        order_verdict = self._risk_engine.check_order(order, self._positions)
        self._bus.publish(order_verdict)

        # Apply the same reduction carve-out to the concrete-order check.
        order_preserves_escalation = order_verdict.action == RiskAction.FORCE_FLATTEN and (
            self._macro.can_transition(MacroState.RISK_LOCKDOWN)
        )
        if (
            intent.intent == TradingIntent.EXIT
            and order_verdict.action != RiskAction.ALLOW
            and not order_preserves_escalation
        ):
            order_verdict = replace(order_verdict, action=RiskAction.ALLOW, scaling_factor=1.0)

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
            self._finalize_tick(t_wall_start, cid, "check_order_force_flatten_simulated")
            return

        if order_verdict.action == RiskAction.REJECT:
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=("risk_check_order_reject", order_verdict.reason),
                trading_intent=intent.intent.name,
            )
            self._finalize_tick(
                t_wall_start,
                cid,
                f"check_order_rejected:{order_verdict.reason}",
            )
            return

        if order_verdict.action == RiskAction.SCALE_DOWN:
            # Compose both scale decisions against the original target.
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
                self._finalize_tick(t_wall_start, cid, "check_order_scale_down_to_zero")
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

        # Suppress duplicates while an order is pending. Forced exits may
        # supersede passive orders; reversals use their own path.
        if self._has_pending_order_for_symbol(order.symbol):
            # A forced market exit supersedes resting passive orders. Keep an
            # existing forced exit to avoid sending a second aggressive leg.
            if intent.signal.strategy_id in _FORCED_MARKET_EXIT_STRATEGIES:
                if self._has_pending_forced_exit_for_symbol(order.symbol):
                    self._append_signal_order_trace(
                        quote,
                        signal,
                        outcome="NO_ORDER",
                        reasons=(
                            "resting_order_guard_forced_exit_already_pending",
                            f"symbol={order.symbol}",
                        ),
                        trading_intent=intent.intent.name,
                    )
                    self._finalize_tick(t_wall_start, cid, "resting_order_pending")
                    return
                self._emit_forced_exit_supersedes_pending_alert(order, cid)
                self._cancel_resting_for_symbol(order.symbol, cid)
            elif intent.intent != TradingIntent.EXIT or self._has_pending_exit_for_symbol(
                order.symbol
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
                self._finalize_tick(t_wall_start, cid, "resting_order_pending")
                return

        # ── Track order lifecycle (Inv-4) ───────────────────────
        self._track_order(
            order.order_id,
            order.side,
            order,
            trading_intent=intent.intent.name,
        )
        # Passive reductions fall back to market if they terminate unfilled.
        if exec_style_override is ExecStyle.PASSIVE and order.order_type is OrderType.LIMIT:
            self._working_exit_fallback[order.order_id] = (
                order.symbol,
                order.side,
                order.quantity,
            )

        # ── M6 → M7: ORDER_SUBMIT ──────────────────────────────
        self._micro.transition(
            MicroState.ORDER_SUBMIT,
            trigger="order_constructed",
            correlation_id=cid,
        )
        submit_error = self._submit_tracked_order(order)
        if submit_error is not None:
            self._append_signal_order_trace(
                quote,
                signal,
                outcome="NO_ORDER",
                reasons=(
                    "order_router_submit_raised",
                    type(submit_error).__name__,
                    repr(submit_error),
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
            self._finalize_tick(t_wall_start, cid, "order_submit_failed")
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
        self._publish_and_apply_order_acks(acks)

        # ── M8 → M9: POSITION_UPDATE ───────────────────────────
        self._micro.transition(
            MicroState.POSITION_UPDATE,
            trigger="order_acknowledged",
            correlation_id=cid,
        )
        self._reconcile_fills(acks, cid)

        # ── M9 → M10: LOG_AND_METRICS ──────────────────────────
        self._finalize_tick(t_wall_start, cid, "position_updated")

    # ── Helpers ─────────────────────────────────────────────────────

    def _finalize_tick(
        self,
        t_wall_start_ns: int,
        correlation_id: str,
        trigger: str,
    ) -> None:
        """Enter M10, emit tick timing metrics, then transition to M0."""
        self._micro.transition(
            MicroState.LOG_AND_METRICS,
            trigger=trigger,
            correlation_id=correlation_id,
        )
        latency_ns = time.perf_counter_ns() - t_wall_start_ns
        now_ns = self._clock.now_ns()

        if self._paper_session_recorder is not None:
            self._paper_session_recorder.record_timing(
                kind="tick_process",
                duration_ns=latency_ns,
                correlation_id=correlation_id,
            )

        self._bus.publish(
            MetricEvent(
                timestamp_ns=now_ns,
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                layer="kernel",
                name="tick_to_decision_latency_ns",
                value=float(latency_ns),
                metric_type=MetricType.HISTOGRAM,
            )
        )

        # Record always-on timers directly so they cannot shift kernel event IDs.
        _attribution_timing_keys = frozenset({"sensor_fanout_ns", "sm_transition_ns"})
        timings = getattr(self, "_tick_timings", {})
        for name, value in timings.items():
            if name in _attribution_timing_keys:
                self._metrics.record(
                    MetricEvent(
                        timestamp_ns=now_ns,
                        correlation_id=correlation_id,
                        sequence=0,
                        layer="kernel",
                        name=name,
                        value=float(value),
                        metric_type=MetricType.HISTOGRAM,
                    )
                )
                continue
            self._bus.publish(
                MetricEvent(
                    timestamp_ns=now_ns,
                    correlation_id=correlation_id,
                    sequence=self._seq.next(),
                    layer="kernel",
                    name=name,
                    value=float(value),
                    metric_type=MetricType.HISTOGRAM,
                )
            )
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
        self._bus.publish(
            Alert(
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
            )
        )

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
        """Return whether calibrated edge clears modeled round-trip cost."""
        if self._signal_min_edge_cost_ratio <= 0 or self._cost_model is None:
            return True
        rt_cost_bps = self._round_trip_cost_bps(
            symbol=symbol,
            entry_side=entry_side,
            quantity=quantity,
            quote=quote,
            is_taker_entry=is_taker_entry,
            is_short_entry=is_short_entry,
        )
        # Gate on realization-calibrated edge; missing factors default to one.
        factor = self._edge_calibration_factors.get(signal.strategy_id, 1.0)
        effective_edge_bps = signal.edge_estimate_bps * factor
        if entry_edge_clears_cost(
            edge_bps=effective_edge_bps,
            rt_cost_bps=rt_cost_bps,
            min_ratio=self._signal_min_edge_cost_ratio,
            basis=self._signal_edge_cost_basis,
        ):
            return True
        gate_detail = (
            detail
            if factor >= 1.0
            else f"{detail}; realization factor={factor:.3f} "
            f"(disclosed {signal.edge_estimate_bps:.2f} -> {effective_edge_bps:.2f} bps)"
        )
        self._emit_signal_edge_gate_suppression_alert(
            signal,
            symbol,
            correlation_id,
            detail=gate_detail,
        )
        return False

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
        """Model entry plus taker-exit cost using current quote and impact settings."""
        assert self._cost_model is not None
        return round_trip_cost_bps(
            self._cost_model,
            symbol=symbol,
            entry_side=entry_side,
            quantity=quantity,
            mid_price=(quote.bid + quote.ask) / Decimal("2"),
            half_spread=(quote.ask - quote.bid) / Decimal("2"),
            is_taker_entry=is_taker_entry,
            is_short_entry=is_short_entry,
            bid_size=quote.bid_size,
            ask_size=quote.ask_size,
            market_impact_factor=self._market_context.market_impact_factor,
            max_impact_half_spreads=self._market_context.max_impact_half_spreads,
            within_l1_impact_factor=self._market_context.within_l1_impact_factor,
            permanent_impact_coefficient=(self._market_context.permanent_impact_coefficient),
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
        """Return whether reversal edge clears the combined exit and entry cost."""
        if self._reversal_min_edge_cost_multiplier <= 0 or self._cost_model is None:
            return 0.0, 0.0, True
        # The aggressive close is a taker but never a new short.
        exit_roundtrip_cost_bps = self._round_trip_cost_bps(
            symbol=symbol,
            entry_side=exit_side,
            quantity=exit_qty,
            quote=quote,
            is_taker_entry=True,
            is_short_entry=False,
        )
        # Price the new-direction entry on the same basis as the entry gate.
        entry_roundtrip_cost_bps = self._round_trip_cost_bps(
            symbol=symbol,
            entry_side=entry_side,
            quantity=entry_qty,
            quote=quote,
            is_taker_entry=(not self._use_passive_entries or self._min_cost_policy is not None),
            is_short_entry=is_short_entry,
        )
        return reversal_edge_gate(
            edge_bps=edge_estimate_bps,
            exit_cost_bps=exit_roundtrip_cost_bps,
            entry_cost_bps=entry_roundtrip_cost_bps,
            multiplier=self._reversal_min_edge_cost_multiplier,
        )

    def _calibrate_regime_engine(self) -> None:
        """Calibrate emissions from a bounded replay prefix.

        The run replays its calibration prefix, so early prefix posteriors use
        moments estimated from later prefix quotes. A prior-session fit is needed
        when strict causal warm-up behavior matters.
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
            # Placeholder emissions cannot support regime-gated entries.
            logger.warning(
                "Regime calibration skipped — regime_calibration_max_quotes "
                "is unset.  Engine will run with placeholder emission "
                "parameters that do not match real US-equity spreads; "
                "RegimeState.calibrated will be False and every "
                "P(state)/dominant/entropy entry gate will fail safe to OFF "
                "(audit P0-1).  Configure a positive integer for a causal "
                "warmup prefix to enable regime-conditioned entries."
            )
            self._bus.publish(
                Alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id="regime_calibration",
                    sequence=self._seq.next(),
                    # Uncalibrated emissions disable the regime-gated book.
                    severity=AlertSeverity.CRITICAL,
                    layer="kernel",
                    alert_name="regime_calibration_unset",
                    message=(
                        "RegimeEngine has no calibration prefix configured "
                        "(regime_calibration_max_quotes is None). Posteriors "
                        "use placeholder emission parameters; RegimeState is "
                        "published with calibrated=False and all "
                        "P(state)/dominant/entropy entry gates fail safe to "
                        "OFF (Inv-11).  Configure a positive integer for a "
                        "causal warmup prefix to enable regime-gated entries."
                    ),
                    context={},
                )
            )
            return

        precomputed = self._regime_calibration_quotes
        if precomputed is not None:
            quotes = list(precomputed)
        else:
            quote_stream = (
                event for event in self._event_log.replay() if isinstance(event, NBBOQuote)
            )
            quotes = list(itertools.islice(quote_stream, max_q))
        if not quotes:
            logger.info("Regime calibration skipped — no quotes in event log")
            return

        prefix_n = len(quotes)
        # Exact total only when the prefix exhausts the quote stream; otherwise
        # counting the suffix is O(full log) at boot — report a lower bound.
        exact_total = precomputed is not None or prefix_n < max_q

        ok = calibrate_fn(quotes)
        if ok:
            if exact_total:
                logger.info(
                    "Regime engine calibrated from %d quotes (prefix cap=%d, total_log=%d)",
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
            self._bus.publish(
                Alert(
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
                )
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
        # Ties: lowest index wins (stable, deterministic replay).
        dominant_idx = max(range(len(posteriors)), key=lambda i: posteriors[i])
        state_names = tuple(self._regime_engine.state_names)
        engine_name = (
            self._regime_engine_registry_name
            if self._regime_engine_registry_name is not None
            else type(self._regime_engine).__name__
        )
        # Prefer per-symbol separation because one symbol can collapse independently.
        discriminability_for_symbol = getattr(
            self._regime_engine, "discriminability_for_symbol", None
        )
        if callable(discriminability_for_symbol):
            d_value = float(discriminability_for_symbol(quote.symbol))
        else:
            d_value = float(getattr(self._regime_engine, "discriminability", float("inf")))
        regime_state = RegimeState(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            symbol=quote.symbol,
            engine_name=engine_name,
            state_names=state_names,
            posteriors=tuple(posteriors),
            dominant_state=dominant_idx,
            dominant_name=state_names[dominant_idx]
            if dominant_idx < len(state_names)
            else "unknown",
            posterior_entropy_nats=regime_posterior_entropy_nats(posteriors),
            # Engines without a calibration flag opt out of the fail-closed gate.
            calibrated=bool(getattr(self._regime_engine, "calibrated", True)),
            # Missing separation defaults to fully discriminative.
            discriminability=d_value,
        )
        self._bus.publish(regime_state)
        self._regime_bus_published_symbols.add(quote.symbol)
        self._maybe_publish_hazard_spike(regime_state, correlation_id)

    def _trade_path_may_emit_horizon_ticks(self, symbol: str) -> bool:
        """Whether trade-path HorizonTicks are safe to emit for *symbol*.

        When no regime engine is configured, ticks are always allowed
        (gates that need ``P(...)`` are not wired).  Otherwise require
        at least one bus-published :class:`RegimeState` for *symbol*
        this session so ``HorizonSignalEngine`` can bind posteriors.
        """
        if self._regime_engine is None:
            return True
        return symbol in self._regime_bus_published_symbols

    def _reset_regime_session_state(self) -> None:
        """Clear hazard-detection state that must not span sessions.

        Called from every ``run_*`` entry point alongside ``_micro.reset``.
        Three structures are cleared:

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
        * ``self._regime_bus_published_symbols`` — forces trade-path
          HorizonTicks to wait for a fresh quote-driven ``RegimeState``
          publish in the new session (see ``_process_trade_inner``).

        The :class:`RegimeEngine` itself is intentionally NOT reset:
        its per-symbol HMM posterior is the carry-over we want
        (boot-time calibration is the only place that wipes it).
        """
        self._last_regime_state.clear()
        self._regime_bus_published_symbols.clear()
        if self._regime_hazard_detector is not None:
            self._regime_hazard_detector.reset()

    def _maybe_publish_hazard_spike(
        self,
        regime_state: RegimeState,
        correlation_id: str,
    ) -> None:
        """Publish a hazard spike from consecutive states on one channel."""
        if self._regime_hazard_detector is None:
            return
        key = (regime_state.symbol, regime_state.engine_name)
        prev = self._last_regime_state.get(key)
        self._last_regime_state[key] = regime_state
        spike = self._regime_hazard_detector.detect(prev, regime_state)
        if spike is None:
            return
        self._bus.publish(
            RegimeHazardSpike(
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
            )
        )

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
            self._bus.publish(
                KillSwitchActivation(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=correlation_id,
                    sequence=self._seq.next(),
                    reason="risk_escalation_lockdown",
                    activated_by="orchestrator",
                )
            )

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
            order_id = derive_order_id(f"emergency_flatten:{correlation_id}:{symbol}:{seq}")

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
                # Price lockdown fills with panic slippage and depleted depth.
                reason="FORCE_FLATTEN",
            )

            try:
                self._track_order(order_id, side, order)
                submit_exc = self._submit_tracked_order(
                    order,
                    trigger="emergency_flatten",
                )
                if submit_exc is not None:
                    failures[symbol] = f"submit_exception: {submit_exc!r}"
                    continue

                self._bus.publish(order)
                acks = self._poll_order_router_acks({order_id})
                self._publish_and_apply_order_acks(acks)
                self._reconcile_fills(acks, correlation_id)
                # A reject / zero-fill ack still leaves the position open.
                # Surface it as a failure so the residual alert sees it.
                non_fill_acks = [
                    a
                    for a in acks
                    if a.order_id == order_id
                    and (a.filled_quantity or 0) == 0
                    and a.status in (OrderAckStatus.REJECTED, OrderAckStatus.CANCELLED)
                ]
                if non_fill_acks:
                    failures[symbol] = (
                        f"{non_fill_acks[0].status.name}: {non_fill_acks[0].reason or 'no reason'}"
                    )
            except Exception as exc:
                logger.exception(
                    "Emergency flatten failed for %s (qty=%d) -- "
                    "position may remain open at LOCKED",
                    symbol,
                    pos.quantity,
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
            self._bus.publish(
                Alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=correlation_id,
                    sequence=self._seq.next(),
                    severity=AlertSeverity.CRITICAL,
                    layer="kernel",
                    alert_name="emergency_flatten_incomplete",
                    message=msg,
                )
            )
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
            entry * self._stop_loss_pct if self._stop_loss_pct > 0 else self._stop_loss_per_share
        )
        trail_activate_threshold = (
            entry * self._trail_activate_pct
            if self._trail_activate_pct > 0
            else self._trail_activate_per_share
        )

        triggered = False

        if stop_threshold > 0 and unrealized_per_share < -stop_threshold:
            triggered = True

        if (
            trail_activate_threshold > 0
            and peak >= trail_activate_threshold
            and unrealized_per_share < peak * self._trail_pct
        ):
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

    def _session_flatten_deadline_ns(self, quote: NBBOQuote) -> int | None:
        """Exchange-time ns at/after which the session flattens, or None.

        ``None`` when session flatten is disabled or no RTH session is
        configured.  The deadline is ``rth_close - buffer`` so an operator
        can unwind before the closing auction.

        The bounds are resolved for *this quote's* NY session date via
        :meth:`TradingSessionBounds.resolve_for_timestamp` so a multi-day
        replay rebinds the close per replayed day rather than pinning every
        day to the single ``session_date`` the bounds were booted with
        (which, for a CLI date *range*, falls back to the stale
        ``event_calendar_path`` date and would otherwise flag every quote
        as past-close — see ``apply_backtest_session_dates_from_cli``).
        """
        if not self._session_flatten_enabled:
            return None
        bounds = self._trading_session_bounds
        if bounds is None:
            return None
        effective = bounds.resolve_for_timestamp(quote.exchange_timestamp_ns)
        return effective.rth_close_ns - (
            self._session_flatten_seconds_before_close * 1_000_000_000
        )

    def _in_session_flatten_window(self, quote: NBBOQuote) -> bool:
        """True once the quote crosses the session-flatten deadline."""
        deadline = self._session_flatten_deadline_ns(quote)
        return deadline is not None and quote.exchange_timestamp_ns >= deadline

    def _check_session_flat(self, quote: NBBOQuote) -> Signal | None:
        """Return a synthetic flat signal for an open position at close.

        Independent of alpha behaviour: once the quote crosses the
        session-flatten deadline, any non-zero position for the symbol is
        unwound via the normal EXIT path (forced MARKET — the close must
        not be left to a passive non-fill).  Returns ``None`` when the
        window has not opened or the book is already flat.
        """
        if not self._in_session_flatten_window(quote):
            return None
        if self._positions.get(quote.symbol).quantity == 0:
            return None
        return Signal(
            timestamp_ns=quote.timestamp_ns,
            correlation_id=quote.correlation_id,
            sequence=self._signal_seq.next(),
            source_layer="SIGNAL",
            symbol=quote.symbol,
            strategy_id="__session_flat__",
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

        # Clamp nonzero targets to the minimum viable order; risk may scale them down.
        if 0 < target < self._min_order_shares:
            target = self._min_order_shares

        return target

    def _record_size_shadow(self, signal: Signal, quote: NBBOQuote) -> None:
        """Compare the edge/vol/inventory-tilted target with the base.

        For each real sized signal, compute the tilted target and append a
        :class:`SizeDivergence` when it differs from the live single-factor
        base target. It runs before the minimum-order clamp and risk engine and
        has no order, bus, journal, or parity effects. It is a no-op unless a sink is
        wired and at least one tilt factor is enabled.
        """
        sizer = self._size_shadow_sizer
        sink = self._size_shadow_sink
        if (
            sizer is None
            or sink is None
            or not sizer.config.any_enabled
            or self._alpha_registry is None
            or signal.strategy_id.startswith("__")
        ):
            return
        try:
            alpha = self._alpha_registry.get(signal.strategy_id)
        except KeyError:
            return
        risk_budget = alpha.manifest.risk_budget
        mid_price = (quote.bid + quote.ask) / Decimal(2)
        if mid_price <= 0:
            return

        base_target = sizer.base.compute_target_quantity(
            signal=signal,
            risk_budget=risk_budget,
            symbol_price=mid_price,
            account_equity=self._account_equity,
        )
        if base_target <= 0:
            return
        bd = sizer.tilt_breakdown(signal, risk_budget)
        tilted = apply_tilt(base_target, bd.combined, risk_budget.max_position_per_symbol)
        if tilted == base_target:
            return
        sink.append(
            SizeDivergence(
                symbol=signal.symbol,
                signal_sequence=signal.sequence,
                strategy_id=signal.strategy_id,
                edge_bps=float(signal.edge_estimate_bps),
                base_target_qty=base_target,
                tilted_target_qty=tilted,
                edge_factor=bd.edge,
                vol_factor=bd.vol,
                inventory_factor=bd.inventory,
                combined_tilt=bd.combined,
                inventory_qty=bd.inventory_qty,
                timestamp_ns=int(quote.exchange_timestamp_ns),
            )
        )

    def _plan_for_signal(
        self,
        signal: Signal,
        current_position: Position,
        target_qty: int | None,
        quote: NBBOQuote,
        *,
        desired: DesiredPosition | None = None,
    ) -> PositionPlan:
        """Build the planner's ``PositionPlan`` for a signal.

        Shared by shadow comparison and the active planner path.
        Resolves the ``None`` sizer target via the translator default so
        the planner sees the translator's effective magnitude.
        ``desired`` overrides the per-signal target with a net target.
        """
        assert self._position_manager is not None
        if desired is None:
            default_target = getattr(
                self._intent_translator,
                "_default_target",
                100,
            )
            desired = desired_from_signal(
                signal,
                target_qty,
                default_target_quantity=default_target,
            )
        return self._position_manager.plan(
            desired=desired,
            current=current_position,
            market=replace(
                self._market_context,
                quote=quote,
                cost_model=self._cost_model,
            ),
            config=PositionManagerConfig(
                shadow=not self._position_manager_drive,
                enabled=self._position_manager_drive,
                enable_trim=self._position_manager_enable_trim,
                trim_edge_gate_multiplier=(self._position_manager_trim_edge_gate_multiplier),
                urgency_exec=self._position_manager_urgency_exec,
            ),
        )

    def _record_portfolio_net_shadow(self, intent: SizedPositionIntent) -> None:
        """Feed portfolio targets into the net shadow measurement.

        Records each ``TargetPosition`` (``target_usd → shares`` via the
        latest mark) as a standing target so the cross-alpha ``NetDivergence``
        measurement spans both the SIGNAL and PORTFOLIO paths.

        Measurement-only: active when a net-shadow sink is wired **and**
        netting is not driving — feeding PORTFOLIO targets while the PORTFOLIO
        path also self-drives would double-count. This method has no order, bus,
        or journal effects.
        """
        if self._net_shadow_sink is None or self._enable_portfolio_netting:
            return
        mark_fn = getattr(self._positions, "latest_mark", None)
        if not callable(mark_fn):
            return
        for symbol, tgt in intent.target_positions.items():
            mark = mark_fn(symbol)
            if mark is None or mark <= 0:
                continue
            target_shares = int(
                (Decimal(str(tgt.target_usd)) / mark).to_integral_value(
                    rounding=ROUND_HALF_UP,
                )
            )
            desired = DesiredPosition(
                symbol=symbol,
                target_qty=target_shares,
                direction=(target_shares > 0) - (target_shares < 0),
                urgency=tgt.urgency,
            )
            self._desired_target_book.put(
                standing_target_from_desired(
                    desired,
                    strategy_id=intent.strategy_id,
                    signal_timestamp_ns=int(intent.timestamp_ns),
                    horizon_seconds=intent.horizon_seconds,
                    staleness_k=self._net_staleness_k,
                )
            )
            # Horizon-zero targets are one-tick-only.
            if intent.horizon_seconds <= 0:
                self._net_shadow_transient_keys.add((intent.strategy_id, symbol))

    def _record_net_shadow(
        self,
        buf_snapshot: list[Signal],
        winner: Signal | None,
        quote: NBBOQuote,
    ) -> None:
        """Maintain standing targets and compare the net target with the winner.

        For every real (non-synthetic) alpha signal buffered this tick, record
        its standing desired target (budget-capped by the sizer, ``k×horizon``
        expiry).  Then, for the arbitrated winner's symbol, compare the
        budget-weighted portfolio net to the winner-take-all target and append
        a :class:`NetDivergence` when they disagree.  Pure measurement — no
        orders, bus, journal, or parity effects; no-op unless a sink is wired.
        """
        sink = self._net_shadow_sink
        # Maintain targets only for live netting or shadow comparison.
        if sink is None and not self._enable_portfolio_netting:
            return
        default_target = getattr(
            self._intent_translator,
            "_default_target",
            100,
        )

        def _signed_target(sig: Signal) -> int:
            tq = self._compute_target_quantity(sig, quote)
            return desired_from_signal(
                sig,
                tq,
                default_target_quantity=default_target,
            ).target_qty

        # Remove the prior tick's horizon-zero targets.
        for prev_strategy_id, prev_symbol in self._net_shadow_transient_keys:
            self._desired_target_book.clear(prev_strategy_id, prev_symbol)
        self._net_shadow_transient_keys.clear()

        for sig in buf_snapshot:
            if sig.strategy_id.startswith("__"):
                continue  # synthetic kernel signal, not an alpha target
            desired = desired_from_signal(
                sig,
                self._compute_target_quantity(sig, quote),
                default_target_quantity=default_target,
            )
            self._desired_target_book.put(
                standing_target_from_desired(
                    desired,
                    strategy_id=sig.strategy_id,
                    signal_timestamp_ns=int(sig.timestamp_ns),
                    horizon_seconds=sig.horizon_seconds,
                    staleness_k=self._net_staleness_k,
                )
            )
            if sig.horizon_seconds <= 0:
                self._net_shadow_transient_keys.add((sig.strategy_id, sig.symbol))

        # Divergence recording is shadow-only.
        if sink is None or winner is None or winner.strategy_id.startswith("__"):
            return
        now_ns = int(quote.timestamp_ns)
        net = self._portfolio_netter.net(winner.symbol, now_ns)
        winner_target = _signed_target(winner)
        if net.target_qty != winner_target:
            sink.append(
                NetDivergence(
                    symbol=winner.symbol,
                    signal_sequence=winner.sequence,
                    winner_strategy_id=winner.strategy_id,
                    winner_target_qty=winner_target,
                    net_target_qty=net.target_qty,
                    contributing_alphas=len(
                        self._desired_target_book.live_targets(winner.symbol, now_ns)
                    ),
                    timestamp_ns=int(quote.exchange_timestamp_ns),
                    detail=f"net={net.target_qty} winner={winner_target}",
                )
            )

    def _record_position_manager_shadow(
        self,
        signal: Signal,
        current_position: Position,
        target_qty: int | None,
        intent: OrderIntent,
        quote: NBBOQuote,
    ) -> None:
        """Run the shadow planner and record decision divergence.

        No-op unless both a position manager and a divergence sink are
        wired.  Strictly observational — it builds no orders, publishes
        nothing on the bus, and writes no journal records, so it cannot
        move a parity hash. ``OrderIntent`` continues to drive shadow-mode execution.
        """
        manager = self._position_manager
        sink = self._position_manager_shadow_sink
        if manager is None or sink is None:
            return
        plan = self._plan_for_signal(
            signal,
            current_position,
            target_qty,
            quote,
        )
        divergence = compare_plan_to_intent(
            intent_name=intent.intent.name,
            intent_target_quantity=intent.target_quantity,
            current_quantity=current_position.quantity,
            plan=plan,
            symbol=signal.symbol,
            signal_sequence=signal.sequence,
        )
        if divergence is not None:
            sink.append(divergence)

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
        exit_order_id = derive_order_id(f"{cid}:{seq_exit}:exit")

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

        # Shared exposure and drawdown checks cannot block or resize a full close.
        exit_verdict = self._risk_engine.check_order(
            exit_order,
            self._positions,
        )
        self._bus.publish(exit_verdict)
        if exit_verdict.action == RiskAction.FORCE_FLATTEN:
            if self._macro.can_transition(MacroState.RISK_LOCKDOWN):
                # Same global halt as standalone SIGNAL/order gates —
                # _emergency_flatten_all() closes this leg (and every other
                # open position) directly with a properly-tagged flatten,
                # so defer to it here rather than also submitting this leg.
                self._escalate_risk(cid)
                self._finalize_tick(t_wall_start, cid, "reverse_exit_force_flatten_escalation")
                return
            # BACKTEST_MODE has no reachable lockdown transition, so there
            # is no compensating flatten to rely on — normalize to ALLOW so
            # this reduce still submits instead of stranding the position.
            exit_verdict = replace(exit_verdict, action=RiskAction.ALLOW, scaling_factor=1.0)
        elif exit_verdict.action != RiskAction.ALLOW:
            exit_verdict = replace(exit_verdict, action=RiskAction.ALLOW, scaling_factor=1.0)

        # ── ENTRY leg: passive LIMIT (or MARKET if passive disabled) ─
        #
        # Risk-check entry against the position expected after the exit leg.
        entry_order: OrderRequest | None = None
        entry_qty = round(entry_qty_raw * verdict.scaling_factor)
        # Attach combined reversal cost only when the entry leg is evaluated.
        reverse_signal: Signal = intent.signal

        # Signed adjustment: the exit leg removes close_qty from position.
        exit_signed_adj = -close_qty if exit_side == Side.SELL else close_qty
        post_exit_positions = PostExitPositionView(
            self._positions,
            intent.symbol,
            exit_signed_adj,
        )

        if entry_qty >= self._min_order_shares:
            entry_side = exit_side  # same direction for both legs
            short_sale = intent.intent == TradingIntent.REVERSE_LONG_TO_SHORT
            tier = self._borrow_tier_for(intent.symbol)
            is_short = htb_fee_applies(tier, short_sale)

            # The reversal entry must cover both legs using the same calibrated
            # edge as the ordinary entry gate. The exit always submits.
            edge_calibration_factor = self._edge_calibration_factors.get(
                intent.signal.strategy_id, 1.0
            )
            effective_edge_bps = intent.signal.edge_estimate_bps * edge_calibration_factor
            (
                reversal_cost_bps,
                reversal_required_bps,
                reversal_edge_passes,
            ) = self._reversal_passes_combined_edge_gate(
                edge_estimate_bps=effective_edge_bps,
                symbol=intent.symbol,
                exit_side=exit_side,
                exit_qty=close_qty,
                entry_side=entry_side,
                entry_qty=entry_qty,
                quote=quote,
                is_short_entry=is_short,
            )
            # Expose combined cost to traces and alerts.
            reverse_signal = replace(
                intent.signal,
                reversal_cost_estimate_bps=reversal_cost_bps,
            )

            if not reversal_edge_passes:
                deficit_bps = reversal_required_bps - effective_edge_bps
                calibration_note = (
                    ""
                    if edge_calibration_factor >= 1.0
                    else f"; realization factor={edge_calibration_factor:.3f} "
                    f"(disclosed {intent.signal.edge_estimate_bps:.2f} -> "
                    f"{effective_edge_bps:.2f} bps)"
                )
                self._bus.publish(
                    Alert(
                        timestamp_ns=self._clock.now_ns(),
                        correlation_id=cid,
                        sequence=self._seq.next(),
                        severity=AlertSeverity.WARNING,
                        layer="kernel",
                        alert_name="reversal_edge_insufficient",
                        message=(
                            f"Reversal entry suppressed (flatten-only): "
                            f"edge_bps={effective_edge_bps:.4f} below required "
                            f"{reversal_required_bps:.4f} "
                            f"({self._reversal_min_edge_cost_multiplier}× combined "
                            f"round-trip cost {reversal_cost_bps:.4f}); "
                            f"deficit={deficit_bps:.4f} bps "
                            f"(symbol={intent.symbol!r}, "
                            f"strategy_id={intent.strategy_id!r})"
                            f"{calibration_note}."
                        ),
                        context={
                            "edge_bps": effective_edge_bps,
                            "required_bps": reversal_required_bps,
                            "deficit_bps": deficit_bps,
                            "symbol": intent.symbol,
                            "strategy_id": intent.strategy_id,
                            "order_id": exit_order.order_id,
                        },
                    )
                )

            # Check entry edge against cost unless the reversal guard already
            # suppressed the flip.
            entry_passes_edge_gate = reversal_edge_passes and self._signal_passes_edge_cost_gate(
                intent.signal,
                symbol=intent.symbol,
                entry_side=entry_side,
                quantity=entry_qty,
                quote=quote,
                is_taker_entry=(
                    not self._use_passive_entries or self._min_cost_policy is not None
                ),
                is_short_entry=is_short,
                correlation_id=cid,
                detail="reverse_entry_leg_suppressed",
            )

            if entry_passes_edge_gate:
                seq_entry = self._seq.next()
                entry_order_id = derive_order_id(f"{cid}:{seq_entry}:entry")

                order_type, limit_price, entry_is_moc = self._resolve_order_route(
                    strategy_id=intent.strategy_id,
                    symbol=intent.symbol,
                    side=entry_side,
                    quantity=entry_qty,
                    quote=quote,
                    is_short=is_short,
                    is_exit_or_stop=False,
                    edge_bps=intent.signal.edge_estimate_bps,
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
                    g12_disclosed_cost_total_bps=(intent.signal.disclosed_cost_total_bps),
                )

                # Risk check entry leg against post-exit position view.
                entry_rv = self._risk_engine.check_order(
                    entry_order,
                    post_exit_positions,
                )
                self._bus.publish(entry_rv)
                if entry_rv.action in (
                    RiskAction.REJECT,
                    RiskAction.FORCE_FLATTEN,
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
                            entry_order,
                            quantity=scaled,
                        )

        # ── M6 → M7: ORDER_SUBMIT ─────────────────────────────────
        self._micro.transition(
            MicroState.ORDER_SUBMIT,
            trigger="reverse_orders_constructed",
            correlation_id=cid,
        )

        # Attribute the reversal to its exit leg; stamp the new entry separately.
        self._track_order(
            exit_order.order_id,
            exit_order.side,
            exit_order,
            trading_intent=intent.intent.name,
        )
        exit_submit_error = self._submit_tracked_order(exit_order)
        if exit_submit_error is not None:
            self._micro.transition(
                MicroState.ORDER_ACK,
                trigger="reverse_exit_submit_failed",
                correlation_id=cid,
            )
            acks = self._poll_order_router_acks({exit_order.order_id})
            self._publish_and_apply_order_acks(acks)
            self._micro.transition(
                MicroState.POSITION_UPDATE,
                trigger="reverse_acks_after_failed_exit_submit",
                correlation_id=cid,
            )
            self._reconcile_fills(acks, cid)
            self._finalize_tick(t_wall_start, cid, "reverse_aborted_exit_submit_failed")
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
                entry_order.order_id,
                entry_order.side,
                entry_order,
                trading_intent=entry_intent_name,
            )
            if self._submit_tracked_order(entry_order) is None:
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
        self._publish_and_apply_order_acks(acks)

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
        self._finalize_tick(t_wall_start, cid, "reverse_position_updated")

    def _try_build_order_from_intent(
        self,
        intent: OrderIntent,
        verdict: RiskVerdict,
        correlation_id: str,
        quote: NBBOQuote | None = None,
        *,
        exec_style: ExecStyle | None = None,
    ) -> tuple[OrderRequest | None, str | None]:
        """Construct an order and return a stable failure token on suppression.

        When ``exec_style`` is ``ExecStyle.PASSIVE``, a discretionary working
        leg posts near the BBO regardless of the static
        ``_use_passive_entries`` flag. ``None`` uses default routing.
        Stop-exits and MOC orders always short-circuit to MARKET and ignore
        the hint (Inv-11).
        """
        side = self._side_from_intent(intent)
        seq = self._seq.next()
        order_id = derive_order_id(f"{correlation_id}:{seq}")

        # Exits bypass minimum size and risk scaling so any position can close.
        is_exit_or_stop = (
            intent.intent == TradingIntent.EXIT or intent.signal.strategy_id == "__stop_exit__"
        )
        quantity = (
            intent.target_quantity
            if is_exit_or_stop
            else round(intent.target_quantity * verdict.scaling_factor)
        )
        if quantity <= 0:
            return None, "rounded_quantity_after_risk_scaling_le_zero"
        if not is_exit_or_stop and quantity < self._min_order_shares:
            return None, "quantity_below_platform_min_order_shares"

        # Only hard-tier short sales carry the HTB fee flag;
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
                    not self._use_passive_entries or self._min_cost_policy is not None
                ),
                is_short_entry=is_short,
                correlation_id=correlation_id,
                detail="standalone_intent_suppressed",
            )
        ):
            return None, "signal_edge_below_min_edge_cost_ratio_gate"

        order_type, limit_price, is_moc = self._resolve_order_route(
            strategy_id=intent.strategy_id,
            symbol=intent.symbol,
            side=side,
            quantity=quantity,
            quote=quote,
            is_short=is_short,
            is_exit_or_stop=is_exit_or_stop,
            edge_bps=intent.signal.edge_estimate_bps,
            exec_style=exec_style,
            forced_market=(intent.signal.strategy_id in _FORCED_MARKET_EXIT_STRATEGIES),
        )

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
                # Forced-exit reasons activate panic slippage and depleted depth.
                reason=_FORCED_EXIT_PANIC_REASON.get(intent.signal.strategy_id, ""),
                g12_disclosed_cost_total_bps=(intent.signal.disclosed_cost_total_bps),
            ),
            None,
        )

    def _resolve_order_route(
        self,
        *,
        strategy_id: str,
        symbol: str,
        side: Side,
        quantity: int,
        quote: NBBOQuote | None,
        is_short: bool,
        is_exit_or_stop: bool,
        edge_bps: float,
        exec_style: ExecStyle | None = None,
        forced_market: bool = False,
    ) -> tuple[OrderType, Decimal | None, bool]:
        """Resolve order type, limit price, and MOC flag from execution policy."""
        is_moc = (
            strategy_id in self._moc_strategy_ids
            and self._moc_bounds_configured
            and not is_exit_or_stop
        )
        if is_moc:
            return OrderType.MARKET, None, True

        if exec_style is ExecStyle.PASSIVE and quote is not None and not forced_market:
            limit_price = quote.bid if side == Side.BUY else quote.ask
            return OrderType.LIMIT, limit_price, False

        if not self._use_passive_entries or quote is None or forced_market:
            return OrderType.MARKET, None, False

        use_passive = True
        if self._min_cost_policy is not None:
            use_passive = (
                self._min_cost_policy.decide(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    mid_price=(quote.bid + quote.ask) / Decimal("2"),
                    half_spread=(quote.ask - quote.bid) / Decimal("2"),
                    is_short=is_short,
                    force_aggressive=is_exit_or_stop,
                    bid_size=quote.bid_size,
                    ask_size=quote.ask_size,
                    edge_bps=edge_bps,
                )
                == "passive"
            )
        if use_passive:
            return (
                OrderType.LIMIT,
                quote.bid if side == Side.BUY else quote.ask,
                False,
            )
        return OrderType.MARKET, None, False

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
            self._bus.publish(
                Alert(
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
                )
            )
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
        self._publish_and_apply_order_acks(acks)
        self._reconcile_fills(acks, order.correlation_id)
        # Accepted broker cancels resolve asynchronously; rejected ones resolve locally.
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
                self._bus.publish(
                    Alert(
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
                    )
                )
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
            order.symbol == symbol and sm.state not in _TERMINAL_ORDER_STATES and side == exit_side
            for sm, side, order in self._active_orders.values()
        )

    def _has_pending_forced_exit_for_symbol(self, symbol: str) -> bool:
        """True if a forced MARKET exit (stop / session-flat) is already in flight.

        Distinguishes an aggressive exit already crossing the book from a
        merely-resting passive cover.  The resting-order guard cancels stale
        passive orders to let a forced MARKET exit through (Inv-11) but must
        not stack a second aggressive leg on top of one already pending —
        that would overshoot the position.
        """
        return any(
            order.symbol == symbol
            and sm.state not in _TERMINAL_ORDER_STATES
            and order.strategy_id in _FORCED_MARKET_EXIT_STRATEGIES
            for sm, _, order in self._active_orders.values()
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
            self._publish_and_apply_order_acks(cancel_acks)
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

    def _publish_and_apply_order_acks(self, acks: list[OrderAck]) -> None:
        """Publish router acks in order, then advance their order state machines."""
        for ack in acks:
            self._bus.publish(ack)
            self._apply_ack_to_order(ack)

    def _submit_tracked_order(
        self,
        order: OrderRequest,
        *,
        trigger: str = "submitted",
    ) -> Exception | None:
        """Submit a tracked order and terminalize its state if routing fails."""
        self._transition_order(
            order.order_id,
            OrderState.SUBMITTED,
            trigger,
            correlation_id=order.correlation_id,
        )
        try:
            self._backend.order_router.submit(order)
        except Exception as exc:
            self._reject_order_after_submit_failure(order, exc)
            return exc
        return None

    def _reject_order_after_submit_failure(
        self,
        order: OrderRequest,
        exc: BaseException,
    ) -> None:
        """Transition a tracked order to REJECTED when ``submit`` raises (Inv-11)."""
        self._bus.publish(
            Alert(
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
            )
        )
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
        self._bus.publish(
            Alert(
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
            )
        )
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
            self._publish_and_apply_order_acks(acks)
            self._reconcile_fills(acks, correlation_id)
            # Escalate an unfilled working exit to a market fallback
            # unfilled to a guaranteed MARKET fallback (after reconcile, so
            # the residual reflects this drain's fills).
            self._escalate_unfilled_working_exits(acks, correlation_id)
        if self._paper_session_recorder is not None:
            self._paper_session_recorder.record_timing(
                kind="drain_async_fills",
                duration_ns=time.perf_counter_ns() - t0,
                correlation_id=correlation_id,
                extra={"ack_count": len(acks)},
            )

    def _escalate_unfilled_working_exits(
        self,
        acks: list[OrderAck],
        correlation_id: str,
    ) -> None:
        """Send unfilled residuals from terminated passive reductions to market."""
        if not self._working_exit_fallback:
            return
        for ack in acks:
            if ack.order_id not in self._working_exit_fallback:
                continue
            if ack.status not in (
                OrderAckStatus.FILLED,
                OrderAckStatus.CANCELLED,
                OrderAckStatus.EXPIRED,
            ):
                continue
            symbol, side, original_qty = self._working_exit_fallback.pop(ack.order_id)
            filled = self._order_filled_qty.pop(ack.order_id, 0)
            if ack.status is OrderAckStatus.FILLED:
                continue  # fully worked passively — no fallback needed
            residual = original_qty - filled
            if residual < 1:
                continue
            self._submit_working_exit_fallback(
                symbol,
                side,
                residual,
                ack.order_id,
                correlation_id,
            )

    def _submit_working_exit_fallback(
        self,
        symbol: str,
        side: Side,
        quantity: int,
        parent_order_id: str,
        correlation_id: str,
    ) -> None:
        """Submit the guaranteed MARKET residual for a non-filled working exit."""
        order_id = derive_order_id(f"{parent_order_id}:working_fallback")
        order = OrderRequest(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            strategy_id="__working_exit_fallback__",
            reason="WORKING_EXIT_FALLBACK",
        )
        self._track_order(order.order_id, order.side, order, trading_intent="EXIT")
        if self._submit_tracked_order(order) is not None:
            return
        self._bus.publish(order)
        self._bus.publish(
            Alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                severity=AlertSeverity.INFO,
                layer="kernel",
                alert_name="working_exit_market_fallback",
                message=(
                    f"Working reduction did not fill passively; escalating "
                    f"{quantity} {side.name} {symbol} to MARKET "
                    f"(parent_order_id={parent_order_id})."
                ),
                context={
                    "symbol": symbol,
                    "side": side.name,
                    "quantity": quantity,
                    "parent_order_id": parent_order_id,
                    "fallback_order_id": order_id,
                },
            )
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

        ``trading_intent`` is recorded for fill reconciliation and attribution.
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
            self._bus.publish(
                Alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=cid,
                    sequence=self._seq.next(),
                    severity=AlertSeverity.WARNING,
                    layer="kernel",
                    alert_name="ack_for_unknown_order",
                    message=f"Ack for unknown order_id={ack.order_id}, status={ack.status.name}",
                    context={"order_id": ack.order_id, "status": ack.status.name},
                )
            )
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
                self._bus.publish(
                    Alert(
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
                    )
                )
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
        self._bus.publish(
            Alert(
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
            )
        )

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
            # Debit cancel or expiry fees even without a fill.
            if (
                ack.status
                in (
                    OrderAckStatus.CANCELLED,
                    OrderAckStatus.EXPIRED,
                )
                and ack.fees
                and ack.fees > 0
            ):
                self._positions.debit_fees(ack.symbol, ack.fees)
                if self._strategy_positions is not None and ack.order_id in self._active_orders:
                    strategy_id = self._active_orders[ack.order_id][2].strategy_id
                    if strategy_id:
                        self._strategy_positions.debit_fees(
                            strategy_id,
                            ack.symbol,
                            ack.fees,
                        )
                fee_position = self._positions.get(ack.symbol)
                self._bus.publish(
                    PositionUpdate(
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
                    )
                )

            if ack.status in (
                OrderAckStatus.FILLED,
                OrderAckStatus.PARTIALLY_FILLED,
            ):
                if ack.fill_price is None or ack.filled_quantity <= 0:
                    self._bus.publish(
                        Alert(
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
                        )
                    )
                    continue
            else:
                fill_like = ack.fill_price is not None and ack.filled_quantity > 0
                if fill_like:
                    self._bus.publish(
                        Alert(
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
                        )
                    )
                continue

            if ack.order_id not in self._active_orders:
                self._bus.publish(
                    Alert(
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
                    )
                )
                continue

            _, side, order = self._active_orders[ack.order_id]
            signed_qty = ack.filled_quantity
            if side == Side.SELL:
                signed_qty = -signed_qty

            # Track fills so a working-exit fallback submits only the residual.
            if ack.order_id in self._working_exit_fallback:
                self._order_filled_qty[ack.order_id] = (
                    self._order_filled_qty.get(ack.order_id, 0) + ack.filled_quantity
                )

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
            # Mirror the fill into the observational FIFO lot ledger.
            self._lot_ledger.apply_fill(
                ack.symbol,
                signed_qty,
                ack.fill_price,
                timestamp_ns=ack.timestamp_ns,
                strategy_id=order.strategy_id,
                intent=self._order_trading_intent.get(ack.order_id, ""),
            )

            if position.quantity == 0:
                self._peak_pnl_per_share.pop(ack.symbol, None)

            # Feed the PDT counter when the risk engine supports it.
            record_fill = getattr(self._risk_engine, "record_fill", None)
            if callable(record_fill):
                record_fill(
                    ack.symbol,
                    prev_qty,
                    position.quantity,
                    ack.timestamp_ns,
                )

            # ── Per-alpha fill attribution (multi-alpha mode) ──
            if self._fill_ledger is not None and self._strategy_positions is not None:
                try:
                    alpha_allocs = self._fill_ledger.allocate_fill(
                        ack.order_id,
                        ack.filled_quantity,
                        ack.fill_price,
                        total_fees=ack.fees,
                        is_final=ack.status == OrderAckStatus.FILLED,
                    )
                except Exception:
                    logger.exception(
                        "Fill attribution failed for order %s — "
                        "falling back to proportional distribution",
                        ack.order_id,
                    )
                    alpha_allocs = []

                if alpha_allocs:
                    for strat_id, sym, alpha_signed, price, alloc_fees in alpha_allocs:
                        self._strategy_positions.update(
                            strat_id,
                            sym,
                            alpha_signed,
                            price,
                            fees=alloc_fees,
                            timestamp_ns=ack.timestamp_ns,
                        )
                else:
                    # Without attribution, split proportionally to keep stores in
                    # sync. Aggregate PnL stays exact; per-alpha PnL is estimated.
                    self._distribute_fill_to_strategies(
                        ack.symbol,
                        signed_qty,
                        ack.fill_price,
                        ack.fees,
                        ack.timestamp_ns,
                    )
            self._bus.publish(
                PositionUpdate(
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
                )
            )

            disclosed = order.g12_disclosed_cost_total_bps
            alert_ratio = self._realized_cost_alert_ratio
            if disclosed > 0:
                breached = float(ack.cost_bps) > disclosed * alert_ratio
                if not breached:
                    # A fill within the disclosed band breaks the streak.
                    self._realized_cost_breach_streak.pop(order.strategy_id, None)
                else:
                    streak = self._realized_cost_breach_streak.get(order.strategy_id, 0) + 1
                    self._realized_cost_breach_streak[order.strategy_id] = streak
                    # Repeated cost overruns can trigger the kill switch.
                    escalate = (
                        self._realized_cost_escalation_enabled
                        and streak >= self._realized_cost_escalation_streak
                    )
                    severity = AlertSeverity.CRITICAL if escalate else AlertSeverity.WARNING
                    self._bus.publish(
                        Alert(
                            timestamp_ns=self._clock.now_ns(),
                            correlation_id=correlation_id,
                            sequence=self._seq.next(),
                            severity=severity,
                            layer="kernel",
                            alert_name="g12_realized_cost_exceeds_disclosure",
                            message=(
                                f"Fill cost_bps={float(ack.cost_bps):.4f} exceeds "
                                f"{alert_ratio}× G12 disclosed one-way "
                                f"cost_total_bps={disclosed:.4f} "
                                f"(strategy_id={order.strategy_id!r}, "
                                f"symbol={ack.symbol!r}, order_id={ack.order_id!r}, "
                                f"streak={streak})"
                            ),
                            context={
                                "strategy_id": order.strategy_id,
                                "symbol": ack.symbol,
                                "order_id": ack.order_id,
                                "realized_cost_bps": float(ack.cost_bps),
                                "g12_disclosed_cost_total_bps": disclosed,
                                "alert_ratio": alert_ratio,
                                "breach_streak": streak,
                                "escalated": escalate,
                            },
                        )
                    )
                    if (
                        escalate
                        and self._kill_switch is not None
                        and not self._kill_switch.is_active
                    ):
                        self._kill_switch.activate(
                            reason="realized_cost_persistent_overrun",
                            activated_by="orchestrator",
                        )

            if self._trade_journal is not None:
                _trade_mech, _trade_hl = self._last_signal_mechanism.get(
                    (order.strategy_id, ack.symbol),
                    (None, 0),
                )
                self._trade_journal.record(
                    TradeRecord(
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
                            ack.order_id,
                            "",
                        ),
                        trend_mechanism=_trade_mech,
                        expected_half_life_seconds=_trade_hl,
                        regime_state=self._regime_label_for(ack.symbol),
                        # Preserve forced-exit class and producing layer on the trade.
                        metadata={
                            "order_reason": order.reason,
                            "order_source_layer": order.source_layer,
                        },
                    )
                )
            if order.strategy_id not in _FORCED_MARKET_EXIT_STRATEGIES:
                self._alpha_symbols_with_fills.add((order.strategy_id, ack.symbol))

        self._prune_terminal_orders()

    def _regime_label_for(self, symbol: str) -> str:
        """Dominant regime-state name for *symbol* at fill time (forensics).

        Pure provenance capture for the trade journal: reads the regime
        engine's already-computed posterior (no new computation, no
        decision — Inv-5-safe) and returns its argmax state name.  Returns
        "" when there is no engine or no posterior yet for the symbol, so a
        cold or regime-less deployment simply records an empty regime label.
        """
        engine = self._regime_engine
        if engine is None:
            return ""
        post = engine.current_state(symbol)
        if not post:
            return ""
        names = list(engine.state_names)
        if not names:
            return ""
        idx = max(range(len(post)), key=lambda i: post[i])
        return names[idx] if idx < len(names) else ""

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

        # Inv-5: iterate strategies in a deterministic (sorted) order.
        # ``strategy_ids()`` returns a ``frozenset``; materialising it directly
        # would make the largest-remainder tie-break and per-alpha fee split
        # depend on hash-iteration order (process/seed dependent).
        strategy_ids = sorted(self._strategy_positions.strategy_ids())
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
                sid,
                symbol,
                alloc_sign * alloc_qty,
                fill_price,
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
            oid
            for oid, (sm, _, _) in self._active_orders.items()
            if sm.state in _TERMINAL_ORDER_STATES
        ]
        for oid in terminal_ids:
            del self._active_orders[oid]
            self._order_trading_intent.pop(oid, None)

    # ── Observability ───────────────────────────────────────────────

    def _emit_state_transition(self, record: TransitionRecord) -> None:
        """Emit a StateTransition event for every state machine change."""
        self._bus.publish(
            StateTransition(
                timestamp_ns=record.timestamp_ns,
                correlation_id=record.correlation_id,
                sequence=self._seq.next(),
                machine_name=record.machine_name,
                from_state=record.from_state,
                to_state=record.to_state,
                trigger=record.trigger,
                metadata=record.metadata,
            )
        )

    def _on_metric_event(self, event: Event) -> None:
        """Forward MetricEvents from the bus to the MetricCollector."""
        if isinstance(event, MetricEvent):
            self._metrics.record(event)

    def _on_alert_event(self, event: Event) -> None:
        """Forward Alert events from the bus to the AlertManager."""
        if isinstance(event, Alert) and self._alert_manager is not None:
            self._alert_manager.emit(event)

    # ── Bus-driven signal handler ───────────────────────────────────

    def _on_bus_signal(self, event: Event) -> None:
        """Buffer a SIGNAL-layer ``Signal`` for the current tick's M4 drain.

        Filtered for safety / correctness:

        * ``layer != "SIGNAL"`` — PORTFOLIO order flow uses
          ``SizedPositionIntent``, not this handler.
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
                    reasons=("filtered_alpha_consumed_by_portfolio_composition",),
                )
            return
        agg_qty = self._positions.get(event.symbol).quantity
        if is_redundant_gate_close_flat(
            event,
            aggregate_qty=agg_qty,
            alpha_has_prior_fill=(event.strategy_id, event.symbol)
            in self._alpha_symbols_with_fills,
        ):
            if self._signal_order_trace_sink is not None and q is not None:
                self._append_signal_order_trace(
                    q,
                    event,
                    outcome="NO_ORDER",
                    reasons=("filtered_redundant_gate_close_flat",),
                )
            return
        self._signal_buffer.append(event)
        # Cache mechanism metadata for fill attribution, never for decisions.
        if event.trend_mechanism is not None or event.expected_half_life_seconds:
            self._last_signal_mechanism[(event.strategy_id, event.symbol)] = (
                event.trend_mechanism,
                event.expected_half_life_seconds,
            )
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
                    self._alpha_registry,
                    "portfolio_alphas",
                    None,
                )
                if portfolio_alphas_fn is not None:
                    for module in portfolio_alphas_fn():
                        deps = getattr(module, "depends_on_signals", ())
                        consumed.update(deps)
            self._consumed_by_portfolio_ids = frozenset(consumed)
        return alpha_id in self._consumed_by_portfolio_ids

    def _standalone_signal_actionable_for_strategy_ownership(
        self,
        signal: Signal,
    ) -> bool:
        """Return False when *signal* would exit book the alpha does not own."""
        if self._strategy_positions is None:
            return True
        sym = signal.symbol
        strat_qty = self._strategy_positions.get(signal.strategy_id, sym).quantity
        agg_qty = self._positions.get(sym).quantity
        return standalone_signal_actionable_for_strategy(
            signal,
            strategy_qty=strat_qty,
            aggregate_qty=agg_qty,
            alpha_has_prior_fill=(signal.strategy_id, sym) in self._alpha_symbols_with_fills,
        )

    def _filter_standalone_signals_by_strategy_ownership(
        self,
        signals: Sequence[Signal],
    ) -> list[Signal]:
        """Drop cross-alpha gate-close hijacks and foreign exit signals."""
        return [s for s in signals if self._standalone_signal_actionable_for_strategy_ownership(s)]

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
        buf = self._filter_standalone_signals_by_strategy_ownership(
            self._signal_buffer,
        )
        quote = self._tick_quote_for_trace
        if quote is not None and self._signal_order_trace_sink is not None:
            actionable_ids = {id(s) for s in buf}
            for s in self._signal_buffer:
                if id(s) in actionable_ids:
                    continue
                self._append_signal_order_trace(
                    quote,
                    s,
                    outcome="NO_ORDER",
                    reasons=("filtered_no_strategy_position_for_exit",),
                )
        if not buf:
            return None
        if len(buf) > 1:
            agg_qty = self._positions.get(buf[0].symbol).quantity
            harmless = collision_is_harmless_flat_gate_close(buf, agg_qty)
            self._arbitration_collisions.append(
                StandaloneArbitrationCollision(
                    candidate_count=len(buf),
                    strategy_ids=tuple(sorted({s.strategy_id for s in buf})),
                    kinds=tuple(
                        sorted((s.strategy_id, s.direction.name, s.regime_gate_state) for s in buf)
                    ),
                    harmless=harmless,
                )
            )
            ids = sorted({s.strategy_id for s in buf})
            if harmless:
                if not self._logged_harmless_arbitration_collision:
                    self._logged_harmless_arbitration_collision = True
                    logger.debug(
                        "orchestrator: %d standalone SIGNAL candidate(s) from %d "
                        "alpha id(s) on flat book (%s); all gate-close FLAT — "
                        "no order impact.  Prefer PORTFOLIO aggregation for "
                        "production multi-alpha books.",
                        len(buf),
                        len(ids),
                        ids,
                    )
            elif not self._warned_multi_standalone_signals:
                self._warned_multi_standalone_signals = True
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

    # Bus-driven sized-intent handler.

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
        # Feed portfolio targets into the net shadow measurement.
        self._record_portfolio_net_shadow(event)
        if self._quote_tick_in_flight:
            self._pending_sized_intents.append(event)
        else:
            self._submit_portfolio_leg_without_micro_walk(event, event.correlation_id)

    # Import the controller's signature so hazard filtering cannot drift.

    def _on_bus_hazard_order(self, event: Event) -> None:
        """Route reducing RISK-layer forced-exit orders to the execution backend.

        Handles both risk-layer exit authors that share this non-vetoable bridge:
        the :class:`~feelies.risk.hazard_exit.HazardExitController` and the
        Stage-0 :class:`~feelies.risk.exit_composer.ExitComposer`.  Both stamp
        ``source_layer="RISK"`` and a reason in
        :data:`_RISK_FORCED_EXIT_REASONS`.  The order is validated with
        ``check_order`` (not ``check_sized_intent``), so a cost/edge veto that may
        suppress an *entry* can never suppress a mandated safety exit (Inv-11).

        Tight source and reason filters prevent double submission of orders
        already routed by the normal signal, portfolio, or emergency paths.
        """
        if not isinstance(event, OrderRequest):
            return
        if event.source_layer != HAZARD_EXIT_SOURCE_LAYER:
            return
        if event.reason not in _RISK_FORCED_EXIT_REASONS:
            return
        # Hazard IDs remain in a dedicated set after active orders are pruned.
        if event.order_id in self._hazard_submitted_order_ids:
            return
        self._hazard_submitted_order_ids.add(event.order_id)
        hv = self._risk_engine.check_order(event, self._positions)
        # Trust the exit fail-safe only when the order reduces live exposure.
        current_qty = self._positions.get(event.symbol).quantity
        signed_qty = event.quantity if event.side == Side.BUY else -event.quantity
        order_reduces = abs(current_qty + signed_qty) < abs(current_qty)
        # Do not broadcast FORCE_FLATTEN while this handler submits a local exit.
        if hv.action != RiskAction.FORCE_FLATTEN:
            self._bus.publish(hv)
        if hv.action == RiskAction.REJECT and not order_reduces:
            # Non-exit order carrying a hazard reason: REJECT is authoritative.
            self._bus.publish(
                Alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=event.correlation_id,
                    sequence=self._seq.next(),
                    severity=AlertSeverity.CRITICAL,
                    layer="kernel",
                    alert_name="hazard_exit_nonreducing_reject_blocked",
                    message=(
                        "check_order returned REJECT on a hazard-tagged order "
                        "that does not reduce the live position "
                        f"(strategy_id={event.strategy_id!r}, symbol={event.symbol!r}, "
                        f"current_qty={current_qty}, side={event.side.name}, "
                        f"order_qty={event.quantity}, reason={hv.reason!r}) — "
                        "blocking submission (REJECT is authoritative for "
                        "non-exit orders)."
                    ),
                    context={
                        "order_id": event.order_id,
                        "risk_reason": hv.reason,
                    },
                )
            )
            return
        if hv.action == RiskAction.REJECT:
            self._bus.publish(
                Alert(
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
                )
            )
        self._track_order(event.order_id, event.side, event)
        submit_error = self._submit_tracked_order(event, trigger=event.reason)
        if submit_error is not None:
            logger.error(
                "Hazard exit order submission failed for %s "
                "(strategy_id=%s, reason=%s, order_id=%s); position "
                "remains open and will be retried on the next spike.",
                event.symbol,
                event.strategy_id,
                event.reason,
                event.order_id,
                exc_info=(
                    type(submit_error),
                    submit_error,
                    submit_error.__traceback__,
                ),
            )
            return
        acks = self._poll_order_router_acks({event.order_id})
        self._publish_and_apply_order_acks(acks)
        self._reconcile_fills(acks, event.correlation_id)

    # ── Configuration and data integrity ────────────────────────────

    # LULD halt modeling.

    def _update_halt_state(self, trade: Trade) -> None:
        """Register halt and resume edges from the trade tape.

        On halt-on for a symbol not already halted: mark it halted, cancel
        any resting orders (Inv-11), and emit ``SymbolHalted``.  On resume:
        clear the halt, open the entry blackout window, and emit the resume
        ``SymbolHalted``.  Inert when no halt codes are configured.
        """
        if not self._halt_on_codes and not self._halt_off_codes:
            return
        status = classify_halt_status(
            trade.conditions,
            self._halt_on_codes,
            self._halt_off_codes,
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
        self._bus.publish(
            SymbolHalted(
                timestamp_ns=ts,
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                source_layer="kernel",
                symbol=symbol,
                halted=halted,
                reason=reason,
                blackout_until_ns=blackout_until_ns,
            )
        )

    # ── Reg-SHO / SSR short-sale restriction ────────────────────────

    def _update_ssr_state(self, trade: Trade) -> None:
        """Activate sticky session SSR state from trade condition codes."""
        if not self._ssr_codes:
            return
        if not (set(trade.conditions) & self._ssr_codes):
            return
        symbol = trade.symbol.upper()
        if symbol in self._ssr_active:
            return
        self._ssr_active.add(symbol)
        self._bus.publish(
            Alert(
                timestamp_ns=trade.timestamp_ns,
                correlation_id=trade.correlation_id,
                sequence=self._seq.next(),
                severity=AlertSeverity.INFO,
                layer="kernel",
                alert_name="ssr_triggered",
                message=f"SSR became active intraday for {symbol} (Reg-SHO 201).",
                context={"symbol": symbol},
            )
        )

    # ── Static borrow availability ───────────────────────────────────

    def _borrow_tier_for(self, symbol: str) -> BorrowTier:
        """Locate tier for ``symbol``; omitted symbols use the default tier."""
        return self._borrow_tier.get(symbol.upper(), self._borrow_default_tier)

    def _borrow_blocks_intent(self, intent: OrderIntent) -> bool:
        """True when locate is unavailable and this intent is a short sale."""
        return self._borrow_tier_for(
            intent.symbol
        ) == BorrowTier.UNAVAILABLE and is_short_sale_intent(intent)

    def _emit_locate_unavailable_alert(
        self,
        intent: OrderIntent,
        correlation_id: str,
    ) -> None:
        """Publish the forensic marker for a refused short entry (no locate)."""
        self._bus.publish(
            Alert(
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
            )
        )

    def _emit_forced_exit_supersedes_pending_alert(
        self,
        order: OrderRequest,
        correlation_id: str,
    ) -> None:
        """Publish a forensic marker when a forced MARKET exit supersedes a
        stale resting order.

        Operator visibility (Inv-11): a hard-stop / session-flat MARKET exit
        cancelled a pending passive order for the symbol so the aggressive
        close could cross immediately.  Distinct from a duplicate-exit
        suppression so post-trade forensics can attribute the cancel-and-cross
        to the safety control rather than to alpha behaviour.
        """
        self._bus.publish(
            Alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                severity=AlertSeverity.WARNING,
                layer="kernel",
                alert_name="forced_exit_supersedes_pending_order",
                message=(
                    f"Forced MARKET exit {order.strategy_id!r} on "
                    f"{order.symbol!r}: cancelling resting order(s) so the "
                    f"aggressive close can cross immediately (Inv-11)."
                ),
                context={
                    "symbol": order.symbol,
                    "strategy_id": order.strategy_id,
                    "order_id": order.order_id,
                },
            )
        )

    def _ssr_blocks_intent(self, intent: OrderIntent) -> bool:
        """True when SSR (refuse_short) must refuse this short-opening order."""
        if intent.symbol.upper() not in self._ssr_active:
            return False
        return is_short_sale_intent(intent)

    def _emit_ssr_suppression_alert(
        self,
        intent: OrderIntent,
        correlation_id: str,
    ) -> None:
        """Publish the forensic marker for a refused SSR short entry."""
        self._bus.publish(
            Alert(
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
            )
        )

    def _publish_rejected_event_alert(
        self,
        event: NBBOQuote | Trade,
        correlation_id: str,
        data_health_reason: str,
    ) -> None:
        """Publish a rejected market event's fields as an alert.

        A quote or trade blocked by :meth:`_data_health_blocks_trading` never
        reaches ``EventLog.append`` (fail-safe for trading), so without this
        the exact event that triggered the block is unrecoverable for
        post-incident replay.  Publishing it as a typed ``Alert`` keeps the
        provenance on the same bus every other layer already observes
        (Inv-7/Inv-13) instead of adding a bespoke sink.
        """
        if isinstance(event, NBBOQuote):
            context: dict[str, Any] = {
                "event_type": "NBBOQuote",
                "bid": str(event.bid),
                "ask": str(event.ask),
                "bid_size": event.bid_size,
                "ask_size": event.ask_size,
            }
        else:
            context = {
                "event_type": "Trade",
                "price": str(event.price),
                "size": event.size,
            }
        context["symbol"] = event.symbol
        context["exchange_timestamp_ns"] = event.exchange_timestamp_ns
        context["sequence_number"] = event.sequence_number
        context["data_health_reason"] = data_health_reason
        self._bus.publish(
            Alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                severity=AlertSeverity.WARNING,
                layer="kernel",
                alert_name="market_event_rejected_by_data_health",
                message=(
                    f"{context['event_type']} for {event.symbol!r} rejected by "
                    f"data-health gate ({data_health_reason})"
                ),
                context=context,
            )
        )

    def _data_health_blocks_trading(self, symbol: str, correlation_id: str) -> str | None:
        """Return the block reason when the normalizer forbids this symbol, else None.

        The returned string is suitable for rejection alerts:
        ``SYMBOL_UNTRACKED`` for strict coverage, otherwise the ``DataHealth``
        name. ``None`` means the symbol may be consumed.

        CORRUPTED always halts trading for the symbol when a normalizer is wired.
        GAP_DETECTED does the same only when ``PlatformConfig.degrade_on_data_gap``
        is enabled (strict paper/live policy).

        ``HALTED`` blocks the tick without escalating macro state; LULD halts
        are recoverable and ``DataHealth.HALTED → HEALTHY`` is the resume
        path.  This sits alongside the orchestrator-side ``_halted_symbols``
        edge tracker (which retains the cancel-resting + post-halt blackout
        side effects) so the normalizer's view is *also* load-bearing here:
        if the two drift, the more conservative gate wins.
        """
        if self._normalizer is None:
            return None
        health = self._normalizer.health(symbol)
        cfg_syms = (
            {s.upper() for s in self._config.symbols} if self._config is not None else frozenset()
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
                    return "SYMBOL_UNTRACKED"
        if health == DataHealth.CORRUPTED:
            # Force-flatten the affected symbol before transitioning macro.
            # CORRUPTED is terminal — leaving an open position to mark at
            # the last-known quote would carry stale risk through DEGRADED.
            self._force_flatten_symbol_on_degrade(
                symbol,
                correlation_id,
                reason="DATA_CORRUPTED",
            )
            if self._macro.can_transition(MacroState.DEGRADED):
                self._macro.transition(
                    MacroState.DEGRADED,
                    trigger=f"DATA_CORRUPTED:{symbol}",
                    correlation_id=correlation_id,
                )
            return health.name
        if health == DataHealth.HALTED:
            # A recoverable LULD halt blocks the symbol without degrading macro state.
            return health.name
        degrade_gap = getattr(self._config, "degrade_on_data_gap", False)
        if degrade_gap and health == DataHealth.GAP_DETECTED:
            # GAP_DETECTED can recover to HEALTHY, but the macro DEGRADED
            # transition is sticky (requires explicit operator command).
            # Unwind the affected symbol at the last-known mark so the
            # book doesn't carry stale exposure through the gap window.
            self._force_flatten_symbol_on_degrade(
                symbol,
                correlation_id,
                reason="DATA_GAP_DETECTED",
            )
            if self._macro.can_transition(MacroState.DEGRADED):
                self._macro.transition(
                    MacroState.DEGRADED,
                    trigger=f"DATA_GAP_DETECTED:{symbol}",
                    correlation_id=correlation_id,
                )
            return health.name
        return None

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
        order_id = derive_order_id(f"degrade_flatten:{reason}:{symbol}:{seq}")
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
            self._publish_and_apply_order_acks(acks)
            self._reconcile_fills(acks, correlation_id)
        except Exception as exc:  # noqa: BLE001 — fail-safe; never raise
            logger.exception(
                "Force-flatten on %s failed for symbol=%s (qty=%d, side=%s); "
                "position remains open and will require manual intervention.",
                reason,
                symbol,
                qty,
                side.name,
            )
            self._bus.publish(
                Alert(
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
                )
            )

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

        """
        if self._feature_snapshots is None:
            return
        self._restore_regime_snapshot()

    def _restore_regime_snapshot(self) -> None:
        if self._feature_snapshots is None or self._regime_engine is None:
            return
        regime_version = self._REGIME_VERSION_PREFIX + type(self._regime_engine).__name__
        result = self._feature_snapshots.load(
            self._REGIME_SNAPSHOT_KEY,
            regime_version,
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
        """Checkpoint regime state without blocking shutdown on failure."""
        if self._feature_snapshots is None:
            return
        self._checkpoint_regime_snapshot()

    def _checkpoint_regime_snapshot(self) -> None:
        if self._feature_snapshots is None or self._regime_engine is None:
            return
        regime_version = self._REGIME_VERSION_PREFIX + type(self._regime_engine).__name__
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
                "Regime snapshot checkpoint failed -- next boot will cold-start regime engine",
                exc_info=True,
            )
