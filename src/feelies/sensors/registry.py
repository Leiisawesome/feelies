"""SensorRegistry — owns per-symbol sensor state and routes raw events.

Architectural decisions (plan §3.1):

1. **Registry-as-single-subscriber (C4).**  The registry registers one
   handler per ``(event_type)`` on the bus and fans out to every
   sensor instance.  This keeps bus-handler count O(event_types)
   regardless of how many sensors are configured (capacity ⇒ S6).

2. **Pre-baked SensorProvenance (S4).**  Each ``(sensor_id, sensor_version)``
   gets one immutable :class:`feelies.core.events.SensorProvenance`
   instance built at registration time from ``subscribes_to`` +
   ``input_sensor_ids``.  The registry's ``_stamp`` helper builds a
   fresh :class:`feelies.core.events.SensorReading` wrapper around the
   sensor-returned value on every emission, overriding audit fields
   (``sequence``, ``correlation_id``, ``source_layer``, ``provenance``)
   so producers cannot diverge from the platform's determinism contract.
   The ``SensorProvenance`` itself is shared (no per-event allocation),
   but ``SensorReading`` is re-allocated once per emission (H5 / audit).

3. **Throttle gate at registry level (S5).**  When a spec sets
   ``throttled_ms``, the registry tracks last-emit timestamps per
   ``(sensor_id, symbol)`` and short-circuits *emission* inside the
   throttle window.  For stateless sensors (``spec.stateful=False``,
   the default) the ``update()`` call is also skipped.  For stateful
   (accumulator) sensors (``spec.stateful=True``) ``update()`` is
   called on every event so the estimator remains unbiased; only the
   resulting ``SensorReading`` is suppressed until the window expires
   (H4 / M4 audit).

4. **Topological registration order.**  A spec with
   ``input_sensor_ids`` can only be registered after every input has
   been registered.  Violations raise
   :class:`feelies.sensors.errors.UnresolvedSensorDependencyError` at
   ``register()`` time, so misconfiguration fails loudly at boot, not
   silently at first event.

5. **Version-pin conflict detection.**  Re-registering the same
   ``(sensor_id, sensor_version)`` raises
   :class:`feelies.sensors.errors.DuplicateSensorRegistrationError`.
   Two sensors with the same ``sensor_id`` but different
   ``sensor_version`` are intentionally allowed (and treated as
   independent registrations).

The registry never publishes ``Signal``, ``OrderIntent``, or
``OrderAck`` (Inv-E).  It only publishes ``SensorReading`` events.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    Event,
    MetricEvent,
    MetricType,
    NBBOQuote,
    SensorProvenance,
    SensorReading,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator, make_correlation_id
from feelies.monitoring.telemetry import MetricCollector
from feelies.sensors.errors import (
    DuplicateSensorRegistrationError,
    UnresolvedSensorDependencyError,
)
from feelies.sensors.protocol import Sensor
from feelies.sensors.spec import SensorSpec

_logger = logging.getLogger(__name__)


# A throttle bookkeeping entry keyed by (sensor_id, symbol).
# Stored as nanoseconds to avoid float drift across runs.
_ThrottleKey = tuple[str, str]


class SensorRegistry:
    """Routes ``NBBOQuote`` / ``Trade`` events to registered sensors.

    Construction parameters:

    - ``bus``: the platform event bus.  The registry subscribes once
      per event type the first time a spec mentions that type.
    - ``sequence_generator``: a *dedicated* sequence generator owned
      by the registry — separate from the orchestrator's main
      ``_sequence`` (Inv-A / C1).  All ``SensorReading`` events draw
      sequence numbers from this generator only.
    - ``symbols``: the universe.  Per-symbol state is allocated lazily
      on first event for that symbol, but only for symbols in this
      set; events for unknown symbols are dropped silently (the
      universe is the source of truth).
    """

    __slots__ = (
        "_bus",
        "_sequence_generator",
        "_symbols",
        "_specs",
        "_specs_by_id",
        "_sensors",
        "_provenance",
        "_state",
        "_throttle_last_ns",
        "_subscribed_types",
        "_publish_target",
        "_metric_collector",
        "_metrics_seq",
    )

    def __init__(
        self,
        *,
        bus: EventBus,
        sequence_generator: SequenceGenerator,
        symbols: frozenset[str],
        metric_collector: MetricCollector | None = None,
    ) -> None:
        self._bus = bus
        self._sequence_generator = sequence_generator
        self._symbols = symbols
        self._specs: list[SensorSpec] = []
        self._specs_by_id: dict[str, list[SensorSpec]] = {}
        self._sensors: dict[tuple[str, str], Sensor] = {}
        self._provenance: dict[tuple[str, str], SensorProvenance] = {}
        self._state: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._throttle_last_ns: dict[_ThrottleKey, int] = {}
        self._subscribed_types: set[type[Event]] = set()
        self._publish_target: list[SensorReading] | None = None
        # Plan §4.5: ``feelies.sensor.reading.count`` (counter) and
        # ``feelies.sensor.reading.latency`` (histogram, nanoseconds)
        # are emitted on every successful sensor update when a metric
        # collector is wired.  A *dedicated* sequence generator keeps
        # MetricEvent sequence numbers separate from SensorReading
        # sequences so adding metrics never perturbs the locked
        # Level-2 hash (Inv-A / C1).
        self._metric_collector = metric_collector
        self._metrics_seq: SequenceGenerator | None = (
            SequenceGenerator() if metric_collector is not None else None
        )

    # ── Registration ─────────────────────────────────────────────────

    def register(self, spec: SensorSpec) -> None:
        """Register a sensor spec.

        Raises :class:`DuplicateSensorRegistrationError` on
        ``(sensor_id, sensor_version)`` collision and
        :class:`UnresolvedSensorDependencyError` when an upstream
        ``input_sensor_id`` is not yet registered.
        """
        key = spec.key
        if key in self._sensors:
            raise DuplicateSensorRegistrationError(
                f"sensor {key[0]!r} version {key[1]!r} already registered"
            )

        for upstream in spec.input_sensor_ids:
            if upstream not in self._specs_by_id:
                raise UnresolvedSensorDependencyError(
                    f"sensor {spec.sensor_id!r} declares input "
                    f"{upstream!r} which is not registered; register "
                    f"upstream sensors first (topological order)"
                )

        sensor: Sensor = spec.cls(**spec.params)

        # Validate the instantiated object satisfies the Protocol shape.
        # (Done here rather than via ``isinstance(sensor, Sensor)`` so
        # the diagnostic mentions which attribute is missing.)
        if getattr(sensor, "sensor_id", None) != spec.sensor_id:
            raise ValueError(
                f"sensor instance for {spec.sensor_id!r} reports "
                f"sensor_id={getattr(sensor, 'sensor_id', None)!r}; must "
                f"match spec"
            )
        if getattr(sensor, "sensor_version", None) != spec.sensor_version:
            raise ValueError(
                f"sensor instance for {spec.sensor_id!r} reports "
                f"sensor_version={getattr(sensor, 'sensor_version', None)!r}; "
                f"must match spec.sensor_version={spec.sensor_version!r}"
            )

        provenance = SensorProvenance(
            input_sensor_ids=tuple(sorted(spec.input_sensor_ids)),
            input_event_kinds=tuple(
                sorted(t.__name__ for t in spec.subscribes_to)
            ),
        )

        self._sensors[key] = sensor
        self._provenance[key] = provenance
        self._specs.append(spec)
        self._specs_by_id.setdefault(spec.sensor_id, []).append(spec)

        # Subscribe-once per event type.
        for event_type in spec.subscribes_to:
            if event_type not in self._subscribed_types:
                self._bus.subscribe(event_type, self._on_event)
                self._subscribed_types.add(event_type)

        # Pre-allocate per-symbol state so the first event has zero
        # surprises (matters for parity tests against fixtures where
        # the first event triggers state allocation).
        for symbol in self._symbols:
            self._state[(spec.sensor_id, spec.sensor_version, symbol)] = (
                sensor.initial_state()
            )

    # ── Public introspection ─────────────────────────────────────────

    def is_empty(self) -> bool:
        """True iff no sensors have been registered.

        The orchestrator uses this to skip the new micro-state
        transitions entirely, preserving the legacy execution path
        bit-for-bit (Inv-A).
        """
        return not self._specs

    @property
    def specs(self) -> tuple[SensorSpec, ...]:
        """Read-only view of registered specs in registration order."""
        return tuple(self._specs)

    # ── Dispatch ─────────────────────────────────────────────────────

    def _on_event(self, event: Event) -> None:
        """Bus handler — fans event out to every interested sensor.

        Iteration order: ``self._specs`` is preserved insertion order,
        which after Phase 2 bootstrap is also topological order across
        sensors.  Determinism (Inv-C) is therefore guaranteed without
        additional sorting on the hot path.
        """
        if not isinstance(event, (NBBOQuote, Trade)):
            return

        symbol = event.symbol
        if symbol not in self._symbols:
            # M13: log at DEBUG so universe-drift (config out of sync with
            # replay file) is observable without flooding production logs.
            _logger.debug(
                "SensorRegistry: dropping event for unknown symbol %r "
                "(known symbols: %s); check that the replay/live feed "
                "universe matches the configured symbol set",
                symbol,
                sorted(self._symbols),
            )
            return

        published: list[SensorReading] | None = self._publish_target

        for spec in self._specs:
            if type(event) not in spec.subscribes_to:
                continue

            throttle_key: _ThrottleKey = (spec.sensor_id, symbol)
            inside_throttle_window = False
            if spec.throttled_ms is not None and spec.throttled_ms > 0:
                last_ns = self._throttle_last_ns.get(throttle_key)
                if (
                    last_ns is not None
                    and (event.timestamp_ns - last_ns)
                    < spec.throttled_ms * 1_000_000
                ):
                    if not spec.stateful:
                        # H4 / M4: stateless sensors are skipped entirely
                        # inside the throttle window (original behaviour).
                        continue
                    # H4 / M4: stateful (accumulator) sensors must still
                    # advance their internal state on every event; only
                    # *emission* is suppressed by the throttle window.
                    inside_throttle_window = True

            sensor = self._sensors[spec.key]
            state = self._state[(spec.sensor_id, spec.sensor_version, symbol)]
            t0 = (
                time.perf_counter_ns()
                if self._metric_collector is not None
                else 0
            )
            try:
                raw = sensor.update(event, state, spec.params)
            except Exception:
                _logger.exception(
                    "sensor %s/%s raised on event for symbol %s",
                    spec.sensor_id,
                    spec.sensor_version,
                    symbol,
                )
                raise

            if raw is None:
                continue

            # Suppress emission (but not state advance) when inside the
            # throttle window for stateful sensors (H4 / M4).
            if inside_throttle_window:
                continue

            reading = self._stamp(raw, spec=spec, event=event, symbol=symbol)
            self._throttle_last_ns[throttle_key] = event.timestamp_ns

            self._bus.publish(reading)
            if published is not None:
                published.append(reading)

            if self._metric_collector is not None:
                latency_ns = time.perf_counter_ns() - t0
                self._emit_reading_metrics(
                    spec=spec,
                    symbol=symbol,
                    ts_ns=event.timestamp_ns,
                    latency_ns=latency_ns,
                )

    def _stamp(
        self,
        reading: SensorReading,
        *,
        spec: SensorSpec,
        event: Event,
        symbol: str,
    ) -> SensorReading:
        """Re-emit ``reading`` with registry-controlled provenance fields.

        The sensor produces a ``SensorReading`` with the *value* and
        *warmth* it computed.  The registry overrides the audit
        fields — ``sequence``, ``correlation_id``, ``source_layer``,
        ``provenance`` — so producers cannot accidentally diverge from
        the platform's determinism contract.
        """
        seq = self._sequence_generator.next()
        correlation_id = make_correlation_id(
            symbol=f"sensor:{spec.sensor_id}",
            exchange_timestamp_ns=event.timestamp_ns,
            sequence=seq,
        )
        provenance = self._provenance[spec.key]
        return SensorReading(
            timestamp_ns=event.timestamp_ns,
            correlation_id=correlation_id,
            sequence=seq,
            source_layer="SENSOR",
            symbol=symbol,
            sensor_id=spec.sensor_id,
            sensor_version=spec.sensor_version,
            value=reading.value,
            confidence=reading.confidence,
            warm=reading.warm,
            provenance=provenance,
        )

    # ── Monitoring (plan §4.5) ───────────────────────────────────────

    def _emit_reading_metrics(
        self,
        *,
        spec: SensorSpec,
        symbol: str,
        ts_ns: int,
        latency_ns: int,
    ) -> None:
        """Emit per-reading monitoring metrics.

        Two metrics per published ``SensorReading`` (plan §4.5):

        - ``feelies.sensor.reading.count`` — counter (``value=1.0``).
        - ``feelies.sensor.reading.latency`` — histogram, value in
          nanoseconds (raw ``time.perf_counter_ns()`` delta around
          the sensor's ``update`` call).

        Both share the ``layer="sensor"`` namespace so the
        :class:`InMemoryMetricCollector` summary key resolves to
        ``sensor.feelies.sensor.reading.count`` / ``...latency``.
        """
        assert self._metric_collector is not None
        assert self._metrics_seq is not None
        # Sequence numbers for metrics come from a *separate*
        # generator so MetricEvent emission cannot perturb the locked
        # SensorReading sequence (Inv-A / C1).
        seq_count = self._metrics_seq.next()
        cid = make_correlation_id(
            symbol=f"metric:sensor:{spec.sensor_id}",
            exchange_timestamp_ns=ts_ns,
            sequence=seq_count,
        )
        tags = {"sensor_id": spec.sensor_id, "symbol": symbol}
        self._metric_collector.record(MetricEvent(
            timestamp_ns=ts_ns,
            correlation_id=cid,
            sequence=seq_count,
            source_layer="SENSOR",
            layer="sensor",
            name="feelies.sensor.reading.count",
            value=1.0,
            metric_type=MetricType.COUNTER,
            tags=tags,
        ))
        seq_lat = self._metrics_seq.next()
        self._metric_collector.record(MetricEvent(
            timestamp_ns=ts_ns,
            correlation_id=cid,
            sequence=seq_lat,
            source_layer="SENSOR",
            layer="sensor",
            name="feelies.sensor.reading.latency",
            value=float(latency_ns),
            metric_type=MetricType.HISTOGRAM,
            tags={"sensor_id": spec.sensor_id},
        ))

    # ── Test / forensic helpers ──────────────────────────────────────

    def collect_into(self, target: list[SensorReading] | None) -> None:
        """Mirror every published ``SensorReading`` into ``target``.

        Used by parity recorders and Level-4 baseline tests so they do
        not have to also subscribe to the bus (avoiding double-delivery
        ordering surprises).  Pass ``None`` to disable mirroring.
        """
        self._publish_target = target
