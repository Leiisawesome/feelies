"""Tests for the four Phase-2 sensor-layer metrics.

Plan §4.5 requires the following metrics to be emitted into the
:class:`InMemoryMetricCollector` whenever a metric collector is wired
into the registry / scheduler / aggregator:

- ``feelies.sensor.reading.count`` — counter, per ``SensorReading``.
- ``feelies.sensor.reading.latency`` — histogram, per ``SensorReading``.
- ``feelies.horizon.tick.emitted`` — counter, per ``HorizonTick``.
- ``feelies.feature.snapshot.stale_fraction`` — gauge, per snapshot.

These tests exercise each component in isolation (no orchestrator) so
the metric flow is validated independently of the legacy execution
path.  They also verify that the metric sequence numbers come from a
*dedicated* generator separate from the locked event streams (Inv-A /
C1) — the simplest way to assert this is to check that the locked
event sequences (e.g. SensorReading.sequence) start at 1 and are
contiguous regardless of how many metrics fire alongside them.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    HorizonTick,
    MetricType,
    NBBOQuote,
    SensorReading,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.features.aggregator import HorizonAggregator
from feelies.monitoring.in_memory import InMemoryMetricCollector
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec


def _quote(*, ts_ns: int, symbol: str = "AAPL") -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{ts_ns}",
        sequence=ts_ns,
        symbol=symbol,
        bid=Decimal("100.00"),
        ask=Decimal("100.02"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts_ns,
    )


# ── Sensor-reading metrics ──────────────────────────────────────────


def test_registry_emits_reading_count_and_latency_per_reading() -> None:
    """Registry emits a count metric (not a latency histogram) per reading.

    S6: the latency histogram was removed because ``time.perf_counter_ns()``
    in the deterministic dispatch path violates A-CLOCK-01.  Only the
    count metric is now emitted; latency monitoring should be done via a
    dedicated monitoring subscriber outside the hot path.
    """
    bus = EventBus()
    mc = InMemoryMetricCollector()
    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset({"AAPL"}),
        metric_collector=mc,
    )
    registry.register(SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.0.0",
        cls=MicroPriceSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ))

    captured: list[SensorReading] = []
    bus.subscribe(SensorReading, captured.append)

    bus.publish(_quote(ts_ns=1_000_000_000))
    bus.publish(_quote(ts_ns=2_000_000_000))
    bus.publish(_quote(ts_ns=3_000_000_000))

    assert len(captured) == 3
    counts = [
        e for e in mc.events
        if e.name == "feelies.sensor.reading.count"
    ]
    # S6: latency histogram removed (A-CLOCK-01 violation in dispatch path).
    latencies = [
        e for e in mc.events
        if e.name == "feelies.sensor.reading.latency"
    ]
    assert len(counts) == 3
    assert len(latencies) == 0  # S6: no longer emitted
    assert all(e.metric_type is MetricType.COUNTER for e in counts)
    assert all(e.value == 1.0 for e in counts)
    # Tags must include sensor_id and symbol for the count metric.
    assert all(
        e.tags.get("sensor_id") == "micro_price" for e in counts
    )
    assert all(e.tags.get("symbol") == "AAPL" for e in counts)
    assert all(e.layer == "sensor" for e in counts)


def test_registry_metrics_dont_perturb_sensor_reading_sequence() -> None:
    """SensorReading.sequence must remain contiguous regardless of metrics.

    Verifies the dedicated metric sequence generator (Inv-A / C1).
    """
    bus = EventBus()
    mc = InMemoryMetricCollector()
    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset({"AAPL"}),
        metric_collector=mc,
    )
    registry.register(SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.0.0",
        cls=MicroPriceSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ))
    captured: list[SensorReading] = []
    bus.subscribe(SensorReading, captured.append)

    for i in range(5):
        bus.publish(_quote(ts_ns=(i + 1) * 1_000_000_000))

    assert [r.sequence for r in captured] == [0, 1, 2, 3, 4]


def test_registry_without_metric_collector_emits_nothing() -> None:
    bus = EventBus()
    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset({"AAPL"}),
    )
    registry.register(SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.0.0",
        cls=MicroPriceSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ))
    # Just exercise it: publish a quote and confirm no crash + no
    # metrics by inspecting that no MetricCollector was wired.
    bus.publish(_quote(ts_ns=1_000_000_000))


# ── Horizon-tick metrics ────────────────────────────────────────────


def test_scheduler_emits_tick_emitted_metric_per_tick() -> None:
    mc = InMemoryMetricCollector()
    scheduler = HorizonScheduler(
        horizons=frozenset({30}),
        session_id="TEST",
        symbols=frozenset({"AAPL"}),
        session_open_ns=1_000_000_000_000,
        sequence_generator=SequenceGenerator(),
        metric_collector=mc,
    )

    # First event → boundary 0, emits a SYMBOL + a UNIVERSE tick = 2.
    ticks_a = scheduler.on_event(_quote(ts_ns=1_001_000_000_000))
    assert len(ticks_a) == 2

    # Cross into next 30s window → another SYMBOL + UNIVERSE = 2.
    ticks_b = scheduler.on_event(_quote(ts_ns=1_031_000_000_000))
    assert len(ticks_b) == 2

    metrics = [
        e for e in mc.events
        if e.name == "feelies.horizon.tick.emitted"
    ]
    assert len(metrics) == 4
    assert all(e.metric_type is MetricType.COUNTER for e in metrics)
    assert all(e.value == 1.0 for e in metrics)
    assert all(e.layer == "scheduler" for e in metrics)
    scopes = [e.tags["scope"] for e in metrics]
    assert scopes.count("SYMBOL") == 2
    assert scopes.count("UNIVERSE") == 2
    assert all(e.tags["horizon_seconds"] == "30" for e in metrics)


def test_scheduler_metrics_dont_perturb_tick_sequence() -> None:
    mc = InMemoryMetricCollector()
    scheduler = HorizonScheduler(
        horizons=frozenset({30}),
        session_id="TEST",
        symbols=frozenset({"AAPL"}),
        session_open_ns=1_000_000_000_000,
        sequence_generator=SequenceGenerator(),
        metric_collector=mc,
    )
    ticks: list[HorizonTick] = []
    ticks.extend(scheduler.on_event(_quote(ts_ns=1_001_000_000_000)))
    ticks.extend(scheduler.on_event(_quote(ts_ns=1_031_000_000_000)))
    assert [t.sequence for t in ticks] == [0, 1, 2, 3]


# ── Snapshot stale-fraction metric ─────────────────────────────────


def test_aggregator_emits_stale_fraction_per_snapshot() -> None:
    bus = EventBus()
    mc = InMemoryMetricCollector()
    agg = HorizonAggregator(
        bus=bus,
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=600,
        sequence_generator=SequenceGenerator(),
        metric_collector=mc,
    )
    agg.attach()

    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)

    # Publish two ticks to generate two passive-mode snapshots.
    bus.publish(HorizonTick(
        timestamp_ns=1_030_000_000_000,
        correlation_id="t1",
        sequence=1,
        horizon_seconds=30,
        boundary_index=1,
        scope="SYMBOL",
        symbol="AAPL",
        session_id="TEST",
    ))
    bus.publish(HorizonTick(
        timestamp_ns=1_060_000_000_000,
        correlation_id="t2",
        sequence=2,
        horizon_seconds=30,
        boundary_index=2,
        scope="SYMBOL",
        symbol="AAPL",
        session_id="TEST",
    ))

    assert len(captured) == 2
    metrics = [
        e for e in mc.events
        if e.name == "feelies.feature.snapshot.stale_fraction"
    ]
    assert len(metrics) == 2
    assert all(e.metric_type is MetricType.GAUGE for e in metrics)
    assert all(e.layer == "feature" for e in metrics)
    # Passive mode: 0 features → fraction = 0.0 by convention.
    assert all(e.value == 0.0 for e in metrics)
    assert all(e.tags["horizon_seconds"] == "30" for e in metrics)


def test_aggregator_metrics_dont_perturb_snapshot_sequence() -> None:
    bus = EventBus()
    mc = InMemoryMetricCollector()
    agg = HorizonAggregator(
        bus=bus,
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=600,
        sequence_generator=SequenceGenerator(),
        metric_collector=mc,
    )
    agg.attach()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)

    for i, ts in enumerate([1_030_000_000_000, 1_060_000_000_000, 1_090_000_000_000]):
        bus.publish(HorizonTick(
            timestamp_ns=ts,
            correlation_id=f"t{i}",
            sequence=i + 1,
            horizon_seconds=30,
            boundary_index=i + 1,
            scope="SYMBOL",
            symbol="AAPL",
            session_id="TEST",
        ))

    assert [s.sequence for s in captured] == [0, 1, 2]


# ── Summary keys ────────────────────────────────────────────────────


def test_metric_collector_summary_keys_match_plan() -> None:
    """The summary key format ``layer.name`` must match plan §4.5."""

    bus = EventBus()
    mc = InMemoryMetricCollector()
    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset({"AAPL"}),
        metric_collector=mc,
    )
    registry.register(SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.0.0",
        cls=MicroPriceSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ))
    bus.publish(_quote(ts_ns=1_000_000_000))

    keys = set(mc.summaries.keys())
    assert "sensor.feelies.sensor.reading.count" in keys
    # S6: latency histogram removed from registry dispatch path (A-CLOCK-01).
    assert "sensor.feelies.sensor.reading.latency" not in keys
