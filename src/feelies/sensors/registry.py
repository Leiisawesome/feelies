"""Own per-symbol sensor state and publish stamped readings.

The registry subscribes once per raw event type, fans out in registration order,
and precomputes immutable provenance. Dependencies must be registered first;
duplicate ID-version pairs fail at startup. Throttling skips stateless updates
but still advances stateful estimators, suppressing only their emission. The
registry publishes ``SensorReading`` events only.
"""

from __future__ import annotations

import logging
import math
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
from feelies.sensors.protocol import Sensor, SensorEmission
from feelies.sensors.spec import SensorSpec

_logger = logging.getLogger(__name__)


# A throttle bookkeeping entry keyed by (sensor_id, symbol).
# Stored as nanoseconds to avoid float drift across runs.
_ThrottleKey = tuple[str, str]


def _is_finite_value(value: Any) -> bool:
    """True iff every numeric component of a sensor value is finite.

    A non-finite (``NaN`` or ``±Inf``) sensor value must never reach
    the bus — it permanently poisons downstream rolling accumulators (a NaN
    folded into a Welford mean stays NaN forever), silently flips regime-gate
    comparisons (``NaN < x`` is ``False``), and propagates into signal edge and
    position sizing.  Scalars and every component of a tuple value are checked.
    """
    if isinstance(value, tuple):
        return all(math.isfinite(v) for v in value)
    return math.isfinite(value)


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
        "_emit_reading_metrics_enabled",
    )

    def __init__(
        self,
        *,
        bus: EventBus,
        sequence_generator: SequenceGenerator,
        symbols: frozenset[str],
        metric_collector: MetricCollector | None = None,
        emit_reading_metrics: bool = True,
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
        # Metrics use a separate sequence so observability cannot perturb readings.
        self._metric_collector = metric_collector
        self._emit_reading_metrics_enabled = emit_reading_metrics
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
            input_event_kinds=tuple(sorted(t.__name__ for t in spec.subscribes_to)),
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

        # Pre-allocate symbol state so the first event performs no allocation.
        for symbol in self._symbols:
            self._state[(spec.sensor_id, spec.sensor_version, symbol)] = sensor.initial_state()

    # ── Public introspection ─────────────────────────────────────────

    def is_empty(self) -> bool:
        """True iff no sensors have been registered.

        The orchestrator uses this to skip sensor micro-states and preserve
        parity when no sensors are registered.
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
        which after bootstrap is also topological order across
        sensors.  Determinism (Inv-C) is therefore guaranteed without
        additional sorting on the hot path.
        """
        if not isinstance(event, (NBBOQuote, Trade)):
            return

        symbol = event.symbol
        if symbol not in self._symbols:
            # Log config/feed universe drift without flooding production logs.
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
                    and (event.timestamp_ns - last_ns) < spec.throttled_ms * 1_000_000
                ):
                    if not spec.stateful:
                        # Stateless sensors are skipped entirely
                        # inside the throttle window (original behaviour).
                        continue
                    # Stateful sensors advance on every event; only emission
                    # is suppressed inside the throttle window.
                    inside_throttle_window = True

            sensor = self._sensors[spec.key]
            state = self._state[(spec.sensor_id, spec.sensor_version, symbol)]
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

            # Suppress non-finite readings without advancing the emission throttle.
            if not _is_finite_value(raw.value):
                _logger.warning(
                    "sensor %s/%s produced a non-finite value %r for symbol "
                    "%s at ts=%d; suppressing emission (3P-1 fail-safe)",
                    spec.sensor_id,
                    spec.sensor_version,
                    raw.value,
                    symbol,
                    event.timestamp_ns,
                )
                if self._metric_collector is not None:
                    self._emit_nonfinite_metric(spec=spec, symbol=symbol, ts_ns=event.timestamp_ns)
                continue

            # Suppress emission (but not state advance) when inside the
            # throttle window for stateful sensors.
            if inside_throttle_window:
                continue

            reading = self._stamp(raw, spec=spec, event=event, symbol=symbol)
            self._throttle_last_ns[throttle_key] = event.timestamp_ns

            self._bus.publish(reading)
            if published is not None:
                published.append(reading)

            if self._metric_collector is not None and self._emit_reading_metrics_enabled:
                self._emit_reading_metrics(
                    spec=spec,
                    symbol=symbol,
                    ts_ns=event.timestamp_ns,
                )

    def _stamp(
        self,
        emission: SensorEmission | SensorReading,
        *,
        spec: SensorSpec,
        event: Event,
        symbol: str,
    ) -> SensorReading:
        """Build a registry-stamped ``SensorReading`` from a sensor emission.

        Sensors preferably return :class:`SensorEmission` (value/warm/
        confidence only).  Returning a full ``SensorReading`` remains
        supported; the registry overrides platform fields — ``sequence``,
        ``correlation_id``, ``source_layer``, ``provenance`` — so
        producers cannot diverge from the determinism contract.

        ``parent_correlation_id`` is set to the originating market-data
        event's ``correlation_id`` to preserve the parent-child trace.
        """
        if isinstance(emission, SensorReading) and emission.correlation_id != "placeholder":
            # Sensors should leave correlation_id as "placeholder";
            # the registry is the sole authority that sets real IDs.
            _logger.debug(
                "sensor %s returned SensorReading with non-placeholder "
                "correlation_id %r; registry will override",
                spec.sensor_id,
                emission.correlation_id,
            )
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
            value=emission.value,
            confidence=emission.confidence,
            warm=emission.warm,
            provenance=provenance,
            parent_correlation_id=event.correlation_id,  # Preserve event lineage.
        )

    # Monitoring.

    def _emit_reading_metrics(
        self,
        *,
        spec: SensorSpec,
        symbol: str,
        ts_ns: int,
    ) -> None:
        """Emit per-reading monitoring metrics.

        One metric is emitted per published ``SensorReading``:

        - ``feelies.sensor.reading.count`` — counter (``value=1.0``).

        Latency monitoring belongs in a dedicated subscriber outside the
        deterministic sensor path.

        The metric uses the ``layer="sensor"`` namespace so the
        :class:`InMemoryMetricCollector` summary key resolves to
        ``sensor.feelies.sensor.reading.count``.
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
        self._metric_collector.record(
            MetricEvent(
                timestamp_ns=ts_ns,
                correlation_id=cid,
                sequence=seq_count,
                source_layer="SENSOR",
                layer="sensor",
                name="feelies.sensor.reading.count",
                value=1.0,
                metric_type=MetricType.COUNTER,
                tags=tags,
            )
        )

    def _emit_nonfinite_metric(
        self,
        *,
        spec: SensorSpec,
        symbol: str,
        ts_ns: int,
    ) -> None:
        """Emit ``feelies.sensor.nonfinite.count`` for one suppressed value.

        Counter (``value=1.0``), one per suppressed non-finite emission, so the
        fail-safe is observable in monitoring rather than silent.  Uses the same
        dedicated metrics sequence generator as the per-reading counter so it
        cannot perturb the sensor-reading sequence.
        """
        assert self._metric_collector is not None
        assert self._metrics_seq is not None
        seq = self._metrics_seq.next()
        cid = make_correlation_id(
            symbol=f"metric:sensor-nonfinite:{spec.sensor_id}",
            exchange_timestamp_ns=ts_ns,
            sequence=seq,
        )
        self._metric_collector.record(
            MetricEvent(
                timestamp_ns=ts_ns,
                correlation_id=cid,
                sequence=seq,
                source_layer="SENSOR",
                layer="sensor",
                name="feelies.sensor.nonfinite.count",
                value=1.0,
                metric_type=MetricType.COUNTER,
                tags={"sensor_id": spec.sensor_id, "symbol": symbol},
            )
        )

    # Inspection helpers.

    def collect_into(self, target: list[SensorReading] | None) -> None:
        """Mirror every published ``SensorReading`` into ``target``.

        Used by parity recorders and Level-4 baseline tests so they do
        not have to also subscribe to the bus (avoiding double-delivery
        ordering surprises).  Pass ``None`` to disable mirroring.
        """
        self._publish_target = target
