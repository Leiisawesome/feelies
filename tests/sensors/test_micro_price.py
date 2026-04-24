"""Hand-computed unit vector for the Stoikov micro-price sensor."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.micro_price import MicroPriceSensor


def _q(*, bid: str, ask: str, bs: int, as_: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="X",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bs,
        ask_size=as_,
        exchange_timestamp_ns=1,
    )


def test_balanced_book_equals_mid() -> None:
    """Equal sizes ⇒ micro = mid."""
    s = MicroPriceSensor()
    state = s.initial_state()
    r = s.update(_q(bid="100.00", ask="100.10", bs=100, as_=100), state, {})
    assert r is not None
    assert r.value == pytest.approx(100.05)


def test_heavy_bid_pulls_micro_toward_ask() -> None:
    """bid_size=300, ask_size=100 ⇒ (100.10*300 + 100.00*100) / 400 = 100.075."""
    s = MicroPriceSensor()
    state = s.initial_state()
    r = s.update(_q(bid="100.00", ask="100.10", bs=300, as_=100), state, {})
    assert r is not None
    assert r.value == pytest.approx(100.075)


def test_heavy_ask_pulls_micro_toward_bid() -> None:
    """bid_size=50, ask_size=200 ⇒ (100.10*50 + 100.00*200) / 250 = 100.02."""
    s = MicroPriceSensor()
    state = s.initial_state()
    r = s.update(_q(bid="100.00", ask="100.10", bs=50, as_=200), state, {})
    assert r is not None
    assert r.value == pytest.approx(100.02)


def test_zero_depth_falls_back_to_mid_and_marks_unwarm() -> None:
    s = MicroPriceSensor(warm_after=1)
    state = s.initial_state()
    r = s.update(_q(bid="100.00", ask="100.10", bs=0, as_=0), state, {})
    assert r is not None
    assert r.value == pytest.approx(100.05)
    assert r.warm is False


def test_warm_flag_flips_after_threshold() -> None:
    s = MicroPriceSensor(warm_after=2)
    state = s.initial_state()
    r1 = s.update(_q(bid="100.00", ask="100.10", bs=100, as_=100), state, {})
    r2 = s.update(_q(bid="100.00", ask="100.10", bs=100, as_=100), state, {})
    assert r1 is not None and r2 is not None
    assert r1.warm is False
    assert r2.warm is True


def test_trade_event_returns_none() -> None:
    s = MicroPriceSensor()
    state = s.initial_state()
    trade = Trade(
        timestamp_ns=1, correlation_id="t", sequence=1, symbol="X",
        price=Decimal("100.00"), size=100, exchange_timestamp_ns=1,
    )
    assert s.update(trade, state, {}) is None
