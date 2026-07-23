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
instance for performance and reproducible provenance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

from feelies.core.events import Event, NBBOQuote, Trade

_logger = logging.getLogger(__name__)


_VALID_SUBSCRIPTION_TYPES: tuple[type[Event], ...] = (NBBOQuote, Trade)


@dataclass(frozen=True, kw_only=True)
class SensorSpec:
    """Immutable sensor registration.

    ``(sensor_id, sensor_version)`` is unique. Dependencies must be registered
    first, subscriptions are limited to quotes and trades, and throttling skips
    the sensor update entirely to preserve deterministic state.
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
      ``sensor.update()`` is skipped; the sensor advances only on emissions.
    * ``stateful=True``: ``sensor.update()`` is called on every event
      regardless of the throttle window, but the resulting
      ``SensorReading`` is only *emitted* (published to the bus) when
      outside the window.  This separates "state advance" from
      "emission rate-limiting" so the estimator remains unbiased.

    Operators MUST set ``stateful=True`` for any accumulator sensor
    paired with a non-null ``throttled_ms``. Otherwise skipped updates bias
    the estimator.
    """
    stateless_throttle_ok: bool = False
    """Operator acknowledgment that a ``throttled_ms`` + ``stateful=False``
    pair is intentional for a *truly* non-accumulator sensor.

    Load-time / warning only — the registry ignores this flag.  YAML
    loaders set it when ``stateful: false`` is written explicitly next
    to a non-null throttle (affirmative "I checked: no accumulator").
    Omitting ``stateful`` while setting ``throttled_ms`` still warns.
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
            t.__name__ for t in self.subscribes_to if t not in _VALID_SUBSCRIPTION_TYPES
        )
        if invalid:
            valid = tuple(t.__name__ for t in _VALID_SUBSCRIPTION_TYPES)
            raise ValueError(
                f"SensorSpec({self.sensor_id!r}).subscribes_to contains "
                f"unsupported event types {invalid}; valid types are {valid}"
            )
        if self.min_history < 0:
            raise ValueError(
                f"SensorSpec({self.sensor_id!r}).min_history must be >= 0, got {self.min_history}"
            )
        if self.throttled_ms is not None and self.throttled_ms < 0:
            raise ValueError(
                f"SensorSpec({self.sensor_id!r}).throttled_ms must be >= 0 "
                f"or None, got {self.throttled_ms}"
            )
        # Skipping updates biases accumulators; require an explicit stateless opt-in.
        if (
            self.throttled_ms is not None
            and self.throttled_ms > 0
            and not self.stateful
            and not self.stateless_throttle_ok
        ):
            _logger.warning(
                "SensorSpec(%r): throttled_ms=%d is set but stateful=False; "
                "update() will be SKIPPED inside the throttle window.  This is "
                "only safe for a truly stateless sensor — any accumulator "
                "(EWMA/Hawkes/Kyle/rolling-window) MUST set stateful=True or "
                "skipped events will bias the estimator (H4/M4 audit).  "
                "To silence for a verified-stateless sensor, set "
                "stateful: false explicitly in YAML (or "
                "stateless_throttle_ok=True in code).",
                self.sensor_id,
                self.throttled_ms,
            )

    @property
    def key(self) -> tuple[str, str]:
        """Composite registration key — used by the registry."""
        return (self.sensor_id, self.sensor_version)
