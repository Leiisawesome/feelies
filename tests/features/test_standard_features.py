"""Unit tests for concrete HorizonFeature implementations in feelies.features.impl.

Covers:

- :class:`SensorPassthroughFeature` — scalar sensor exposed directly
- :class:`TupleComponentFeature` — one index of a tuple sensor reading
- :class:`RollingZscoreFeature` — normalised z-score over rolling window
- :class:`RollingPercentileFeature` — empirical CDF rank in rolling window
- Multi-horizon aggregator wiring — same feature_id at two horizons does
  not collide in state or snapshot values
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    HorizonTick,
    SensorReading,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.features.aggregator import HorizonAggregator
from feelies.features.impl.rolling_stats import (
    RollingPercentileFeature,
    RollingZscoreFeature,
)
from feelies.features.impl.sensor_passthrough import (
    SensorPassthroughFeature,
    TupleComponentFeature,
)


# ── Helpers ────────────────────────────────────────────────────────


def _reading(
    *,
    symbol: str = "AAPL",
    ts_ns: int,
    sensor_id: str = "ofi_ewma",
    value: Any = 1.0,
    warm: bool = True,
) -> SensorReading:
    return SensorReading(
        timestamp_ns=ts_ns,
        correlation_id=f"r-{ts_ns}",
        sequence=ts_ns,
        symbol=symbol,
        sensor_id=sensor_id,
        sensor_version="1.0.0",
        value=value,
        warm=warm,
    )


def _tick(
    *,
    horizon: int = 30,
    boundary: int = 1,
    ts_ns: int = 30_000_000_000,
    symbol: str = "AAPL",
    scope: str = "SYMBOL",
) -> HorizonTick:
    return HorizonTick(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{horizon}-{scope}-{boundary}",
        sequence=boundary + 1,
        horizon_seconds=horizon,
        boundary_index=boundary,
        scope=scope,
        symbol=symbol,
        session_id="TEST",
    )


_DUMMY_TICK = _tick()


# ── SensorPassthroughFeature ───────────────────────────────────────


class TestSensorPassthroughFeature:
    def test_feature_id_defaults_to_sensor_id(self) -> None:
        f = SensorPassthroughFeature("ofi_ewma", 30)
        assert f.feature_id == "ofi_ewma"

    def test_feature_id_override(self) -> None:
        f = SensorPassthroughFeature("ofi_ewma", 30, feature_id="ofi_raw")
        assert f.feature_id == "ofi_raw"

    def test_horizon_seconds_set(self) -> None:
        f = SensorPassthroughFeature("ofi_ewma", 120)
        assert f.horizon_seconds == 120

    def test_input_sensor_ids(self) -> None:
        f = SensorPassthroughFeature("ofi_ewma", 30)
        assert f.input_sensor_ids == ("ofi_ewma",)

    def test_finalize_no_readings_returns_cold(self) -> None:
        f = SensorPassthroughFeature("ofi_ewma", 30)
        state = f.initial_state()
        value, warm, stale = f.finalize(_DUMMY_TICK, state, {})
        assert value == 0.0
        assert warm is False
        assert stale is False

    def test_observe_scalar_then_finalize(self) -> None:
        f = SensorPassthroughFeature("ofi_ewma", 30)
        state = f.initial_state()
        f.observe(_reading(ts_ns=1, value=3.14), state, {})
        value, warm, stale = f.finalize(_DUMMY_TICK, state, {})
        assert value == 3.14
        assert warm is True
        assert stale is False

    def test_observe_updates_to_latest(self) -> None:
        f = SensorPassthroughFeature("ofi_ewma", 30)
        state = f.initial_state()
        f.observe(_reading(ts_ns=1, value=1.0), state, {})
        f.observe(_reading(ts_ns=2, value=9.9), state, {})
        value, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert value == 9.9

    def test_cold_reading_ignored(self) -> None:
        f = SensorPassthroughFeature("ofi_ewma", 30)
        state = f.initial_state()
        f.observe(_reading(ts_ns=1, value=5.0, warm=False), state, {})
        _, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert warm is False

    def test_tuple_value_ignored(self) -> None:
        f = SensorPassthroughFeature("scheduled_flow_window", 30)
        state = f.initial_state()
        f.observe(_reading(ts_ns=1, sensor_id="scheduled_flow_window", value=(1.0, 60.0, 0.5, 0.3)), state, {})
        _, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert warm is False


# ── TupleComponentFeature ──────────────────────────────────────────


class TestTupleComponentFeature:
    def test_extracts_component_0(self) -> None:
        f = TupleComponentFeature("scheduled_flow_window", 0, "scheduled_flow_window_active", 120)
        state = f.initial_state()
        f.observe(
            _reading(ts_ns=1, sensor_id="scheduled_flow_window", value=(1.0, 45.0, 0.9, 0.2)),
            state, {},
        )
        value, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert value == 1.0
        assert warm is True

    def test_extracts_component_3(self) -> None:
        f = TupleComponentFeature("scheduled_flow_window", 3, "scheduled_flow_window_direction_prior", 120)
        state = f.initial_state()
        f.observe(
            _reading(ts_ns=1, sensor_id="scheduled_flow_window", value=(1.0, 45.0, 0.9, 0.25)),
            state, {},
        )
        value, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert abs(value - 0.25) < 1e-9

    def test_cold_reading_ignored(self) -> None:
        f = TupleComponentFeature("scheduled_flow_window", 0, "sfw_active", 120)
        state = f.initial_state()
        f.observe(
            _reading(ts_ns=1, sensor_id="scheduled_flow_window", value=(1.0, 45.0, 0.9, 0.2), warm=False),
            state, {},
        )
        _, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert warm is False

    def test_scalar_reading_ignored(self) -> None:
        f = TupleComponentFeature("ofi_ewma", 0, "ofi_0", 30)
        state = f.initial_state()
        # SensorPassthrough would take this; TupleComponent should skip it
        f.observe(_reading(ts_ns=1, value=5.5), state, {})
        _, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert warm is False

    def test_out_of_bounds_index_ignored(self) -> None:
        f = TupleComponentFeature("scheduled_flow_window", 10, "far_out", 30)
        state = f.initial_state()
        f.observe(
            _reading(ts_ns=1, sensor_id="scheduled_flow_window", value=(1.0, 2.0)),
            state, {},
        )
        _, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert warm is False

    def test_no_readings_returns_cold(self) -> None:
        f = TupleComponentFeature("scheduled_flow_window", 1, "sfw_ttc", 120)
        state = f.initial_state()
        _, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert warm is False


# ── RollingZscoreFeature ───────────────────────────────────────────


class TestRollingZscoreFeature:
    def test_feature_id_defaults(self) -> None:
        f = RollingZscoreFeature("ofi_ewma", 120)
        assert f.feature_id == "ofi_ewma_zscore"

    def test_feature_id_override(self) -> None:
        f = RollingZscoreFeature("ofi_ewma", 120, feature_id="my_zscore")
        assert f.feature_id == "my_zscore"

    def test_cold_until_min_samples(self) -> None:
        f = RollingZscoreFeature("ofi_ewma", 30, min_samples=5)
        state = f.initial_state()
        for i in range(4):
            f.observe(_reading(ts_ns=i, value=float(i)), state, {})
        _, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert warm is False

    def test_warm_at_min_samples(self) -> None:
        f = RollingZscoreFeature("ofi_ewma", 30, min_samples=5)
        state = f.initial_state()
        for i in range(5):
            f.observe(_reading(ts_ns=i, value=float(i)), state, {})
        _, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert warm is True

    def test_zscore_of_mean_is_near_zero(self) -> None:
        f = RollingZscoreFeature("ofi_ewma", 30, min_samples=5)
        state = f.initial_state()
        # All same value → std ~0 → returns (0.0, True, False)
        for _ in range(10):
            f.observe(_reading(ts_ns=1, value=3.0), state, {})
        value, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert abs(value) < 1e-9
        assert warm is True

    def test_zscore_extremes_and_sign(self) -> None:
        f = RollingZscoreFeature("ofi_ewma", 30, min_samples=5)
        state = f.initial_state()
        # Feed values 0..9 (mean=4.5, std≈3.03); latest=9 → z>0
        for v in range(10):
            f.observe(_reading(ts_ns=v, value=float(v)), state, {})
        value, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert warm is True
        assert value > 0  # latest=9 is above mean

    def test_cold_readings_not_included(self) -> None:
        f = RollingZscoreFeature("ofi_ewma", 30, min_samples=3)
        state = f.initial_state()
        # 2 warm + 1 cold — should stay under min_samples
        for v in range(2):
            f.observe(_reading(ts_ns=v, value=float(v)), state, {})
        f.observe(_reading(ts_ns=99, value=99.0, warm=False), state, {})
        _, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert warm is False

    def test_tuple_value_not_observed(self) -> None:
        f = RollingZscoreFeature("ofi_ewma", 30, min_samples=2)
        state = f.initial_state()
        f.observe(_reading(ts_ns=1, value=(1.0, 2.0)), state, {})
        f.observe(_reading(ts_ns=2, value=(3.0, 4.0)), state, {})
        _, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert warm is False

    def test_max_samples_fifo_eviction(self) -> None:
        f = RollingZscoreFeature("ofi_ewma", 30, min_samples=5, max_samples=10)
        state = f.initial_state()
        # Fill beyond max_samples
        for i in range(20):
            f.observe(_reading(ts_ns=i, value=float(i)), state, {})
        vals: deque = state["vals"]
        assert len(vals) == 10
        # Oldest should be evicted; latest should be 19.0
        assert vals[-1] == 19.0


# ── RollingPercentileFeature ───────────────────────────────────────


class TestRollingPercentileFeature:
    def test_feature_id_defaults(self) -> None:
        f = RollingPercentileFeature("kyle_lambda_60s", 300)
        assert f.feature_id == "kyle_lambda_60s_percentile"

    def test_cold_until_min_samples(self) -> None:
        f = RollingPercentileFeature("kyle_lambda_60s", 300, min_samples=5)
        state = f.initial_state()
        for i in range(4):
            f.observe(_reading(ts_ns=i, sensor_id="kyle_lambda_60s", value=float(i)), state, {})
        value, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert warm is False
        assert abs(value - 0.5) < 1e-9  # neutral prior during warm-up

    def test_warm_at_min_samples(self) -> None:
        f = RollingPercentileFeature("kyle_lambda_60s", 300, min_samples=5)
        state = f.initial_state()
        for i in range(5):
            f.observe(_reading(ts_ns=i, sensor_id="kyle_lambda_60s", value=float(i)), state, {})
        _, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert warm is True

    def test_max_value_is_100th_percentile(self) -> None:
        f = RollingPercentileFeature("kyle_lambda_60s", 300, min_samples=5)
        state = f.initial_state()
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            f.observe(_reading(ts_ns=1, sensor_id="kyle_lambda_60s", value=v), state, {})
        value, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert abs(value - 1.0) < 1e-9  # 5/5 values <= 5.0
        assert warm is True

    def test_min_value_is_near_zero(self) -> None:
        f = RollingPercentileFeature("kyle_lambda_60s", 300, min_samples=5)
        state = f.initial_state()
        for v in [5.0, 4.0, 3.0, 2.0, 1.0]:
            f.observe(_reading(ts_ns=1, sensor_id="kyle_lambda_60s", value=v), state, {})
        # Reload latest with the 1.0 we just appended (already last)
        value, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        # 1/5 values <= 1.0
        assert abs(value - 0.2) < 1e-9
        assert warm is True

    def test_cold_readings_not_included(self) -> None:
        f = RollingPercentileFeature("kyle_lambda_60s", 300, min_samples=3)
        state = f.initial_state()
        for v in range(2):
            f.observe(_reading(ts_ns=v, sensor_id="kyle_lambda_60s", value=float(v)), state, {})
        f.observe(_reading(ts_ns=99, sensor_id="kyle_lambda_60s", value=9.0, warm=False), state, {})
        _, warm, _ = f.finalize(_DUMMY_TICK, state, {})
        assert warm is False


# ── Multi-horizon aggregator integration ───────────────────────────


def _make_agg(features: list) -> tuple[HorizonAggregator, list[HorizonFeatureSnapshot]]:
    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)
    agg = HorizonAggregator(
        bus=bus,
        horizon_features=features,
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=600,
        sequence_generator=SequenceGenerator(),
    )
    agg.attach()
    return agg, captured


def test_multi_horizon_same_feature_id_no_state_collision() -> None:
    """ofi_ewma passthrough at horizon=30 and horizon=120 must not share state."""
    feat_30 = SensorPassthroughFeature("ofi_ewma", 30)
    feat_120 = SensorPassthroughFeature("ofi_ewma", 120)
    agg, captured = _make_agg([feat_30, feat_120])

    # Two readings at different values — both states should accumulate independently
    agg.on_sensor_reading(_reading(ts_ns=1_000_000_000, value=11.0))
    agg.on_sensor_reading(_reading(ts_ns=2_000_000_000, value=22.0))

    agg.on_horizon_tick(_tick(horizon=30, boundary=1, ts_ns=30_000_000_000))
    agg.on_horizon_tick(_tick(horizon=120, boundary=1, ts_ns=120_000_000_000))

    snap_30 = next(s for s in captured if s.horizon_seconds == 30)
    snap_120 = next(s for s in captured if s.horizon_seconds == 120)

    # Both should see the same latest reading (passthrough is stateless except "last value")
    assert snap_30.values["ofi_ewma"] == 22.0
    assert snap_120.values["ofi_ewma"] == 22.0
    # Snapshots are distinct objects
    assert snap_30 is not snap_120


def test_multi_horizon_snapshot_only_contains_matching_horizon_features() -> None:
    """The h=30 snapshot must not contain ofi_ewma from the h=120 feature."""
    feat_30 = SensorPassthroughFeature("ofi_ewma", 30)
    feat_120 = SensorPassthroughFeature("quote_hazard_rate", 120, feature_id="qhr")
    agg, captured = _make_agg([feat_30, feat_120])

    agg.on_sensor_reading(_reading(ts_ns=1_000_000_000, sensor_id="ofi_ewma", value=5.0))
    agg.on_sensor_reading(_reading(ts_ns=1_000_000_001, sensor_id="quote_hazard_rate", value=0.3))

    agg.on_horizon_tick(_tick(horizon=30, boundary=1, ts_ns=30_000_000_000))
    snap = captured[-1]
    assert snap.horizon_seconds == 30
    assert "ofi_ewma" in snap.values
    assert "qhr" not in snap.values  # h=120 feature must not appear in h=30 snapshot


def test_aggregator_active_mode_not_passive() -> None:
    feat = SensorPassthroughFeature("ofi_ewma", 30)
    agg, _ = _make_agg([feat])
    assert not agg.is_passive()


def test_aggregator_accepts_list_input() -> None:
    """Verify that passing a list (not Mapping) is accepted."""
    bus = EventBus()
    features = [SensorPassthroughFeature("ofi_ewma", 30)]
    agg = HorizonAggregator(
        bus=bus,
        horizon_features=features,
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=60,
        sequence_generator=SequenceGenerator(),
    )
    assert not agg.is_passive()


def test_zscore_and_passthrough_same_sensor_different_feature_ids() -> None:
    """SensorPassthrough + RollingZscore both observe the same sensor_id
    but produce distinct keys in snapshot.values."""
    passthrough = SensorPassthroughFeature("ofi_ewma", 120)
    zscore = RollingZscoreFeature("ofi_ewma", 120, min_samples=5)
    agg, captured = _make_agg([passthrough, zscore])

    # Feed enough warm readings to warm up the zscore
    for i in range(6):
        agg.on_sensor_reading(_reading(ts_ns=i * 1_000_000_000, value=float(i)))

    agg.on_horizon_tick(_tick(horizon=120, boundary=1, ts_ns=120_000_000_000))
    assert len(captured) == 1
    snap = captured[0]
    # Both keys present
    assert "ofi_ewma" in snap.values
    assert "ofi_ewma_zscore" in snap.values
    # Passthrough holds the raw latest reading (5.0)
    assert snap.values["ofi_ewma"] == 5.0
    # Zscore is warm
    assert snap.warm.get("ofi_ewma_zscore") is True
