"""Tests for SensorRegistry: routing, throttling, topo-order, version pin."""

from __future__ import annotations

import pytest

from feelies.bus.event_bus import EventBus
from feelies.core.events import NBBOQuote, SensorReading, Trade
from feelies.core.identifiers import SequenceGenerator
from feelies.sensors.errors import (
    DuplicateSensorRegistrationError,
    UnresolvedSensorDependencyError,
)
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec
from tests.sensors._helpers import CountingSensor, make_quote, make_trade


def _make_registry(symbols: tuple[str, ...] = ("AAPL",)) -> tuple[SensorRegistry, EventBus, list[SensorReading]]:
    bus = EventBus()
    readings: list[SensorReading] = []
    bus.subscribe(SensorReading, readings.append)
    registry = SensorRegistry(
        bus=bus, sequence_generator=SequenceGenerator(), symbols=frozenset(symbols)
    )
    return registry, bus, readings


def test_registry_is_empty_when_no_specs_registered() -> None:
    registry, _, _ = _make_registry()
    assert registry.is_empty() is True


def test_registry_dispatches_quote_to_registered_sensor() -> None:
    registry, bus, readings = _make_registry()
    registry.register(SensorSpec(
        sensor_id="counting",
        sensor_version="1.0.0",
        cls=CountingSensor,
        subscribes_to=(NBBOQuote,),
    ))
    assert registry.is_empty() is False
    bus.publish(make_quote())
    assert len(readings) == 1
    assert readings[0].sensor_id == "counting"
    assert readings[0].value == 1.0
    assert readings[0].source_layer == "SENSOR"


def test_registry_publishes_in_spec_order_for_two_sensors() -> None:
    registry, bus, readings = _make_registry()
    registry.register(SensorSpec(
        sensor_id="alpha", sensor_version="1.0.0", cls=CountingSensor,
        subscribes_to=(NBBOQuote,), params={"sensor_id": "alpha"},
    ))
    registry.register(SensorSpec(
        sensor_id="beta", sensor_version="1.0.0", cls=CountingSensor,
        subscribes_to=(NBBOQuote,), params={"sensor_id": "beta"},
    ))
    bus.publish(make_quote())
    assert [r.sensor_id for r in readings] == ["alpha", "beta"]


def test_registry_assigns_monotonic_sequence_numbers() -> None:
    registry, bus, readings = _make_registry()
    registry.register(SensorSpec(
        sensor_id="a", sensor_version="1.0.0", cls=CountingSensor,
        subscribes_to=(NBBOQuote,), params={"sensor_id": "a"},
    ))
    bus.publish(make_quote(ts_ns=1_000_000_000))
    bus.publish(make_quote(ts_ns=2_000_000_000))
    assert [r.sequence for r in readings] == [0, 1]


def test_registry_drops_events_for_unknown_symbols() -> None:
    registry, bus, readings = _make_registry(symbols=("AAPL",))
    registry.register(SensorSpec(
        sensor_id="x", sensor_version="1.0.0", cls=CountingSensor,
        subscribes_to=(NBBOQuote,), params={"sensor_id": "x"},
    ))
    bus.publish(make_quote(symbol="MSFT"))
    assert readings == []


def test_registry_routes_only_subscribed_event_types() -> None:
    registry, bus, readings = _make_registry()
    registry.register(SensorSpec(
        sensor_id="quote_only", sensor_version="1.0.0", cls=CountingSensor,
        subscribes_to=(NBBOQuote,), params={"sensor_id": "quote_only"},
    ))
    registry.register(SensorSpec(
        sensor_id="trade_only", sensor_version="1.0.0", cls=CountingSensor,
        subscribes_to=(Trade,), params={"sensor_id": "trade_only"},
    ))
    bus.publish(make_quote())
    assert [r.sensor_id for r in readings] == ["quote_only"]
    bus.publish(make_trade())
    assert [r.sensor_id for r in readings] == ["quote_only", "trade_only"]


def test_duplicate_registration_raises() -> None:
    registry, _, _ = _make_registry()
    spec = SensorSpec(
        sensor_id="x", sensor_version="1.0.0", cls=CountingSensor,
        subscribes_to=(NBBOQuote,), params={"sensor_id": "x"},
    )
    registry.register(spec)
    with pytest.raises(DuplicateSensorRegistrationError):
        registry.register(spec)


def test_distinct_versions_of_same_sensor_id_coexist() -> None:
    registry, bus, readings = _make_registry()
    registry.register(SensorSpec(
        sensor_id="x", sensor_version="1.0.0", cls=CountingSensor,
        subscribes_to=(NBBOQuote,), params={"sensor_id": "x", "sensor_version": "1.0.0"},
    ))
    registry.register(SensorSpec(
        sensor_id="x", sensor_version="2.0.0", cls=CountingSensor,
        subscribes_to=(NBBOQuote,), params={"sensor_id": "x", "sensor_version": "2.0.0"},
    ))
    bus.publish(make_quote())
    versions = sorted(r.sensor_version for r in readings)
    assert versions == ["1.0.0", "2.0.0"]


def test_unresolved_input_sensor_dependency_raises() -> None:
    registry, _, _ = _make_registry()
    with pytest.raises(UnresolvedSensorDependencyError):
        registry.register(SensorSpec(
            sensor_id="downstream", sensor_version="1.0.0", cls=CountingSensor,
            subscribes_to=(NBBOQuote,), input_sensor_ids=("upstream",),
            params={"sensor_id": "downstream"},
        ))


def test_topological_order_accepted_when_upstream_first() -> None:
    registry, _, _ = _make_registry()
    registry.register(SensorSpec(
        sensor_id="upstream", sensor_version="1.0.0", cls=CountingSensor,
        subscribes_to=(NBBOQuote,), params={"sensor_id": "upstream"},
    ))
    # Should not raise.
    registry.register(SensorSpec(
        sensor_id="downstream", sensor_version="1.0.0", cls=CountingSensor,
        subscribes_to=(NBBOQuote,), input_sensor_ids=("upstream",),
        params={"sensor_id": "downstream"},
    ))


def test_throttle_skips_within_window_and_emits_after() -> None:
    registry, bus, readings = _make_registry()
    registry.register(SensorSpec(
        sensor_id="thr", sensor_version="1.0.0", cls=CountingSensor,
        subscribes_to=(NBBOQuote,), params={"sensor_id": "thr"},
        throttled_ms=100,
    ))
    bus.publish(make_quote(ts_ns=0))
    bus.publish(make_quote(ts_ns=50_000_000))
    bus.publish(make_quote(ts_ns=150_000_000))
    assert [r.timestamp_ns for r in readings] == [0, 150_000_000]


def test_provenance_pre_baked_and_shared_across_emissions() -> None:
    registry, bus, readings = _make_registry()
    registry.register(SensorSpec(
        sensor_id="p", sensor_version="1.0.0", cls=CountingSensor,
        subscribes_to=(NBBOQuote, Trade), params={"sensor_id": "p"},
    ))
    bus.publish(make_quote(ts_ns=1))
    bus.publish(make_quote(ts_ns=2))
    assert readings[0].provenance is readings[1].provenance
    assert readings[0].provenance.input_event_kinds == ("NBBOQuote", "Trade")


def test_correlation_id_format_is_sensor_prefixed() -> None:
    registry, bus, readings = _make_registry()
    registry.register(SensorSpec(
        sensor_id="abc", sensor_version="1.0.0", cls=CountingSensor,
        subscribes_to=(NBBOQuote,), params={"sensor_id": "abc"},
    ))
    bus.publish(make_quote(ts_ns=42))
    assert readings[0].correlation_id.startswith("sensor:abc:")


def test_subscribe_once_per_event_type() -> None:
    registry, bus, _ = _make_registry()
    # If the registry ever subscribed twice we'd see double dispatch.
    for i in range(5):
        registry.register(SensorSpec(
            sensor_id=f"s{i}", sensor_version="1.0.0", cls=CountingSensor,
            subscribes_to=(NBBOQuote,), params={"sensor_id": f"s{i}"},
        ))
    readings: list[SensorReading] = []
    bus.subscribe(SensorReading, readings.append)
    bus.publish(make_quote())
    assert sorted(r.sensor_id for r in readings) == ["s0", "s1", "s2", "s3", "s4"]
