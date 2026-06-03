"""HorizonWindowedFeature — true event-time windowing (audit P1-1)."""

from __future__ import annotations

import pytest

from feelies.core.events import HorizonTick, SensorReading
from feelies.features.impl.horizon_windowed import HorizonWindowedFeature

_NS = 1_000_000_000


def _reading(ts_ns: int, value, *, warm: bool = True) -> SensorReading:
    return SensorReading(
        timestamp_ns=ts_ns,
        correlation_id="c",
        sequence=1,
        source_layer="SENSORS",
        symbol="AAPL",
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        value=value,
        warm=warm,
    )


def _tick(ts_ns: int) -> HorizonTick:
    return HorizonTick(
        timestamp_ns=ts_ns,
        correlation_id="c2",
        sequence=2,
        source_layer="FEATURES",
        horizon_seconds=30,
        boundary_index=1,
        session_id="US_EQUITY_RTH_2026-01-15",
        scope="SYMBOL",
        symbol="AAPL",
    )


def _drive(feat: HorizonWindowedFeature, samples, *, tick_ts: int):
    state = feat.initial_state()
    for ts, v in samples:
        feat.observe(_reading(ts, v), state, {})
    return feat.finalize(_tick(tick_ts), state, {})


def test_construction_validates_reducer_and_min_samples() -> None:
    with pytest.raises(ValueError):
        HorizonWindowedFeature("ofi_ewma", 30, reducer="bogus")
    with pytest.raises(ValueError):
        HorizonWindowedFeature("ofi_ewma", 30, reducer="zscore", min_samples=1)


def test_window_is_time_bounded_not_count_bounded() -> None:
    """The defining P1-1 property: horizon width changes the window.

    Same reading stream, two horizons → different in-window sample sets,
    so the mean differs.  Under the old count-window features these were
    identical.
    """
    # One reading per second for 120 s: value ramps 0..119.
    samples = [(i * _NS, float(i)) for i in range(120)]
    tick_ts = 119 * _NS

    short = HorizonWindowedFeature(
        "ofi_ewma", 30, reducer="mean", min_samples=1,
    )
    long = HorizonWindowedFeature(
        "ofi_ewma", 120, reducer="mean", min_samples=1,
    )
    short_mean, sw, _ = _drive(short, samples, tick_ts=tick_ts)
    long_mean, lw, _ = _drive(long, samples, tick_ts=tick_ts)

    assert sw and lw
    # 30 s window keeps ~last 30 readings (mean ≈ 104.5); 120 s keeps all
    # 120 (mean ≈ 59.5).  They MUST differ — that is the whole point.
    assert short_mean > long_mean + 20.0
    assert long_mean == pytest.approx(59.5, abs=1.0)


def test_finalize_evicts_at_tick_boundary() -> None:
    """A silent sensor's window shrinks at the boundary, not just on obs."""
    feat = HorizonWindowedFeature("ofi_ewma", 30, reducer="last", min_samples=1)
    state = feat.initial_state()
    feat.observe(_reading(0, 5.0), state, {})
    feat.observe(_reading(1 * _NS, 7.0), state, {})
    # Tick 100 s later: both readings are older than the 30 s window.
    val, warm, stale = feat.finalize(_tick(100 * _NS), state, {})
    assert warm is False  # window emptied → not enough samples
    assert val == 0.0


def test_sum_reducer_integrates_over_window() -> None:
    samples = [(i * _NS, 2.0) for i in range(10)]  # 10 readings of 2.0
    feat = HorizonWindowedFeature("ofi_ewma", 30, reducer="sum", min_samples=1)
    val, warm, _ = _drive(feat, samples, tick_ts=9 * _NS)
    assert warm
    assert val == pytest.approx(20.0)


def test_zscore_latest_vs_window() -> None:
    # Flat at 1.0 then a jump to 10.0 as the latest sample.
    samples = [(i * _NS, 1.0) for i in range(40)] + [(40 * _NS, 10.0)]
    feat = HorizonWindowedFeature("ofi_ewma", 120, reducer="zscore", min_samples=5)
    z, warm, _ = _drive(feat, samples, tick_ts=40 * _NS)
    assert warm
    assert z > 3.0  # latest is far above the window mean


def test_zscore_constant_window_is_zero() -> None:
    samples = [(i * _NS, 4.0) for i in range(40)]
    feat = HorizonWindowedFeature("ofi_ewma", 120, reducer="zscore", min_samples=5)
    z, warm, _ = _drive(feat, samples, tick_ts=39 * _NS)
    assert warm
    assert z == 0.0


def test_zscore_numerically_stable_on_price_level() -> None:
    """micro_price-style: large level (~$227), tiny cent-scale variance.

    Naive Σx²/n − mean² would lose most precision; Welford must keep the
    z finite and correctly signed.
    """
    base = 227.0
    samples = [
        (i * _NS, base + (0.01 if i % 2 else -0.01)) for i in range(60)
    ]
    samples.append((60 * _NS, base + 0.05))  # latest pops up 5 cents
    feat = HorizonWindowedFeature(
        "micro_price", 120, reducer="zscore", min_samples=10,
    )
    z, warm, _ = _drive(feat, samples, tick_ts=60 * _NS)
    assert warm
    assert z > 1.0  # clearly positive, finite, not NaN
    assert z <= 10.0  # clamped envelope


def test_cold_readings_ignored() -> None:
    samples = [(i * _NS, 3.0, False) for i in range(40)]
    feat = HorizonWindowedFeature("ofi_ewma", 30, reducer="mean", min_samples=1)
    state = feat.initial_state()
    for ts, v, _w in samples:
        feat.observe(_reading(ts, v, warm=False), state, {})
    val, warm, _ = feat.finalize(_tick(39 * _NS), state, {})
    assert warm is False
    assert val == 0.0


def test_deterministic_across_two_runs() -> None:
    samples = [(i * _NS, float((i * 7) % 13)) for i in range(200)]
    feat = HorizonWindowedFeature("ofi_ewma", 120, reducer="zscore", min_samples=5)
    a = _drive(feat, samples, tick_ts=199 * _NS)
    b = _drive(feat, samples, tick_ts=199 * _NS)
    assert a == b


def test_percentile_reducer_hazen() -> None:
    # Window 0..9; latest is 9 (the max) → Hazen (10 - 0.5)/10 = 0.95.
    samples = [(i * _NS, float(i)) for i in range(10)]
    feat = HorizonWindowedFeature(
        "kyle_lambda_60s", 30, reducer="percentile", min_samples=1,
    )
    val, warm, _ = _drive(feat, samples, tick_ts=9 * _NS)
    assert warm
    assert val == pytest.approx(0.95)
    assert feat.feature_id == "kyle_lambda_60s_percentile"


def test_percentile_neutral_prior_during_warmup() -> None:
    feat = HorizonWindowedFeature(
        "kyle_lambda_60s", 30, reducer="percentile", min_samples=5,
    )
    val, warm, _ = _drive(feat, [(0, 1.0)], tick_ts=0)
    assert warm is False
    assert val == pytest.approx(0.5)  # neutral, not 0.0


def test_tuple_sum_components() -> None:
    feat = HorizonWindowedFeature(
        "hawkes_intensity", 30, reducer="mean", min_samples=1,
        tuple_sum_component_indices=(0, 1),
    )
    state = feat.initial_state()
    feat.observe(_reading(0, (2.0, 3.0, 0.6, 8.0)), state, {})
    feat.observe(_reading(1 * _NS, (4.0, 1.0, 0.8, 8.0)), state, {})
    val, warm, _ = feat.finalize(_tick(1 * _NS), state, {})
    assert warm
    # means of (2+3)=5 and (4+1)=5 → 5.0
    assert val == pytest.approx(5.0)
