"""RollingZscoreFeature tuple handling — Hawkes intensity path."""

from __future__ import annotations

import pytest

from feelies.core.events import HorizonTick, SensorReading
from feelies.features.impl.rolling_stats import RollingZscoreFeature


def test_rolling_zscore_skips_tuple_without_component_sum_config() -> None:
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
        sensor_version="1.2.0",
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


def test_rolling_zscore_sums_configured_tuple_components_for_hawkes() -> None:
    feat = RollingZscoreFeature(
        "hawkes_intensity",
        horizon_seconds=30,
        min_samples=1,
        max_samples=50,
        tuple_sum_component_indices=(0, 1),
    )
    state = feat.initial_state()
    reading = SensorReading(
        timestamp_ns=1_000,
        correlation_id="c",
        sequence=1,
        source_layer="SENSORS",
        symbol="TEST",
        sensor_id="hawkes_intensity",
        sensor_version="1.2.0",
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
    assert warm is True
    assert val == pytest.approx(0.0)
    assert stale is False
