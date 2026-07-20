"""Lock relative order for determinism-critical bus subscribers.

The synchronous bus dispatches in registration order. Tests use subsequences so
unrelated subscribers may be added. Quote-router ordering is covered by behavior
tests because its lambda subscriber has no owning component to inspect.
"""

from __future__ import annotations


from feelies.bootstrap import build_platform
from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    Event,
    HorizonFeatureSnapshot,
    HorizonTick,
    OrderRequest,
    SensorReading,
    Signal,
    SizedPositionIntent,
)
from feelies.kernel.orchestrator import Orchestrator
from feelies.storage.memory_event_log import InMemoryEventLog

from tests.integration.test_phase4_e2e import (
    _make_phase4_config,
    _synth_multi_symbol_events,
)


def _build_platform() -> Orchestrator:
    config = _make_phase4_config()
    event_log = InMemoryEventLog()
    event_log.append_batch(_synth_multi_symbol_events())
    orchestrator, _ = build_platform(config, event_log=event_log)
    return orchestrator


def _owner_names(bus: EventBus, event_type: type[Event]) -> list[str]:
    """Owning-component class name for each registered handler, in order."""
    names: list[str] = []
    for handler in bus._handlers.get(event_type, []):
        owner = getattr(handler, "__self__", None)
        if owner is not None:
            names.append(type(owner).__name__)
        else:  # bare function / lambda — identify by qualname
            qualname: str = getattr(handler, "__qualname__", repr(handler))
            names.append(qualname)
    return names


def _assert_before(names: list[str], first: str, second: str) -> None:
    assert first in names, f"{first} not subscribed (got {names})"
    assert second in names, f"{second} not subscribed (got {names})"
    assert names.index(first) < names.index(second), (
        f"canonical bus order violated: expected {first!r} before {second!r}, got {names}"
    )


def test_sensor_reading_handler_order() -> None:
    # SensorRegistry → HorizonAggregator → HorizonSignalEngine: the aggregator
    # buffers the reading before the signal engine's sensor-cache consults it.
    names = _owner_names(_build_platform()._bus, SensorReading)
    _assert_before(names, "HorizonAggregator", "HorizonSignalEngine")


def test_horizon_feature_snapshot_handler_order() -> None:
    # HorizonSignalEngine emits Signals from the snapshot before the
    # UniverseSynchronizer folds the snapshot into its barrier cache.
    names = _owner_names(_build_platform()._bus, HorizonFeatureSnapshot)
    _assert_before(names, "HorizonSignalEngine", "UniverseSynchronizer")


def test_horizon_tick_handler_order() -> None:
    # The aggregator publishes the snapshot for a crossed boundary before the
    # synchronizer closes the barrier on the same tick.
    names = _owner_names(_build_platform()._bus, HorizonTick)
    _assert_before(names, "HorizonAggregator", "UniverseSynchronizer")


def test_signal_handler_order() -> None:
    # The composition layer (UniverseSynchronizer) is constructed before the
    # Orchestrator in ``build_platform``, so it subscribes to Signal first.
    # The order is immaterial to correctness — the synchronizer only collects
    # portfolio-consumed signals while ``_on_bus_signal`` skips those — but it
    # is deterministic and pinned here so a construction-order refactor surfaces.
    names = _owner_names(_build_platform()._bus, Signal)
    _assert_before(names, "UniverseSynchronizer", "Orchestrator")


def test_sized_intent_handler_order() -> None:
    # Composition + observability consumers are wired before the Orchestrator,
    # which buffers the intent for its M5–M10 drain after the synchronous bus
    # dispatch completes (so subscriber order does not change execution).
    names = _owner_names(_build_platform()._bus, SizedPositionIntent)
    _assert_before(names, "CrossSectionalTracker", "HorizonMetricsCollector")
    _assert_before(names, "CrossSectionalTracker", "Orchestrator")
    _assert_before(names, "HorizonMetricsCollector", "Orchestrator")


def test_order_request_handler_order() -> None:
    # HorizonMetricsCollector (composition layer) records every order before the
    # Orchestrator's hazard bridge — constructed later — filters/routes it.
    names = _owner_names(_build_platform()._bus, OrderRequest)
    _assert_before(names, "HorizonMetricsCollector", "Orchestrator")
