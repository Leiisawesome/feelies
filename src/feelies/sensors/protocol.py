"""Contract for deterministic Layer-1 sensors.

Sensors incrementally consume quotes or trades while the registry owns their
per-symbol state. Emissions carry value, warmth, and confidence; the registry
adds provenance. ``None`` skips publication. Returning a full
``SensorReading`` remains supported for compatibility.
"""

from __future__ import annotations

from typing import Any, Mapping, NamedTuple, Protocol, runtime_checkable

from feelies.core.events import NBBOQuote, SensorReading, Trade


class SensorEmission(NamedTuple):
    """Lightweight sensor output — registry stamps into ``SensorReading``.

    Prefer this over constructing a placeholder ``SensorReading`` so the
    hot path allocates the event exactly once.
    """

    value: float | tuple[float, ...]
    warm: bool
    confidence: float = 1.0


@runtime_checkable
class Sensor(Protocol):
    """Layer-1 sensor over raw market events.

    Implementations are typically module-level singletons holding only
    immutable parameters; per-symbol mutable state is kept in the
    ``state`` dict passed to :meth:`update`.
    """

    sensor_id: str
    sensor_version: str

    def initial_state(self) -> dict[str, Any]:
        """Return a fresh state dict for a new symbol.

        Called once per ``(sensor_id, symbol)`` pair at registration
        time.  The returned dict is owned by the registry and mutated
        in-place by subsequent :meth:`update` calls.
        """
        ...

    def update(
        self,
        event: NBBOQuote | Trade,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> SensorEmission | SensorReading | None:
        """Advance state by one event and optionally emit a reading.

        Implementations must:

        - Mutate ``state`` exactly once per call (incremental).
        - Be deterministic: same ``(event, state, params)`` always
          yields the same ``(state, return_value)`` (Inv 5).
        - Return ``None`` to skip emission (e.g. a quote-only sensor
          receiving a ``Trade``).  The registry does not publish
          ``None`` to the bus.
        - Prefer :class:`SensorEmission`; set ``warm`` based on the
          sensor's own warmth criteria.  The registry trusts this flag.
        """
        ...
