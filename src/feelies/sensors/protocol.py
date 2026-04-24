"""Sensor Protocol — the contract every Layer-1 sensor satisfies.

A ``Sensor`` is a deterministic, incremental computation over raw
market events (``NBBOQuote``, ``Trade``).  It owns no instance state;
all mutable state lives in a per-symbol ``dict`` owned by the
:class:`feelies.sensors.registry.SensorRegistry` and threaded through
``update()``.  This mirrors the legacy ``FeatureComputation`` Protocol
in :mod:`feelies.features.definition` and inherits the same
determinism guarantees (Inv 5).

Design notes (plan §3.1):

- **No** ``is_warm`` method.  Sensors set ``warm`` directly on the
  ``SensorReading`` they return; this avoids two-call redundancy and
  keeps warmness an emission-time concern.
- ``update()`` may return ``None`` to skip an emission (used by
  trade-only sensors when they receive a quote, and vice versa).  The
  registry never publishes ``None``.
- ``provenance`` on the emitted ``SensorReading`` is **pre-baked** by
  the registry from the sensor's ``SensorSpec``; sensors must attach
  the provided ``provenance`` instance verbatim and not allocate a
  fresh one per call (plan §3.1 / S4).
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from feelies.core.events import NBBOQuote, SensorReading, Trade


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
    ) -> SensorReading | None:
        """Advance state by one event and optionally emit a reading.

        Implementations must:

        - Mutate ``state`` exactly once per call (incremental).
        - Be deterministic: same ``(event, state, params)`` always
          yields the same ``(state, return_value)`` (Inv 5).
        - Return ``None`` to skip emission (e.g. a quote-only sensor
          receiving a ``Trade``).  The registry does not publish
          ``None`` to the bus.
        - Set ``warm`` on the returned ``SensorReading`` based on the
          sensor's own warmth criteria; the registry trusts this flag.
        """
        ...
