"""Declarative SensorSpec — registers one sensor with the registry.

A ``SensorSpec`` is the immutable declaration the registry consumes at
boot time.  It binds a sensor implementation (``cls``) to:

- a registration key (``sensor_id`` + ``sensor_version``);
- the event types it subscribes to (``subscribes_to``);
- any upstream sensors it depends on (``input_sensor_ids``);
- bound parameters (``params``);
- a warm-up minimum (``min_history``);
- an optional throttle expressed in milliseconds (``throttled_ms``).

The registry pre-bakes a :class:`feelies.core.events.SensorProvenance`
record from ``subscribes_to`` and ``input_sensor_ids`` at registration
time so each emitted reading shares the same immutable provenance
instance — both for performance (no per-event allocation) and for
audit reproducibility (plan §3.1 / S4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from feelies.core.events import Event, NBBOQuote, Trade


_VALID_SUBSCRIPTION_TYPES: tuple[type[Event], ...] = (NBBOQuote, Trade)


@dataclass(frozen=True, kw_only=True)
class SensorSpec:
    """One row in the sensor registration table.

    Fields:

    - ``sensor_id`` / ``sensor_version`` — composite registration key.
      Two specs sharing the same ``(id, version)`` raise
      :class:`feelies.sensors.errors.DuplicateSensorRegistrationError`
      at registration time.
    - ``cls`` — class implementing the :class:`feelies.sensors.protocol.Sensor`
      Protocol.  The registry instantiates it once via
      ``cls(**params)`` and reuses the singleton across all symbols.
    - ``params`` — keyword arguments forwarded to ``cls(**params)`` and
      also threaded into every ``update()`` call as the ``params``
      mapping (kept immutable as a frozen mapping view).
    - ``subscribes_to`` — tuple of event classes the sensor consumes.
      Must be a subset of ``(NBBOQuote, Trade)`` in Phase 2; the
      registry uses this tuple to populate
      ``SensorProvenance.input_event_kinds``.
    - ``input_sensor_ids`` — upstream sensors whose ``SensorReading``
      events this sensor consumes (cross-sensor dependencies, e.g.
      ``structural_break_score`` over ``hawkes_intensity``).  The
      registry enforces topological registration order.
    - ``min_history`` — minimum number of warmup events before
      ``warm=True`` readings are emitted.  Sensors should consult this
      via ``params`` (the registry does not gate on it; warmth is a
      sensor-level concern as per :mod:`feelies.sensors.protocol`).
    - ``throttled_ms`` — optional emit-rate limiter, enforced at the
      registry level (plan §3.1 / S5).  ``None`` disables throttling.
      The registry skips an ``update()`` call if the time since the
      last emission for this ``(sensor_id, symbol)`` is below the
      threshold; the sensor is *not* invoked in that case (preserves
      determinism vs. running and discarding).
    """

    sensor_id: str
    sensor_version: str
    cls: type[Any]
    params: Mapping[str, Any] = field(default_factory=dict)
    subscribes_to: tuple[type[Event], ...] = (NBBOQuote,)
    input_sensor_ids: tuple[str, ...] = ()
    min_history: int = 0
    throttled_ms: int | None = None
    stateful: bool = False
    """When ``True`` the sensor is an accumulator (e.g. EWMA, Hawkes
    intensity, Kyle-lambda): its ``update()`` call *must not* be skipped
    even when the registry is inside a throttle window, because every
    skipped event biases the estimator.

    Effect on throttle behaviour:

    * ``stateful=False`` (default): when inside the throttle window,
      ``sensor.update()`` is skipped entirely (legacy behaviour,
      preserves the original determinism contract — the sensor only
      advances on emissions).
    * ``stateful=True``: ``sensor.update()`` is called on every event
      regardless of the throttle window, but the resulting
      ``SensorReading`` is only *emitted* (published to the bus) when
      outside the window.  This separates "state advance" from
      "emission rate-limiting" so the estimator remains unbiased.

    Operators MUST set ``stateful=True`` for any accumulator sensor
    paired with a non-null ``throttled_ms``.  Setting
    ``throttled_ms`` on a stateful sensor without this flag is
    undefined behaviour (H4 / M4 audit).
    """

    def __post_init__(self) -> None:
        if not self.sensor_id:
            raise ValueError("SensorSpec.sensor_id must be non-empty")
        if not self.sensor_version:
            raise ValueError("SensorSpec.sensor_version must be non-empty")
        if not self.subscribes_to:
            raise ValueError(
                f"SensorSpec({self.sensor_id!r}).subscribes_to must declare "
                f"at least one event type"
            )
        invalid = tuple(
            t.__name__
            for t in self.subscribes_to
            if t not in _VALID_SUBSCRIPTION_TYPES
        )
        if invalid:
            valid = tuple(t.__name__ for t in _VALID_SUBSCRIPTION_TYPES)
            raise ValueError(
                f"SensorSpec({self.sensor_id!r}).subscribes_to contains "
                f"unsupported event types {invalid}; valid types are {valid}"
            )
        if self.min_history < 0:
            raise ValueError(
                f"SensorSpec({self.sensor_id!r}).min_history must be >= 0, "
                f"got {self.min_history}"
            )
        if self.throttled_ms is not None and self.throttled_ms < 0:
            raise ValueError(
                f"SensorSpec({self.sensor_id!r}).throttled_ms must be >= 0 "
                f"or None, got {self.throttled_ms}"
            )

    @property
    def key(self) -> tuple[str, str]:
        """Composite registration key — used by the registry."""
        return (self.sensor_id, self.sensor_version)
