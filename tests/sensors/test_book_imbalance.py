"""Unit tests for :class:`feelies.sensors.impl.book_imbalance.BookImbalanceSensor`.

This module covers crossed books, zero depth, warm-up thresholds, gap-driven
cold reversion, and ignored trade events. Sign and winsorization are covered by
the shared sensor tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.book_imbalance import BookImbalanceSensor

_NS = 1_000_000_000


def _q(*, bid: str, ask: str, bs: int, as_: int, ts: int = 1, seq: int = 1) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q-{seq}",
        sequence=seq,
        symbol="X",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bs,
        ask_size=as_,
        exchange_timestamp_ns=ts,
    )


def test_bid_heavy_book_is_positive() -> None:
    s = BookImbalanceSensor(warm_after=1)
    state = s.initial_state()
    r = s.update(_q(bid="100.00", ask="100.02", bs=300, as_=100), state, {})
    assert r is not None
    assert r.value == pytest.approx((300 - 100) / 400)


def test_ask_heavy_book_is_negative() -> None:
    s = BookImbalanceSensor(warm_after=1)
    state = s.initial_state()
    r = s.update(_q(bid="100.00", ask="100.02", bs=100, as_=300), state, {})
    assert r is not None
    assert r.value == pytest.approx((100 - 300) / 400)


def test_zero_depth_is_undefined_not_balanced() -> None:
    """Total depth 0 must not be conflated with a balanced (0.0, warm) book."""
    s = BookImbalanceSensor(warm_after=1)
    state = s.initial_state()
    r = s.update(_q(bid="100.00", ask="100.02", bs=0, as_=0), state, {})
    assert r is not None
    assert r.value == 0.0
    assert r.warm is False


def test_crossed_book_is_rejected() -> None:
    """A crossed NBBO must be
    dropped like every sibling price-consuming sensor (ofi_ewma, ofi_raw,
    micro_price, spread_z_30d, ...), not folded into the imbalance series."""
    s = BookImbalanceSensor(warm_after=1)
    state = s.initial_state()
    r = s.update(_q(bid="100.02", ask="100.00", bs=300, as_=100), state, {})
    assert r is None


def test_locked_book_is_allowed() -> None:
    """bid == ask is locked, not crossed — every sibling sensor accepts it."""
    s = BookImbalanceSensor(warm_after=1)
    state = s.initial_state()
    r = s.update(_q(bid="100.00", ask="100.00", bs=300, as_=100), state, {})
    assert r is not None
    assert r.value == pytest.approx((300 - 100) / 400)


def test_non_positive_side_is_rejected() -> None:
    s = BookImbalanceSensor(warm_after=1)
    state = s.initial_state()
    r = s.update(_q(bid="0", ask="100.00", bs=300, as_=100), state, {})
    assert r is None


def test_warm_flag_flips_after_threshold() -> None:
    s = BookImbalanceSensor(warm_after=2, warm_window_seconds=60)
    state = s.initial_state()
    r1 = s.update(_q(bid="100.00", ask="100.02", bs=100, as_=100, ts=0, seq=0), state, {})
    r2 = s.update(_q(bid="100.00", ask="100.02", bs=100, as_=100, ts=1, seq=1), state, {})
    assert r1 is not None and r2 is not None
    assert r1.warm is False
    assert r2.warm is True


def test_sliding_warm_window_reverts_to_cold_after_gap() -> None:
    """S3: the warm gate is a *sliding* event-time window, not a monotonic
    counter — once the quotes that satisfied ``warm_after`` age out of
    ``warm_window_seconds``, the sensor must revert to ``warm=False``,
    mirroring the ``ofi_ewma`` / ``micro_price`` docstring's stated
    behaviour (a sustained data gap un-warms the sensor)."""
    s = BookImbalanceSensor(warm_after=3, warm_window_seconds=60)
    state = s.initial_state()

    for i in range(3):
        r = s.update(_q(bid="100.00", ask="100.02", bs=100, as_=100, ts=i * _NS, seq=i), state, {})
    assert r is not None
    assert r.warm is True  # 3 quotes within the 60s window satisfy warm_after=3

    # A single quote 1000s later: the prior three timestamps are now more
    # than warm_window_seconds=60s stale and are evicted, leaving only this
    # one reading in the trailing window.
    after_gap = s.update(
        _q(bid="100.00", ask="100.02", bs=100, as_=100, ts=1000 * _NS, seq=99), state, {}
    )
    assert after_gap is not None
    assert after_gap.warm is False


def test_trade_event_returns_none() -> None:
    s = BookImbalanceSensor()
    state = s.initial_state()
    trade = Trade(
        timestamp_ns=1,
        correlation_id="t",
        sequence=1,
        symbol="X",
        price=Decimal("100.00"),
        size=100,
        exchange_timestamp_ns=1,
    )
    assert s.update(trade, state, {}) is None
