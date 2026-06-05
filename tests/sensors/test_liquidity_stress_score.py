"""Tests for LiquidityStressScoreSensor (LIQUIDITY_STRESS fingerprint)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.liquidity_stress_score import LiquidityStressScoreSensor

_NS = 1_000_000_000


def _quote(ts_ns: int, bid: str, ask: str, bid_sz: int = 500, ask_sz: int = 500) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{ts_ns}",
        sequence=ts_ns,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_sz,
        ask_size=ask_sz,
        exchange_timestamp_ns=ts_ns,
    )


def _trade(ts_ns: int) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{ts_ns}",
        sequence=ts_ns,
        symbol="AAPL",
        price=Decimal("100.00"),
        size=100,
        exchange_timestamp_ns=ts_ns,
    )


def _drive(sensor, events):
    state = sensor.initial_state()
    last = None
    for ev in events:
        r = sensor.update(ev, state, params={})
        if r is not None:
            last = r
    return last, state


def test_constructor_validates() -> None:
    with pytest.raises(ValueError, match="window"):
        LiquidityStressScoreSensor(window=1)
    with pytest.raises(ValueError, match="sensitivity"):
        LiquidityStressScoreSensor(sensitivity=0.0)
    with pytest.raises(ValueError, match="min_std"):
        LiquidityStressScoreSensor(min_std=0.0)


def test_trade_returns_none() -> None:
    s = LiquidityStressScoreSensor()
    assert s.update(_trade(1), s.initial_state(), params={}) is None


def test_calm_book_scores_near_zero() -> None:
    s = LiquidityStressScoreSensor(window=200, warm_after=50)
    # Constant spread and depth → no adverse deviation → score 0.
    evs = [_quote((i + 1) * _NS, "100.00", "100.02", 500, 500) for i in range(120)]
    last, _ = _drive(s, evs)
    assert last is not None and last.warm is True
    assert last.value == pytest.approx(0.0, abs=1e-9)


def test_spread_spike_raises_score() -> None:
    s = LiquidityStressScoreSensor(window=500, warm_after=50, min_std=1e-6)
    evs = [_quote((i + 1) * _NS, "100.00", "100.02", 500, 500) for i in range(100)]
    # Tiny jitter to give the baseline non-zero variance, then a wide spread.
    evs.append(_quote(101 * _NS, "100.00", "100.03", 500, 500))  # 50% wider
    evs.append(_quote(102 * _NS, "100.00", "100.10", 500, 500))  # blowout
    last, _ = _drive(s, evs)
    assert last is not None
    assert last.value > 0.5
    assert 0.0 <= last.value <= 1.0


def test_depth_collapse_raises_score() -> None:
    s = LiquidityStressScoreSensor(window=500, warm_after=50, min_std=1e-6)
    evs = []
    for i in range(100):
        # small depth jitter so std > 0
        sz = 500 + (i % 5)
        evs.append(_quote((i + 1) * _NS, "100.00", "100.02", sz, sz))
    evs.append(_quote(101 * _NS, "100.00", "100.02", 10, 10))  # depth collapse
    last, _ = _drive(s, evs)
    assert last is not None
    assert last.value > 0.5


def test_value_bounded_unit_interval() -> None:
    s = LiquidityStressScoreSensor(window=300, warm_after=20, min_std=1e-6)
    evs = []
    for i in range(200):
        wide = 0.02 + (i % 7) * 0.01
        sz = max(10, 500 - (i % 11) * 40)
        evs.append(_quote((i + 1) * _NS, "100.00", f"{100.00 + wide:.2f}", sz, sz))
    last, _ = _drive(s, evs)
    assert last is not None
    assert 0.0 <= last.value <= 1.0


def test_warm_gate() -> None:
    s = LiquidityStressScoreSensor(window=100, warm_after=30)
    st = s.initial_state()
    r = None
    for i in range(29):
        r = s.update(_quote((i + 1) * _NS, "100.00", "100.02"), st, params={})
    assert r is not None and r.warm is False
    r = s.update(_quote(30 * _NS, "100.00", "100.02"), st, params={})
    assert r is not None and r.warm is True


def test_bad_quote_dropped() -> None:
    s = LiquidityStressScoreSensor(window=100, warm_after=1)
    st = s.initial_state()
    assert s.update(_quote(1 * _NS, "0", "100.02"), st, params={}) is None
    assert s.update(_quote(2 * _NS, "100.00", "0"), st, params={}) is None


def test_deterministic() -> None:
    evs = []
    for i in range(150):
        wide = 0.02 + ((i * 3) % 5) * 0.005
        sz = 500 - ((i * 7) % 9) * 30
        evs.append(_quote((i + 1) * _NS, "100.00", f"{100.00 + wide:.3f}", sz, sz))
    a, _ = _drive(LiquidityStressScoreSensor(window=100, warm_after=20, min_std=1e-6), evs)
    b, _ = _drive(LiquidityStressScoreSensor(window=100, warm_after=20, min_std=1e-6), evs)
    assert a is not None and b is not None
    assert a.value == b.value and a.warm == b.warm
