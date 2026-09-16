"""R-01 — reset-cascade invocation pin on FIX-1.

S16 proves every mutator has a reset path. R6 proves Orchestrator.reset
exists and that a second replay fingerprints equal to a cold start.
Neither records which reset() bodies the cascade actually entered. This
spy does: MUST_INVOKE must all fire, DECLARED_UNINVOKED must not.

The spy wraps, it does not replace. It is installed after the first
boot and run_backtest and torn down when orchestrator.reset() returns.
Matching is by MRO name so _BacktestMetricCollector counts as
InMemoryMetricCollector. An AST walk of Orchestrator.reset is not this
detector; it cannot type the getattr bus walk.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from feelies.bootstrap import build_platform
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.conformance.test_null_alpha_conservation import (
    _HORIZON_SECONDS,
    _NULL_ALPHA,
    _SENSOR_SPECS,
    _UNIVERSE,
    _synth_events,
)
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS

MUST_INVOKE: frozenset[str] = frozenset(
    {
        "AlphaBudgetRiskWrapper",
        "AlphaRegistry",
        "BacktestOrderRouter",
        "BasicRiskEngine",
        "CompositionEngine",
        "CrossSectionalTracker",
        "EventBus",
        "FillAttributionLedger",
        "HMM3StateFractional",
        "HorizonAggregator",
        "HorizonMetricsCollector",
        "HorizonScheduler",
        "HorizonSignalEngine",
        "InMemoryMetricCollector",
        "MemoryPositionStore",
        "Orchestrator",
        "RegimeGate",
        "RegimeStateCache",
        "SensorRegistry",
        "SequenceGenerator",
        "SimulatedClock",
        "StateMachine",
        "StopExitController",
        "StrategyPositionStore",
        "UniverseSynchronizer",
        "_HaltTradeability",
    }
)

DECLARED_UNINVOKED: frozenset[str] = frozenset(
    {
        "DeferralCapController",  # owed, decouple tape
        "ExitComposer",  # owed, decouple tape
        "HazardExitController",  # owed, hazard tape
        "IBOrderRouter",  # never: IB / paper_rth
        "InMemoryEventLog",  # never: the tape
        "InMemoryKillSwitch",  # never: operator kwargs; Inv-11
        "MassiveHistoricalIngestor",  # never: ingest, not replay
        "MassiveNormalizer",  # owed, injected-normalizer BACKTEST
        "MetricSummary",  # never: parent clear; S16 owns reset
        "MocFillController",  # owed, moc_session_date
        "PassiveLimitOrderRouter",  # owed, execution_mode=passive_limit
        "QuoteReplayObserver",  # never: CLI; reset hits monotonic
        "QuoteTraceIndex",  # never: nested in that observer
        "RegimeHazardDetector",  # owed, hazard tape
        "RthEntryFillGate",  # never: no-op body; S16 owns reset
        "_WarmTimestampIndex",  # never: parent clear; S16 owns reset
    }
)

# StrategyPositionStore and FillAttributionLedger expose reset() and are
# wrapped with the rest of MUST_INVOKE.

_TapeId = Literal[
    "fix1",
    "portfolio",
    "hazard_decouple",
    "passive_limit",
    "injected_normalizer",
]

_TAPES: tuple[_TapeId, ...] = ("fix1", "portfolio")

_PORTFOLIO_DIR = Path(__file__).resolve().parent / "fixtures" / "portfolio"
_UPSTREAM_SIGNAL = _PORTFOLIO_DIR / "upstream_signal.alpha.yaml"
_NULL_PORTFOLIO = _PORTFOLIO_DIR / "null_portfolio.alpha.yaml"

_RESET_CLASS_IMPORTS: tuple[tuple[str, str], ...] = (
    ("feelies.alpha.registry", "AlphaRegistry"),
    ("feelies.broker.ib.router", "IBOrderRouter"),
    ("feelies.bus.event_bus", "EventBus"),
    ("feelies.composition.engine", "CompositionEngine"),
    ("feelies.composition.synchronizer", "UniverseSynchronizer"),
    ("feelies.core.clock", "SimulatedClock"),
    ("feelies.core.data_health", "_HaltTradeability"),
    ("feelies.core.identifiers", "SequenceGenerator"),
    ("feelies.core.regime_gate", "RegimeGate"),
    ("feelies.core.state_machine", "StateMachine"),
    ("feelies.execution.backtest_router", "BacktestOrderRouter"),
    ("feelies.execution.moc_fill", "MocFillController"),
    ("feelies.execution.passive_limit_router", "PassiveLimitOrderRouter"),
    ("feelies.execution.trading_session", "RthEntryFillGate"),
    ("feelies.features.aggregator", "HorizonAggregator"),
    ("feelies.features.aggregator", "_WarmTimestampIndex"),
    ("feelies.harness.backtest_prep", "QuoteReplayObserver"),
    ("feelies.harness.backtest_prep", "QuoteTraceIndex"),
    ("feelies.ingestion.massive_ingestor", "MassiveHistoricalIngestor"),
    ("feelies.ingestion.massive_normalizer", "MassiveNormalizer"),
    ("feelies.kernel.orchestrator", "Orchestrator"),
    ("feelies.monitoring.horizon_metrics", "HorizonMetricsCollector"),
    ("feelies.monitoring.in_memory", "InMemoryKillSwitch"),
    ("feelies.monitoring.in_memory", "InMemoryMetricCollector"),
    ("feelies.monitoring.in_memory", "MetricSummary"),
    ("feelies.portfolio.cross_sectional_tracker", "CrossSectionalTracker"),
    ("feelies.portfolio.fill_attribution", "FillAttributionLedger"),
    ("feelies.portfolio.memory_position_store", "MemoryPositionStore"),
    ("feelies.portfolio.strategy_position_store", "StrategyPositionStore"),
    ("feelies.risk.basic_risk", "BasicRiskEngine"),
    ("feelies.risk.deferral_cap", "DeferralCapController"),
    ("feelies.risk.exit_composer", "ExitComposer"),
    ("feelies.risk.hazard_exit", "HazardExitController"),
    ("feelies.risk.risk_wrapper", "AlphaBudgetRiskWrapper"),
    ("feelies.risk.stop_exit", "StopExitController"),
    ("feelies.sensors.horizon_scheduler", "HorizonScheduler"),
    ("feelies.sensors.registry", "SensorRegistry"),
    ("feelies.services.regime_engine", "HMM3StateFractional"),
    ("feelies.services.regime_hazard_detector", "RegimeHazardDetector"),
    ("feelies.services.regime_state_cache", "RegimeStateCache"),
    ("feelies.signals.horizon_engine", "HorizonSignalEngine"),
    ("feelies.storage.memory_event_log", "InMemoryEventLog"),
)


def _config(
    tape_id: Literal[
        "fix1",
        "portfolio",
        "hazard_decouple",
        "passive_limit",
        "injected_normalizer",
    ] = "fix1",
) -> PlatformConfig:
    if tape_id == "fix1":
        return PlatformConfig(
            symbols=frozenset(_UNIVERSE),
            mode=OperatingMode.BACKTEST,
            alpha_specs=[_NULL_ALPHA],
            regime_engine="hmm_3state_fractional",
            sensor_specs=_SENSOR_SPECS,
            horizons_seconds=frozenset({_HORIZON_SECONDS}),
            session_open_ns=SESSION_OPEN_NS,
            account_equity=1_000_000.0,
            enforce_trend_mechanism=False,
        )
    if tape_id == "portfolio":
        return PlatformConfig(
            symbols=frozenset(_UNIVERSE),
            mode=OperatingMode.BACKTEST,
            alpha_specs=[_UPSTREAM_SIGNAL, _NULL_PORTFOLIO],
            regime_engine="hmm_3state_fractional",
            sensor_specs=_SENSOR_SPECS,
            horizons_seconds=frozenset({300}),
            session_open_ns=SESSION_OPEN_NS,
            account_equity=1_000_000.0,
            enforce_trend_mechanism=False,
        )
    if tape_id == "hazard_decouple":
        raise NotImplementedError("hazard_decouple tape is not live until R-04")
    if tape_id == "passive_limit":
        raise NotImplementedError("passive_limit tape is not live until R-05")
    if tape_id == "injected_normalizer":
        raise NotImplementedError("injected_normalizer tape is not live until R-06")
    raise AssertionError(f"unknown tape_id {tape_id!r}")


def _named_reset_classes() -> list[type[Any]]:
    loaded: list[type[Any]] = []
    for module_name, class_name in _RESET_CLASS_IMPORTS:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if class_name == "IBOrderRouter" and exc.name == "ibapi":
                continue
            raise
        loaded.append(getattr(module, class_name))
    names = {cls.__name__ for cls in loaded}
    expected = MUST_INVOKE | DECLARED_UNINVOKED
    if "IBOrderRouter" not in names:
        expected = expected - {"IBOrderRouter"}
    assert names == expected, (
        f"spy class roster drifted: extra {sorted(names - expected)}; "
        f"missing {sorted(expected - names)}"
    )
    return loaded


@contextmanager
def _spy_named_resets() -> Iterator[set[str]]:
    invoked: set[str] = set()
    tracked = MUST_INVOKE | DECLARED_UNINVOKED
    originals: list[tuple[type[Any], Any]] = []
    for cls in _named_reset_classes():
        original = getattr(cls, "reset", None)
        if not callable(original):
            continue

        def _make_spy(orig: Any) -> Any:
            def spy(*args: Any, **kwargs: Any) -> Any:
                if args:
                    for mro_cls in type(args[0]).__mro__:
                        if mro_cls.__name__ in tracked:
                            invoked.add(mro_cls.__name__)
                return orig(*args, **kwargs)

            return spy

        cls.reset = _make_spy(original)
        originals.append((cls, original))
    try:
        yield invoked
    finally:
        for cls, original in originals:
            cls.reset = original


def test_reset_cascade_on_fix1_matches_must_invoke_pin() -> None:
    invoked_union: set[str] = set()
    for tape_id in _TAPES:
        config = _config(tape_id)
        event_log = InMemoryEventLog()
        event_log.append_batch(_synth_events())
        orchestrator, _ = build_platform(config, event_log=event_log)
        orchestrator.boot(config)
        orchestrator.run_backtest()
        with _spy_named_resets() as invoked:
            orchestrator.reset()
        invoked_union |= invoked
    missing = MUST_INVOKE - invoked_union
    leaked = invoked_union & DECLARED_UNINVOKED
    assert not missing, f"MUST_INVOKE not entered: {sorted(missing)}"
    assert not leaked, f"DECLARED_UNINVOKED entered: {sorted(leaked)}"
