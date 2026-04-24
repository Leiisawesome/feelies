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
