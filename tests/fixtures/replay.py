"""Helpers to replay an event-log fixture through the orchestrator.

Used by Phase-2 determinism tests:

- :func:`replay_quotes_through_scheduler` — minimal harness that
  builds a ``HorizonScheduler`` (no orchestrator) and walks a fixture
  through it, returning the emitted ``HorizonTick`` stream for hash
  comparison (Level-2 baseline).
- :func:`replay_through_registry` — builds a bus + registry +
  scheduler + recorder and walks a fixture through them.  Returns the
  recorder so consumers can inspect every event the bus saw.

These helpers intentionally do *not* boot the full ``Orchestrator``
to keep the determinism tests focused: orchestrator booting drags in
the alpha registry, regime engine, etc., which are unrelated to
sensor/scheduler determinism and would otherwise make a Level-2 hash
brittle to unrelated platform changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from collections.abc import Sequence

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    Event,
    HorizonFeatureSnapshot,
    HorizonTick,
    NBBOQuote,
    SensorReading,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.features.aggregator import HorizonAggregator
from feelies.features.protocol import HorizonFeature
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec
from tests.fixtures.event_logs._generate import (
    DEFAULT_OUTPUT,
    SESSION_OPEN_NS,
    load,
)


@dataclass
class BusRecorder:
    """Captures every published event from the bus, in order."""

    events: list[Event] = field(default_factory=list)
    horizon_ticks: list[HorizonTick] = field(default_factory=list)
    sensor_readings: list[SensorReading] = field(default_factory=list)
    snapshots: list[HorizonFeatureSnapshot] = field(default_factory=list)

    def install(self, bus: EventBus) -> None:
        bus.subscribe_all(self._on_event)

    def _on_event(self, event: Event) -> None:
        self.events.append(event)
        if isinstance(event, HorizonTick):
            self.horizon_ticks.append(event)
        elif isinstance(event, SensorReading):
            self.sensor_readings.append(event)
        elif isinstance(event, HorizonFeatureSnapshot):
            self.snapshots.append(event)


def replay_quotes_through_scheduler(
    *,
    horizons: frozenset[int] = frozenset({30, 120, 300}),
    symbols: frozenset[str] = frozenset({"AAPL"}),
    fixture_path: Path = DEFAULT_OUTPUT,
    session_open_ns: int = SESSION_OPEN_NS,
    session_id: str = "TEST_SYNTH",
) -> tuple[tuple[HorizonTick, ...], HorizonScheduler]:
    """Drive a ``HorizonScheduler`` directly from the fixture.

    Returns ``(emitted_ticks, scheduler)``.  No bus, no registry,
    no orchestrator — pure scheduler under test.  Suitable for
    locking the Level-2 ``HorizonTick`` baseline.
    """
    scheduler = HorizonScheduler(
        horizons=horizons,
        session_id=session_id,
        symbols=symbols,
        session_open_ns=session_open_ns,
        sequence_generator=SequenceGenerator(),
    )
    emitted: list[HorizonTick] = []
    for event in load(fixture_path):
        emitted.extend(scheduler.on_event(event))
    return tuple(emitted), scheduler


def replay_through_registry(
    *,
    sensor_specs: tuple[SensorSpec, ...],
    horizons: frozenset[int] = frozenset({30, 120, 300}),
    symbols: frozenset[str] = frozenset({"AAPL"}),
    fixture_path: Path = DEFAULT_OUTPUT,
    session_open_ns: int = SESSION_OPEN_NS,
    session_id: str = "TEST_SYNTH",
) -> BusRecorder:
    """Compose bus + registry + scheduler; replay the fixture.

    The orchestrator is *not* involved (kept out so determinism tests
    do not couple to alpha/registry composition).  Sensor readings
    come through the registry's bus subscription; horizon ticks are
    published manually after each event, mirroring the orchestrator's
    real wiring (but inline instead of via micro-state walk).
    """
    bus = EventBus()
    recorder = BusRecorder()
    recorder.install(bus)

    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=symbols,
    )
    for spec in sensor_specs:
        registry.register(spec)

    scheduler = HorizonScheduler(
        horizons=horizons,
        session_id=session_id,
        symbols=symbols,
        session_open_ns=session_open_ns,
        sequence_generator=SequenceGenerator(),
    )

    for event in load(fixture_path):
        if not isinstance(event, (NBBOQuote, Trade)):
            continue
        bus.publish(event)
        for tick in scheduler.on_event(event):
            bus.publish(tick)

    return recorder


def replay_through_aggregator(
    *,
    sensor_specs: tuple[SensorSpec, ...],
    horizon_features: Sequence[HorizonFeature] | None = None,
    horizons: frozenset[int] = frozenset({30, 120, 300}),
    symbols: frozenset[str] = frozenset({"AAPL"}),
    fixture_path: Path = DEFAULT_OUTPUT,
    session_open_ns: int = SESSION_OPEN_NS,
    session_id: str = "TEST_SYNTH",
) -> BusRecorder:
    """Compose bus + registry + scheduler + aggregator; replay the fixture.

    When *horizon_features* is ``None`` the aggregator runs in
    passive-emitter mode (empty ``values`` / ``warm`` / ``stale`` dicts).
    Pass a non-empty list to exercise the active Phase-3.5 path where
    ``HorizonFeatureSnapshot.values`` is populated with real sensor-derived
    feature values — this is the production mode after commit df632ef.
    """
    bus = EventBus()
    recorder = BusRecorder()
    recorder.install(bus)

    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=symbols,
    )
    for spec in sensor_specs:
        registry.register(spec)

    scheduler = HorizonScheduler(
        horizons=horizons,
        session_id=session_id,
        symbols=symbols,
        session_open_ns=session_open_ns,
        sequence_generator=SequenceGenerator(),
    )

    aggregator = HorizonAggregator(
        bus=bus,
        symbols=symbols,
        sensor_buffer_seconds=2 * max(horizons),
        sequence_generator=SequenceGenerator(),
        horizon_features=list(horizon_features) if horizon_features is not None else [],
    )
    aggregator.attach()

    for event in load(fixture_path):
        if not isinstance(event, (NBBOQuote, Trade)):
            continue
        bus.publish(event)
        for tick in scheduler.on_event(event):
            bus.publish(tick)

    return recorder


def hash_horizon_tick_stream(ticks: tuple[HorizonTick, ...]) -> str:
    """SHA-256 over a canonical line-per-tick representation.

    Used by Level-2 determinism tests to lock a baseline.  The
    canonical form intentionally excludes only the auto-bound
    ``timestamp_ns`` of the tick itself if it would vary between
    runs (it does not, but we make this explicit for clarity).
    """
    import hashlib

    lines: list[str] = []
    for tick in ticks:
        lines.append(
            f"{tick.sequence}|{tick.horizon_seconds}|{tick.boundary_index}|"
            f"{tick.scope}|{tick.symbol or '-'}|{tick.session_id}|"
            f"{tick.correlation_id}|{tick.timestamp_ns}"
        )
    payload = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "BusRecorder",
    "hash_horizon_tick_stream",
    "replay_quotes_through_scheduler",
    "replay_through_aggregator",
    "replay_through_registry",
]
