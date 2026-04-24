"""Bootstrap — one-call system composition from configuration.

Reads a ``PlatformConfig`` (or YAML path), discovers alphas, creates
a shared ``RegimeEngine``, composes all layers, and returns a
ready-to-boot ``Orchestrator``.

This is the only place where concrete implementations are selected
and wired together.  The orchestrator and all downstream components
interact only through protocols.

Bus subscription order (Inv-D in the Phase-2 / Phase-3 plan)
------------------------------------------------------------

Subscriptions on the shared ``EventBus`` are dispatched in
**registration order** (see :class:`feelies.bus.event_bus.EventBus`).
For deterministic forensic ordering across runs we register handlers
in this canonical order:

1. ``BacktestOrderRouter`` (when present) — receives ``NBBOQuote``
   first so resting-order fills are attributed to the quote that
   triggered them, before any sensor sees the same quote.
2. ``SensorRegistry`` — single subscriber per ``NBBOQuote`` /
   ``Trade``; fans out to every registered sensor in spec order.
3. ``HorizonAggregator`` — Phase-2-β subscriber; consumes
   ``HorizonTick`` + ``SensorReading`` and emits
   ``HorizonFeatureSnapshot`` (passive in P2-α).
4. ``HorizonSignalEngine`` — Phase-3-α subscriber; consumes
   ``HorizonFeatureSnapshot`` + ``RegimeState`` + ``SensorReading``
   and emits ``Signal(layer='SIGNAL')`` events.  Subscribed *after*
   the aggregator so the snapshot it receives is the canonical
   per-boundary view.
5. ``MetricEvent`` consumers — wired by the orchestrator
   constructor (the ``MetricCollector``) so metrics drained later in
   the tick are recorded after every functional handler ran.

Phase-2 components (``SensorRegistry``, ``HorizonScheduler``,
``HorizonAggregator``) are only constructed when
``config.sensor_specs`` is non-empty *or* when
``config.horizons_seconds`` is non-empty AND the operator opts in by
mode (see ``_create_sensor_layer``).  Phase-3 components
(``HorizonSignalEngine``) are only constructed when at least one
``layer: SIGNAL`` alpha is registered (see
``_create_signal_layer``).  Default ``PlatformConfig`` instances
therefore wire **no Phase-2 / Phase-3 components**, preserving the
legacy execution path bit-for-bit (Inv-A).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

from feelies.alpha.composite import CompositeFeatureEngine, CompositeSignalEngine
from feelies.alpha.discovery import load_and_register
from feelies.alpha.fill_attribution import FillAttributionLedger
from feelies.alpha.loader import AlphaLoader
from feelies.alpha.multi_alpha_evaluator import MultiAlphaEvaluator
from feelies.alpha.portfolio_layer_module import (
    LoadedPortfolioLayerModule,
    _DefaultPortfolioConstructor,
)
from feelies.alpha.registry import AlphaRegistry
from feelies.alpha.risk_wrapper import AlphaBudgetRiskWrapper
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.bus.event_bus import EventBus
from feelies.composition.cross_sectional import CrossSectionalRanker
from feelies.composition.engine import (
    CompositionEngine,
    RegisteredPortfolioAlpha,
)
from feelies.composition.factor_neutralizer import (
    FactorNeutralizer,
    MissingFactorLoadingsError,
)
from feelies.composition.sector_matcher import SectorMatcher
from feelies.composition.synchronizer import UniverseSynchronizer
from feelies.composition.turnover_optimizer import TurnoverOptimizer
from feelies.core.clock import Clock, SimulatedClock, WallClock
from feelies.core.events import NBBOQuote
from feelies.core.errors import ConfigurationError
from feelies.core.identifiers import SequenceGenerator
from feelies.core.platform_config import OperatingMode, PlatformConfig
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
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter
from feelies.features.aggregator import HorizonAggregator
from feelies.kernel.orchestrator import Orchestrator
from feelies.monitoring.in_memory import (
    InMemoryAlertManager,
    InMemoryKillSwitch,
    InMemoryMetricCollector,
)
from feelies.monitoring.horizon_metrics import HorizonMetricsCollector
from feelies.portfolio.cross_sectional_tracker import CrossSectionalTracker
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.risk.hazard_exit import HazardExitController, HazardPolicy
from feelies.risk.position_sizer import BudgetBasedSizer
from feelies.services.regime_engine import RegimeEngine, get_regime_engine
from feelies.services.regime_hazard_detector import RegimeHazardDetector
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.storage.memory_feature_snapshot import InMemoryFeatureSnapshotStore
from feelies.storage.memory_trade_journal import InMemoryTradeJournal

logger = logging.getLogger(__name__)


class StaleFactorLoadingsError(RuntimeError):
    """Raised when factor loadings are missing or stale at bootstrap.

    Phase-4-finalize hard fail-stop: every symbol in any loaded
    PORTFOLIO alpha's effective universe MUST have a fresh loadings
    row (within ``factor_loadings_max_age_seconds``) — otherwise the
    composition pipeline would silently neutralize against a stale
    factor model.  Inv-11 fail-safe: refuse to boot rather than emit
    quietly-wrong sized intents.
    """


class UniverseScaleError(RuntimeError):
    """Raised when a PORTFOLIO universe exceeds the v0.2 cap (§15.1)."""


def build_platform(
    config: PlatformConfig | str | Path,
    event_log: InMemoryEventLog | None = None,
) -> tuple[Orchestrator, PlatformConfig]:
    """Compose the full platform from configuration.

    Args:
        config: A ``PlatformConfig`` instance, or a path to a YAML file.
        event_log: Optional pre-populated event log (for backtest with
            pre-ingested data).  If None, an empty in-memory log is created.

    Returns:
        ``(orchestrator, config)`` — caller does
        ``orchestrator.boot(config)`` then ``orchestrator.run_*()``.
    """
    if isinstance(config, (str, Path)):
        config = PlatformConfig.from_yaml(config)

    config.validate()

    clock = _select_clock(config.mode)
    bus = EventBus()

    regime_engine = _create_regime_engine(config.regime_engine)

    registry_clock = None if config.mode == OperatingMode.BACKTEST else clock
    registry = AlphaRegistry(clock=registry_clock)
    loader = AlphaLoader(
        regime_engine=regime_engine,
        enforce_trend_mechanism=config.enforce_trend_mechanism,
        enforce_layer_gates=config.enforce_layer_gates,
    )

    _load_alphas(config, registry, loader)

    feature_engine = CompositeFeatureEngine(registry, clock)
    signal_engine = CompositeSignalEngine(
        registry,
        entry_cooldown_ticks=config.signal_entry_cooldown_ticks,
    )

    risk_config = RiskConfig(
        max_position_per_symbol=config.risk_max_position_per_symbol,
        max_gross_exposure_pct=config.risk_max_gross_exposure_pct,
        max_drawdown_pct=config.risk_max_drawdown_pct,
        account_equity=_decimal(config.account_equity),
    )
    risk_engine = BasicRiskEngine(
        config=risk_config,
        regime_engine=regime_engine,
    )

    if event_log is None:
        event_log = InMemoryEventLog()

    cost_model = DefaultCostModel(DefaultCostModelConfig(
        min_spread_cost_bps=_decimal(config.cost_min_spread_bps),
        commission_per_share=_decimal(config.cost_commission_per_share),
        taker_exchange_per_share=_decimal(config.cost_taker_exchange_per_share),
        maker_exchange_per_share=_decimal(config.cost_maker_exchange_per_share),
        passive_adverse_selection_bps=_decimal(config.cost_passive_adverse_selection_bps),
        sell_regulatory_bps=_decimal(config.cost_sell_regulatory_bps),
        stress_multiplier=_decimal(config.cost_stress_multiplier),
        min_commission=_decimal(config.cost_min_commission),
        max_commission_pct=_decimal(config.cost_max_commission_pct),
        htb_borrow_annual_bps=_decimal(config.cost_htb_borrow_annual_bps),
    ))
    backend, backtest_router = _create_backend(
        config.mode, event_log, clock,
        fill_latency_ns=config.backtest_fill_latency_ns,
        cost_model=cost_model,
        execution_mode=config.execution_mode,
        passive_fill_delay_ticks=config.passive_fill_delay_ticks,
        passive_max_resting_ticks=config.passive_max_resting_ticks,
        passive_queue_position_shares=config.passive_queue_position_shares,
        passive_cancel_fee_per_share=config.passive_cancel_fee_per_share,
        market_impact_factor=config.cost_market_impact_factor,
    )

    if backtest_router is not None:
        bus.subscribe(NBBOQuote, lambda e: backtest_router.on_quote(e))  # type: ignore[arg-type]

    # ── Phase-2 sensor layer (additive, optional) ─────────────────
    # Constructed *after* the backtest-router subscription so resting
    # fills attribute to the quote that triggered them before any
    # sensor sees the same quote (Inv-D / canonical bus ordering, see
    # module docstring).  When ``config.sensor_specs`` is empty the
    # registry is created but stays subscription-less and ``is_empty()``
    # returns True, so the orchestrator transparently skips the new
    # micro-states (Inv-A: legacy bit-identical path preserved).
    position_store = MemoryPositionStore()
    strategy_positions = StrategyPositionStore()
    trade_journal = InMemoryTradeJournal()
    feature_snapshots = InMemoryFeatureSnapshotStore()
    position_sizer = BudgetBasedSizer(regime_engine=regime_engine)
    intent_translator = SignalPositionTranslator()

    kill_switch = InMemoryKillSwitch()
    alert_manager = InMemoryAlertManager(kill_switch=kill_switch)
    metric_collector = InMemoryMetricCollector()

    # Compose the Phase-2 sensor layer *after* the metric collector
    # exists so monitoring metrics (plan §4.5) wire automatically.
    (
        sensor_seq,
        horizon_seq,
        snapshot_seq,
        sensor_registry,
        horizon_scheduler,
        horizon_aggregator,
    ) = _create_sensor_layer(config, bus, metric_collector=metric_collector)
    # ``horizon_aggregator`` is intentionally unused below; it is
    # already attached to the bus inside ``_create_sensor_layer`` and
    # does not require any orchestrator-side wiring in Phase 2 because
    # the orchestrator never reads ``HorizonFeatureSnapshot`` events
    # (they are consumed by forensics / parity recorders only).
    del horizon_aggregator

    # ── Phase-3 SIGNAL layer (additive, optional) ─────────────────
    # Created *after* the aggregator so its bus subscription is
    # registered after the aggregator's — the canonical handler-call
    # order is therefore: BacktestRouter → SensorRegistry →
    # HorizonAggregator → HorizonSignalEngine → MetricCollector
    # (Inv-D / module docstring).
    #
    # Resolves SIGNAL-alpha sensor dependencies fail-fast against the
    # constructed sensor registry, so any missing sensor surfaces at
    # boot rather than as silent suppression at first snapshot.
    signal_seq, horizon_signal_engine = _create_signal_layer(
        registry=registry,
        bus=bus,
        clock=clock,
        sensor_registry=sensor_registry,
    )

    # ── Phase-4 PORTFOLIO / composition layer (additive, optional) ──
    #
    # Constructed *after* the SIGNAL engine so the bus subscription
    # ordering is: (existing handlers) → UniverseSynchronizer →
    # CompositionEngine → CrossSectionalTracker → HorizonMetricsCollector.
    # This keeps the snapshot/signal/tick handlers running BEFORE the
    # synchronizer reads the cache, and the engine reads the context
    # AFTER the synchronizer publishes it (single-threaded synchronous
    # bus dispatch).
    #
    # When no PORTFOLIO alpha is registered the helper returns all
    # ``None`` and the orchestrator's optional ctor args stay unset
    # (Inv-A: legacy LEGACY_SIGNAL parity hash unchanged).
    (
        composition_engine,
        cross_sectional_tracker,
        composition_metrics,
        hazard_exit_controller,
    ) = _create_composition_layer(
        config=config,
        bus=bus,
        registry=registry,
        position_store=position_store,
    )

    # Phase-3.1: hazard detector + dedicated _hazard_seq generator.
    # Constructed only when at least one alpha declares
    # ``hazard_exit.enabled: true`` so default deployments stay
    # bit-identical to v0.2 (Inv-A).  When constructed but no
    # regime engine is wired, the orchestrator silently skips
    # publishing spikes — the detector still exists but never
    # observes a RegimeState pair.
    hazard_seq, regime_hazard_detector = _create_hazard_detector(registry)

    # ── Multi-alpha execution components ──
    risk_wrapper = AlphaBudgetRiskWrapper(
        inner=risk_engine,
        registry=registry,
        strategy_positions=strategy_positions,
        platform_config=risk_config,
        account_equity=_decimal(config.account_equity),
    )
    fill_ledger = FillAttributionLedger()
    multi_alpha_evaluator: MultiAlphaEvaluator | None = None
    if len(registry) > 1:
        multi_alpha_evaluator = MultiAlphaEvaluator(
            registry=registry,
            intent_translator=intent_translator,
            risk_wrapper=risk_wrapper,
            strategy_positions=strategy_positions,
            position_sizer=position_sizer,
            account_equity=_decimal(config.account_equity),
            entry_cooldown_ticks=config.signal_entry_cooldown_ticks,
        )

    orchestrator = Orchestrator(
        clock=clock,
        bus=bus,
        backend=backend,
        feature_engine=feature_engine,
        signal_engine=signal_engine,
        risk_engine=risk_engine,
        position_store=position_store,
        event_log=event_log,
        metric_collector=metric_collector,
        alert_manager=alert_manager,
        kill_switch=kill_switch,
        regime_engine=regime_engine,
        position_sizer=position_sizer,
        intent_translator=intent_translator,
        alpha_registry=registry,
        account_equity=_decimal(config.account_equity),
        trade_journal=trade_journal,
        feature_snapshots=feature_snapshots,
        multi_alpha_evaluator=multi_alpha_evaluator,
        fill_ledger=fill_ledger,
        strategy_positions=strategy_positions,
        cost_model=cost_model,
        sensor_registry=sensor_registry,
        horizon_scheduler=horizon_scheduler,
        horizon_signal_engine=horizon_signal_engine,
        sensor_sequence_generator=sensor_seq,
        horizon_sequence_generator=horizon_seq,
        snapshot_sequence_generator=snapshot_seq,
        signal_sequence_generator=signal_seq,
        regime_hazard_detector=regime_hazard_detector,
        hazard_sequence_generator=hazard_seq,
        composition_engine=composition_engine,
        cross_sectional_tracker=cross_sectional_tracker,
        composition_metrics_collector=composition_metrics,
        hazard_exit_controller=hazard_exit_controller,
    )

    config_snapshot = config.snapshot()
    orchestrator.config_snapshot = config_snapshot  # type: ignore[attr-defined]

    logger.info(
        "Platform composed: mode=%s, symbols=%s, alphas=%d, regime=%s, "
        "config_checksum=%s",
        config.mode.name,
        sorted(config.symbols),
        len(registry),
        config.regime_engine or "none",
        config_snapshot.checksum[:12],
    )

    return orchestrator, config


def _select_clock(mode: OperatingMode) -> Clock:
    if mode == OperatingMode.BACKTEST:
        return SimulatedClock()
    return WallClock()


def _create_regime_engine(engine_name: str | None) -> RegimeEngine | None:
    if engine_name is None:
        return None
    try:
        engine = get_regime_engine(engine_name)
        logger.info("Created shared RegimeEngine: %s", engine_name)
        return engine
    except KeyError:
        raise ConfigurationError(
            f"Unknown regime engine '{engine_name}': not found in registry. "
            "Check the 'regime_engine' field in your platform configuration."
        ) from None


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
        alpha_id_guess = name[:-len(".alpha.yaml")] if name.endswith(".alpha.yaml") else spec_path.stem
        overrides = config.parameter_overrides.get(alpha_id_guess)
        module = loader.load(spec_path, param_overrides=overrides)
        registry.register(module)
        logger.info("Registered alpha '%s' from explicit path %s", module.manifest.alpha_id, spec_path)


def _create_backend(
    mode: OperatingMode,
    event_log: InMemoryEventLog,
    clock: Clock,
    *,
    fill_latency_ns: int = 0,
    cost_model: DefaultCostModel | None = None,
    execution_mode: str = "market",
    passive_fill_delay_ticks: int = 3,
    passive_max_resting_ticks: int = 50,
    passive_queue_position_shares: int = 0,
    passive_cancel_fee_per_share: float = 0.0,
    market_impact_factor: float = 0.5,
) -> tuple[ExecutionBackend, BacktestOrderRouter | PassiveLimitOrderRouter | None]:
    if mode == OperatingMode.BACKTEST:
        if execution_mode == "passive_limit":
            backend, router = build_passive_limit_backend(
                event_log, clock,
                latency_ns=fill_latency_ns,
                cost_model=cost_model,
                fill_delay_ticks=passive_fill_delay_ticks,
                max_resting_ticks=passive_max_resting_ticks,
                queue_position_shares=passive_queue_position_shares,
                cancel_fee_per_share=_decimal(passive_cancel_fee_per_share),
            )
            return backend, router

        backend, router = build_backtest_backend(
            event_log, clock,
            latency_ns=fill_latency_ns,
            cost_model=cost_model,
            market_impact_factor=market_impact_factor,
        )
        return backend, router

    raise NotImplementedError(
        f"ExecutionBackend for mode {mode.name} is not yet implemented. "
        f"Paper and live routers are future work."
    )


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _derive_session_id(config: PlatformConfig) -> str:
    """Build a deterministic session id from platform config.

    The session id is folded into every ``HorizonTick.session_id``
    field; consumers use it for forensic grouping.  Format
    (plan §3.2 / M5):

        f"{market_id}_{session_kind}_{date}"

    where ``date`` is derived from ``session_open_ns`` when set, else
    ``"UNANCHORED"`` (signalling the scheduler will lazy-bind on the
    first event).
    """
    if config.session_open_ns is None:
        date_str = "UNANCHORED"
    else:
        # nanoseconds since epoch → ISO date (UTC); avoids any
        # timezone-dependent drift that would defeat replay parity.
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(
            config.session_open_ns / 1_000_000_000, tz=timezone.utc
        )
        date_str = dt.strftime("%Y-%m-%d")
    return f"{config.market_id}_{config.session_kind}_{date_str}"


def _create_sensor_layer(
    config: PlatformConfig,
    bus: EventBus,
    *,
    metric_collector: InMemoryMetricCollector | None = None,
) -> tuple[
    SequenceGenerator,
    SequenceGenerator,
    SequenceGenerator,
    SensorRegistry | None,
    HorizonScheduler | None,
    HorizonAggregator | None,
]:
    """Compose the Phase-2 sensor layer.

    Returns a 6-tuple ``(sensor_seq, horizon_seq, snapshot_seq,
    sensor_registry, horizon_scheduler, horizon_aggregator)``.

    Even when no sensors are configured we still return fresh
    ``SequenceGenerator`` instances so the orchestrator has stable
    counters to reference; they simply never advance in that case.
    The registry, scheduler and aggregator are returned as ``None``
    when the config has no sensors (registry) or no horizons
    (scheduler / aggregator), so the orchestrator's dispatch helpers
    short-circuit for free.

    Subscription order is governed by the module-level docstring and
    is the *single* place this is documented authoritatively.
    """
    sensor_seq = SequenceGenerator()
    horizon_seq = SequenceGenerator()
    snapshot_seq = SequenceGenerator()

    sensor_registry: SensorRegistry | None = None
    if config.sensor_specs:
        sensor_registry = SensorRegistry(
            bus=bus,
            sequence_generator=sensor_seq,
            symbols=frozenset(config.symbols),
            metric_collector=metric_collector,
        )
        for spec in config.sensor_specs:
            sensor_registry.register(spec)
        logger.info(
            "Sensor registry composed: %d specs, %d symbols",
            len(config.sensor_specs),
            len(config.symbols),
        )

    horizon_scheduler: HorizonScheduler | None = None
    horizon_aggregator: HorizonAggregator | None = None
    if config.horizons_seconds and (
        sensor_registry is not None or config.sensor_specs
    ):
        # Only construct the scheduler when sensors exist; without
        # downstream consumers the scheduler would emit ticks into
        # the void and inflate the bus traffic for no benefit.  This
        # also keeps the legacy demo (no sensors) free of any
        # HorizonTick events.
        horizon_scheduler = HorizonScheduler(
            horizons=config.horizons_seconds,
            session_id=_derive_session_id(config),
            symbols=frozenset(config.symbols),
            session_open_ns=config.session_open_ns,
            sequence_generator=horizon_seq,
            metric_collector=metric_collector,
        )
        logger.info(
            "HorizonScheduler composed: horizons=%s, session_id=%s, "
            "session_open_ns=%s",
            sorted(config.horizons_seconds),
            horizon_scheduler._session_id if hasattr(
                horizon_scheduler, "_session_id"
            ) else "<unknown>",
            config.session_open_ns,
        )
        # Buffer 2 × max(horizon) per plan §4.3 so any feature whose
        # window equals the longest registered horizon still has full
        # history available at finalize time.
        sensor_buffer_seconds = 2 * max(config.horizons_seconds)
        horizon_aggregator = HorizonAggregator(
            bus=bus,
            horizon_features={},  # passive in Phase 2 — see plan §4.3.
            symbols=frozenset(config.symbols),
            sensor_buffer_seconds=sensor_buffer_seconds,
            sequence_generator=snapshot_seq,
            metric_collector=metric_collector,
        )
        horizon_aggregator.attach()
        logger.info(
            "HorizonAggregator composed (passive mode): "
            "buffer_window=%ds, symbols=%d",
            sensor_buffer_seconds,
            len(config.symbols),
        )

    return (
        sensor_seq,
        horizon_seq,
        snapshot_seq,
        sensor_registry,
        horizon_scheduler,
        horizon_aggregator,
    )


def _create_hazard_detector(
    registry: AlphaRegistry,
) -> tuple[SequenceGenerator, RegimeHazardDetector | None]:
    """Construct a :class:`RegimeHazardDetector` iff any alpha opts in.

    Returns ``(hazard_seq, detector_or_None)``.  The sequence generator
    is always returned so the orchestrator has a stable counter
    reference even when no alpha uses hazard exits — the empty counter
    advances zero times in that case (Inv-A: bit-identical legacy
    parity preserved).

    Activation rule (§20.7.1): the detector is only constructed when
    at least one registered alpha's manifest declares
    ``hazard_exit.enabled: true``.  This keeps the default Phase-3-α
    deployment free of any hazard-related cost and ensures Level-5
    parity hash baselines are not generated by accident.
    """
    hazard_seq = SequenceGenerator()

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
) -> tuple[SequenceGenerator, HorizonSignalEngine | None]:
    """Compose the Phase-3 :class:`HorizonSignalEngine` if SIGNAL alphas exist.

    Returns ``(signal_seq, engine_or_None)``.  The sequence generator
    is always returned (so the orchestrator has a stable counter
    reference even when the engine is absent — Inv-A: legacy
    deployments continue to use the empty counter and emit identical
    bytes).

    SIGNAL-alpha sensor dependencies are resolved against
    ``sensor_registry``'s declared spec ids before the engine is
    attached.  When ``sensor_registry is None`` the engine still
    receives the empty sensor universe; loaders that declared
    ``depends_on_sensors`` will fail validation at boot via
    :class:`feelies.alpha.registry.UnresolvedDependencyError`.
    """
    signal_seq = SequenceGenerator()

    signal_alphas = registry.signal_alphas()
    if not signal_alphas:
        return signal_seq, None

    if sensor_registry is None:
        known_sensor_ids: frozenset[str] = frozenset()
    else:
        known_sensor_ids = frozenset(
            spec.sensor_id for spec in sensor_registry.specs
        )

    registry.resolve_signal_dependencies(known_sensor_ids)

    engine = HorizonSignalEngine(
        bus=bus,
        signal_sequence_generator=signal_seq,
        clock=clock,
    )
    for module in signal_alphas:
        if not isinstance(module, LoadedSignalLayerModule):
            continue
        engine.register(RegisteredSignal(
            alpha_id=module.manifest.alpha_id,
            horizon_seconds=module.horizon_seconds,
            signal=module.signal,
            params=module.params,
            gate=module.gate,
            cost_arithmetic=module.cost,
            trend_mechanism=module.trend_mechanism_enum,
            expected_half_life_seconds=module.expected_half_life_seconds,
            consumed_features=module.consumed_features,
        ))
    engine.attach()
    logger.info(
        "HorizonSignalEngine composed: %d SIGNAL alpha(s) attached",
        len(engine.signals),
    )
    return signal_seq, engine


def _create_composition_layer(
    *,
    config: PlatformConfig,
    bus: EventBus,
    registry: AlphaRegistry,
    position_store: MemoryPositionStore,
) -> tuple[
    CompositionEngine | None,
    CrossSectionalTracker | None,
    HorizonMetricsCollector | None,
    HazardExitController | None,
]:
    """Compose the Phase-4 PORTFOLIO / composition layer (additive).

    Returns ``(composition_engine, cross_sectional_tracker,
    horizon_metrics_collector, hazard_exit_controller)``.  All four
    are ``None`` when no PORTFOLIO alpha is registered — the legacy
    LEGACY_SIGNAL parity hash stays bit-stable in that case (Inv-A).

    Subscription order on the shared bus (registration order is
    dispatch order):

        UniverseSynchronizer.attach()
            → emits CrossSectionalContext after barrier close
        CompositionEngine.attach()
            → consumes CrossSectionalContext, publishes
              SizedPositionIntent
        CrossSectionalTracker.attach()
            → records per-strategy gross/net/factor breakdown
        HorizonMetricsCollector.attach()
            → publishes 12 composition + hazard metrics
        HazardExitController.attach()
            → consumes RegimeHazardSpike + Trade, publishes
              OrderRequest(reason="HAZARD_SPIKE" | "HARD_EXIT_AGE")

    Fail-stop guards (Inv-11):

    * ``UniverseScaleError`` when any PORTFOLIO universe exceeds
      ``composition_max_universe_size``.
    * ``StaleFactorLoadingsError`` when the configured loadings file
      is older than ``factor_loadings_max_age_seconds``.  The check
      is bypassed when ``factor_loadings_dir`` is ``None`` (which
      makes the neutralizer a no-op anyway).
    """
    portfolio_alphas = registry.portfolio_alphas()
    if not portfolio_alphas:
        return None, None, None, None

    portfolio_modules = [
        m for m in portfolio_alphas
        if isinstance(m, LoadedPortfolioLayerModule)
    ]
    if not portfolio_modules:
        # PORTFOLIO alphas exist but none use the layer-3 module type
        # (defensive — the loader always produces this type for
        # ``layer: PORTFOLIO`` specs).  Skip wiring rather than wire
        # half a pipeline.
        logger.warning(
            "PORTFOLIO alphas registered but none are "
            "LoadedPortfolioLayerModule instances; skipping composition wiring"
        )
        return None, None, None, None

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

    _enforce_factor_loadings_freshness(config, sorted(universe))

    intent_seq = SequenceGenerator()
    ctx_seq = SequenceGenerator()
    metric_seq = SequenceGenerator()

    synchronizer = UniverseSynchronizer(
        bus=bus,
        universe=universe,
        horizons=horizons,
        ctx_sequence_generator=ctx_seq,
    )
    synchronizer.attach()

    try:
        neutralizer = FactorNeutralizer(
            factor_model=config.factor_model,
            loadings_dir=config.factor_loadings_dir,
        )
    except MissingFactorLoadingsError as exc:
        raise StaleFactorLoadingsError(
            f"FactorNeutralizer construction failed: {exc}"
        ) from exc

    sector_matcher = SectorMatcher(
        sector_map_path=config.sector_map_path,
    )

    capital_usd = float(config.account_equity)
    optimizer = TurnoverOptimizer(
        capital_usd=capital_usd,
        lambda_tc=config.composition_lambda_tc,
        lambda_risk=config.composition_lambda_risk,
    )

    decay_enabled = any(
        bool(m.params.get("decay_weighting_enabled", False))
        for m in portfolio_modules
    )
    ranker = CrossSectionalRanker(
        decay_weighting_enabled=decay_enabled,
    )

    def _position_lookup(symbol: str) -> float:
        pos = position_store.get(symbol)
        mark = position_store.latest_mark(symbol)
        if mark is None:
            mark = pos.avg_entry_price
        return float(int(pos.quantity) * Decimal(mark))

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
        # to the engine we just built.  This is a no-op for inline
        # ``construct:`` blocks, which carry their own callable.
        construct = module._construct  # noqa: SLF001 — bootstrap rewires
        if isinstance(construct, _DefaultPortfolioConstructor):
            module._construct = _DefaultPortfolioConstructor(  # noqa: SLF001
                engine_thunk=lambda e=engine: e,
                strategy_id=module.alpha_id,
            )
        engine.register(RegisteredPortfolioAlpha(
            alpha_id=module.alpha_id,
            horizon_seconds=module.horizon_seconds,
            alpha=module,
            params=module.params,
        ))
    engine.attach()

    cross_sectional_tracker = CrossSectionalTracker(bus=bus)
    cross_sectional_tracker.attach()

    horizon_metrics = HorizonMetricsCollector(
        bus=bus,
        metric_sequence_generator=metric_seq,
    )
    horizon_metrics.attach()

    hazard_exit_controller: HazardExitController | None = None
    hazard_modules = [
        m for m in portfolio_modules
        if _hazard_block_enabled(getattr(m.manifest, "hazard_exit", None))
    ]
    if hazard_modules:
        hazard_seq_local = SequenceGenerator()
        hazard_exit_controller = HazardExitController(
            bus=bus,
            sequence_generator=hazard_seq_local,
            position_store=position_store,
        )
        for module in sorted(hazard_modules, key=lambda m: m.alpha_id):
            block = getattr(module.manifest, "hazard_exit", None) or {}
            policy = HazardPolicy(
                strategy_id=module.alpha_id,
                hazard_score_threshold=float(
                    block.get(
                        "hazard_score_threshold",
                        HazardPolicy.__dataclass_fields__[
                            "hazard_score_threshold"
                        ].default,
                    )
                ),
                min_age_seconds=int(
                    block.get(
                        "min_age_seconds",
                        HazardPolicy.__dataclass_fields__[
                            "min_age_seconds"
                        ].default,
                    )
                ),
                hard_exit_age_seconds=(
                    int(block["hard_exit_age_seconds"])
                    if block.get("hard_exit_age_seconds") is not None
                    else None
                ),
                universe=tuple(module.universe),
            )
            hazard_exit_controller.register_policy(policy)
        hazard_exit_controller.attach()

    logger.info(
        "PORTFOLIO composition layer composed: %d alpha(s), "
        "universe_size=%d, horizons=%s, hazard_exit=%s, "
        "decay_weighting=%s",
        len(portfolio_modules),
        len(universe),
        sorted(horizons),
        hazard_exit_controller is not None,
        decay_enabled,
    )

    return (
        engine,
        cross_sectional_tracker,
        horizon_metrics,
        hazard_exit_controller,
    )


def _hazard_block_enabled(block: object | None) -> bool:
    if not isinstance(block, dict):
        return False
    return bool(block.get("enabled", False)) is True


def _enforce_factor_loadings_freshness(
    config: PlatformConfig,
    universe_sorted: list[str],
) -> None:
    """Fail-stop on missing or stale loadings rows.

    The neutralizer accepts ``loadings_dir is None`` (no-op pass-through),
    so the freshness check only fires when an operator explicitly
    points at a loadings file.  When fired, every symbol in
    ``universe_sorted`` MUST appear in ``loadings.json`` and the file
    mtime must be within ``factor_loadings_max_age_seconds`` — else we
    raise rather than silently neutralize against a stale or partial
    factor model (Inv-11).
    """
    if config.factor_loadings_dir is None:
        return
    import json
    import time

    path = config.factor_loadings_dir / "loadings.json"
    if not path.is_file():
        raise StaleFactorLoadingsError(
            f"factor loadings file not found: {path}"
        )

    age_seconds = time.time() - path.stat().st_mtime
    if age_seconds > config.factor_loadings_max_age_seconds:
        raise StaleFactorLoadingsError(
            f"factor loadings file {path} is {age_seconds:.0f}s old, "
            f"exceeds factor_loadings_max_age_seconds="
            f"{config.factor_loadings_max_age_seconds}s"
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StaleFactorLoadingsError(
            f"cannot parse factor loadings file {path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise StaleFactorLoadingsError(
            f"factor loadings file {path} is not a JSON object"
        )

    missing = [s for s in universe_sorted if s not in data]
    if missing:
        raise StaleFactorLoadingsError(
            f"factor loadings file {path} is missing rows for "
            f"{len(missing)} universe symbol(s): {missing[:8]}"
            + ("..." if len(missing) > 8 else "")
        )
