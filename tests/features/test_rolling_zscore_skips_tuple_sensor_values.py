"""Regression guard: tuple-valued sensor readings are ignored by RollingZscoreFeature.

``HawkesIntensitySensor`` emits a 4-tuple (see sensor docstring). The
Phase-2 wiring in ``bootstrap._horizon_features_for`` attaches a
:class:`RollingZscoreFeature` directly to ``sensor_id="hawkes_intensity"``.
That feature's ``observe`` implementation deliberately skips tuple
values (tuple sensors are expected to use ``TupleComponentFeature``).

Therefore ``hawkes_intensity_zscore`` cannot warm from real Hawkes
readings until bootstrap exposes a scalar series (e.g. a tuple component
feature feeding a rolling statistic). This test documents the behaviour
so an institutional audit can point at executable evidence.
"""

from __future__ import annotations

from feelies.core.events import HorizonTick, SensorReading
from feelies.features.impl.rolling_stats import RollingZscoreFeature


def test_rolling_zscore_does_not_accumulate_hawkes_tuple_readings() -> None:
    feat = RollingZscoreFeature(
        "hawkes_intensity",
        horizon_seconds=30,
        min_samples=1,
        max_samples=50,
    )
    state = feat.initial_state()
    reading = SensorReading(
        timestamp_ns=1_000,
        correlation_id="c",
        sequence=1,
        source_layer="SENSORS",
        symbol="TEST",
        sensor_id="hawkes_intensity",
        sensor_version="1.1.0",
        value=(1.0, 2.0, 0.66, 8.0),
        warm=True,
    )
    feat.observe(reading, state, {})
    tick = HorizonTick(
        timestamp_ns=2_000,
        correlation_id="c2",
        sequence=2,
        source_layer="FEATURES",
        horizon_seconds=30,
        boundary_index=1,
        session_id="US_EQUITY_RTH_2026-01-15",
        scope="SYMBOL",
        symbol="TEST",
    )
    val, warm, stale = feat.finalize(tick, state, {})
    assert warm is False
    assert val == 0.0
    assert stale is False
