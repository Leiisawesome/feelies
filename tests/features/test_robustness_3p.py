"""Test non-finite demotion and Welford drift recomputation."""

from __future__ import annotations

import math
from typing import Any, Mapping

from feelies.bus.event_bus import EventBus
from feelies.core.events import HorizonFeatureSnapshot, HorizonTick, SensorReading
from feelies.core.identifiers import SequenceGenerator
from feelies.features.aggregator import HorizonAggregator
from feelies.features.impl.horizon_windowed import HorizonWindowedFeature

_NS = 1_000_000_000


# Non-finite warm features become cold.


class _NaNFeature:
    feature_id = "nan_feature"
    feature_version = "1.0.0"
    input_sensor_ids: tuple[str, ...] = ("any",)
    horizon_seconds = 30

    def initial_state(self) -> dict[str, Any]:
        return {}

    def observe(
        self, reading: SensorReading, state: dict[str, Any], params: Mapping[str, Any]
    ) -> None:
        return None

    def finalize(
        self, tick: HorizonTick, state: dict[str, Any], params: Mapping[str, Any]
    ) -> tuple[float, bool, bool]:
        # Claims to be warm but returns a non-finite value (a reducer bug).
        return float("nan"), True, False


def test_aggregator_demotes_nonfinite_feature_to_cold() -> None:
    bus = EventBus()
    agg = HorizonAggregator(
        bus=bus,
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=60,
        sequence_generator=SequenceGenerator(),
        horizon_features=[_NaNFeature()],
    )
    snaps: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, snaps.append)
    agg.attach()

    tick = HorizonTick(
        timestamp_ns=30 * _NS,
        correlation_id="t",
        sequence=0,
        horizon_seconds=30,
        boundary_index=1,
        scope="SYMBOL",
        symbol="AAPL",
        session_id="T",
    )
    out = agg.on_horizon_tick(tick)
    assert len(out) == 1
    snap = out[0]
    # The non-finite value must NOT appear in values, and warm is forced False.
    assert "nan_feature" not in snap.values
    assert snap.warm["nan_feature"] is False
    assert all(math.isfinite(v) for v in snap.values.values())


# Reverse-Welford drift is recomputed from the window.


def test_welford_recompute_on_drift_flag() -> None:
    feat = HorizonWindowedFeature("s", 30, reducer="zscore", feature_id="s_zscore", min_samples=2)
    state = feat.initial_state()
    # Build a window of known values via the public observe path.
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    for i, x in enumerate(xs):
        reading = SensorReading(
            timestamp_ns=i * _NS,
            correlation_id="r",
            sequence=i,
            symbol="AAPL",
            sensor_id="s",
            sensor_version="1.0.0",
            value=x,
            warm=True,
        )
        feat.observe(reading, state, {})

    # Simulate accumulator corruption + the drift flag the remove path sets.
    state["mean"] = -999.0
    state["M2"] = -1.0
    state["_drift_dirty"] = True

    # An eviction sweep (nothing expires at cutoff 0) must still recompute.
    feat._evict_before(state, 0)

    n = len(xs)
    exp_mean = sum(xs) / n
    exp_m2 = sum((x - exp_mean) ** 2 for x in xs)
    assert state["_drift_dirty"] is False
    assert math.isclose(state["mean"], exp_mean, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(state["M2"], exp_m2, rel_tol=0, abs_tol=1e-9)
    assert state["n"] == n
