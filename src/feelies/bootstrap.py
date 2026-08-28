"""Compose the platform from configuration.

This module selects concrete implementations and returns a ready-to-boot
``Orchestrator``. Bus handlers register in causal order: router, sensors,
horizon aggregation, signal generation, then metrics. Optional layers are
omitted when their configuration is empty.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from feelies.alpha.discovery import load_and_register
from feelies.portfolio.fill_attribution import FillAttributionLedger
from feelies.alpha.layer_validator import validate_decouple_symbol_scope
from feelies.alpha.loader import AlphaLoader
from feelies.alpha.portfolio_layer_module import (
    LoadedPortfolioLayerModule,
    _DefaultPortfolioConstructor,
)
from feelies.promotion.evidence import (
    GateThresholds,
    apply_gate_thresholds_overrides,
)
from feelies.promotion.ledger import PromotionLedger
from feelies.promotion.lifecycle import LifecycleRevocation
from feelies.alpha.dependency_graph import (
    consumed_features_for_signal_registration,
    maybe_prune_unused_sensors,
    required_warm_feature_ids_for_signal_alpha,
    warn_unread_sensor_dependencies,
)
from feelies.alpha.registry import AlphaRegistry
from feelies.risk.risk_wrapper import AlphaBudgetRiskWrapper
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.bus.event_bus import EventBus
from feelies.core.clock import Clock, SimulatedClock, WallClock
from feelies.core.config import ConfigSnapshot
from feelies.core.events import (
    Alert,
    AlertSeverity,
    Event,
    KillSwitchActivation,
    NBBOQuote,
    OrderAck,
    PositionUpdate,
    RiskVerdict,
    SymbolHalted,
)
from feelies.core.errors import ConfigurationError
from feelies.core.identifiers import SequenceGenerator
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.core.wiring_manifest import manifest_hash
from feelies.core.session_clock import rth_open_ns
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.registry import SensorRegistry
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_backend import (
    build_backtest_backend,
    build_passive_limit_backend,
)
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import DefaultCostModel, DefaultCostModelConfig
from feelies.execution.intent import SignalPositionTranslator
from feelies.execution.position_manager import TargetPositionManager
from feelies.execution.moc_session import (
    MocSessionBounds,
    build_moc_bounds_from_platform,
)
from feelies.execution.trading_session import (
    TradingSessionBounds,
    build_trading_session_from_platform,
)
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter
from feelies.execution.regulatory.pdt_constraint import (
    AccountType,
    PDTConfig,
    PDTConstraint,
)
from feelies.features.aggregator import HorizonAggregator
from feelies.features.impl.horizon_windowed import HorizonWindowedFeature
from feelies.features.impl.rolling_stats import RollingZscoreFeature
from feelies.features.impl.sensor_passthrough import (
    SensorPassthroughFeature,
    TupleComponentFeature,
    TupleSignedImbalanceFeature,
)
from feelies.features.protocol import HorizonFeature
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.ingestion.normalizer import MarketDataNormalizer
from feelies.kernel.orchestrator import Orchestrator as KernelOrchestrator
from feelies.kernel.signal_order_trace import SignalOrderTraceRow
from feelies.monitoring.in_memory import (
    InMemoryAlertManager,
    InMemoryKillSwitch,
    InMemoryMetricCollector,
)
from feelies.monitoring.horizon_metrics import HorizonMetricsCollector
from feelies.portfolio.cross_sectional_tracker import CrossSectionalTracker
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.position_book_view import PositionBookView
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.risk.buying_power import BuyingPowerConfig
from feelies.risk.engine import RiskEngine
from feelies.risk.deferral_cap import DeferralCapController, DeferralPolicy
from feelies.risk.exit_composer import ExitComposer, ExitComposerPolicy
from feelies.risk.hazard_exit import HazardExitController, HazardPolicy
from feelies.risk.stop_exit import StopExitController, StopExitPolicy
from feelies.risk.edge_weighted_sizer import (
    EdgeWeightedSizer,
    SizeDivergence,
    SizerTiltConfig,
)
from feelies.risk.position_sizer import BudgetBasedSizer
from feelies.services.regime_engine import RegimeEngine, get_regime_engine
from feelies.services.regime_state_cache import RegimeStateCache
from feelies.services.regime_hazard_detector import RegimeHazardDetector
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.storage.memory_feature_snapshot import InMemoryFeatureSnapshotStore
from feelies.storage.memory_trade_journal import InMemoryTradeJournal
from feelies.storage.submitted_order_journal import DurableSubmittedOrderJournal

if TYPE_CHECKING:
    from feelies.broker.ib import IBGatewayConnection
    from feelies.composition.engine import CompositionEngine
    from feelies.execution.portfolio_netter import NetDivergence
    from feelies.ingestion.massive_ws import MassiveLiveFeed

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _BackendBundle:
    """Backend plus PAPER-only handles used by the entry script."""

    backend: ExecutionBackend
    live_feed: "MassiveLiveFeed | None" = None
    ib_connection: "IBGatewayConnection | None" = None


class StaleFactorLoadingsError(RuntimeError):
    """Raised when required factor loadings are missing or stale."""


class UniverseScaleError(RuntimeError):
    """Raised when a PORTFOLIO universe exceeds the v0.2 cap (§15.1)."""


class _BacktestMetricCollector(InMemoryMetricCollector):
    """Metric collector that never buffers the raw event list."""

    def __init__(self) -> None:
        super().__init__()
        self._store_raw_events = False


def _root_orchestrator_class() -> type[KernelOrchestrator]:
    class Orchestrator(KernelOrchestrator):
        """Composition-root orchestrator: lifecycle handles injected at init."""

        def __init__(
            self,
            *,
            config_snapshot: ConfigSnapshot,
            live_feed: object | None,
            ib_connection: object | None,
            **kwargs: Any,
        ) -> None:
            super().__init__(**kwargs)
            self.config_snapshot = config_snapshot
            self.live_feed = live_feed
            self.ib_connection = ib_connection

    return Orchestrator


_RootOrchestrator: Any = _root_orchestrator_class()


class _NotificationObserver:
    """Additive observer for previously zero-subscriber domain events.

    Records every delivery. KillSwitchActivation also surfaces an alert
    on the in-memory manager (not the bus — no extra ``self._seq`` draw).
    """

    __slots__ = ("_alerts", "records")

    def __init__(self, alert_manager: InMemoryAlertManager) -> None:
        self._alerts = alert_manager
        self.records: list[Event] = []

    def on_event(self, event: Event) -> None:
        self.records.append(event)
        if isinstance(event, KillSwitchActivation):
            self._alerts.emit(
                Alert(
                    timestamp_ns=event.timestamp_ns,
                    correlation_id=event.correlation_id,
                    sequence=event.sequence,
                    severity=AlertSeverity.WARNING,
                    layer="monitoring",
                    alert_name="kill_switch_activation",
                    message=event.reason,
                    context={"activated_by": event.activated_by},
                )
            )


def _attach_notification_observer(bus: EventBus, observer: _NotificationObserver) -> None:
    bus.subscribe(OrderAck, observer.on_event)
    bus.subscribe(PositionUpdate, observer.on_event)
    bus.subscribe(RiskVerdict, observer.on_event)
    bus.subscribe(SymbolHalted, observer.on_event)
    bus.subscribe(KillSwitchActivation, observer.on_event)


def build_platform(
    config: PlatformConfig | str | Path,
    event_log: InMemoryEventLog | None = None,
    *,
    signal_order_trace_sink: list[SignalOrderTraceRow] | None = None,
    net_shadow_sink: "list[NetDivergence] | None" = None,
    size_shadow_sink: "list[SizeDivergence] | None" = None,
    normalizer: MarketDataNormalizer | None = None,
    precomputed_ex_date_spans: dict[str, tuple[date, date]] | None = None,
    regime_calibration_quotes: tuple[NBBOQuote, ...] | None = None,
    edge_calibration_factors: "Mapping[str, float] | None" = None,
) -> tuple[KernelOrchestrator, PlatformConfig]:
    """Compose an orchestrator and resolved platform config.

    Optional precomputed corporate-action spans and regime quotes avoid replay
    rescans. A live normalizer enables per-event data-health gates.
    """
    config_source: Path | None = None
    if isinstance(config, (str, Path)):
        config_source = Path(config)
        config = PlatformConfig.from_yaml(config)

    config.validate()

    # Zero explicitly disables the cost gate; any other ratio must cover cost.
    _edge_ratio = config.signal_min_edge_cost_ratio
    if _edge_ratio != 0.0 and _edge_ratio < 1.0:
        raise ConfigurationError(
            f"signal_min_edge_cost_ratio={_edge_ratio} is a positive but "
            "sub-unity cost gate, which understates round-trip cost (Inv-12). "
            "Use >= 1.0 (>= 1.5 recommended), or exactly 0 to explicitly "
            "disable the gate for deliberate sub-cost research."
        )
    if 1.0 <= _edge_ratio < 1.5:
        logger.warning(
            "signal_min_edge_cost_ratio=%s is below the Inv-12 target of 1.5; "
            "the runtime cost gate is active but looser than recommended.",
            _edge_ratio,
        )

    if config.mode.name == "PAPER" and config.ib_port == 4001:
        logger.warning(
            "PAPER mode configured with ib_port=4001 (typically LIVE/TWS). "
            "IB Gateway paper accounts usually listen on port 4002.",
        )

    if (
        config.mode.name == "BACKTEST"
        and config.backtest_enforce_ingest_terminal_health
        and not config.ingest_terminal_symbol_health
    ):
        raise ConfigurationError(
            "backtest_enforce_ingest_terminal_health=True requires "
            "ingest_terminal_symbol_health to be populated before "
            "build_platform (e.g. scripts/run_backtest.py after ingest).",
        )

    if event_log is None:
        # Live feeds log arrival order, which need not be timestamp-monotonic.
        # Replays retain strict ordering.
        enforce_market_order = config.mode.name != "PAPER"
        event_log = InMemoryEventLog(enforce_market_order=enforce_market_order)
    _enforce_ex_date_replay_guard(
        config,
        event_log,
        precomputed_spans=precomputed_ex_date_spans,
    )

    clock = _select_clock(config.mode)
    config = _ensure_session_open_ns_for_paper(config, clock)
    bus = EventBus()

    regime_engine = _create_regime_engine(
        config.regime_engine,
        config.regime_engine_options,
    )
    if config.enforce_regime_state_scale_alignment and regime_engine is not None:
        _validate_regime_engine_risk_scale_alignment(regime_engine)

    registry_clock = None if config.mode.name == "BACKTEST" else clock
    promotion_ledger = (
        PromotionLedger(config.promotion_ledger_path)
        if config.promotion_ledger_path is not None
        else None
    )
    # Threshold precedence: defaults, platform overrides, then alpha overrides.
    gate_thresholds = _build_platform_gate_thresholds(config, source=config_source)
    registry = AlphaRegistry(
        clock=registry_clock,
        gate_thresholds=gate_thresholds,
        promotion_ledger=promotion_ledger,
        # Alpha overrides may not loosen operator-pinned platform floors.
        platform_gate_threshold_overrides=config.gate_thresholds_overrides,
    )
    loader = AlphaLoader(
        regime_engine=regime_engine,
        enforce_trend_mechanism=config.enforce_trend_mechanism,
        enforce_layer_gates=config.enforce_layer_gates,
        regime_engine_options=config.regime_engine_options,
    )

    _load_alphas(config, registry, loader)
    config = maybe_prune_unused_sensors(config, registry)

    risk_config = RiskConfig(
        max_position_per_symbol=config.risk_max_position_per_symbol,
        max_gross_exposure_pct=config.risk_max_gross_exposure_pct,
        max_drawdown_pct=config.risk_max_drawdown_pct,
        account_equity=_decimal(config.account_equity),
        regime_vol_breakout_scale=config.risk_regime_vol_breakout_scale,
        regime_compression_scale=config.risk_regime_compression_scale,
        regime_normal_scale=config.risk_regime_normal_scale,
    )
    # Warn when the per-symbol cap cannot bind before the gross cap.
    _max_gross = config.account_equity * config.risk_max_gross_exposure_pct / 100.0
    # Use $1 as the boot-time price floor when marks are unavailable.
    _vacuous_threshold_shares = _max_gross / 1.0
    if config.risk_max_position_per_symbol > _vacuous_threshold_shares:
        logger.warning(
            "risk_max_position_per_symbol=%d shares is vacuously "
            "non-binding under the gross-exposure cap "
            "(max_gross=$%.0f, equivalent to %.0f shares at $1/share). "
            "Set the per-symbol cap below the gross-equivalent share "
            "count for the lowest-priced symbol in the universe, or "
            "treat the gross cap as the binding constraint.",
            config.risk_max_position_per_symbol,
            _max_gross,
            _vacuous_threshold_shares,
        )
    # Isolate risk alerts so they cannot shift orchestrator event IDs.
    _seq_thread_safe = config.mode.name != "BACKTEST"
    risk_alert_seq = SequenceGenerator(stream="risk_alert", thread_safe=_seq_thread_safe)
    pdt_constraint = PDTConstraint(
        PDTConfig(
            account_type=AccountType.MARGIN_25K,
            account_id=config.account_id,
            min_equity=_decimal(config.pdt_min_equity_usd),
        )
    )
    buying_power_config = BuyingPowerConfig(
        account_type="margin_25k",
        intraday_multiplier=_decimal(config.risk_margin_intraday_buying_power_multiplier),
        overnight_multiplier=_decimal(config.risk_margin_overnight_buying_power_multiplier),
    )
    trading_session_bounds = _resolve_trading_session_bounds(config)
    moc_bounds = _resolve_moc_bounds(config)
    # One read path for regime: consumers read what was published, never the
    # live engine (see feelies.services.regime_state_cache).
    regime_states = RegimeStateCache(bus=bus)
    regime_states.attach()
    risk_engine = BasicRiskEngine(
        config=risk_config,
        regime_states=regime_states,
        bus=bus,
        alert_sequence_generator=risk_alert_seq,
        pdt_constraint=pdt_constraint,
        buying_power_config=buying_power_config,
        trading_session_bounds=trading_session_bounds,
        account_id=config.account_id,
        # Warn in PAPER when an entry gate is not wired.
        warn_on_inert_entry_gates=config.mode.name == "PAPER",
    )

    cost_model = DefaultCostModel(
        DefaultCostModelConfig(
            min_spread_cost_bps=_decimal(config.cost_min_spread_bps),
            commission_per_share=_decimal(config.cost_commission_per_share),
            taker_exchange_per_share=_decimal(config.cost_taker_exchange_per_share),
            maker_exchange_per_share=_decimal(config.cost_maker_exchange_per_share),
            passive_adverse_selection_bps=_decimal(config.cost_passive_adverse_selection_bps),
            through_fill_adverse_selection_bps=_decimal(
                config.cost_through_fill_adverse_selection_bps
            ),
            sell_regulatory_bps=_decimal(config.cost_sell_regulatory_bps),
            stress_multiplier=_decimal(config.cost_stress_multiplier),
            min_commission=_decimal(config.cost_min_commission),
            max_commission_pct=_decimal(config.cost_max_commission_pct),
            htb_borrow_annual_bps=_decimal(config.cost_htb_borrow_annual_bps),
            finra_taf_per_share=_decimal(config.cost_finra_taf_per_share),
            finra_taf_max_per_order=_decimal(config.cost_finra_taf_max_per_order),
            min_commission_applies_to_per_share_only=(
                config.cost_min_commission_applies_to_per_share_only
            ),
            spread_floor_taker_only=config.cost_spread_floor_taker_only,
        )
    )
    # PAPER shares one normalizer between the feed and orchestrator.
    if normalizer is None and config.mode.name == "PAPER":
        normalizer = MassiveNormalizer(
            clock=clock,
            halt_on_codes=frozenset(config.halt_on_condition_codes),
            halt_off_codes=frozenset(config.halt_off_condition_codes),
        )
        normalizer.register_symbols(config.symbols)

    bundle = _create_backend(
        config,
        event_log,
        clock,
        cost_model=cost_model,
        normalizer=normalizer,
        moc_bounds=moc_bounds,
        session_bounds=trading_session_bounds,
    )
    backend = bundle.backend
    router = getattr(backend, "order_router", None)
    if isinstance(
        router,
        (BacktestOrderRouter, PassiveLimitOrderRouter),
    ):
        def _on_backtest_quote(event: NBBOQuote) -> None:
            router.on_quote(event)

        bus.subscribe(NBBOQuote, _on_backtest_quote)

    position_store = MemoryPositionStore()
    strategy_positions = StrategyPositionStore()
    trade_journal = InMemoryTradeJournal()
    feature_snapshots = InMemoryFeatureSnapshotStore()
    # Size and limit scales are sequential controls sourced from one config.
    base_sizer = BudgetBasedSizer(
        regime_states=regime_states,
        regime_factors={
            "vol_breakout": risk_config.regime_vol_breakout_scale,
            "compression_clustering": risk_config.regime_compression_scale,
            "normal": risk_config.regime_normal_scale,
        },
    )
    # Keep tilted sizing shadow-only unless explicitly promoted to live decisions.
    sizer_tilt_config = SizerTiltConfig(
        edge_enabled=config.sizer_edge_weighting_enabled,
        edge_ref_bps=config.sizer_edge_ref_bps,
        edge_floor=config.sizer_edge_floor,
        edge_cap=config.sizer_edge_cap,
        vol_enabled=config.sizer_vol_targeting_enabled,
        vol_target_bps=config.sizer_vol_target_bps,
        vol_floor=config.sizer_vol_floor,
        vol_cap=config.sizer_vol_cap,
        inventory_enabled=config.sizer_inventory_penalty_enabled,
        inventory_floor=config.sizer_inventory_floor,
        tilt_floor=config.sizer_tilt_floor,
        tilt_cap=config.sizer_tilt_cap,
    )
    # Volatility tilt remains inactive until a realized-vol provider is supplied.
    tilted_sizer = EdgeWeightedSizer(
        base_sizer,
        sizer_tilt_config,
        inventory_provider=lambda symbol: int(
            PositionBookView.from_store(position_store).get(symbol)
        ),
    )
    position_sizer = tilted_sizer if config.sizer_tilt_drive else base_sizer
    # Live tilted sizing may exceed the base size, so surface it at startup.
    if config.sizer_tilt_drive and config.mode.name == "PAPER":
        logger.warning(
            "bootstrap: sizer_tilt_drive=true in %s mode — the position "
            "sizer can size SIGNAL-path orders above the single-factor "
            "baseline (up to %.2fx combined). Verify this is an intended, "
            "reviewed deployment choice for this run.",
            config.mode.name,
            config.sizer_tilt_cap,
        )
    intent_translator = SignalPositionTranslator()
    # The planner drives live intents and optionally emits partial reductions.
    position_manager = TargetPositionManager(
        trim_min_fraction=config.position_manager_trim_min_fraction,
    )

    kill_switch = InMemoryKillSwitch()
    alert_manager = InMemoryAlertManager(kill_switch=kill_switch)
    metric_collector: InMemoryMetricCollector
    if config.mode.name == "BACKTEST":
        metric_collector = _BacktestMetricCollector()
    else:
        metric_collector = InMemoryMetricCollector()

    # Create metrics first so sensor monitoring subscribes during composition.
    sensor_registry, horizon_scheduler = _create_sensor_layer(
        config,
        bus,
        metric_collector=metric_collector,
        thread_safe_sequences=_seq_thread_safe,
    )
    # The signal layer uses this list for dependency coverage checks.
    _built_horizon_features = _build_horizon_features(config)

    # Subscribe signals after aggregation and fail fast on missing sensor inputs.
    horizon_signal_engine = _create_signal_layer(
        registry=registry,
        bus=bus,
        clock=clock,
        sensor_registry=sensor_registry,
        horizon_features=_built_horizon_features,
        regime_min_discriminability=config.regime_min_discriminability,
        metric_collector=metric_collector,
        thread_safe_sequences=_seq_thread_safe,
    )

    # Subscribe composition after SIGNAL so synchronization observes updated caches.
    composition_engine = _create_composition_layer(
        config=config,
        bus=bus,
        registry=registry,
        position_store=position_store,
        strategy_positions=strategy_positions,
        clock=clock,
        thread_safe_sequences=_seq_thread_safe,
    )

    # Platform-level stop-loss / session flatten.  Returns None (and never
    # subscribes) when neither is configured, so default deployments are
    # unaffected.  Attached before the alpha-driven authors so a stop and a
    # hazard spike on the same dispatch resolve in a fixed order (Inv-5).
    _create_stop_exit_controller(
        bus=bus,
        config=config,
        position_store=position_store,
        trading_session_bounds=trading_session_bounds,
        thread_safe_sequences=_seq_thread_safe,
    )

    # Scan every active alpha so SIGNAL-layer hazard exits receive a controller.
    hazard_exit_controller = _create_hazard_exit_controller(
        bus=bus,
        registry=registry,
        position_store=position_store,
        fallback_universe=config.symbols,
        thread_safe_sequences=_seq_thread_safe,
    )

    # Attach the cap before the composer to keep subscriber order deterministic.
    deferral_cap_controller = _create_deferral_cap_controller(
        bus=bus,
        registry=registry,
        horizon_signal_engine=horizon_signal_engine,
        strategy_positions=strategy_positions,
        fallback_universe=config.symbols,
        session_flatten_enabled=config.session_flatten_enabled,
        session_flatten_seconds_before_close=config.session_flatten_seconds_before_close,
        thread_safe_sequences=_seq_thread_safe,
    )
    exit_composer = _create_exit_composer(
        bus=bus,
        horizon_signal_engine=horizon_signal_engine,
        strategy_positions=strategy_positions,
        fallback_universe=config.symbols,
        thread_safe_sequences=_seq_thread_safe,
    )

    # Build the detector only when an alpha enables hazard exits.
    hazard_seq, regime_hazard_detector = _create_hazard_detector(
        registry,
        thread_safe_sequences=_seq_thread_safe,
    )

    # Apply per-alpha risk budgets in addition to platform caps.
    risk_wrapper = AlphaBudgetRiskWrapper(
        inner=risk_engine,
        registry=registry,
        strategy_positions=strategy_positions,
        platform_config=risk_config,
        account_equity=_decimal(config.account_equity),
    )
    effective_risk_engine: RiskEngine = (
        risk_wrapper if config.enforce_per_alpha_risk_budget else risk_engine
    )
    fill_ledger = FillAttributionLedger()

    # Explicit edge factors override the configured calibration store.
    if edge_calibration_factors is not None:
        resolved_edge_factors: dict[str, float] = dict(edge_calibration_factors)
    else:
        resolved_edge_factors = {}
        if config.edge_calibration_path is not None:
            from feelies.forensics.edge_calibration import EdgeCalibrationStore

            resolved_edge_factors = EdgeCalibrationStore(
                str(config.edge_calibration_path)
            ).factors()

    # PAPER warns when its active cost gate lacks the backtest calibration haircut.
    if (
        config.signal_min_edge_cost_ratio > 0
        and not resolved_edge_factors
        and config.mode.name == "PAPER"
    ):
        logger.warning(
            "B4 edge-vs-cost gate is active (signal_min_edge_cost_ratio=%s) but no "
            "edge calibration is configured; every alpha gates on its full "
            "disclosed edge. A backtest run with --edge-calibration gates on a "
            "haircut edge and will admit fewer trades than this deployment "
            "(Inv-9 parity). Set edge_calibration_path to an artifact emitted by "
            "`--emit-edge-calibration`.",
            config.signal_min_edge_cost_ratio,
        )

    # Stamp the snapshot from the injected clock so a backtest's provenance
    # record is deterministic (SimulatedClock); only PAPER reads wall time
    # (WallClock).  Inv-10: no raw wall-clock read at the bootstrap edge.
    config_snapshot = config.snapshot(ts_ns=clock.now_ns())
    orchestrator = _RootOrchestrator(
        config_snapshot=config_snapshot,
        live_feed=bundle.live_feed,
        ib_connection=bundle.ib_connection,
        clock=clock,
        bus=bus,
        backend=backend,
        risk_engine=effective_risk_engine,
        position_store=position_store,
        event_log=event_log,
        metric_collector=metric_collector,
        alert_manager=alert_manager,
        kill_switch=kill_switch,
        regime_engine=regime_engine,
        regime_engine_registry_name=config.regime_engine,
        position_sizer=position_sizer,
        intent_translator=intent_translator,
        alpha_registry=registry,
        account_equity=_decimal(config.account_equity),
        trade_journal=trade_journal,
        feature_snapshots=feature_snapshots,
        fill_ledger=fill_ledger,
        strategy_positions=strategy_positions,
        cost_model=cost_model,
        sensor_registry=sensor_registry,
        horizon_scheduler=horizon_scheduler,
        horizon_signal_engine=horizon_signal_engine,
        regime_hazard_detector=regime_hazard_detector,
        hazard_sequence_generator=hazard_seq,
        composition_engine=composition_engine,
        hazard_exit_controller=hazard_exit_controller,
        trading_session_bounds=trading_session_bounds,
        moc_bounds_configured=moc_bounds is not None,
        edge_calibration_factors=resolved_edge_factors,
        signal_order_trace_sink=signal_order_trace_sink,
        net_shadow_sink=net_shadow_sink,
        size_shadow_sizer=tilted_sizer if size_shadow_sink is not None else None,
        size_shadow_sink=size_shadow_sink,
        normalizer=normalizer,
        regime_calibration_quotes=regime_calibration_quotes,
        thread_safe_sequences=_seq_thread_safe,
        position_manager=position_manager,
        position_manager_enable_trim=config.position_manager_enable_trim,
        position_manager_trim_edge_gate_multiplier=(
            config.position_manager_trim_edge_gate_multiplier
        ),
        position_manager_urgency_exec=config.position_manager_urgency_exec,
        net_shadow_portfolio_max_abs_qty=config.risk_max_position_per_symbol,
    )
    _attach_notification_observer(
        bus, _NotificationObserver(alert_manager)
    )

    # Wire IB connectivity / unknown-status alerts onto the shared bus so
    # operators have programmatic visibility into IB link-state events and
    # unrecognised order-status strings during live/paper sessions.
    if bundle.ib_connection is not None and hasattr(bundle.ib_connection, "on_alert_event"):
        _ib_alert_seq = SequenceGenerator(stream="ib_alert", thread_safe=True)
        _ib_clock = clock  # captured by closure

        def _publish_ib_alert(error_code: int, error_msg: str) -> None:
            bus.publish(
                Alert(
                    timestamp_ns=_ib_clock.now_ns(),
                    correlation_id="",
                    sequence=_ib_alert_seq.next(),
                    severity=AlertSeverity.WARNING,
                    layer="broker.ib",
                    alert_name="ib_connectivity_event",
                    message=error_msg,
                    context={"error_code": error_code},
                )
            )

        bundle.ib_connection.on_alert_event(_publish_ib_alert)

    _wire_decouple_revocation_hook(registry, exit_composer, deferral_cap_controller)

    logger.info(
        "Platform composed: mode=%s, symbols=%s, alphas=%d, regime=%s, "
        "config_checksum=%s, wiring_manifest_hash=%s",
        config.mode.name,
        sorted(config.symbols),
        len(registry),
        config.regime_engine or "none",
        config_snapshot.checksum[:12],
        manifest_hash()[:12],
    )

    return orchestrator, config


def _wire_decouple_revocation_hook(
    registry: AlphaRegistry,
    exit_composer: ExitComposer | None,
    deferral_cap_controller: DeferralCapController | None,
) -> None:
    """Route lifecycle revocation to the Stage-0 exit authors.

    The event timestamp is preserved so flattening remains replay-deterministic."""
    if exit_composer is None:
        return

    def _on_revocation(revocation: LifecycleRevocation) -> None:
        exit_composer.revoke_and_flatten(
            revocation.alpha_id,
            now_ns=revocation.timestamp_ns,
            correlation_id=revocation.correlation_id,
        )
        if deferral_cap_controller is not None:
            deferral_cap_controller.revoke(revocation.alpha_id)

    registry.set_lifecycle_revocation_hook(_on_revocation)


def _select_clock(mode: OperatingMode) -> Clock:
    if mode.name == "BACKTEST":
        return SimulatedClock()
    return WallClock()


def _ensure_session_open_ns_for_paper(
    config: PlatformConfig,
    clock: Clock,
) -> PlatformConfig:
    """Anchor PAPER horizon boundaries to the current RTH open when absent."""
    if config.mode.name == "BACKTEST":
        return config
    if config.session_open_ns is not None:
        return config
    if not config.horizons_seconds or not config.sensor_specs:
        return config
    anchored_ns = clock.now_ns()
    logger.info(
        "H10: auto-anchoring session_open_ns=%d for mode=%s "
        "(set platform.yaml: session_open_ns explicitly to override)",
        anchored_ns,
        config.mode.name,
    )
    return replace(config, session_open_ns=anchored_ns)


def _build_platform_gate_thresholds(
    config: PlatformConfig,
    *,
    source: Path | None = None,
) -> GateThresholds | None:
    """Resolve platform gate thresholds and report invalid overrides once."""
    overrides = config.gate_thresholds_overrides
    if not overrides:
        return None
    try:
        return apply_gate_thresholds_overrides(GateThresholds(), overrides)
    except ValueError as exc:
        where = f"{source}: " if source is not None else ""
        raise ConfigurationError(f"{where}gate_thresholds: {exc}") from exc


def _validate_regime_engine_risk_scale_alignment(engine: RegimeEngine) -> None:
    """Fail boot when regime posteriors use names BasicRiskEngine cannot scale."""
    # Read the single source of truth from BasicRiskEngine so the validation
    # cannot drift if the risk engine adds, renames, or removes a regime
    # scale key.
    valid = BasicRiskEngine.REGIME_SCALE_STATE_NAMES
    unknown = frozenset(engine.state_names) - valid
    if unknown:
        raise ConfigurationError(
            "RegimeEngine state_names contain entries not mapped by "
            "BasicRiskEngine regime scaling: "
            f"{sorted(unknown)}. Expected subset of {valid}. "
            "Extend RiskConfig / regime_vol_*_scale or disable "
            "enforce_regime_state_scale_alignment."
        )


def _create_regime_engine(
    engine_name: str | None,
    options: dict[str, object] | None = None,
) -> RegimeEngine | None:
    if engine_name is None:
        return None
    try:
        kwargs = dict(options or {})
        engine = get_regime_engine(engine_name, **kwargs)
        logger.info("Created shared RegimeEngine: %s", engine_name)
        return engine
    except KeyError:
        raise ConfigurationError(
            f"Unknown regime engine '{engine_name}': not found in registry. "
            "Check the 'regime_engine' field in your platform configuration."
        ) from None
    except TypeError as exc:
        raise ConfigurationError(
            f"Invalid regime_engine_options for engine {engine_name!r}: {exc}"
        ) from exc


def _load_alphas(
    config: PlatformConfig,
    registry: AlphaRegistry,
    loader: AlphaLoader,
) -> None:
    if config.alpha_spec_dir is not None:
        load_and_register(
            config.alpha_spec_dir,
            registry,
            loader,
            parameter_overrides=config.parameter_overrides,
        )

    for spec_path in config.alpha_specs:
        name = spec_path.name
        alpha_id_guess = (
            name[: -len(".alpha.yaml")] if name.endswith(".alpha.yaml") else spec_path.stem
        )
        overrides = config.parameter_overrides.get(alpha_id_guess)
        module = loader.load(spec_path, param_overrides=overrides)
        registry.register(module)
        logger.info(
            "Registered alpha '%s' from explicit path %s", module.manifest.alpha_id, spec_path
        )

    _enforce_decouple_symbol_scope(config, registry)


def _enforce_decouple_symbol_scope(config: PlatformConfig, registry: AlphaRegistry) -> None:
    """Reject decoupled SIGNAL alphas that exceed the supported symbol scope."""
    entries: list[tuple[str, frozenset[str], bool]] = []
    for alpha_id in sorted(registry.alpha_ids()):
        manifest = registry.get(alpha_id).manifest
        policy = manifest.safety_exit_policy
        is_decoupled = policy is not None and policy.get("mode") == "decouple_caps_only"
        symbols = manifest.symbols
        resolved = frozenset(symbols) if symbols else frozenset(config.symbols)
        entries.append((alpha_id, resolved, is_decoupled))
    validate_decouple_symbol_scope(
        entries,
        # This platform flattens the promoting strategy's slice, not symbol-net.
        backstop_slice_scoped=True,
    )


def _resolve_trading_session_bounds(
    config: PlatformConfig,
) -> TradingSessionBounds | None:
    """Resolve RTH bounds for entry-fill suppression."""
    cal_path = str(config.event_calendar_path) if config.event_calendar_path is not None else None
    session_date = config.rth_session_date or config.moc_session_date
    return build_trading_session_from_platform(
        rth_session_gating_enabled=config.rth_session_gating_enabled,
        rth_session_date=session_date,
        event_calendar_path=cal_path,
        rth_open_et=config.rth_open_et,
        rth_close_et=config.rth_close_et,
        early_close_dates=config.early_close_dates,
        early_close_rth_close_et=config.early_close_rth_close_et,
        market_holiday_dates=config.market_holiday_dates,
        no_entry_first_seconds=config.no_entry_first_seconds,
    )


def _resolve_moc_bounds(config: PlatformConfig) -> MocSessionBounds | None:
    """Resolve closing-auction bounds, or ``None`` when disabled."""
    if not config.moc_strategy_ids:
        return None
    cal_path = str(config.event_calendar_path) if config.event_calendar_path is not None else None
    return build_moc_bounds_from_platform(
        moc_session_date=config.moc_session_date,
        event_calendar_path=cal_path,
        moc_cutoff_et=config.moc_cutoff_et,
        official_close_et=config.official_close_et,
        early_close_dates=config.early_close_dates,
        early_close_moc_cutoff_et=config.early_close_moc_cutoff_et,
        early_close_official_close_et=config.early_close_official_close_et,
    )


def _create_backend(
    config: PlatformConfig,
    event_log: InMemoryEventLog,
    clock: Clock,
    *,
    cost_model: DefaultCostModel,
    normalizer: MarketDataNormalizer | None = None,
    moc_bounds: MocSessionBounds | None = None,
    session_bounds: TradingSessionBounds | None = None,
) -> _BackendBundle:
    """Compose the configured backend and its operator-facing handles."""
    if moc_bounds is None:
        moc_bounds = _resolve_moc_bounds(config)
    if session_bounds is None:
        session_bounds = _resolve_trading_session_bounds(config)
    if config.mode == OperatingMode.BACKTEST:
        if config.execution_mode in ("passive_limit", "minimum_cost"):
            backend, _ = build_passive_limit_backend(
                event_log,
                clock,
                latency_ns=config.backtest_fill_latency_ns,
                market_data_latency_ns=config.market_data_latency_ns,
                cost_model=cost_model,
                market_impact_factor=config.cost_market_impact_factor,
                max_impact_half_spreads=config.cost_max_impact_half_spreads,
                fill_delay_ticks=config.passive_fill_delay_ticks,
                max_resting_ticks=config.passive_max_resting_ticks,
                queue_position_shares=config.passive_queue_position_shares,
                cancel_fee_per_share=_decimal(config.passive_cancel_fee_per_share),
                fill_hazard_max=_decimal(config.passive_fill_hazard_max),
                stop_slippage_half_spreads=config.cost_stop_slippage_half_spreads,
                within_l1_impact_factor=config.cost_within_l1_impact_factor,
                permanent_impact_coefficient=config.cost_permanent_impact_coefficient,
                stop_depth_depletion_factor=config.cost_stop_depth_depletion_factor,
                through_fill_size_cap_enabled=(config.passive_through_fill_size_cap_enabled),
                require_trade_for_level_fill=config.passive_require_trade_for_level_fill,
                moc_bounds=moc_bounds,
                moc_penalty_bps=config.cost_moc_penalty_bps,
                trading_session_bounds=session_bounds,
            )
            return _BackendBundle(backend=backend)

        backend, _ = build_backtest_backend(
            event_log,
            clock,
            latency_ns=config.backtest_fill_latency_ns,
            market_data_latency_ns=config.market_data_latency_ns,
            cost_model=cost_model,
            market_impact_factor=config.cost_market_impact_factor,
            max_impact_half_spreads=config.cost_max_impact_half_spreads,
            stop_slippage_half_spreads=config.cost_stop_slippage_half_spreads,
            within_l1_impact_factor=config.cost_within_l1_impact_factor,
            permanent_impact_coefficient=config.cost_permanent_impact_coefficient,
            stop_depth_depletion_factor=config.cost_stop_depth_depletion_factor,
            max_resting_ticks=config.passive_max_resting_ticks,
            moc_bounds=moc_bounds,
            moc_penalty_bps=config.cost_moc_penalty_bps,
            trading_session_bounds=session_bounds,
        )
        return _BackendBundle(backend=backend)

    if config.mode == OperatingMode.PAPER:
        api_key = (os.environ.get("MASSIVE_API_KEY") or "").strip()
        if not api_key:
            raise ConfigurationError("MASSIVE_API_KEY env var is required for OperatingMode.PAPER")
        if not isinstance(normalizer, MassiveNormalizer):
            actual = "None" if normalizer is None else type(normalizer).__name__
            raise ConfigurationError(
                f"PAPER mode requires a MassiveNormalizer instance, got {actual}"
            )
        # Keep the optional IB stack out of BACKTEST-only imports.
        from feelies.execution.paper_backend import build_paper_backend

        backend, live_feed, ib_conn = build_paper_backend(
            massive_api_key=api_key,
            symbols=sorted(config.symbols),
            clock=clock,
            normalizer=normalizer,
            ib_host=config.ib_host,
            ib_port=config.ib_port,
            ib_client_id=config.ib_client_id,
            massive_ws_url=config.massive_ws_url,
        )
        router = getattr(backend, "order_router", None)
        can_bind_ib = hasattr(ib_conn, "bind_submitted_order_journal")
        if router is not None or can_bind_ib:
            submitted_order_journal = DurableSubmittedOrderJournal(
                _submitted_order_journal_path(config),
                clock=clock,
            )
            if router is not None:
                submitted_order_journal.install_on(router)
            if can_bind_ib:
                ib_conn.bind_submitted_order_journal(submitted_order_journal)
        return _BackendBundle(
            backend=backend,
            live_feed=live_feed,
            ib_connection=ib_conn,
        )

    raise AssertionError(f"Unhandled operating mode: {config.mode!r}")


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _submitted_order_journal_path(config: PlatformConfig) -> Path:
    """PAPER/live journal path. Not a PlatformConfig field (parity hash)."""
    base = config.cache_dir
    if base is None:
        base = Path.home() / ".feelies" / "cache"
    return Path(base) / f"submitted_order_journal-{config.ib_client_id}.jsonl"


def _derive_session_id(config: PlatformConfig) -> str:
    """Build the deterministic horizon session identifier."""
    if config.session_open_ns is None:
        date_str = "UNANCHORED"
    else:
        # nanoseconds since epoch → ISO date (UTC); avoids any
        # timezone-dependent drift that would defeat replay parity.
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(config.session_open_ns / 1_000_000_000, tz=timezone.utc)
        date_str = dt.strftime("%Y-%m-%d")
    return f"{config.market_id}_{config.session_kind}_{date_str}"


# Map each sensor to the horizon features it produces. Unlisted sensors remain
# available to the gate DSL through the live sensor cache.
_HORIZON_FEATURE_FACTORIES: dict[str, Callable[[int], list[HorizonFeature]]] = {
    # Snapshot spread_z_30d so horizon staleness applies to gate evaluation.
    "spread_z_30d": lambda h: [
        SensorPassthroughFeature("spread_z_30d", h),
    ],
    # Normalize OFI within each alpha's event-time horizon.
    "ofi_ewma": lambda h: [
        SensorPassthroughFeature("ofi_ewma", h),
        HorizonWindowedFeature(
            "ofi_ewma",
            h,
            reducer="zscore",
            feature_id="ofi_ewma_zscore",
        ),
    ],
    # Sum raw signed flow once per event; summing the EWMA double-counts decay tails.
    "ofi_raw": lambda h: [
        HorizonWindowedFeature(
            "ofi_raw",
            h,
            reducer="sum",
            feature_id="ofi_integrated",
            min_samples=1,
        ),
        # Hazen percentile of the latest raw OFI within the horizon.
        HorizonWindowedFeature(
            "ofi_raw",
            h,
            reducer="percentile",
            feature_id="ofi_integrated_percentile",
        ),
    ],
    # Book imbalance is level-invariant; expose its latest and normalized values.
    "book_imbalance": lambda h: [
        SensorPassthroughFeature("book_imbalance", h),
        HorizonWindowedFeature(
            "book_imbalance",
            h,
            reducer="zscore",
            feature_id="book_imbalance_zscore",
        ),
        # The horizon mean captures persistent imbalance with less point noise.
        HorizonWindowedFeature(
            "book_imbalance",
            h,
            reducer="mean",
            feature_id="book_imbalance_mean",
        ),
    ],
    # Keep Kyle features on the alpha's event-time horizon.
    "kyle_lambda_60s": lambda h: [
        HorizonWindowedFeature(
            "kyle_lambda_60s",
            h,
            reducer="zscore",
            feature_id="kyle_lambda_60s_zscore",
        ),
        HorizonWindowedFeature(
            "kyle_lambda_60s",
            h,
            reducer="percentile",
            feature_id="kyle_lambda_60s_percentile",
        ),
    ],
    "quote_replenish_asymmetry": lambda h: [
        HorizonWindowedFeature(
            "quote_replenish_asymmetry",
            h,
            reducer="zscore",
            feature_id="quote_replenish_asymmetry_zscore",
        ),
    ],
    # Normalize hazard rate across symbols while retaining the raw gate input.
    "quote_hazard_rate": lambda h: [
        SensorPassthroughFeature("quote_hazard_rate", h),
        HorizonWindowedFeature(
            "quote_hazard_rate",
            h,
            reducer="zscore",
            feature_id="quote_hazard_rate_zscore",
        ),
    ],
    # Inventory pressure is already normalized and fast-decaying; expose only
    # the latest value at the two horizons allowed by its half-life envelope.
    "inventory_pressure": lambda h: (
        [SensorPassthroughFeature("inventory_pressure", h)] if h in (30, 120) else []
    ),
    # Liquidity-stress inputs are normalized; flicker also gets a relative z-score.
    "liquidity_stress_score": lambda h: [
        SensorPassthroughFeature("liquidity_stress_score", h),
    ],
    "quote_flicker_rate": lambda h: [
        SensorPassthroughFeature("quote_flicker_rate", h),
        HorizonWindowedFeature(
            "quote_flicker_rate",
            h,
            reducer="zscore",
            feature_id="quote_flicker_rate_zscore",
        ),
    ],
    # Expose both total Hawkes burst magnitude and signed buy/sell imbalance.
    "hawkes_intensity": lambda h: [
        HorizonWindowedFeature(
            "hawkes_intensity",
            h,
            reducer="zscore",
            feature_id="hawkes_intensity_zscore",
            tuple_sum_component_indices=(0, 1),
        ),
        TupleSignedImbalanceFeature(
            "hawkes_intensity",
            0,
            1,
            "hawkes_intensity_imbalance",
            h,
        ),
    ],
    "trade_through_rate": lambda h: [
        SensorPassthroughFeature("trade_through_rate", h),
    ],
    "scheduled_flow_window": lambda h: [
        TupleComponentFeature(
            "scheduled_flow_window",
            0,
            "scheduled_flow_window_active",
            h,
        ),
        TupleComponentFeature(
            "scheduled_flow_window",
            1,
            "seconds_to_window_close",
            h,
        ),
        # Preserve window identity so distinct scheduled events do not collapse.
        TupleComponentFeature(
            "scheduled_flow_window",
            2,
            "scheduled_flow_window_id_hash",
            h,
        ),
        TupleComponentFeature(
            "scheduled_flow_window",
            3,
            "scheduled_flow_window_direction_prior",
            h,
        ),
    ],
    "micro_price": lambda h: [
        SensorPassthroughFeature("micro_price", h),
        HorizonWindowedFeature(
            "micro_price",
            h,
            reducer="zscore",
            feature_id="micro_price_zscore",
        ),
        # Drift captures directional change without leaking the absolute price level.
        HorizonWindowedFeature(
            "micro_price",
            h,
            reducer="delta",
            feature_id="micro_price_drift",
        ),
    ],
    "realized_vol_30s": lambda h: [
        SensorPassthroughFeature("realized_vol_30s", h),
        # Volatility uses a longer count baseline; horizon normalization is too noisy.
        RollingZscoreFeature(
            "realized_vol_30s",
            h,
            feature_id="realized_vol_30s_zscore",
        ),
    ],
}


def _horizon_features_for(
    sensor_id: str,
    horizon: int,
) -> list[HorizonFeature]:
    """Return the HorizonFeature instances for *sensor_id* at *horizon*."""
    factory = _HORIZON_FEATURE_FACTORIES.get(sensor_id)
    if factory is None:
        return []
    return factory(horizon)


def _build_horizon_features(
    config: PlatformConfig,
) -> list[HorizonFeature]:
    """Build the full HorizonFeature list from registered sensors + horizons.

    Creates features for every (sensor_id, horizon_seconds) pair that
    has an entry in *_horizon_features_for*.  Sensors without an entry
    are skipped silently — they are fully handled by the gate DSL via
    the sensor_cache path in HorizonSignalEngine._build_bindings.
    """
    if not config.sensor_specs or not config.horizons_seconds:
        return []
    registered = {spec.sensor_id for spec in config.sensor_specs}
    features: list[HorizonFeature] = []
    for sensor_id in sorted(registered):  # sorted for determinism
        for h in sorted(config.horizons_seconds):
            features.extend(_horizon_features_for(sensor_id, h))
    return features


def _create_sensor_layer(
    config: PlatformConfig,
    bus: EventBus,
    *,
    metric_collector: InMemoryMetricCollector | None = None,
    thread_safe_sequences: bool = True,
) -> tuple[SensorRegistry | None, HorizonScheduler | None]:
    """Compose and attach the sensor layer; return dispatch-facing components."""
    sensor_seq = SequenceGenerator(stream="sensor", thread_safe=thread_safe_sequences)
    horizon_seq = SequenceGenerator(stream="horizon", thread_safe=thread_safe_sequences)
    snapshot_seq = SequenceGenerator(stream="snapshot", thread_safe=thread_safe_sequences)

    sensor_registry: SensorRegistry | None = None
    if config.sensor_specs:
        sensor_registry = SensorRegistry(
            bus=bus,
            sequence_generator=sensor_seq,
            symbols=frozenset(config.symbols),
            metric_collector=metric_collector,
            emit_reading_metrics=config.mode.name != "BACKTEST",
        )
        # Inject the runtime calendar object that YAML cannot represent.
        import dataclasses as _dc
        from feelies.sensors.impl.scheduled_flow_window import (
            ScheduledFlowWindowSensor as _SFWS,
        )
        from feelies.storage.reference.event_calendar import (
            load_event_calendar as _load_calendar,
        )

        _calendar = (
            _load_calendar(config.event_calendar_path)
            if config.event_calendar_path is not None
            else None
        )
        for spec in config.sensor_specs:
            if spec.cls is _SFWS:
                if _calendar is None:
                    raise ConfigurationError(
                        "sensor 'scheduled_flow_window' requires "
                        "event_calendar_path to be set in PlatformConfig"
                    )
                spec = _dc.replace(spec, params={**spec.params, "calendar": _calendar})
            sensor_registry.register(spec)
        logger.info(
            "Sensor registry composed: %d specs, %d symbols",
            len(config.sensor_specs),
            len(config.symbols),
        )

    horizon_scheduler: HorizonScheduler | None = None
    horizon_aggregator: HorizonAggregator | None = None
    if config.horizons_seconds and (sensor_registry is not None or config.sensor_specs):
        # Live boundary indices need an explicit anchor; deterministic replays may
        # bind to their first ordered event.
        if config.session_open_ns is None:
            if config.mode.name != "BACKTEST":
                raise ConfigurationError(
                    "H10: session_open_ns must be set explicitly for "
                    f"mode={config.mode.name} deployments.  "
                    "Lazy-binding from the first market event yields "
                    "non-deterministic boundary indices (audit H10)."
                )
            logger.warning(
                "H10: session_open_ns is None; the HorizonScheduler "
                "will auto-bind to the first event timestamp.  "
                "Replay parity is preserved only when the replayed "
                "event log is strictly ordered and never partially "
                "replayed (acceptable for BACKTEST mode only)."
            )
        # Skip the scheduler without sensor consumers. For RTH equity replays,
        # anchor an unpinned grid to the open so the first bucket is complete.
        _anchor_fn = (
            rth_open_ns
            if (
                config.session_open_ns is None
                and config.session_kind == "RTH"
                and config.market_id == "US_EQUITY"
            )
            else None
        )
        horizon_scheduler = HorizonScheduler(
            horizons=config.horizons_seconds,
            session_id=_derive_session_id(config),
            symbols=frozenset(config.symbols),
            session_open_ns=config.session_open_ns,
            sequence_generator=horizon_seq,
            metric_collector=metric_collector,
            session_open_anchor_fn=_anchor_fn,
        )
        logger.info(
            "HorizonScheduler composed: horizons=%s, session_id=%s, session_open_ns=%s",
            sorted(config.horizons_seconds),
            horizon_scheduler._session_id
            if hasattr(horizon_scheduler, "_session_id")
            else "<unknown>",
            config.session_open_ns,
        )
        # Two horizon lengths preserve a full longest-window history.
        sensor_buffer_seconds = 2 * max(config.horizons_seconds)
        _active_features = _build_horizon_features(config)
        horizon_aggregator = HorizonAggregator(
            bus=bus,
            horizon_features=_active_features,
            symbols=frozenset(config.symbols),
            sensor_buffer_seconds=sensor_buffer_seconds,
            sequence_generator=snapshot_seq,
            metric_collector=metric_collector,
            # Warn at construction when features declare unknown sensors.
            known_sensor_ids=frozenset(
                spec.sensor_id
                for spec in (sensor_registry.specs if sensor_registry is not None else ())
            ),
        )
        horizon_aggregator.attach()
        _mode_label = "active" if _active_features else "passive"
        logger.info(
            "HorizonAggregator composed (%s mode): buffer_window=%ds, symbols=%d, features=%d",
            _mode_label,
            sensor_buffer_seconds,
            len(config.symbols),
            len(_active_features),
        )

    return sensor_registry, horizon_scheduler


def _create_hazard_detector(
    registry: AlphaRegistry,
    *,
    thread_safe_sequences: bool = True,
) -> tuple[SequenceGenerator, RegimeHazardDetector | None]:
    """Create the shared hazard sequence and opt-in detector.

    The detector remains absent unless at least one alpha enables hazard exits."""
    hazard_seq = SequenceGenerator(stream="hazard", thread_safe=thread_safe_sequences)

    def _opts_in(manifest_block: dict[str, object] | None) -> bool:
        if not isinstance(manifest_block, dict):
            return False
        flag = manifest_block.get("enabled", False)
        return bool(flag) is True

    enabled = any(
        _opts_in(getattr(module.manifest, "hazard_exit", None))
        for module in registry.active_alphas()
    )
    if not enabled:
        return hazard_seq, None

    detector = RegimeHazardDetector()
    logger.info(
        "RegimeHazardDetector wired: at least one alpha declares "
        "hazard_exit.enabled=true; emitting RegimeHazardSpike events"
    )
    return hazard_seq, detector


def _create_signal_layer(
    *,
    registry: AlphaRegistry,
    bus: EventBus,
    clock: Clock,
    sensor_registry: SensorRegistry | None,
    horizon_features: list[HorizonFeature] | None = None,
    regime_min_discriminability: float = 0.0,
    metric_collector: InMemoryMetricCollector | None = None,
    thread_safe_sequences: bool = True,
) -> HorizonSignalEngine | None:
    """Compose and attach the SIGNAL engine when SIGNAL alphas exist."""
    signal_seq = SequenceGenerator(stream="signal", thread_safe=thread_safe_sequences)

    signal_alphas = registry.signal_alphas()
    if not signal_alphas:
        return None

    if sensor_registry is None:
        known_sensor_ids: frozenset[str] = frozenset()
    else:
        known_sensor_ids = frozenset(spec.sensor_id for spec in sensor_registry.specs)

    registry.resolve_signal_dependencies(known_sensor_ids)

    # Warn when a dependency maps to neither a feature nor a cached sensor.
    feature_ids: frozenset[str] = frozenset(f.feature_id for f in (horizon_features or []))
    covered = feature_ids | known_sensor_ids
    for alpha in signal_alphas:
        depends = getattr(alpha, "depends_on_sensors", ())
        uncovered = [sid for sid in depends if sid not in covered]
        if uncovered:
            logger.warning(
                "H3/M2 boot validation: alpha %r declares "
                "depends_on_sensors entries %s that are not covered by "
                "any registered HorizonFeature (feature_ids=%s) or "
                "sensor cache (sensor_ids=%s).  snapshot.values.get() "
                "will silently return None for these keys at runtime.",
                alpha.manifest.alpha_id,
                uncovered,
                sorted(feature_ids),
                sorted(known_sensor_ids),
            )

    engine = HorizonSignalEngine(
        bus=bus,
        signal_sequence_generator=signal_seq,
        clock=clock,
        regime_min_discriminability=regime_min_discriminability,
        metric_collector=metric_collector,
    )
    for module in signal_alphas:
        if not isinstance(module, LoadedSignalLayerModule):
            continue
        warm_ids = required_warm_feature_ids_for_signal_alpha(
            depends_on_sensors=module.depends_on_sensors,
            horizon_seconds=module.horizon_seconds,
            horizon_features=horizon_features or [],
            gate=module.gate,
            signal_source=module.signal_source,
        )
        warn_unread_sensor_dependencies(
            alpha_id=module.manifest.alpha_id,
            depends_on_sensors=module.depends_on_sensors,
            horizon_seconds=module.horizon_seconds,
            horizon_features=horizon_features or [],
            warm_ids=warm_ids,
        )
        consumed_feature_ids = consumed_features_for_signal_registration(
            declared_consumed_features=module.consumed_features,
            required_warm_feature_ids=warm_ids,
        )
        engine.register(
            RegisteredSignal(
                alpha_id=module.manifest.alpha_id,
                horizon_seconds=module.horizon_seconds,
                signal=module.signal,
                params=module.params,
                gate=module.gate,
                cost_arithmetic=module.cost,
                trend_mechanism=module.trend_mechanism_enum,
                expected_half_life_seconds=module.expected_half_life_seconds,
                consumed_features=consumed_feature_ids,
                required_warm_feature_ids=warm_ids,
                # The validated opt-in drives gate suppression and exit authors.
                decouple_gate_close=module.decouple_gate_close,
            )
        )
    engine.attach()
    logger.info(
        "HorizonSignalEngine composed: %d SIGNAL alpha(s) attached",
        len(engine.signals),
    )
    return engine


def _union_portfolio_upstream_strategy_ids(
    portfolio_modules: Sequence[LoadedPortfolioLayerModule],
) -> tuple[str, ...]:
    """Sorted union of SIGNAL alpha_ids referenced by PORTFOLIO specs."""
    ids: set[str] = set()
    for m in portfolio_modules:
        ids.update(m.depends_on_signals)
    return tuple(sorted(ids))


def _composition_signal_horizons(
    registry: AlphaRegistry,
    context_horizons: frozenset[int],
    upstream_strategy_ids: tuple[str, ...],
) -> frozenset[int]:
    """Horizons for which the synchronizer caches Layer-2 ``Signal`` events."""
    hs: set[int] = set(context_horizons)
    for sid in upstream_strategy_ids:
        try:
            mod = registry.get(sid)
        except KeyError:
            continue
        h = getattr(mod, "horizon_seconds", None)
        if isinstance(h, int) and h > 0:
            hs.add(h)
    return frozenset(hs)


def _create_composition_layer(
    *,
    config: PlatformConfig,
    bus: EventBus,
    registry: AlphaRegistry,
    position_store: MemoryPositionStore,
    strategy_positions: StrategyPositionStore,
    clock: Clock,
    thread_safe_sequences: bool = True,
) -> CompositionEngine | None:
    """Compose the portfolio pipeline in deterministic bus order.

    Returns ``None`` when no portfolio alpha exists. Oversized universes and
    stale configured factor loadings fail stop before wiring.
    """
    portfolio_alphas = registry.portfolio_alphas()
    if not portfolio_alphas:
        return None

    # Keep the optional Layer-3 implementation outside SIGNAL-only startup.
    # In particular, importing the turnover optimizer must not initialize the
    # CVXPY solver stack when there is no portfolio alpha to compose.
    from feelies.composition.cross_sectional import CrossSectionalRanker
    from feelies.composition.engine import CompositionEngine, RegisteredPortfolioAlpha
    from feelies.composition.factor_neutralizer import (
        FactorNeutralizer,
        MissingFactorLoadingsError,
    )
    from feelies.composition.sector_matcher import SectorMatcher
    from feelies.composition.synchronizer import UniverseSynchronizer
    from feelies.composition.turnover_optimizer import TurnoverOptimizer

    portfolio_modules = [m for m in portfolio_alphas if isinstance(m, LoadedPortfolioLayerModule)]
    if not portfolio_modules:
        # PORTFOLIO alphas exist but none use the layer-3 module type
        # (defensive — the loader always produces this type for
        # ``layer: PORTFOLIO`` specs).  Skip wiring rather than wire
        # half a pipeline.
        logger.warning(
            "PORTFOLIO alphas registered but none are "
            "LoadedPortfolioLayerModule instances; skipping composition wiring"
        )
        return None

    universe: set[str] = set()
    horizons: set[int] = set()
    for module in portfolio_modules:
        universe.update(module.universe)
        horizons.add(module.horizon_seconds)

    if len(universe) > config.composition_max_universe_size:
        raise UniverseScaleError(
            f"PORTFOLIO universe size {len(universe)} exceeds the v0.2 "
            f"cap composition_max_universe_size="
            f"{config.composition_max_universe_size} (§15.1).  Reduce the "
            f"alpha universe(s) or raise the cap explicitly."
        )

    _enforce_factor_loadings_freshness(config, sorted(universe), clock=clock)

    intent_seq = SequenceGenerator(stream="intent", thread_safe=thread_safe_sequences)
    ctx_seq = SequenceGenerator(stream="ctx", thread_safe=thread_safe_sequences)
    metric_seq = SequenceGenerator(stream="metric", thread_safe=thread_safe_sequences)

    upstream_ids = _union_portfolio_upstream_strategy_ids(portfolio_modules)
    signal_horizons = _composition_signal_horizons(
        registry,
        frozenset(horizons),
        upstream_ids,
    )
    synchronizer = UniverseSynchronizer(
        bus=bus,
        universe=universe,
        horizons=horizons,
        ctx_sequence_generator=ctx_seq,
        signal_horizons=signal_horizons,
        upstream_strategy_ids=upstream_ids,
        signal_max_age_seconds=config.composition_signal_max_age_seconds,
    )
    synchronizer.attach()

    try:
        neutralizer = FactorNeutralizer(
            factor_model=config.factor_model,
            loadings_dir=config.factor_loadings_dir,
        )
    except MissingFactorLoadingsError as exc:
        raise StaleFactorLoadingsError(f"FactorNeutralizer construction failed: {exc}") from exc

    sector_matcher = SectorMatcher(
        sector_map_path=config.sector_map_path,
    )

    capital_usd = float(config.account_equity)
    optimizer = TurnoverOptimizer(
        capital_usd=capital_usd,
        # In small universes, a tight per-name cap can collapse relative weights.
        gross_cap_pct=config.composition_gross_cap_pct,
        per_name_cap_pct=config.composition_per_name_cap_pct,
        lambda_tc=config.composition_lambda_tc,
        lambda_risk=config.composition_lambda_risk,
        # Select ECOS explicitly; installed optional packages never change behavior.
        require_solver=(config.composition_optimizer_mode == "ecos"),
    )

    decay_enabled = any(
        bool(m.params.get("decay_weighting_enabled", False)) for m in portfolio_modules
    )
    ranker = CrossSectionalRanker(
        decay_weighting_enabled=decay_enabled,
    )

    def _position_lookup(strategy_id: str, symbol: str) -> float:
        # Turnover is strategy-scoped; market marks remain shared by symbol.
        pos = strategy_positions.get(strategy_id, symbol)
        slice_book = PositionBookView.from_quantities(
            {
                sym: float(p.quantity)
                for sym, p in strategy_positions.open_positions(strategy_id).items()
            }
        )
        mark = position_store.latest_mark(symbol)
        if mark is None:
            mark = pos.avg_entry_price
        return float(int(slice_book.get(symbol)) * Decimal(mark))

    engine = CompositionEngine(
        bus=bus,
        intent_sequence_generator=intent_seq,
        ranker=ranker,
        neutralizer=neutralizer,
        sector_matcher=sector_matcher,
        optimizer=optimizer,
        completeness_threshold=config.composition_completeness_threshold,
        position_lookup=_position_lookup,
    )

    for module in sorted(portfolio_modules, key=lambda m: m.alpha_id):
        # Re-bind the default constructor so its engine-thunk resolves
        # to the engine we just built.  Inline ``construct:`` blocks
        # already carry their own callable. A new module instance is
        # constructed rather than patched after init.
        construct = module._construct  # noqa: SLF001 — bootstrap rewires
        alpha = module
        if isinstance(construct, _DefaultPortfolioConstructor):
            alpha = LoadedPortfolioLayerModule(
                manifest=module.manifest,
                construct=_DefaultPortfolioConstructor(
                    engine_thunk=lambda e=engine: e,
                    strategy_id=module.alpha_id,
                    feeder_strategy_ids=module.depends_on_signals,
                    mechanism_caps=module.mechanism_caps,
                    global_mechanism_cap=module.max_share_of_gross,
                    neutralize=module.factor_neutralization_disclosed,
                    consumes_mechanisms=module.consumes_mechanisms,
                ),
                universe=module.universe,
                horizon_seconds=module.horizon_seconds,
                consumes_mechanisms=module.consumes_mechanisms,
                max_share_of_gross=module.max_share_of_gross,
                factor_neutralization_disclosed=module.factor_neutralization_disclosed,
                depends_on_signals=module.depends_on_signals,
                params=module.params,
                mechanism_caps=module.mechanism_caps,
            )
        engine.register(
            RegisteredPortfolioAlpha(
                alpha_id=module.alpha_id,
                horizon_seconds=module.horizon_seconds,
                alpha=alpha,
                params=module.params,
            )
        )
    engine.attach()

    cross_sectional_tracker = CrossSectionalTracker(bus=bus)
    cross_sectional_tracker.attach()

    horizon_metrics = HorizonMetricsCollector(
        bus=bus,
        metric_sequence_generator=metric_seq,
    )
    horizon_metrics.attach()

    logger.info(
        "PORTFOLIO composition layer composed: %d alpha(s), "
        "universe_size=%d, horizons=%s, decay_weighting=%s",
        len(portfolio_modules),
        len(universe),
        sorted(horizons),
        decay_enabled,
    )

    return engine


def _create_stop_exit_controller(
    *,
    bus: EventBus,
    config: PlatformConfig,
    position_store: MemoryPositionStore,
    trading_session_bounds: TradingSessionBounds | None,
    thread_safe_sequences: bool = True,
) -> StopExitController | None:
    """Attach platform stop and session-flatten exits when configured."""
    policy = StopExitPolicy(
        stop_loss_per_share=config.stop_loss_per_share,
        trail_activate_per_share=config.trail_activate_per_share,
        stop_loss_pct=config.stop_loss_pct,
        trail_activate_pct=config.trail_activate_pct,
        trail_pct=config.trail_pct,
        session_flatten_enabled=config.session_flatten_enabled,
        session_flatten_seconds_before_close=(config.session_flatten_seconds_before_close),
    )
    if not policy.any_enabled:
        return None
    controller = StopExitController(
        bus=bus,
        sequence_generator=SequenceGenerator(
            stream="stop_exit", thread_safe=thread_safe_sequences
        ),
        position_store=position_store,
        policy=policy,
        trading_session_bounds=trading_session_bounds,
    )
    controller.attach()
    logger.info(
        "StopExitController wired: stop=%s (pct=%.4f, per_share=%.4f), "
        "trail=%s (activate_pct=%.4f, retain=%.2f), session_flatten=%s (%ds before close)",
        policy.stop_enabled,
        policy.stop_loss_pct,
        policy.stop_loss_per_share,
        policy.trail_activate_pct > 0 or policy.trail_activate_per_share > 0,
        policy.trail_activate_pct,
        policy.trail_pct,
        policy.session_flatten_enabled,
        policy.session_flatten_seconds_before_close,
    )
    return controller


def _create_hazard_exit_controller(
    *,
    bus: EventBus,
    registry: AlphaRegistry,
    position_store: MemoryPositionStore,
    fallback_universe: Iterable[str],
    thread_safe_sequences: bool = True,
) -> HazardExitController | None:
    """Attach hazard-exit policies declared by SIGNAL or PORTFOLIO alphas."""
    fallback = tuple(sorted(fallback_universe))

    candidates = [
        m
        for m in registry.active_alphas()
        if _hazard_block_enabled(getattr(m.manifest, "hazard_exit", None))
    ]
    if not candidates:
        return None

    seq = SequenceGenerator(stream="hazard_exit", thread_safe=thread_safe_sequences)
    controller = HazardExitController(
        bus=bus,
        sequence_generator=seq,
        position_store=position_store,
    )
    for module in sorted(candidates, key=lambda m: m.manifest.alpha_id):
        block = getattr(module.manifest, "hazard_exit", None) or {}
        alpha_id = module.manifest.alpha_id
        per_universe = tuple(getattr(module, "universe", ()) or ())
        universe = per_universe or fallback

        explicit_hard = block.get("hard_exit_age_seconds")
        if explicit_hard is None:
            half_life = int(getattr(module, "expected_half_life_seconds", 0) or 0)
            if half_life <= 0:
                # LoadedPortfolioLayerModule does not expose
                # ``expected_half_life_seconds`` directly; fall back to the
                # manifest's ``trend_mechanism:`` block so PORTFOLIO alphas
                # also benefit from the HM-1 default.
                tm_block = getattr(module.manifest, "trend_mechanism", None) or {}
                try:
                    half_life = int(tm_block.get("expected_half_life_seconds", 0) or 0)
                except (TypeError, ValueError):
                    half_life = 0
            derived_hard = 2 * half_life if half_life > 0 else None
            hard_exit = derived_hard
        else:
            hard_exit = int(explicit_hard)

        policy = HazardPolicy(
            strategy_id=alpha_id,
            hazard_score_threshold=float(
                block.get(
                    "hazard_score_threshold",
                    HazardPolicy.__dataclass_fields__["hazard_score_threshold"].default,
                )
            ),
            min_age_seconds=int(
                block.get(
                    "min_age_seconds",
                    HazardPolicy.__dataclass_fields__["min_age_seconds"].default,
                )
            ),
            hard_exit_age_seconds=hard_exit,
            universe=universe,
            # §20.5.3: loader already validated/canonicalized to a tuple of
            # "<from> -> <to>" / bare-state strings; empty ⇒ all departures.
            applies_to_regimes=tuple(block.get("applies_to_regimes", ()) or ()),
        )
        controller.register_policy(policy)

    controller.attach()
    logger.info(
        "HazardExitController wired: %d alpha(s) opted in (%s); "
        "default hard_exit_age_seconds for missing values = "
        "2 × expected_half_life_seconds",
        len(candidates),
        ", ".join(sorted(m.manifest.alpha_id for m in candidates)),
    )
    return controller


def _hazard_block_enabled(block: object | None) -> bool:
    if not isinstance(block, dict):
        return False
    return bool(block.get("enabled", False)) is True


def _create_exit_composer(
    *,
    bus: EventBus,
    horizon_signal_engine: HorizonSignalEngine | None,
    strategy_positions: StrategyPositionStore,
    fallback_universe: Iterable[str],
    thread_safe_sequences: bool = True,
) -> ExitComposer | None:
    """Attach the Stage-0 exit composer for decoupled SIGNAL alphas."""
    if horizon_signal_engine is None:
        return None
    decoupled = [s for s in horizon_signal_engine.signals if s.decouple_gate_close]
    if not decoupled:
        return None

    fallback = tuple(sorted(fallback_universe))
    composer = ExitComposer(
        bus=bus,
        sequence_generator=SequenceGenerator(
            stream="exit_composer", thread_safe=thread_safe_sequences
        ),
        position_store=strategy_positions,
    )
    for registered in sorted(decoupled, key=lambda s: s.alpha_id):
        composer.register_policy(
            ExitComposerPolicy(
                strategy_id=registered.alpha_id,
                universe=fallback,
                # Stage 0: no story map configured (Phase-4/Stage-1 flips this).
                story_configured=False,
            )
        )
    composer.attach()
    logger.info(
        "ExitComposer wired: %d decoupled SIGNAL alpha(s) (%s)",
        len(decoupled),
        ", ".join(sorted(s.alpha_id for s in decoupled)),
    )
    return composer


def _create_deferral_cap_controller(
    *,
    bus: EventBus,
    registry: AlphaRegistry,
    horizon_signal_engine: HorizonSignalEngine | None,
    strategy_positions: StrategyPositionStore,
    fallback_universe: Iterable[str],
    session_flatten_enabled: bool,
    session_flatten_seconds_before_close: int,
    thread_safe_sequences: bool = True,
) -> DeferralCapController | None:
    """Attach bounded-deferral exits for decoupled SIGNAL alphas."""
    if horizon_signal_engine is None:
        return None
    decoupled = [s for s in horizon_signal_engine.signals if s.decouple_gate_close]
    if not decoupled:
        return None

    fallback = tuple(sorted(fallback_universe))
    controller = DeferralCapController(
        bus=bus,
        sequence_generator=SequenceGenerator(
            stream="deferral_cap", thread_safe=thread_safe_sequences
        ),
        position_store=strategy_positions,
        session_flatten_enabled=session_flatten_enabled,
        session_flatten_seconds_before_close=session_flatten_seconds_before_close,
    )
    for registered in sorted(decoupled, key=lambda s: s.alpha_id):
        alpha_id = registered.alpha_id
        block = registry.get(alpha_id).manifest.safety_exit_policy or {}
        max_hold = block.get("max_hold_after_safe_off")
        hard_age = block.get("hard_exit_age_seconds")
        if max_hold is None or hard_age is None:
            # Unreachable via the loader, which rejects a decoupled spec missing
            # either ceiling (design §3.6).  Fail loudly rather than wire a
            # controller that would silently never bound the deferral.
            raise ValueError(
                f"alpha {alpha_id!r} is decoupled (decouple_caps_only) but its "
                f"safety_exit_policy is missing "
                f"{'max_hold_after_safe_off' if max_hold is None else 'hard_exit_age_seconds'}; "
                "both ceilings are mandatory under decoupling (design §2.3/§3.6)"
            )
        controller.register_policy(
            DeferralPolicy(
                strategy_id=alpha_id,
                max_hold_after_safe_off_seconds=int(max_hold),
                hard_exit_age_seconds=int(hard_age),
                universe=fallback,
            )
        )
    controller.attach()
    logger.info(
        "DeferralCapController wired: %d decoupled SIGNAL alpha(s) (%s)",
        len(decoupled),
        ", ".join(sorted(s.alpha_id for s in decoupled)),
    )
    return controller


def _enforce_ex_date_replay_guard(
    config: PlatformConfig,
    event_log: InMemoryEventLog,
    *,
    precomputed_spans: dict[str, tuple[date, date]] | None = None,
) -> None:
    """Refuse backtests whose replay span crosses a known ex-date."""
    if not config.backtest_enforce_ex_date_guard:
        return
    if config.mode.name != "BACKTEST":
        return
    if config.ex_date_calendar_path is None:
        return
    from feelies.storage.reference.corporate_actions import (
        RAW_UNADJUSTED_L1_POLICY,
        check_ex_date_replay_window,
        load_ex_date_calendar,
    )

    calendar = load_ex_date_calendar(config.ex_date_calendar_path)
    violations = check_ex_date_replay_window(
        config.symbols,
        event_log,
        calendar,
        precomputed_spans=precomputed_spans,
    )
    if not violations:
        return
    detail = "; ".join(v.message() for v in violations)
    raise ConfigurationError(f"BT-18 ex-date replay guard ({RAW_UNADJUSTED_L1_POLICY}): {detail}")


def _enforce_factor_loadings_freshness(
    config: PlatformConfig,
    universe_sorted: list[str],
    *,
    clock: Clock,
) -> None:
    """Require a fresh factor row for every composition symbol.

    The check is fail-stop and uses the injected clock for deterministic age."""
    if config.factor_loadings_dir is None:
        return
    import json

    path = config.factor_loadings_dir / "loadings.json"
    if not path.is_file():
        raise StaleFactorLoadingsError(f"factor loadings file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StaleFactorLoadingsError(f"cannot parse factor loadings file {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise StaleFactorLoadingsError(f"factor loadings file {path} is not a JSON object")

    # Effective file timestamp: embedded ``_meta.as_of_ns`` (reproducible)
    # else filesystem mtime (drifts with the checkout).
    embedded_as_of_seconds: float | None = None
    meta = data.get("_meta")
    if isinstance(meta, dict):
        raw_as_of = meta.get("as_of_ns")
        if isinstance(raw_as_of, (int, float)) and not isinstance(raw_as_of, bool):
            embedded_as_of_seconds = float(raw_as_of) / 1_000_000_000
    file_as_of_seconds = (
        embedded_as_of_seconds if embedded_as_of_seconds is not None else path.stat().st_mtime
    )

    if config.session_open_ns is not None:
        reference_time = config.session_open_ns / 1_000_000_000
    elif config.mode.name != "BACKTEST":
        reference_time = clock.now_ns() / 1_000_000_000
        logger.warning(
            "factor loadings freshness: no session_open_ns configured; using the "
            "injected wall clock as the reference — configure session_open_ns or "
            "embed _meta.as_of_ns in %s for a reproducible verdict",
            path,
        )
    else:
        raise StaleFactorLoadingsError(
            f"factor_loadings_dir is configured ({config.factor_loadings_dir}) but "
            "session_open_ns is unset in BACKTEST mode, so there is no causal "
            "reference time to evaluate freshness against (Inv-5/Inv-11: refuse "
            "rather than guess). Set session_open_ns, or embed _meta.as_of_ns in "
            f"{path} and compare it via session_open_ns once set."
        )
    age_seconds = reference_time - file_as_of_seconds
    if age_seconds > config.factor_loadings_max_age_seconds:
        raise StaleFactorLoadingsError(
            f"factor loadings file {path} is {age_seconds:.0f}s old, "
            f"exceeds factor_loadings_max_age_seconds="
            f"{config.factor_loadings_max_age_seconds}s"
        )

    missing = [s for s in universe_sorted if s not in data]
    if missing:
        raise StaleFactorLoadingsError(
            f"factor loadings file {path} is missing rows for "
            f"{len(missing)} universe symbol(s): {missing[:8]}"
            + ("..." if len(missing) > 8 else "")
        )
