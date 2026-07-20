"""Contracts for horizon-aware Layer-2 features.

Features fold sensor readings into aggregator-owned per-symbol state. The
aggregator calls ``finalize`` at each horizon tick and records the value,
warmth, staleness, and versioned provenance in a feature snapshot.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from feelies.core.events import HorizonTick, SensorReading


@runtime_checkable
class HorizonFeature(Protocol):
    """Layer-2 feature contract: aggregate sensor readings per horizon.

    Lifecycle (per symbol, per horizon):

    1.  ``initial_state()`` is called once on first observation of
        the ``(symbol, horizon)`` pair.  The returned dict is owned
        by the aggregator and mutated in place.
    2.  ``observe(reading, state, params)`` is called on every
        ``SensorReading`` whose ``sensor_id`` is listed in
        ``input_sensor_ids``.  The feature folds the reading into
        ``state``; no value is emitted.
    3.  ``finalize(tick, state, params)`` is called when a
        ``HorizonTick`` for this ``(symbol, horizon)`` arrives.  The
        feature returns ``(value, warm, stale)``; the aggregator
        bundles these into a ``HorizonFeatureSnapshot``.

    Determinism (Inv-5): two identical event sequences must produce
    identical ``(value, warm, stale)`` triples.  Implementations
    must therefore avoid wall-clock reads, RNG without explicit
    seeding, and any iteration over unordered collections.
    """

    feature_id: str
    feature_version: str
    input_sensor_ids: tuple[str, ...]
    horizon_seconds: int

    def initial_state(self) -> dict[str, Any]:
        """Return the starting state for a new ``(symbol, horizon)`` pair."""
        ...

    def observe(
        self,
        reading: SensorReading,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> None:
        """Fold a sensor reading into the per-symbol/per-horizon state.

        Must not emit any event; emission is the aggregator's
        responsibility on ``HorizonTick``.
        """
        ...

    def finalize(
        self,
        tick: HorizonTick,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> tuple[float, bool, bool]:
        """Compute the feature's value at the tick boundary.

        Returns ``(value, warm, stale)``:

        - ``value``: the scalar Layer-2 feature value.
        - ``warm``: ``True`` once enough history has accumulated.
        - ``stale``: ``True`` if no fresh sensor readings arrived in
          this horizon window — used downstream to suppress signal
          generation on stale features (Inv-11 fail-safe default).

        Implementations may also reset windowed state inside this
        method (e.g. zeroing a per-window counter), since the
        aggregator will not call ``observe`` again until the next
        sensor reading arrives.
        """
        ...


__all__ = ["HorizonFeature"]
