"""Hand-computed unit vector for the rolling spread z-score sensor."""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor


def _q(*, bid: str, ask: str, ts: int = 1) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"c-{ts}",
        sequence=ts,
        symbol="X",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts,
    )


def test_constructor_rejects_small_window() -> None:
    with pytest.raises(ValueError):
        SpreadZScoreSensor(window=1)


def test_first_quote_emits_zero_z() -> None:
    s = SpreadZScoreSensor(window=10, warm_after=1)
    state = s.initial_state()
    r = s.update(_q(bid="100.00", ask="100.10"), state, {})
    assert r is not None
    assert r.value == 0.0


def test_constant_spread_emits_zero_z_with_floor() -> None:
    """All identical spreads ⇒ std=0, output 0.0 via min_std floor."""
    s = SpreadZScoreSensor(window=10, warm_after=1)
    state = s.initial_state()
    last = None
    for ts in range(5):
        last = s.update(_q(bid="100.00", ask="100.10", ts=ts), state, {})
    assert last is not None and last.value == 0.0


def test_handcomputed_zscore_for_spread_jump() -> None:
    """Three quotes with spreads [0.10, 0.10, 0.20] ⇒ z ≈ +1.41421.

    We replicate the sensor's float arithmetic exactly to avoid
    spurious mismatches from binary-float representation of decimal
    values.
    """
    s = SpreadZScoreSensor(window=10, warm_after=3)
    state = s.initial_state()
    s.update(_q(bid="100.00", ask="100.10", ts=1), state, {})
    s.update(_q(bid="100.00", ask="100.10", ts=2), state, {})
    r = s.update(_q(bid="100.00", ask="100.20", ts=3), state, {})
    assert r is not None
    # Replicate the exact float math the sensor performs:
    sp1 = 100.10 - 100.00
    sp2 = 100.10 - 100.00
    sp3 = 100.20 - 100.00
    spreads = (sp1, sp2, sp3)
    n = 3
    mean = sum(spreads) / n
    var = max(0.0, sum(s * s for s in spreads) / n - mean * mean)
    expected = (sp3 - mean) / math.sqrt(var)
    assert r.value == pytest.approx(expected, rel=1e-9)
    assert r.warm is True


def test_window_eviction_removes_old_spreads() -> None:
    """Window of 2 ⇒ only the last 2 spreads count."""
    s = SpreadZScoreSensor(window=2, warm_after=2)
    state = s.initial_state()
    s.update(_q(bid="100.00", ask="100.10", ts=1), state, {})  # spread=0.10
    s.update(_q(bid="100.00", ask="100.50", ts=2), state, {})  # spread=0.50
    r = s.update(_q(bid="100.00", ask="100.20", ts=3), state, {})  # spread=0.20
    # Only spreads [0.50, 0.20] remain in window after eviction.
    sp_evict = 100.50 - 100.00
    sp_last = 100.20 - 100.00
    n = 2
    mean = (sp_evict + sp_last) / n
    var = max(0.0, (sp_evict * sp_evict + sp_last * sp_last) / n - mean * mean)
    expected = (sp_last - mean) / math.sqrt(var)
    assert r is not None
    assert r.value == pytest.approx(expected, rel=1e-9)


def test_warm_flag_respects_threshold() -> None:
    s = SpreadZScoreSensor(window=10, warm_after=5)
    state = s.initial_state()
    last = None
    for ts in range(4):
        last = s.update(_q(bid="100.00", ask="100.10", ts=ts), state, {})
    assert last is not None and last.warm is False
    last = s.update(_q(bid="100.00", ask="100.10", ts=5), state, {})
    assert last is not None and last.warm is True


# ── F2 (sensor_review_2026-07-02): Welford drift guard ──────────────────


def test_recompute_from_window_matches_two_pass() -> None:
    """The drift-reset helper must produce the exact two-pass mean/M2."""
    from collections import deque

    vals = [0.10, 0.12, 0.11, 0.30, 0.09, 0.15]
    state = {"spreads": deque(vals), "n": 0, "mean": 0.0, "M2": 0.0}
    SpreadZScoreSensor._recompute_from_window(state)
    n = len(vals)
    mean = sum(vals) / n
    assert state["n"] == n
    assert state["mean"] == pytest.approx(mean, rel=1e-15)
    assert state["M2"] == pytest.approx(sum((v - mean) ** 2 for v in vals), rel=1e-12)


def test_recompute_from_empty_window_is_zeroed() -> None:
    from collections import deque

    state = {"spreads": deque(), "n": 5, "mean": 9.9, "M2": 3.3}
    SpreadZScoreSensor._recompute_from_window(state)
    assert state == {"spreads": state["spreads"], "n": 0, "mean": 0.0, "M2": 0.0}


def test_incremental_variance_tracks_batch_over_long_sliding_run() -> None:
    """Numerical-stability invariant: after a long sliding-window run, the
    incremental Welford mean/M2 must still match a from-scratch two-pass
    computation over the *current* window to tight tolerance — this is what
    the F2 clamp+recompute guard protects against eroding on adversarial
    (large-dynamic-range) inputs."""
    import random

    rng = random.Random(1234)
    window = 50
    s = SpreadZScoreSensor(window=window, warm_after=window, min_std=1e-12)
    state = s.initial_state()
    # Alternate tiny and large spreads to stress the accumulator.
    for i in range(5000):
        spread_cents = rng.choice((1, 1, 1, 500))  # mostly 0.01, occasional 5.00
        bid = "100.00"
        ask = f"{100.00 + spread_cents / 100.0:.2f}"
        s.update(_q(bid=bid, ask=ask, ts=i), state, {})

    live = list(state["spreads"])
    n = len(live)
    batch_mean = sum(live) / n
    batch_m2 = sum((x - batch_mean) ** 2 for x in live)
    assert state["mean"] == pytest.approx(batch_mean, rel=1e-9, abs=1e-12)
    assert state["M2"] == pytest.approx(batch_m2, rel=1e-9, abs=1e-12)
    assert state["M2"] >= 0.0  # never left in a corrupt negative state
