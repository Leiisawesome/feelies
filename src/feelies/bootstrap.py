"""Bootstrap — one-call system composition from configuration.

Reads a ``PlatformConfig`` (or YAML path), discovers alphas, creates
a shared ``RegimeEngine``, composes all layers, and returns a
ready-to-boot ``Orchestrator``.

This is the only place where concrete implementations are selected
and wired together.  The orchestrator and all downstream components
interact only through protocols.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

from feelies.alpha.composite import CompositeFeatureEngine, CompositeSignalEngine
from feelies.alpha.discovery import load_and_register
from feelies.alpha.loader import AlphaLoader
from feelies.alpha.registry import AlphaRegistry
from feelies.bus.event_bus import EventBus
from feelies.core.clock import Clock, SimulatedClock, WallClock
from feelies.core.events import NBBOQuote
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_backend import build_backtest_backend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import DefaultCostModel, DefaultCostModelConfig
from feelies.execution.intent import SignalPositionTranslator
from feelies.kernel.orchestrator import Orchestrator
from feelies.monitoring.in_memory import (
    InMemoryAlertManager,
    InMemoryKillSwitch,
    InMemoryMetricCollector,
)
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.risk.position_sizer import BudgetBasedSizer
from feelies.services.regime_engine import RegimeEngine, get_regime_engine
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.storage.memory_feature_snapshot import InMemoryFeatureSnapshotStore
from feelies.storage.memory_trade_journal import InMemoryTradeJournal

logger = logging.getLogger(__name__)


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
    loader = AlphaLoader(regime_engine=regime_engine)

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

    cost_model = DefaultCostModel(DefaultCostModelConfig())
    backend, backtest_router = _create_backend(
        config.mode, event_log, clock,
        fill_latency_ns=config.backtest_fill_latency_ns,
        cost_model=cost_model,
    )

    if backtest_router is not None:
        bus.subscribe(NBBOQuote, lambda e: backtest_router.on_quote(e))  # type: ignore[arg-type]

    position_store = MemoryPositionStore()
    trade_journal = InMemoryTradeJournal()
    feature_snapshots = InMemoryFeatureSnapshotStore()
    position_sizer = BudgetBasedSizer(regime_engine=regime_engine)
    intent_translator = SignalPositionTranslator()

    kill_switch = InMemoryKillSwitch()
    alert_manager = InMemoryAlertManager(kill_switch=kill_switch)
    metric_collector = InMemoryMetricCollector()

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
        logger.warning("Unknown regime engine '%s', proceeding without", engine_name)
        return None


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
) -> tuple[ExecutionBackend, BacktestOrderRouter | None]:
    if mode == OperatingMode.BACKTEST:
        backend, router = build_backtest_backend(
            event_log, clock,
            latency_ns=fill_latency_ns,
            cost_model=cost_model,
        )
        return backend, router

    raise NotImplementedError(
        f"ExecutionBackend for mode {mode.name} is not yet implemented. "
        f"Paper and live routers are future work."
    )


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))
