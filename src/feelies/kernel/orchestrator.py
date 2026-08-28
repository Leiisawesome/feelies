"""Coordinate deterministic platform state and tick processing.

Domain calculations remain in their owning layers. The orchestrator enforces
trading-mode gates, deterministic order IDs and replay transitions, terminal
order resolution before shutdown, and fail-safe degradation or lockdown. All
modes share the same tick pipeline and publish every state transition.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, fields, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Mapping

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from feelies.portfolio.fill_attribution import FillAttributionLedger
    from feelies.alpha.registry import AlphaRegistry
    from feelies.composition.engine import CompositionEngine
    from feelies.risk.hazard_exit import HazardExitController
    from feelies.portfolio.strategy_position_store import StrategyPositionStore

from feelies.portfolio.fill_attribution import largest_remainder_split, split_fees
from feelies.alpha.arbitration import (
    EdgeWeightedArbitrator,
    SignalArbitrator,
    StandaloneArbitrationCollision,
    collision_is_harmless_flat_gate_close,
    is_redundant_gate_close_flat,
    standalone_signal_actionable_for_strategy,
)
from feelies.core.gate_registry import record_verdict
from feelies.bus.event_bus import EventBus
from feelies.core.clock import Clock
from feelies.core.config import Configuration
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.core.errors import (
    ConfigurationError,
    OrchestratorPipelineAbortError,
    SessionEntryBlockedError,
)
from feelies.core.events import (
    Alert,
    AlertSeverity,
    DeRiskRequirement,
    Event,
    HorizonTick,
    LatencyBreach,
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
from feelies.execution.order_admission import (
    BLOCK_EDGE_BELOW_COST,
    BLOCK_EDGE_UNPRICEABLE,
    BLOCK_LOCATE_UNAVAILABLE,
    BLOCK_SSR,
    ExposureDelta,
    admission_block_reason,
    exposure_delta_from_intent,
    side_for_intent,
)
from feelies.execution.order_lifecycle import (
    _transition_order,
)
from feelies.execution.order_policy import (
    _edge_clears_round_trip_cost,
    _execute_reverse,
    _filter_portfolio_orders_for_admission,
    _plan_for_signal,
    _try_build_order_from_intent,
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
    PlanLeg,
    PositionManager,
    desired_from_signal,
    order_intent_from_plan,
)
from feelies.execution.trading_session import (
    TradingSessionBounds,
    in_session_flatten_window,
)
from feelies.execution.regulatory.borrow_availability import (
    BorrowTier,
    build_borrow_table,
    parse_borrow_tier,
)
from feelies.ingestion.data_integrity import (
    DataHealth,
    _update_halt_state,
    _update_ssr_state,
    _data_health_blocks_trading,
    _verify_data_integrity,
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
from feelies.monitoring.kill_switch import KillSwitch, observe_kill_switch
from feelies.monitoring.latency_budget import (
    _LatencyBudgetMonitor,
    _apply_breach_response,
)
from feelies.monitoring.paper_session_recorder import PaperSessionRecorder
from feelies.monitoring.telemetry import MetricCollector
from feelies.portfolio.position_book_view import PositionBookView
from feelies.portfolio.position_store import PositionStore
from feelies.portfolio.lot_ledger import LotLedger
from feelies.risk.engine import (
    RiskEngine,
    _compute_target_quantity,
    _emergency_flatten_all,
    _escalate_risk,
    _maybe_flip_buying_power_at_rth_close,
)
from feelies.risk.escalation import RiskLevel, create_risk_escalation_machine
from feelies.risk.deferral_cap import (
    DEFERRAL_EXIT_REASONS,
    DEFERRAL_SLICE_SCOPED_REASONS,
)
from feelies.risk.exit_composer import EXIT_COMPOSER_EXIT_REASONS
from feelies.risk.hazard_exit import HAZARD_EXIT_REASONS, HAZARD_EXIT_SOURCE_LAYER
from feelies.risk.stop_exit import STOP_EXIT_REASONS
from feelies.risk.edge_weighted_sizer import (
    EdgeWeightedSizer,
    SizeDivergence,
    apply_tilt,
)
from feelies.risk.position_sizer import BudgetBasedSizer, PositionSizer
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.registry import SensorRegistry
from feelies.services.regime_engine import RegimeEngine, _calibrate_regime_engine, _checkpoint_feature_snapshots, _regime_label_for, _restore_feature_snapshots, _update_regime  # noqa: E501
from feelies.services.regime_hazard_detector import RegimeHazardDetector
from feelies.signals.horizon_engine import HorizonSignalEngine
from feelies.storage.event_log import EventLog
from feelies.storage.feature_snapshot import FeatureSnapshotStore
from feelies.storage.trade_journal import TradeJournal, TradeRecord

if TYPE_CHECKING:
    from feelies.execution.cost_model import CostModel

# Stable correlation IDs for lifecycle transitions.
_PLATFORM_BOOT_CORRELATION_ID = "platform_boot"
_ORCHESTRATOR_SHUTDOWN_CORRELATION_ID = "orchestrator_shutdown"


def _resolve_boot_config(config: Configuration) -> PlatformConfig:
    """Overlay partial test configs onto the orchestrator's legacy defaults."""
    if isinstance(config, PlatformConfig):
        return config
    baseline = PlatformConfig(
        moc_strategy_ids=(),
        rth_session_gating_enabled=False,
        session_flatten_enabled=False,
    )
    overrides = {
        config_field.name: getattr(config, config_field.name)
        for config_field in fields(PlatformConfig)
        if hasattr(config, config_field.name)
    }
    return replace(baseline, **overrides)


_TERMINAL_ORDER_STATES: frozenset[OrderState] = frozenset(
    {
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
    }
)

# Risk-authored exits use one non-vetoable reason registry.
_RISK_FORCED_EXIT_REASONS: frozenset[str] = (
    HAZARD_EXIT_REASONS | EXIT_COMPOSER_EXIT_REASONS | DEFERRAL_EXIT_REASONS | STOP_EXIT_REASONS
)

# Slice-scoped authors may reduce either symbol-net or strategy-slice exposure.
_SLICE_SCOPED_FORCED_EXIT_REASONS: frozenset[str] = (
    EXIT_COMPOSER_EXIT_REASONS | DEFERRAL_EXIT_REASONS
)

# Only unambiguous slice-scoped reasons self-attribute fills.
_SELF_ATTRIBUTED_FORCED_EXIT_REASONS: frozenset[str] = (
    EXIT_COMPOSER_EXIT_REASONS | DEFERRAL_SLICE_SCOPED_REASONS
)


def _order_owns_one_slice(order: OrderRequest) -> bool:
    """Return whether every fill belongs to the order strategy slice."""
    if not order.strategy_id:
        return False
    if order.reason in _SELF_ATTRIBUTED_FORCED_EXIT_REASONS:
        return True
    return order.reason not in _RISK_FORCED_EXIT_REASONS


def _closable_quantity(position_qty: int, side: Side) -> int:
    """Return shares that side can close without crossing through zero."""
    if side is Side.SELL:
        return max(position_qty, 0)
    return max(-position_qty, 0)


def _is_forced_market_exit(order: OrderRequest) -> bool:
    """Identify controller-authored aggressive exits routed through the risk bridge."""
    return (
        order.source_layer == HAZARD_EXIT_SOURCE_LAYER
        and order.reason in _RISK_FORCED_EXIT_REASONS
    )


@dataclass(frozen=True, kw_only=True)
class _TradeJournalLeg:
    """One trade-journal row's share of a single fill."""

    strategy_id: str
    filled_quantity: int
    fees: Decimal
    realized_pnl: Decimal
    metadata: dict[str, str]


def _trade_journal_legs(
    order: OrderRequest,
    *,
    filled_quantity: int,
    fees: Decimal,
    realized_pnl: Decimal,
    attributed_legs: Sequence[tuple[str, int, Decimal, Decimal]],
    announced_quantity: int | None = None,
) -> list[_TradeJournalLeg]:
    """Build per-strategy journal rows for one fill.

    Slice-owned orders keep one owner; symbol-net exits use attributed slice economics. Missing attribution falls back to one aggregate row."""
    base_metadata = {
        "order_reason": order.reason,
        "order_source_layer": order.source_layer,
    }
    if announced_quantity is not None:
        # Present only when the kernel clamped this exit, so its presence is
        # itself the signal that submitted size != announced size.
        base_metadata["forced_exit_announced_quantity"] = str(announced_quantity)
    if not attributed_legs:
        return [
            _TradeJournalLeg(
                strategy_id=order.strategy_id,
                filled_quantity=filled_quantity,
                fees=fees,
                realized_pnl=realized_pnl,
                metadata=base_metadata,
            )
        ]

    # Preserve each slice's realized PnL instead of blending aggregate basis.
    owns_one_slice = _order_owns_one_slice(order)
    metadata = (
        base_metadata
        if owns_one_slice
        else {**base_metadata, "forced_exit_strategy_id": order.strategy_id}
    )
    return [
        _TradeJournalLeg(
            strategy_id=strategy_id,
            filled_quantity=abs(qty),
            fees=leg_fees,
            realized_pnl=leg_realized,
            metadata=dict(metadata),
        )
        for strategy_id, qty, leg_fees, leg_realized in attributed_legs
    ]


def _int_to_direction(sign: int) -> SignalDirection:
    """Map a signed direction (+1 / -1 / 0) to a ``SignalDirection``."""
    if sign > 0:
        return SignalDirection.LONG
    if sign < 0:
        return SignalDirection.SHORT
    return SignalDirection.FLAT


class Orchestrator:
    """Coordinate lifecycle state and the deterministic tick pipeline.

    Domain calculations stay in their owning layers; this class sequences bus dispatch, state transitions, execution, and fail-safe recovery."""

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
        regime_hazard_detector: RegimeHazardDetector | None = None,
        hazard_sequence_generator: SequenceGenerator | None = None,
        composition_engine: "CompositionEngine | None" = None,
        hazard_exit_controller: "HazardExitController | None" = None,
        trading_session_bounds: TradingSessionBounds | None = None,
        moc_bounds_configured: bool = False,
        signal_arbitrator: SignalArbitrator | None = None,
        edge_calibration_factors: Mapping[str, float] | None = None,
        signal_order_trace_sink: list[SignalOrderTraceRow] | None = None,
        regime_calibration_quotes: Sequence[NBBOQuote] | None = None,
        position_manager: "PositionManager | None" = None,
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
            position_sizer if position_sizer is not None else BudgetBasedSizer()
        )
        # Shadow the planner without affecting orders, events, or journals.
        self._position_manager = position_manager
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
        self._seq = SequenceGenerator(stream="orchestrator", **_seq_kw)

        # Optional sensor and horizon components; None keeps the short tick path.
        self._sensor_registry = sensor_registry
        self._horizon_scheduler = horizon_scheduler
        self._horizon_signal_engine = horizon_signal_engine
        # Hazard events use an isolated sequence so exits cannot shift other IDs.
        self._regime_hazard_detector = regime_hazard_detector
        self._hazard_seq = hazard_sequence_generator or SequenceGenerator(stream="hazard", **_seq_kw)
        # Bootstrap wires optional composition components to the bus; these
        # references support orchestration and inspection.
        self._composition_engine = composition_engine
        self._hazard_exit_controller = hazard_exit_controller
        self._signal_arbitrator: SignalArbitrator = (
            signal_arbitrator if signal_arbitrator is not None else EdgeWeightedArbitrator()
        )
        self._signal_order_trace_sink: list[SignalOrderTraceRow] | None = signal_order_trace_sink
        self._paper_session_recorder: PaperSessionRecorder | None = None
        self._quote_tick_in_flight: bool = False; self._in_flight_quote: NBBOQuote | None = None
        self._tick_quote_for_trace: NBBOQuote | None = None
        # Preserve the last quote so inter-quote signals can produce trace rows.
        self._last_quote_context_for_signal_trace: NBBOQuote | None = None
        self._signal_order_trace_seen_sequences: set[int] = set()
        # Only inter-quote signals may cross one quote boundary; M4 consumes them.
        self._carryover_signal_sequences: set[int] = set()
        # Reset session-local hazard history while retaining the regime engine's
        # calibrated posterior across sessions.
        self._last_regime_state: dict[tuple[str, str], RegimeState] = {}
        # Trade-path boundaries wait for a quote-published regime state.
        self._regime_bus_published_symbols: set[str] = set()

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

        self._config: PlatformConfig | None = None

        # Active order state machines keyed by order ID.
        self._active_orders: dict[str, tuple[StateMachine[OrderState], Side, OrderRequest]] = {}
        # Submission-time intent used to stamp TradeRecord attribution.
        self._order_trading_intent: dict[str, str] = {}
        # Pre-clamp quantity of a mandated exit the kernel resized, by order id.
        # Only written on that exceptional path; cleared with the order.
        self._forced_exit_announced_quantity: dict[str, int] = {}
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

        # Static locate tiers; omitted symbols use the configured default.
        self._borrow_tier: dict[str, BorrowTier] = {}
        # AVAILABLE is optimistic; use hard or unavailable for conservative universes.
        self._borrow_default_tier: BorrowTier = BorrowTier.AVAILABLE

        # Strategies routed to MOC once session bounds resolve.
        self._moc_strategy_ids: frozenset[str] = frozenset()
        self._moc_bounds_configured = moc_bounds_configured

        # RTH entry suppression and close buying-power transition.
        self._trading_session_bounds = trading_session_bounds
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

        self._latency_monitor = _LatencyBudgetMonitor()
        self._latency_reduce_only = False
        self._bus.subscribe(LatencyBreach, self._on_latency_breach)

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

        # Route only controller-authored de-risk commands. The handler
        # copies the author's sequence onto an outbound OrderRequest.
        self._bus.subscribe(DeRiskRequirement, self._on_bus_derisk_requirement)

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

    def _finish_no_order(
        self,
        quote: NBBOQuote,
        signal: Signal,
        intent: OrderIntent,
        t_wall_start_ns: int,
        correlation_id: str,
        reasons: Sequence[str],
        trigger: str,
    ) -> None:
        """Record a suppressed signal and close the current micro-state walk."""
        self._append_signal_order_trace(
            quote,
            signal,
            outcome="NO_ORDER",
            reasons=tuple(reasons),
            trading_intent=intent.intent.name,
        )
        self._finalize_tick(t_wall_start_ns, correlation_id, trigger)

    def _trace_buffered_signals_arbitration(
        self,
        quote: NBBOQuote,
        buf_snapshot: list[Signal],
        bus_selected: Signal | None,
    ) -> None:
        if self._signal_order_trace_sink is None or not buf_snapshot:
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

    def _publish_alert(
        self,
        *,
        timestamp_ns: int,
        correlation_id: str,
        severity: AlertSeverity,
        alert_name: str,
        message: str,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        """Publish one kernel alert with the shared provenance envelope."""
        self._bus.publish(
            Alert(
                timestamp_ns=timestamp_ns,
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                severity=severity,
                layer="kernel",
                alert_name=alert_name,
                message=message,
                context=dict(context or {}),
            )
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
    def position_store(self) -> PositionBookView:
        return PositionBookView.from_store(self._positions)

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
    def edge_calibration_factors(self) -> Mapping[str, float]:
        """Expose the immutable edge factors actually applied at boot."""
        return MappingProxyType(dict(self._edge_calibration_factors))

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

        Applies to ``run_backtest`` and ``run_paper`` — kill switch and risk
        escalation must both allow entry.
        """
        if self._kill_switch is not None and observe_kill_switch(self._kill_switch.is_active):
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
        """Bind live position quantity to the optional router RTH entry gate.

        The binding keeps post-close exits distinguishable from new entries."""
        if self._trading_session_bounds is None:
            return
        router = getattr(self._backend, "order_router", None)
        bind = getattr(router, "bind_position_qty", None)
        if not callable(bind):
            return
        bind(lambda sym: int(PositionBookView.from_store(self._positions).get(sym)))

    def _reset_buying_power_phase_for_session(self) -> None:
        """Reset the RTH latch and restore intraday buying power."""
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
            cfg = _resolve_boot_config(config)
            self._config = cfg
            market_impact_factor = Decimal(str(cfg.cost_market_impact_factor))
            max_impact_half_spreads = Decimal(str(cfg.cost_max_impact_half_spreads))
            within_l1_impact_factor = Decimal(str(cfg.cost_within_l1_impact_factor))
            permanent_impact_coefficient = Decimal(str(cfg.cost_permanent_impact_coefficient))
            self._market_context = MarketContext(
                market_impact_factor=market_impact_factor,
                max_impact_half_spreads=max_impact_half_spreads,
                within_l1_impact_factor=within_l1_impact_factor,
                permanent_impact_coefficient=permanent_impact_coefficient,
            )
            self._session_flatten_enabled = cfg.session_flatten_enabled
            self._session_flatten_seconds_before_close = cfg.session_flatten_seconds_before_close
            self._enable_portfolio_netting = cfg.enable_portfolio_netting
            self._net_staleness_k = cfg.net_staleness_k
            if hasattr(config, "risk_max_position_per_symbol"):
                cap = cfg.risk_max_position_per_symbol
                self._net_portfolio_max_abs_qty = cap if cap > 0 else None
                self._portfolio_netter = PortfolioNetter(
                    self._desired_target_book,
                    portfolio_max_abs_qty=self._net_portfolio_max_abs_qty,
                )

            self._halt_on_codes = frozenset(cfg.halt_on_condition_codes)
            self._halt_off_codes = frozenset(cfg.halt_off_condition_codes)
            self._halt_blackout_ns = cfg.halt_resolution_blackout_seconds * 1_000_000_000
            self._ssr_active = {symbol.upper() for symbol in cfg.ssr_active_symbols}
            self._ssr_codes = frozenset(cfg.ssr_trigger_condition_codes)
            self._borrow_tier = build_borrow_table(cfg.borrow_availability)
            self._borrow_default_tier = parse_borrow_tier(cfg.borrow_default_tier)
            if (
                self._borrow_default_tier != BorrowTier.AVAILABLE
                and cfg.cost_htb_borrow_annual_bps == 0.0
            ):
                logger.warning(
                    "borrow_default_tier=%s but cost_htb_borrow_annual_bps=0 — "
                    "short-side borrow cost is not modelled; set "
                    "cost_htb_borrow_annual_bps for HARD-to-borrow names.",
                    self._borrow_default_tier.value,
                )

            self._moc_strategy_ids = frozenset(cfg.moc_strategy_ids)

            self._use_passive_entries = cfg.execution_mode in (
                "passive_limit",
                "minimum_cost",
            )
            if cfg.execution_mode == "minimum_cost" and self._cost_model is not None:
                self._min_cost_policy = MinimumCostExecutionPolicy(
                    cost_model=self._cost_model,
                    config=MinCostPolicyConfig(
                        prefer_passive_bias_bps=Decimal(str(cfg.cost_min_passive_bias_bps)),
                        small_order_aggressive_threshold_shares=(
                            cfg.cost_min_small_order_threshold_shares
                        ),
                        min_half_spread_for_passive=Decimal(
                            str(cfg.cost_min_half_spread_threshold)
                        ),
                        allow_passive_short_entry=cfg.cost_min_allow_passive_short_entry,
                        market_impact_factor=market_impact_factor,
                        max_impact_half_spreads=max_impact_half_spreads,
                        within_l1_impact_factor=within_l1_impact_factor,
                        permanent_impact_coefficient=permanent_impact_coefficient,
                        passive_non_fill_probability=Decimal(
                            str(cfg.cost_min_passive_non_fill_probability)
                        ),
                    ),
                )
            self._min_order_shares = cfg.platform_min_order_shares
            self._signal_min_edge_cost_ratio = cfg.signal_min_edge_cost_ratio
            self._reversal_min_edge_cost_multiplier = cfg.reversal_min_edge_cost_multiplier
            self._signal_edge_cost_basis = cfg.signal_edge_cost_basis
            self._realized_cost_alert_ratio = cfg.realized_cost_alert_ratio
            self._realized_cost_escalation_enabled = cfg.realized_cost_escalation_enabled
            self._realized_cost_escalation_streak = cfg.realized_cost_escalation_streak
            self._regime_calibration_max_quotes = cfg.regime_calibration_max_quotes
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

        if _verify_data_integrity(self):
            self._macro.transition(
                MacroState.READY,
                trigger="DATA_INTEGRITY_OK",
                correlation_id=_PLATFORM_BOOT_CORRELATION_ID,
            )
            _restore_feature_snapshots(self)
            _calibrate_regime_engine(self)
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
        """Run the shared pipeline in PAPER mode."""
        self._run_deployment_session(
            mode=MacroState.PAPER_TRADING_MODE,
            session_name="paper",
            command_trigger="CMD_PAPER_DEPLOY",
            failure_trigger_prefix="PAPER_PIPELINE_FAIL",
            reset_portfolio_consumption=True,
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
        if self._kill_switch is not None and observe_kill_switch(self._kill_switch.is_active):
            logger.warning(
                "recover_from_degraded: refused — kill switch is still active",
            )
            return False
        if _verify_data_integrity(self):
            self._macro.transition(
                MacroState.READY,
                trigger="RECOVERY_VALIDATED",
            )
            return True
        return False

    def unlock_from_lockdown(self, *, audit_token: str) -> None:
        """Unlock only with an audit token and zero exposure.

        The kill switch resets before the risk and macro state machines."""
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
        if self._kill_switch is not None and observe_kill_switch(self._kill_switch.is_active):
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
        """Drain terminal acknowledgements, flush metrics, and enter SHUTDOWN."""
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
        _checkpoint_feature_snapshots(self)
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
            self._publish_alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id="",
                severity=AlertSeverity.WARNING,
                alert_name="pending_orders_at_shutdown",
                message=f"Inv-4 violation: {len(pending)} order(s) not terminally resolved at shutdown",
                context={"order_ids": pending},
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
        """Dispatch backend events through the single mode-independent pipeline.

        Idle ticks drain asynchronous acknowledgements without walking the micro state machine."""
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
        """Process one trade with fail-safe degradation on error."""
        self._process_trade_inner(trade)

    def _process_trade_inner(self, trade: Trade) -> None:
        """Log and publish one trade, then drive trade-sensitive layers."""
        # Update halt state before applying the data-health gate.
        _update_halt_state(self, trade)
        # Update intraday SSR state from the trade tape.
        _update_ssr_state(self, trade)

        trade_block_reason = _data_health_blocks_trading(self, trade.symbol, trade.correlation_id)
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

        # Trades may cross horizons only after a quote has published regime state.
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
        """Record CROSS_SECTIONAL when a horizon boundary was processed."""
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
        quote: NBBOQuote | None = None,
    ) -> None:
        """Drain horizon-buffered PORTFOLIO intents under micro M5–M10 before M3.

        *quote* is the tick that triggered the flush. It is what lets the B4
        edge/cost gate price a leg; without it the gate cannot run and opening
        legs are refused fail-safe (Inv-11).
        """
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
                        quote=quote,
                    )
                    while self._pending_sized_intents:
                        nxt = self._pending_sized_intents.popleft()
                        self._submit_portfolio_leg_without_micro_walk(
                            nxt,
                            correlation_id,
                            quote=quote,
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
                _escalate_risk(self, correlation_id)
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

            orders = _filter_portfolio_orders_for_admission(self,
                orders,
                intent=intent,
                correlation_id=correlation_id,
                quote=quote,
            )
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
                _transition_order(self,
                    order.order_id,
                    OrderState.SUBMITTED,
                    "submitted",
                )
                self._submit_to_router(order, triggering_quote=self._in_flight_quote)
                self._bus.publish(order)

            self._micro.transition(
                MicroState.ORDER_ACK,
                trigger="portfolio_poll_acks",
                correlation_id=correlation_id,
            )
            self._settle_router_acks(
                correlation_id,
                expected_order_ids={o.order_id for o in orders},
                position_update_trigger="portfolio_reconcile",
            )

            self._micro.transition(
                MicroState.LOG_AND_METRICS,
                trigger="portfolio_leg_complete",
                correlation_id=correlation_id,
            )

    def _submit_portfolio_leg_without_micro_walk(
        self,
        intent: SizedPositionIntent,
        correlation_id: str,
        *,
        quote: NBBOQuote | None = None,
    ) -> None:
        """Fail-safe submit when micro cannot enter ``RISK_CHECK`` (should be rare)."""
        sized = self._risk_engine.check_sized_intent(intent, self._positions)
        if sized.requires_global_risk_escalation:
            _escalate_risk(self, correlation_id)
            return
        orders: list[OrderRequest] = list(sized.orders)
        if not orders:
            return
        orders = _filter_portfolio_orders_for_admission(self,
            orders,
            intent=intent,
            correlation_id=correlation_id,
            quote=quote,
        )
        orders = self._filter_portfolio_orders_for_pending_conflicts(
            orders,
            intent=intent,
            correlation_id=correlation_id,
        )
        if not orders:
            return
        for order in orders:
            self._track_order(order.order_id, order.side, order)
            _transition_order(self,
                order.order_id,
                OrderState.SUBMITTED,
                "submitted",
            )
            self._submit_to_router(order, triggering_quote=self._in_flight_quote)
            self._bus.publish(order)
        self._settle_router_acks(
            correlation_id,
            expected_order_ids={o.order_id for o in orders},
        )

    def _process_tick(self, quote: NBBOQuote) -> None:
        """Process one quote through the deterministic micro-state path.

        Any exception degrades the macro state and restores the micro machine to M0."""
        cid = quote.correlation_id
        self._quote_tick_in_flight = True; self._in_flight_quote = quote
        try:
            self._process_tick_inner(quote)
        except Exception as exc:
            self._handle_tick_failure(cid, exc)
        finally:
            self._quote_tick_in_flight = False; self._in_flight_quote = None
            self._micro.bind_timing_sink(None)

    def _handle_tick_failure(self, cid: str, original: Exception) -> None:
        """Recover state machines after a tick-processing exception."""
        exc_name = type(original).__name__

        try:
            self.reset(
                trigger=f"pipeline_abort:{exc_name}",
                correlation_id=cid, for_new_run=False,
            )
            # pending-intent clear lives in reset, not beside it
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
        if self._kill_switch is not None and observe_kill_switch(self._kill_switch.is_active):
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
        quote_block_reason = _data_health_blocks_trading(self, quote.symbol, cid)
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
        # Mark before subscribers so risk exits see current liquidation value.
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

        # Sensor fan-out (+ router on_quote) runs synchronously inside
        # publish; time the call for hot-path attribution.
        t_pub = time.perf_counter_ns()
        self._bus.publish(quote)
        self._tick_timings["sensor_fanout_ns"] = time.perf_counter_ns() - t_pub
        # Use exchange time so risk and routing cross the RTH close together.
        _maybe_flip_buying_power_at_rth_close(self, quote)

        # Reconcile quote-triggered fills and cancels before evaluating signals.
        self._reconcile_resting_fills(cid)

        # ── M1 → M2: STATE_UPDATE ──────────────────────────────
        self._micro.transition(
            MicroState.STATE_UPDATE,
            trigger="event_logged",
            correlation_id=cid,
        )
        _update_regime(self, quote, cid)

        # Optional sensor and horizon stages.
        self._dispatch_sensor_layer(quote, cid)
        self._maybe_transition_cross_sectional_bookend(cid)
        self._flush_pending_sized_intents(correlation_id=cid, quote=quote)

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

        # Stop-loss and session flatten are authored by
        # :class:`~feelies.risk.stop_exit.StopExitController`, which fires off the
        # same quote publish above and routes through the RISK-layer bridge.  The
        # SIGNAL path carries alpha conviction only.
        self._trace_buffered_signals_arbitration(quote, buf_snapshot, signal)
        # Update standing targets and record winner-versus-net divergence.
        self._record_net_shadow(buf_snapshot, signal, quote)
        if buf_snapshot:
            for buffered in buf_snapshot:
                self._carryover_signal_sequences.discard(buffered.sequence)
            self._signal_buffer.clear()

        if signal is None:
            self._finalize_tick(t_wall_start, cid, "no_signal_this_tick")
            return

        # ── Position sizing: compute target quantity from risk budget ──
        target_qty = _compute_target_quantity(self, signal, quote)
        self._record_size_shadow(signal, quote)

        # ── Decision: Signal × Position → OrderIntent ──────────────────
        # Use the planner when driving; otherwise translate the signal directly.
        current_position = self._positions.get(signal.symbol)
        # Only discretionary trims override the builder's execution style.
        exec_style_override: ExecStyle | None = None
        if self._position_manager is not None:
            # With portfolio netting, the winner selects the symbol and the
            # budget-weighted net target selects its position.
            decision_signal = signal
            if self._enable_portfolio_netting:
                net_desired = self._portfolio_netter.net(
                    signal.symbol,
                    int(quote.timestamp_ns),
                )
                plan = _plan_for_signal(self,
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
                plan = _plan_for_signal(self,
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
            # No planner wired (minimal test doubles); translate directly.
            intent = self._intent_translator.translate(
                signal,
                current_position,
                target_qty,
            )

        if intent.intent == TradingIntent.NO_ACTION:
            reasons_no: list[str] = [
                "intent_translator_no_action",
                f"intent_enum={intent.intent.name}",
                f"current_position_qty={intent.current_quantity}",
            ]
            if target_qty == 0:
                reasons_no.insert(0, "position_sizer_returned_zero_target_quantity")
            self._finish_no_order(
                quote,
                signal,
                intent,
                t_wall_start,
                cid,
                reasons_no,
                "intent_no_action",
            )
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
        # Backtests simulate flatten because RISK_LOCKDOWN exists only in PAPER.
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
                _escalate_risk(self, cid)
                self._micro.reset(
                    trigger="pipeline_abort:risk_lockdown",
                    correlation_id=cid,
                )
                return
            self._finish_no_order(
                quote,
                signal,
                intent,
                t_wall_start,
                cid,
                ("risk_check_signal_force_flatten_simulated", verdict.reason),
                "risk_force_flatten_simulated",
            )
            return

        # ── M5 branch: risk rejected → M10 ─────────────────────
        if verdict.action == RiskAction.REJECT:
            self._finish_no_order(
                quote,
                signal,
                intent,
                t_wall_start,
                cid,
                ("risk_check_signal_reject", verdict.reason),
                "risk_reject_no_order",
            )
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

        # Session, halt, and Reg-SHO admission — one shared policy with the
        # PORTFOLIO path (`feelies.execution.order_admission`).  This path
        # answers "does it open exposure?" from the intent matrix; composition
        # answers it from the leg's exposure delta.  Quantity is withheld here
        # because risk scaling has not been applied yet; the minimum-size gate
        # runs in `_try_build_order_from_intent` off the same predicate.
        delta = exposure_delta_from_intent(intent)
        block = admission_block_reason(
            opens_exposure=delta.opens_or_increases_exposure,
            opens_short=delta.opens_or_increases_short,
            in_halt_blackout=self._in_halt_blackout(intent.symbol, quote.timestamp_ns),
            in_session_flatten_window=self._in_session_flatten_window(quote),
            ssr_active=intent.symbol.upper() in self._ssr_active,
            locate_unavailable=(self._borrow_tier_for(intent.symbol) == BorrowTier.UNAVAILABLE),
        )
        if block is not None:
            # Alerts are per-gate forensic markers, not part of the decision.
            if block == BLOCK_SSR:
                self._emit_ssr_suppression_alert(intent, cid)
            elif block == BLOCK_LOCATE_UNAVAILABLE:
                self._emit_locate_unavailable_alert(intent, cid)
            self._finish_no_order(
                quote,
                signal,
                intent,
                t_wall_start,
                cid,
                (block, f"symbol={intent.symbol}"),
                block,
            )
            return

        # Reversals close at market before opening through the entry policy.
        if intent.intent in (
            TradingIntent.REVERSE_LONG_TO_SHORT,
            TradingIntent.REVERSE_SHORT_TO_LONG,
        ):
            _execute_reverse(self, intent, verdict, cid, quote, t_wall_start)
            return

        order, order_build_reason = _try_build_order_from_intent(self,
            intent,
            verdict,
            cid,
            quote,
            exec_style=exec_style_override,
        )
        if order is None:
            self._finish_no_order(
                quote,
                signal,
                intent,
                t_wall_start,
                cid,
                ("order_request_build_failed", order_build_reason or "unknown"),
                "risk_scale_down_to_zero",
            )
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
                _escalate_risk(self, cid)
                self._micro.reset(
                    trigger="pipeline_abort:check_order_lockdown",
                    correlation_id=cid,
                )
                return
            self._finish_no_order(
                quote,
                signal,
                intent,
                t_wall_start,
                cid,
                ("risk_check_order_force_flatten_simulated", order_verdict.reason),
                "check_order_force_flatten_simulated",
            )
            return

        if order_verdict.action == RiskAction.REJECT:
            self._finish_no_order(
                quote,
                signal,
                intent,
                t_wall_start,
                cid,
                ("risk_check_order_reject", order_verdict.reason),
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
                self._finish_no_order(
                    quote,
                    signal,
                    intent,
                    t_wall_start,
                    cid,
                    (
                        "risk_check_order_scale_down_to_zero_quantity",
                        order_verdict.reason,
                    ),
                    "check_order_scale_down_to_zero",
                )
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

        # Suppress duplicates while an order is pending.  Mandated exits are no
        # longer authored here — they arrive on the bus and supersede resting
        # orders inside ``_on_bus_derisk_requirement`` — so this path only ever blocks;
        # it never cancels, and therefore has no cancel-then-submit window in
        # which the book could move under an already-built order.
        if self._has_pending_order_for_symbol(order.symbol):
            if intent.intent != TradingIntent.EXIT or self._has_pending_exit_for_symbol(
                order.symbol
            ):
                self._finish_no_order(
                    quote,
                    signal,
                    intent,
                    t_wall_start,
                    cid,
                    (
                        "resting_order_guard_blocked_duplicate_passive_order",
                        f"symbol={order.symbol}",
                    ),
                    "resting_order_pending",
                )
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
        # ── M8 → M9: POSITION_UPDATE ───────────────────────────
        self._settle_router_acks(
            cid,
            expected_order_ids={order.order_id},
            position_update_trigger="order_acknowledged",
        )

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
        if self._config is not None and self._config.mode is not OperatingMode.BACKTEST:
            samples: dict[str, int] = {str(k): int(v) for k, v in timings.items()}
            samples["tick_to_decision_latency_ns"] = latency_ns
            for breach in self._latency_monitor.observe(
                samples,
                timestamp_ns=now_ns,
                correlation_id=correlation_id,
            ):
                self._bus.publish(breach)
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
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            severity=AlertSeverity.WARNING,
            alert_name="signal_edge_below_min_edge_cost_ratio_gate",
            message=f"Order suppressed: signal.edge_estimate_bps below {self._signal_min_edge_cost_ratio}× round-trip cost ({detail}; strategy_id={signal.strategy_id!r}, symbol={symbol!r}).",
            context={
                "detail": detail,
                "strategy_id": signal.strategy_id,
                "symbol": symbol,
                "edge_estimate_bps": signal.edge_estimate_bps,
                "signal_min_edge_cost_ratio": self._signal_min_edge_cost_ratio,
            },
        )

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
        """Reset stateful regime components at a session boundary.

        Missing reset hooks fail closed when the engine declares persistent state."""
        self._last_regime_state.clear()
        self._regime_bus_published_symbols.clear()
        if self._regime_hazard_detector is not None:
            self._regime_hazard_detector.reset()

    def _in_session_flatten_window(self, quote: NBBOQuote) -> bool:
        """True once the quote crosses the session-flatten deadline.

        Gates entry suppression on the SIGNAL path.  Shares one deadline with
        the end-of-session flatten emission so the two can never disagree about
        when the window opens.
        """
        return self._in_session_flatten_window_at(quote.exchange_timestamp_ns)

    def _in_session_flatten_window_at(self, at_ns: int) -> bool:
        """Event-time form of :meth:`_in_session_flatten_window`.

        The PORTFOLIO path admits legs outside a quote callback, so it carries
        the boundary's own event time rather than a quote (Inv-10: no wall
        clock on the decision path).
        """
        return in_session_flatten_window(
            self._trading_session_bounds,
            enabled=self._session_flatten_enabled,
            seconds_before_close=self._session_flatten_seconds_before_close,
            at_ns=at_ns,
        )

    def _record_size_shadow(self, signal: Signal, quote: NBBOQuote) -> None:
        """Compare the edge/vol/inventory-tilted target with the base.

        For each real sized signal, compute the tilted target and append a
        :class:`SizeDivergence` when it differs from the live single-factor
        base target. It runs before the risk engine and has no order, bus,
        journal, or parity effects. It is a no-op unless a sink is wired and at
        least one tilt factor is enabled.
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
            tq = _compute_target_quantity(self, sig, quote)
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
                _compute_target_quantity(self, sig, quote),
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

    @staticmethod
    def _compose_scaled_quantity(base_quantity: int, *factors: float) -> int:
        """Apply the tightest risk cap exactly once to ``base_quantity``."""
        capped = min(max(0.0, min(1.0, factor)) for factor in factors)
        return round(base_quantity * capped)

    @staticmethod
    def _side_from_intent(intent: OrderIntent) -> Side:
        """Derive order Side from TradingIntent (see ``side_for_intent``)."""
        return side_for_intent(intent)

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
            self._publish_alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=order.correlation_id,
                severity=AlertSeverity.WARNING,
                alert_name="cancel_order_router_unsupported",
                message=f"cancel_order requested for {order_id!r} but {type(self._backend.order_router).__name__} has no cancel_order(...) — resolving SM to CANCELLED locally (Inv-4 shutdown hygiene).",
                context={"order_id": order_id},
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
        self._settle_router_acks(order.correlation_id, expected_order_ids={order_id})
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

    def _portfolio_leg_edge_block(
        self,
        order: OrderRequest,
        *,
        intent: SizedPositionIntent,
        delta: ExposureDelta,
        quote: NBBOQuote | None,
    ) -> str | None:
        """Inv-12 B4 for a PORTFOLIO leg, or ``None`` to admit.

        Reducing legs are never gated: a cost bar may suppress an entry, never
        an unwind (Inv-11), which is the same carve-out the SIGNAL path makes
        for exits.

        Without a quote the gate cannot be priced at all -- the round-trip cost
        model needs a live spread. An opening leg is then refused rather than
        waved through: this is the out-of-tick submit path, and "cannot verify
        the economics" resolves to less exposure, not more.  The flush carries
        one quote (the tick that triggered it), but a PORTFOLIO intent is
        cross-sectional and routinely spans symbols, so a quote for a different
        symbol is treated as no quote: pricing a leg off another name's spread,
        mid and L1 sizes would make the capital decision non-symbol-local.

        The leg's edge is ``TargetPosition.expected_edge_bps``, carried from the
        ranker because the composition weights are z-scores and no longer in bps.
        A leg with no disclosed edge cannot clear a positive cost bar, so 0.0
        fails closed on its own.
        """
        if not delta.opens_or_increases_exposure:
            return None
        if self._signal_min_edge_cost_ratio <= 0 or self._cost_model is None:
            # Gate disarmed by configuration: there is nothing to price, so a
            # missing quote is not a refusal. Checking the quote first would
            # suppress every opening leg on deployments that never enabled B4.
            return None
        if quote is None or quote.symbol != order.symbol:
            return record_verdict("RT.COST_GATE", "FAIL", BLOCK_EDGE_UNPRICEABLE) or BLOCK_EDGE_UNPRICEABLE
        target = intent.target_positions.get(order.symbol)
        edge_bps = target.expected_edge_bps if target is not None else 0.0
        passes, effective_bps, factor = _edge_clears_round_trip_cost(self,
            strategy_id=intent.strategy_id,
            edge_estimate_bps=edge_bps,
            symbol=order.symbol,
            entry_side=order.side,
            quantity=order.quantity,
            quote=quote,
            is_taker_entry=order.order_type is OrderType.MARKET,
            is_short_entry=delta.opens_or_increases_short,
        )
        if passes:
            return record_verdict("RT.COST_GATE", "PASS") or None
        logger.debug(
            "PORTFOLIO leg %s %s %d refused by B4: disclosed %.2f bps x "
            "realization %.3f = %.2f effective (strategy=%s)",
            order.symbol,
            order.side.name,
            order.quantity,
            edge_bps,
            factor,
            effective_bps,
            intent.strategy_id,
        )
        return record_verdict("RT.COST_GATE", "FAIL", BLOCK_EDGE_BELOW_COST) or BLOCK_EDGE_BELOW_COST

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
        bypass this path via :meth:`_on_bus_derisk_requirement` (Inv-11).
        """
        filtered: list[OrderRequest] = []
        for order in orders:
            if self._has_pending_order_for_symbol(order.symbol) and not record_verdict("RT.DUPLICATE_INTENT", "FAIL", order.order_id):
                self._publish_alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=correlation_id,
                    severity=AlertSeverity.WARNING,
                    alert_name="portfolio_leg_skipped_pending_order",
                    message=f"PORTFOLIO leg skipped: pending order on {order.symbol!r} (order_id={order.order_id!r}, strategy={intent.strategy_id!r})",
                    context={
                        "order_id": order.order_id,
                        "symbol": order.symbol,
                        "strategy_id": intent.strategy_id,
                    },
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

    def _forced_exit_reduces(self, order: OrderRequest) -> bool:
        """Whether *order* shrinks the live book it claims to close.

        A composer or deferral-cap exit is slice-scoped: another strategy holding
        the opposite side can leave symbol-net flat while the mandated slice is
        still open.  Treat the order as reducing when it shrinks *either* the
        symbol-net book or its own strategy slice, so a slice flatten is never
        stranded at the non-reducing REJECT branch.  Symbol-net is checked first,
        so a true symbol-net hazard exit (which always reduces net) never needs the
        slice fallback — this keeps the shared ``HARD_EXIT_AGE`` token correct for
        both authors without attributing it.

        Re-evaluated after any resting-order cancel, because the cancel reconciles
        whatever acks were already queued for those orders — including fills — so
        the book can move between the controller sizing the exit and the exit
        reaching the router.
        """
        return self._forced_exit_closable_quantity(order) > 0

    def _forced_exit_closable_quantity(self, order: OrderRequest) -> int:
        """Shares *order* can close right now without crossing into new exposure.

        Magnitude shrinkage is **not** the test.  ``abs(current + signed) <
        abs(current)`` is true for any reduction, including one that crosses zero:
        a mandated ``SELL 100`` into a book a resting cover has already taken to
        long 70 shrinks the magnitude while flipping to short 30.  That is a
        fail-safe control opening exposure, which is exactly what Inv-11 forbids,
        so the clamp is on the closable side only.

        Slice-scoped authors (composer, deferral cap) may legitimately exceed
        symbol-net: another strategy holding the opposite side can leave the net
        flat while the mandated slice is still open, and flattening that slice
        moves the net through zero on purpose (design §3.3).  So they take the
        larger of the two bases rather than being clamped to net.
        """
        net = self._positions.get(order.symbol).quantity
        closable = _closable_quantity(net, order.side)
        if order.reason in _SLICE_SCOPED_FORCED_EXIT_REASONS and (
            self._strategy_positions is not None
        ):
            slice_qty = self._strategy_positions.get(order.strategy_id, order.symbol).quantity
            closable = max(closable, _closable_quantity(slice_qty, order.side))
        return min(order.quantity, closable)

    def _has_pending_forced_exit_for_symbol(self, symbol: str) -> bool:
        """True if a forced MARKET exit is already in flight for *symbol*.

        Distinguishes an aggressive exit already crossing the book from a
        merely-resting passive cover.  The resting-order guard cancels stale
        passive orders to let a forced MARKET exit through (Inv-11) but must
        not stack a second aggressive leg on top of one already pending —
        that would overshoot the position.

        Covers both mandated-exit authors — the kernel's synthetic stop /
        session-flat and the RISK-layer controllers routed through
        :meth:`_on_bus_derisk_requirement` — so neither can stack on the other.
        """
        return any(
            order.symbol == symbol
            and sm.state not in _TERMINAL_ORDER_STATES
            and _is_forced_market_exit(order)
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
        self._settle_router_acks(cid, expected_order_ids=cancel_order_ids)

    def _settle_router_acks(
        self,
        correlation_id: str,
        *,
        expected_order_ids: set[str] | None = None,
        position_update_trigger: str | None = None,
    ) -> list[OrderAck]:
        """Poll and reconcile acknowledgements for one submission phase.

        Expected orders without an ack remain active for later asynchronous drains."""
        acks = self._poll_order_router_acks(expected_order_ids)
        self._publish_and_apply_order_acks(acks)
        if position_update_trigger is not None:
            self._micro.transition(
                MicroState.POSITION_UPDATE,
                trigger=position_update_trigger,
                correlation_id=correlation_id,
            )
        self._reconcile_fills(acks, correlation_id)
        return acks

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
        _transition_order(self,
            order.order_id,
            OrderState.SUBMITTED,
            trigger,
            correlation_id=order.correlation_id,
        )
        try:
            self._submit_to_router(order, triggering_quote=self._in_flight_quote)
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
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=order.correlation_id,
            severity=AlertSeverity.WARNING,
            alert_name="order_submit_failed",
            message=f"order_router.submit raised for order_id={order.order_id!r} symbol={order.symbol!r}: {exc!r}",
            context={
                "order_id": order.order_id,
                "symbol": order.symbol,
                "exc_type": type(exc).__name__,
            },
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
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=order.correlation_id,
            severity=AlertSeverity.WARNING,
            alert_name="order_pipeline_exception",
            message=f"{context}: pipeline failed after submit for order_id={order.order_id!r} symbol={order.symbol!r}: {exc!r}",
            context={
                "order_id": order.order_id,
                "symbol": order.symbol,
                "context": context,
                "exc_type": type(exc).__name__,
            },
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
        """Apply broker acknowledgements received outside the quote submission path.

        This path updates order state and positions without walking the micro machine."""
        t0 = time.perf_counter_ns()
        acks = self._settle_router_acks(correlation_id)
        if acks:
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

    def reset(
        self,
        trigger: str = "reset",
        correlation_id: str = "",
        *,
        for_new_run: bool = True,
    ) -> None:
        """Restore run-scoped state to post-``__init__`` so a second run can boot.

        Bus subscriptions and attach flags stay: the bus cannot unsubscribe.
        Durable stores (submitted-order journal) are not cleared.
        ``for_new_run=False`` is in-session tick recovery: micro reset plus
        pending-intent clear only. Macro stays in the live trading mode so
        DEGRADED can still fire; the book and router maps are not wiped.
        """

        if not for_new_run:
            self._micro.reset(trigger=trigger, correlation_id=correlation_id)
            self._pending_sized_intents.clear()
            return

        def _maybe_reset(obj: object) -> None:
            reset = getattr(obj, "reset", None)
            if callable(reset):
                reset()

        skip = frozenset(
            {"DurableSubmittedOrderJournal", "IBGatewayConnection", "MassiveLiveFeed"}
        )
        _maybe_reset(self._clock)
        _maybe_reset(self._risk_engine)
        _maybe_reset(self._positions)
        _maybe_reset(self._metrics)
        _maybe_reset(self._normalizer)
        _maybe_reset(self._sensor_registry)
        _maybe_reset(self._horizon_scheduler)
        _maybe_reset(self._horizon_signal_engine)
        _maybe_reset(self._composition_engine)
        _maybe_reset(self._hazard_exit_controller)
        _maybe_reset(self._alpha_registry)
        _maybe_reset(getattr(self._backend, "order_router", None))
        _maybe_reset(self._fill_ledger)
        self._bus.reset()

        self._paper_session_recorder = None
        self._quote_tick_in_flight = False
        self._in_flight_quote = None
        self._tick_quote_for_trace = None
        self._last_quote_context_for_signal_trace = None
        self._signal_order_trace_seen_sequences.clear()
        self._carryover_signal_sequences.clear()
        self._last_regime_state.clear()
        self._regime_bus_published_symbols.clear()
        self._realized_cost_breach_streak.clear()
        self._active_orders.clear()
        self._order_trading_intent.clear()
        self._forced_exit_announced_quantity.clear()
        self._last_signal_mechanism.clear()
        self._working_exit_fallback.clear()
        self._order_filled_qty.clear()
        self._deferred_router_acks.clear()
        self._events_prelogged = False
        self._pipeline_abort_requested = False
        self._halted_symbols.clear()
        self._halt_blackout_until_ns.clear()
        self._ssr_active.clear()
        self._rth_close_bp_flipped = False
        self._rth_bp_session_date = None
        self._latency_reduce_only = False
        self._signal_buffer.clear()
        self._alpha_symbols_with_fills.clear()
        self._arbitration_collisions.clear()
        self._pending_sized_intents.clear()
        self._consumed_by_portfolio_ids = None
        self._warned_multi_standalone_signals = False
        self._logged_harmless_arbitration_collision = False
        self._hazard_submitted_order_ids.clear()
        self._net_shadow_transient_keys.clear()
        self._lot_ledger = LotLedger()
        self._desired_target_book = DesiredTargetBook()
        self._portfolio_netter = PortfolioNetter(
            self._desired_target_book,
            portfolio_max_abs_qty=self._net_portfolio_max_abs_qty,
        )
        self._market_context = MarketContext()
        self._latency_monitor = _LatencyBudgetMonitor()

        seen = {id(self)}
        groups = list(self._bus._handlers.values())
        groups.append(self._bus._global_handlers)
        for group in groups:
            for handler in group:
                owner = getattr(handler, "__self__", None)
                if owner is None or id(owner) in seen:
                    continue
                seen.add(id(owner))
                if type(owner).__name__ in skip:
                    continue
                _maybe_reset(owner)

        self._macro.reset(trigger=trigger, correlation_id=correlation_id)
        self._micro.reset(trigger=trigger, correlation_id=correlation_id)
        self._risk_escalation.reset(trigger=trigger, correlation_id=correlation_id)
        self._seq.reset()
        self._hazard_seq.reset()
        _maybe_reset(self._clock)

    def _submit_to_router(
        self,
        order: OrderRequest,
        triggering_quote: NBBOQuote | None = None,
    ) -> None:
        self._backend.order_router.submit(order, triggering_quote=triggering_quote)

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
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            severity=AlertSeverity.INFO,
            alert_name="working_exit_market_fallback",
            message=f"Working reduction did not fill passively; escalating {quantity} {side.name} {symbol} to MARKET (parent_order_id={parent_order_id}).",
            context={
                "symbol": symbol,
                "side": side.name,
                "quantity": quantity,
                "parent_order_id": parent_order_id,
                "fallback_order_id": order_id,
            },
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
        self._record_fill_attribution(order_id, side, order)

    def _record_fill_attribution(
        self,
        order_id: str,
        side: Side,
        order: OrderRequest,
    ) -> None:
        """Record deterministic strategy allocations for an order.

        Single-slice orders self-attribute; symbol-net exits allocate across live slices."""
        if self._fill_ledger is None or not _order_owns_one_slice(order):
            return
        from feelies.portfolio.fill_attribution import AlphaContribution, AttributionRecord

        self._fill_ledger.record(
            AttributionRecord(
                order_id=order_id,
                symbol=order.symbol,
                net_side=side,
                net_quantity=order.quantity,
                contributions=(
                    AlphaContribution(
                        strategy_id=order.strategy_id,
                        signed_quantity=order.quantity,
                        proportion=1.0,
                    ),
                ),
            )
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
            self._publish_alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=cid,
                severity=AlertSeverity.WARNING,
                alert_name="ack_for_unknown_order",
                message=f"Ack for unknown order_id={ack.order_id}, status={ack.status.name}",
                context={"order_id": ack.order_id, "status": ack.status.name},
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
                self._publish_alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=cid,
                    severity=AlertSeverity.WARNING,
                    alert_name="duplicate_terminal_fill_ack",
                    message=f"Ignoring duplicate FILLED ack for order_id={ack.order_id} (already terminal FILLED).",
                    context={"order_id": ack.order_id},
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
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=ack.correlation_id,
            severity=AlertSeverity.WARNING,
            alert_name="ack_inapplicable_to_order_state",
            message=f"Ack status={ack.status.name} cannot be applied to order {ack.order_id} in state {sm.state.name}",
            context={
                "order_id": ack.order_id,
                "ack_status": ack.status.name,
                "order_state": sm.state.name,
            },
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
                    self._publish_alert(
                        timestamp_ns=self._clock.now_ns(),
                        correlation_id=correlation_id,
                        severity=AlertSeverity.WARNING,
                        alert_name="fill_ack_missing_price_or_quantity",
                        message=f"{ack.status.name} ack missing economics (order_id={ack.order_id!r}, symbol={ack.symbol!r}, filled_quantity={ack.filled_quantity}, fill_price={ack.fill_price!r}).",
                        context={
                            "order_id": ack.order_id,
                            "symbol": ack.symbol,
                            "status": ack.status.name,
                            "filled_quantity": ack.filled_quantity,
                            "fill_price": str(ack.fill_price),
                        },
                    )
                    continue
            else:
                fill_like = ack.fill_price is not None and ack.filled_quantity > 0
                if fill_like:
                    self._publish_alert(
                        timestamp_ns=self._clock.now_ns(),
                        correlation_id=correlation_id,
                        severity=AlertSeverity.WARNING,
                        alert_name="fill_payload_inconsistent_with_ack_status",
                        message=f"Ignoring fill-like payload on {ack.status.name} ack (order_id={ack.order_id!r}, symbol={ack.symbol!r}).",
                        context={
                            "order_id": ack.order_id,
                            "symbol": ack.symbol,
                            "status": ack.status.name,
                            "filled_quantity": ack.filled_quantity,
                            "fill_price": str(ack.fill_price),
                        },
                    )
                continue

            if ack.order_id not in self._active_orders:
                self._publish_alert(
                    timestamp_ns=self._clock.now_ns(),
                    correlation_id=correlation_id,
                    severity=AlertSeverity.WARNING,
                    alert_name="fill_for_unknown_order",
                    message=f"Fill for unknown order_id={ack.order_id}, symbol={ack.symbol}, qty={ack.filled_quantity}, price={ack.fill_price}. Rejected: cannot determine side (Inv-11 fail-safe).",
                    context={
                        "order_id": ack.order_id,
                        "symbol": ack.symbol,
                        "filled_quantity": ack.filled_quantity,
                        "fill_price": str(ack.fill_price),
                    },
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

            # Feed the PDT counter when the risk engine supports it.
            record_fill = getattr(self._risk_engine, "record_fill", None)
            if callable(record_fill):
                record_fill(
                    ack.symbol,
                    prev_qty,
                    position.quantity,
                    ack.timestamp_ns,
                )

            # Record per-slice fees and realized PnL for journal attribution.
            attributed_legs: list[tuple[str, int, Decimal, Decimal]] = []
            if self._strategy_positions is not None:
                alpha_allocs: list[tuple[str, str, int, Decimal, Decimal]] = []
                if self._fill_ledger is not None:
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
                        prev_slice = self._strategy_positions.get(strat_id, sym).realized_pnl
                        slice_position = self._strategy_positions.update(
                            strat_id,
                            sym,
                            alpha_signed,
                            price,
                            fees=alloc_fees,
                            timestamp_ns=ack.timestamp_ns,
                        )
                        attributed_legs.append(
                            (
                                strat_id,
                                alpha_signed,
                                alloc_fees,
                                slice_position.realized_pnl - prev_slice,
                            )
                        )
                elif _order_owns_one_slice(order):
                    # Missing ledger data still self-attributes single-slice orders.
                    prev_slice = self._strategy_positions.get(
                        order.strategy_id, ack.symbol
                    ).realized_pnl
                    slice_position = self._strategy_positions.update(
                        order.strategy_id,
                        ack.symbol,
                        signed_qty,
                        ack.fill_price,
                        fees=ack.fees,
                        timestamp_ns=ack.timestamp_ns,
                    )
                    attributed_legs = [
                        (
                            order.strategy_id,
                            signed_qty,
                            ack.fees,
                            slice_position.realized_pnl - prev_slice,
                        )
                    ]
                else:
                    # Without attribution, split proportionally to keep stores in
                    # sync. Aggregate PnL stays exact; per-alpha PnL is estimated.
                    attributed_legs = self._distribute_fill_to_strategies(
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
                    self._publish_alert(
                        timestamp_ns=self._clock.now_ns(),
                        correlation_id=correlation_id,
                        severity=severity,
                        alert_name="g12_realized_cost_exceeds_disclosure",
                        message=f"Fill cost_bps={float(ack.cost_bps):.4f} exceeds {alert_ratio}× G12 disclosed one-way cost_total_bps={disclosed:.4f} (strategy_id={order.strategy_id!r}, symbol={ack.symbol!r}, order_id={ack.order_id!r}, streak={streak})",
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
                    if (
                        escalate
                        and self._kill_switch is not None
                        and not observe_kill_switch(self._kill_switch.is_active)
                    ):
                        self._kill_switch.activate(
                            reason="realized_cost_persistent_overrun",
                            activated_by="orchestrator",
                        )

            if self._trade_journal is not None:
                for leg in _trade_journal_legs(
                    order,
                    filled_quantity=ack.filled_quantity,
                    fees=ack.fees,
                    realized_pnl=position.realized_pnl - prev_realized,
                    attributed_legs=attributed_legs,
                    announced_quantity=self._forced_exit_announced_quantity.get(ack.order_id),
                ):
                    _trade_mech, _trade_hl = self._last_signal_mechanism.get(
                        (leg.strategy_id, ack.symbol),
                        (None, 0),
                    )
                    self._trade_journal.record(
                        TradeRecord(
                            order_id=ack.order_id,
                            symbol=ack.symbol,
                            strategy_id=leg.strategy_id,
                            side=side,
                            requested_quantity=order.quantity,
                            filled_quantity=leg.filled_quantity,
                            fill_price=ack.fill_price,
                            signal_timestamp_ns=order.timestamp_ns,
                            submit_timestamp_ns=order.timestamp_ns,
                            fill_timestamp_ns=ack.timestamp_ns,
                            cost_bps=ack.cost_bps,
                            fees=leg.fees,
                            realized_pnl=leg.realized_pnl,
                            correlation_id=order.correlation_id,
                            trading_intent=self._order_trading_intent.get(
                                ack.order_id,
                                "",
                            ),
                            trend_mechanism=_trade_mech,
                            expected_half_life_seconds=_trade_hl,
                            regime_state=_regime_label_for(self, ack.symbol),
                            # Preserve forced-exit class and producing layer on the
                            # trade; ``forced_exit_strategy_id`` keeps the synthetic
                            # author recoverable now that ``strategy_id`` names the
                            # slice the exit closed (Inv-13).
                            metadata=leg.metadata,
                        )
                    )
            if order.strategy_id:
                self._alpha_symbols_with_fills.add((order.strategy_id, ack.symbol))

        self._prune_terminal_orders()

    def _distribute_fill_to_strategies(
        self,
        symbol: str,
        signed_qty: int,
        fill_price: Decimal,
        fees: Decimal,
        timestamp_ns: int,
    ) -> list[tuple[str, int, Decimal, Decimal]]:
        """Distribute a fill proportionally across per-alpha strategy positions.

        Used when no fill-attribution record exists (emergency flatten,
        stop exit, or attribution failure).  Distributes ``signed_qty``
        proportionally to each strategy's current quantity for this
        symbol, keeping global and strategy position stores in sync.

        Uses largest-remainder rounding so the sum of per-alpha deltas
        equals ``signed_qty`` exactly.

        Returns the ``(strategy_id, signed_quantity, fees, realized_delta)`` legs it
        applied — ``realized_delta`` measured around each slice's own update, so the
        caller can journal a symbol-net forced exit against the slices it actually
        closed instead of the synthetic order's ``strategy_id`` (Inv-13).  Empty when
        no slice book is wired or no strategy holds the symbol.
        """
        if self._strategy_positions is None:
            return []

        # Inv-5: iterate strategies in a deterministic (sorted) order.
        # ``strategy_ids()`` returns a ``frozenset``; materialising it directly
        # would make the largest-remainder tie-break and per-alpha fee split
        # depend on hash-iteration order (process/seed dependent).
        strategy_ids = sorted(self._strategy_positions.strategy_ids())
        if not strategy_ids:
            return []

        # Reducing fills allocate only across slices on the closable side.
        strategy_qtys: list[tuple[str, int]] = []
        for sid in strategy_ids:
            q = self._strategy_positions.get(sid, symbol).quantity
            if q * signed_qty < 0:
                strategy_qtys.append((sid, q))
        if not strategy_qtys:
            # Increasing fills fall back across holders; warn only on store drift.
            strategy_qtys = [
                (sid, q)
                for sid in strategy_ids
                if (q := self._strategy_positions.get(sid, symbol).quantity) != 0
            ]
            if strategy_qtys:
                slice_book_net = sum(q for _sid, q in strategy_qtys)
                symbol_net = self._positions.get(symbol).quantity
                if slice_book_net + signed_qty != symbol_net:
                    logger.warning(
                        "Fill attribution for %s: the slice book and the symbol-net "
                        "store have diverged (slices sum to %d, symbol-net %d after a "
                        "%d-share fill); falling back to a split across all %d holders.",
                        symbol,
                        slice_book_net,
                        symbol_net,
                        signed_qty,
                        len(strategy_qtys),
                    )
        if not strategy_qtys:
            return []

        # Same rounding and fee convention the ledger uses, so a fill rounds
        # identically whichever path attributes it.
        abs_fill = abs(signed_qty)
        alloc_qtys = largest_remainder_split(abs_fill, [abs(q) for _sid, q in strategy_qtys])
        alloc_fees = split_fees(fees, alloc_qtys)

        applied: list[tuple[str, int, Decimal, Decimal]] = []
        alloc_sign = 1 if signed_qty > 0 else -1
        for (sid, _q), alloc_qty, alloc_fee in zip(
            strategy_qtys, alloc_qtys, alloc_fees, strict=True
        ):
            if alloc_qty == 0:
                continue
            prev_slice = self._strategy_positions.get(sid, symbol).realized_pnl
            slice_position = self._strategy_positions.update(
                sid,
                symbol,
                alloc_sign * alloc_qty,
                fill_price,
                fees=alloc_fee,
                timestamp_ns=timestamp_ns,
            )
            applied.append(
                (
                    sid,
                    alloc_sign * alloc_qty,
                    alloc_fee,
                    slice_position.realized_pnl - prev_slice,
                )
            )

        return applied

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
            self._forced_exit_announced_quantity.pop(oid, None)

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

    def _on_latency_breach(self, event: LatencyBreach) -> None:
        """Reduce-only + kill-switch escalation from a recorded breach.

        Replay publishes the stored ``LatencyBreach``; this handler must not
        re-measure. ``LatencyBreach.sequence`` is 0 and this path does not
        draw ``self._seq``.
        """
        self._latency_reduce_only = True
        _apply_breach_response(self._kill_switch, event)

    def _on_alert_event(self, event: Event) -> None:
        """Forward Alert events from the bus to the AlertManager."""
        if isinstance(event, Alert) and self._alert_manager is not None:
            self._alert_manager.emit(event)

    # ── Bus-driven signal handler ───────────────────────────────────

    def _on_bus_signal(self, event: Event) -> None:
        """Buffer actionable standalone signals for the next M4 arbitration walk.

        Portfolio-consumed signals remain on their composition path."""
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
        """Select one deterministic standalone winner from the buffered signals."""
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
                        "no order impact.",
                        len(buf),
                        len(ids),
                        ids,
                    )
            elif not self._warned_multi_standalone_signals:
                self._warned_multi_standalone_signals = True
                logger.warning(
                    "orchestrator: %d standalone SIGNAL candidate(s) from %d "
                    "alpha id(s) fired on the same tick (%s); arbitrating via "
                    "%s — the winner takes the tick and the other alphas' "
                    "conviction is discarded, not blended.  Routing these ids "
                    "through a PORTFOLIO alpha's depends_on_signals would "
                    "aggregate rather than arbitrate, but that path is "
                    "unexercised on the cached corpus and its legs skip the "
                    "SSR, locate, halt-blackout, B4 edge/cost and "
                    "min-order-shares gates this one applies; it is not a "
                    "drop-in remedy.  See configs/bt_multialpha.yaml.",
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

    def _order_request_from_derisk(self, event: DeRiskRequirement) -> OrderRequest:
        """Copy the author's envelope and payload; fill MARKET. No sequence draw."""
        return OrderRequest(
            timestamp_ns=event.timestamp_ns,
            correlation_id=event.correlation_id,
            sequence=event.sequence,
            source_layer=event.source_layer,
            order_id=event.order_id,
            symbol=event.symbol,
            side=event.side,
            order_type=OrderType.MARKET,
            quantity=event.quantity,
            strategy_id=event.strategy_id,
            reason=event.reason,
        )

    def _on_bus_derisk_requirement(self, event: Event) -> None:
        """Submit non-vetoable risk-layer exits received as DeRiskRequirement.

        Sequence and order_id are the author's. The outbound OrderRequest is
        published with order_type=MARKET; the kernel does not draw self._seq.
        Orders are clamped to currently closable exposure and deduplicated."""
        if not isinstance(event, DeRiskRequirement):
            return
        if event.source_layer != HAZARD_EXIT_SOURCE_LAYER:
            return
        order = self._order_request_from_derisk(event)
        self._bus.publish(order)
        # Hazard IDs remain in a dedicated set after active orders are pruned.
        if order.order_id in self._hazard_submitted_order_ids:
            return
        self._hazard_submitted_order_ids.add(order.order_id)
        hv = self._risk_engine.check_order(order, self._positions)
        # Trust the exit fail-safe only when the order reduces live exposure.
        current_qty = self._positions.get(order.symbol).quantity
        order_reduces = self._forced_exit_reduces(order)
        # Do not broadcast FORCE_FLATTEN while this handler submits a local exit.
        if hv.action != RiskAction.FORCE_FLATTEN:
            self._bus.publish(hv)
        if hv.action == RiskAction.REJECT and not order_reduces:
            # Non-exit order carrying a hazard reason: REJECT is authoritative.
            self._publish_alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=order.correlation_id,
                severity=AlertSeverity.CRITICAL,
                alert_name="hazard_exit_nonreducing_reject_blocked",
                message=f"check_order returned REJECT on a hazard-tagged order that does not reduce the live position (strategy_id={order.strategy_id!r}, symbol={order.symbol!r}, current_qty={current_qty}, side={order.side.name}, order_qty={order.quantity}, reason={hv.reason!r}) — blocking submission (REJECT is authoritative for non-exit orders).",
                context={"order_id": order.order_id, "risk_reason": hv.reason},
            )
            return
        if hv.action == RiskAction.REJECT:
            self._publish_alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=order.correlation_id,
                severity=AlertSeverity.WARNING,
                alert_name="hazard_exit_defensive_check_order_reject",
                message=f"Defensive check_order returned REJECT on a hazard exit (strategy_id={order.strategy_id!r}, symbol={order.symbol!r}, reason={hv.reason!r}) — submitting anyway (Inv-11 exit fail-safe).",
                context={"order_id": order.order_id, "risk_reason": hv.reason},
            )
        # Resting-order guard, mirroring the SIGNAL path's forced-exit branch.
        # Deferred until here so an exit that ends up blocked above never cancels
        # a resting order without replacing it: cancelling a resting *cover* and
        # then bailing would leave the book more exposed, not less (Inv-11).
        if self._has_pending_order_for_symbol(order.symbol):
            if self._has_pending_forced_exit_for_symbol(order.symbol):
                # A mandated exit is already crossing; a second aggressive leg
                # would overshoot the position it is closing.
                logger.info(
                    "Forced exit already pending for %s; skipping duplicate "
                    "%s exit (order_id=%s, strategy_id=%s).",
                    order.symbol,
                    order.reason,
                    order.order_id,
                    order.strategy_id,
                )
                return
            self._emit_forced_exit_supersedes_pending_alert(order, order.correlation_id)
            self._cancel_resting_for_symbol(order.symbol, order.correlation_id)

        # Re-clamp after cancellations because queued fills may have moved the book.
        closable = self._forced_exit_closable_quantity(order)
        if closable <= 0:
            self._emit_forced_exit_stood_down_alert(order)
            return
        if closable < order.quantity:
            self._emit_forced_exit_resized_alert(order, closable)
            # Preserve announced size on the trade without republishing bus data.
            self._forced_exit_announced_quantity[order.order_id] = order.quantity
            order = replace(order, quantity=closable)
        self._track_order(order.order_id, order.side, order)
        submit_error = self._submit_tracked_order(order, trigger=order.reason)
        if submit_error is not None:
            logger.error(
                "Hazard exit order submission failed for %s "
                "(strategy_id=%s, reason=%s, order_id=%s); position "
                "remains open and will be retried on the next spike.",
                order.symbol,
                order.strategy_id,
                order.reason,
                order.order_id,
                exc_info=(
                    type(submit_error),
                    submit_error,
                    submit_error.__traceback__,
                ),
            )
            return
        self._settle_router_acks(order.correlation_id, expected_order_ids={order.order_id})

    # ── Configuration and data integrity ────────────────────────────

    # LULD halt modeling.

    def _in_halt_blackout(self, symbol: str, now_ns: int) -> bool:
        """True while a symbol is inside its post-resume entry blackout."""
        deadline = self._halt_blackout_until_ns.get(symbol)
        return deadline is not None and now_ns < deadline


    # ── Reg-SHO / SSR short-sale restriction ────────────────────────


    # ── Static borrow availability ───────────────────────────────────

    def _borrow_tier_for(self, symbol: str) -> BorrowTier:
        """Locate tier for ``symbol``; omitted symbols use the default tier."""
        return self._borrow_tier.get(symbol.upper(), self._borrow_default_tier)

    def _emit_locate_unavailable_alert(
        self,
        intent: OrderIntent,
        correlation_id: str,
    ) -> None:
        """Publish the forensic marker for a refused short entry (no locate)."""
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            severity=AlertSeverity.WARNING,
            alert_name="locate_unavailable",
            message=f"No borrow locate for {intent.symbol!r}: refused short entry ({intent.intent.name}); retries next boundary.",
            context={"symbol": intent.symbol, "intent": intent.intent.name},
        )

    def _emit_forced_exit_resized_alert(self, order: OrderRequest, closable: int) -> None:
        """Publish a marker when a mandated exit is clamped to the settled book.

        The resting-order cancel settled a *partial* fill, so the exit's original
        quantity would now cross zero into opposite exposure.  It is resized to
        the residual rather than stood down, but an operator needs to see that the
        submitted size differs from what the controller authored (Inv-13).
        """
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=order.correlation_id,
            severity=AlertSeverity.WARNING,
            alert_name="forced_exit_resized_after_cancel",
            message=f"Forced exit {order.reason!r} on {order.symbol!r} resized {order.quantity} -> {closable}: cancelling resting orders settled a partial fill, and the original quantity would have crossed zero into opposite exposure (strategy_id={order.strategy_id!r}).",
            context={
                "symbol": order.symbol,
                "strategy_id": order.strategy_id,
                "order_id": order.order_id,
                "reason": order.reason,
                "original_quantity": order.quantity,
                "submitted_quantity": closable,
                "position_quantity": self._positions.get(order.symbol).quantity,
            },
        )

    def _emit_forced_exit_stood_down_alert(self, order: OrderRequest) -> None:
        """Publish a marker when a mandated exit stands down post-cancel.

        The resting-order cancel settled a fill that already closed the book, so
        submitting the exit's now-stale quantity would open the opposite side.
        Standing down is the fail-safe branch (Inv-11), but it is *not* routine —
        an operator needs to see that a mandated exit did not reach the router,
        and forensics needs it to explain the missing order (Inv-13).
        """
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=order.correlation_id,
            severity=AlertSeverity.WARNING,
            alert_name="forced_exit_stood_down_after_cancel",
            message=f"Forced exit {order.reason!r} on {order.symbol!r} stood down: cancelling resting orders settled a fill that already closed the book, so the exit's quantity ({order.quantity}) no longer reduces exposure (strategy_id={order.strategy_id!r}).",
            context={
                "symbol": order.symbol,
                "strategy_id": order.strategy_id,
                "order_id": order.order_id,
                "reason": order.reason,
                "order_quantity": order.quantity,
                "position_quantity": self._positions.get(order.symbol).quantity,
            },
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
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            severity=AlertSeverity.WARNING,
            alert_name="forced_exit_supersedes_pending_order",
            message=f"Forced MARKET exit {order.strategy_id!r} on {order.symbol!r}: cancelling resting order(s) so the aggressive close can cross immediately (Inv-11).",
            context={
                "symbol": order.symbol,
                "strategy_id": order.strategy_id,
                "order_id": order.order_id,
            },
        )

    def _emit_ssr_suppression_alert(
        self,
        intent: OrderIntent,
        correlation_id: str,
    ) -> None:
        """Publish the forensic marker for a refused SSR short entry."""
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            severity=AlertSeverity.WARNING,
            alert_name="ssr_short_suppressed",
            message=f"SSR active for {intent.symbol!r}: refused short entry ({intent.intent.name}); retries next boundary (Reg-SHO 201).",
            context={"symbol": intent.symbol, "intent": intent.intent.name},
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
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            severity=AlertSeverity.WARNING,
            alert_name="market_event_rejected_by_data_health",
            message=f"{context['event_type']} for {event.symbol!r} rejected by data-health gate ({data_health_reason})",
            context=context,
        )


    def _force_flatten_symbol_on_degrade(
        self,
        symbol: str,
        correlation_id: str,
        *,
        reason: str,
    ) -> None:
        """Submit a market exit for one symbol during data-health degradation."""
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
            _transition_order(self,
                order_id,
                OrderState.SUBMITTED,
                f"degrade_flatten:{reason}",
                correlation_id=correlation_id,
            )
            self._submit_to_router(order, triggering_quote=self._in_flight_quote)
            self._bus.publish(order)
            self._settle_router_acks(correlation_id, expected_order_ids={order_id})
        except Exception as exc:  # noqa: BLE001 — fail-safe; never raise
            logger.exception(
                "Force-flatten on %s failed for symbol=%s (qty=%d, side=%s); "
                "position remains open and will require manual intervention.",
                reason,
                symbol,
                qty,
                side.name,
            )
            self._publish_alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=correlation_id,
                severity=AlertSeverity.CRITICAL,
                alert_name="degrade_flatten_failed",
                message=f"Force-flatten on {reason} failed for symbol={symbol!r} (qty={qty}, side={side.name}). Position remains open.",
                context={"symbol": symbol, "reason": reason, "exception": repr(exc)},
            )


    # ── Feature snapshot management ─────────────────────────────────

    _REGIME_SNAPSHOT_KEY = "__regime__"
    _REGIME_VERSION_PREFIX = "regime:"


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


