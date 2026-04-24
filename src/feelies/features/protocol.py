"""Protocols for the Phase-2 horizon-aware feature layer.

Defines the contract a Layer-2 feature implementation must satisfy
to be plugged into ``feelies.features.aggregator.HorizonAggregator``.
A Layer-2 feature consumes ``SensorReading`` events (Layer-1 outputs)
and produces a single scalar value per ``HorizonTick`` boundary, plus
``warm`` / ``stale`` flags that propagate into the
``HorizonFeatureSnapshot``.

This module is **contract-only** in P2-α/β — no concrete features
ship here.  The first concrete features land in Phase 3 (signal
layer); P2-β only wires the protocol so Phase 3 can attach
implementations without re-touching the feature layer.

Design choices (plan §5):

- **Pull, not push** — The aggregator drives ``finalize()`` on every
  registered feature when a ``HorizonTick`` arrives, rather than
  features subscribing to ``SensorReading`` events directly.  This
  keeps the bus subscription count O(1) regardless of how many
  features exist (mirrors the registry-as-single-subscriber pattern
  in :class:`feelies.sensors.registry.SensorRegistry`).
- **Per-symbol state** — Like sensors, features carry per-symbol
  state owned by the aggregator and passed in as a mutable dict.
  The feature implementation never holds per-symbol state on its
  instance.
- **Versioned identity** — ``feature_id`` + ``feature_version``
  participate in the ``HorizonFeatureSnapshot.source_sensors`` /
  provenance trail so consumers can reconstruct exactly which
  feature version produced each value (Inv-13).
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
        - ``warm``: ``True`` once enough history has accumulated for
          the value to be reliable (mirrors the legacy
          :class:`feelies.features.definition.WarmUpSpec` semantics).
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
