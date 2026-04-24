"""Hand-computed unit vector for the OFI-EWMA sensor."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor


def _q(*, bid: str, ask: str, bs: int, as_: int, ts: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"c-{ts}",
        sequence=ts,
        symbol="X",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bs,
        ask_size=as_,
        exchange_timestamp_ns=ts,
    )


def test_constructor_rejects_invalid_alpha() -> None:
    with pytest.raises(ValueError):
        OFIEwmaSensor(alpha=0.0)
    with pytest.raises(ValueError):
        OFIEwmaSensor(alpha=1.1)


def test_first_quote_emits_zero_ofi() -> None:
    s = OFIEwmaSensor(alpha=0.1)
    state = s.initial_state()
    r = s.update(_q(bid="100.00", ask="100.01", bs=100, as_=100, ts=1), state, {})
    assert r is not None
    assert r.value == 0.0
    assert r.warm is False


def test_bid_up_ask_up_handcomputed() -> None:
    """bid: 100.00→100.01 (size 100), ask: 100.01→100.02 (size 100).

    Per OFI definition:
      bid_contrib = +bid_size_t = +100  (bid moved up)
      ask_contrib = +last_ask_size = +100 (ask moved up)
      ofi = 200, alpha=0.1, prev_ewma=0 ⇒ ewma = 20.0
    """
    s = OFIEwmaSensor(alpha=0.1)
    state = s.initial_state()
    s.update(_q(bid="100.00", ask="100.01", bs=100, as_=100, ts=1), state, {})
    r = s.update(_q(bid="100.01", ask="100.02", bs=100, as_=100, ts=2), state, {})
    assert r is not None
    assert r.value == pytest.approx(20.0)


def test_bid_down_ask_down_handcomputed() -> None:
    """bid: 100.00→99.99 (last bid_size=200), ask: 100.01→100.00 (size 100)."""
    s = OFIEwmaSensor(alpha=0.5)
    state = s.initial_state()
    s.update(_q(bid="100.00", ask="100.01", bs=200, as_=100, ts=1), state, {})
    r = s.update(_q(bid="99.99", ask="100.00", bs=300, as_=200, ts=2), state, {})
    # bid_contrib = -last_bid_size = -200
    # ask_contrib = -ask_size_t = -200  (ask moved down → -ask_size_t)
    # ofi = -400, alpha=0.5, prev_ewma=0 ⇒ ewma = -200
    assert r is not None
    assert r.value == pytest.approx(-200.0)


def test_unchanged_quote_with_size_change() -> None:
    """bid stays, bid_size 100→200 ⇒ bid_contrib = +100. Same for ask down."""
    s = OFIEwmaSensor(alpha=1.0)  # no smoothing
    state = s.initial_state()
    s.update(_q(bid="100.00", ask="100.01", bs=100, as_=100, ts=1), state, {})
    r = s.update(_q(bid="100.00", ask="100.01", bs=200, as_=50, ts=2), state, {})
    # bid_contrib = +(200 - 100) = +100
    # ask_contrib = -(50 - 100) = +50
    assert r is not None
    assert r.value == pytest.approx(150.0)


def test_trade_event_returns_none() -> None:
    s = OFIEwmaSensor()
    state = s.initial_state()
    trade = Trade(
        timestamp_ns=1, correlation_id="t", sequence=1, symbol="X",
        price=Decimal("100.00"), size=100, exchange_timestamp_ns=1,
    )
    assert s.update(trade, state, {}) is None


def test_warm_flag_flips_after_threshold() -> None:
    s = OFIEwmaSensor(alpha=0.5, warm_after=3)
    state = s.initial_state()
    last = None
    for i in range(3):
        last = s.update(
            _q(bid="100.00", ask="100.01", bs=100, as_=100, ts=i + 1),
            state, {},
        )
    assert last is not None and last.warm is True
