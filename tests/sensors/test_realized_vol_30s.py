"""Hand-computed unit vector for the realized-volatility sensor."""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor


def _q(*, bid: str, ask: str, ts: int) -> NBBOQuote:
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


def test_constructor_rejects_invalid_window() -> None:
    with pytest.raises(ValueError):
        RealizedVol30sSensor(window_seconds=0)


def test_first_quote_emits_zero_rv() -> None:
    s = RealizedVol30sSensor(window_seconds=30, warm_after=1)
    state = s.initial_state()
    r = s.update(_q(bid="100.00", ask="100.02", ts=1), state, {})
    assert r is not None
    assert r.value == 0.0


def test_handcomputed_two_returns() -> None:
    """mids: 100.01 → 100.02 → 100.03

    log returns: log(100.02/100.01) ≈ 9.99950e-5, log(100.03/100.02) ≈ 9.99850e-5
    sample variance (unbiased): (sum_sq - (sum)^2/n) / (n-1) with n = 2
    """
    s = RealizedVol30sSensor(window_seconds=30, warm_after=1)
    state = s.initial_state()
    s.update(_q(bid="100.00", ask="100.02", ts=1_000_000_000), state, {})
    s.update(_q(bid="100.01", ask="100.03", ts=2_000_000_000), state, {})
    r = s.update(_q(bid="100.02", ask="100.04", ts=3_000_000_000), state, {})
    assert r is not None
    r1 = math.log(100.02 / 100.01)
    r2 = math.log(100.03 / 100.02)
    n = 2
    mu = (r1 + r2) / float(n)
    var = ((r1 - mu) ** 2 + (r2 - mu) ** 2) / float(n - 1)
    expected = math.sqrt(max(0.0, var))
    assert r.value == pytest.approx(expected, rel=1e-12)


def test_window_eviction_drops_old_returns() -> None:
    """A return outside the trailing window is excluded from the sum."""
    s = RealizedVol30sSensor(window_seconds=2, warm_after=1)
    state = s.initial_state()
    s.update(_q(bid="100.00", ask="100.02", ts=0), state, {})
    s.update(_q(bid="101.00", ask="101.02", ts=1_000_000_000), state, {})  # in window
    # Move forward 5 seconds — the prior return drops out of the 2s window;
    # a single-log-return window yields n=1 → std undefined → emitted 0.0.
    r = s.update(_q(bid="101.50", ask="101.52", ts=6_000_000_000), state, {})
    assert r is not None
    assert r.value == 0.0


def test_zero_or_negative_quote_returns_none() -> None:
    """Defensive: pathological book is skipped silently."""
    s = RealizedVol30sSensor()
    state = s.initial_state()
    bad = NBBOQuote(
        timestamp_ns=1, correlation_id="c", sequence=1, symbol="X",
        bid=Decimal("0"), ask=Decimal("0"), bid_size=0, ask_size=0,
        exchange_timestamp_ns=1,
    )
    assert s.update(bad, state, {}) is None


def test_warm_flag_after_threshold() -> None:
    s = RealizedVol30sSensor(window_seconds=30, warm_after=3)
    state = s.initial_state()
    last = None
    for i in range(5):
        last = s.update(_q(bid="100.00", ask="100.02", ts=i * 100_000_000), state, {})
    assert last is not None
    assert last.warm is True  # 4 returns observed, ≥ threshold of 3
