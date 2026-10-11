"""Fill publication must not precede the order's arrival time.

Row 2 is ``market_fill.append_market_fill_acks`` via the deferred market
flush. Row 4 is ``passive_limit_router._emit_passive_fill``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, OrderAckStatus, OrderRequest, OrderType, Side
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import ZeroCostModel
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter

pytestmark = pytest.mark.backtest_validation


def _market_quote(symbol: str, bid: str, ask: str, ts: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id="q1",
        sequence=1,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts,
    )


def _market_order(symbol: str) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=2000,
        correlation_id="o1",
        sequence=2,
        order_id="ord1",
        symbol=symbol,
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=50,
    )


def _passive_quote(
    *,
    bid: str = "100.00",
    ask: str = "100.10",
    bid_size: int = 500,
    ask_size: int = 500,
    ts: int = 1000,
    seq: int = 1,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id="q",
        sequence=seq,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts,
        sequence_number=seq,
    )


def _buy_limit() -> OrderRequest:
    return OrderRequest(
        timestamp_ns=0,
        correlation_id="c",
        sequence=1,
        order_id="p1",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        limit_price=Decimal("100.05"),
    )


def test_market_fill_published_before_live_raises() -> None:
    """Row 2: a deferred market fill while the clock is still before arrival."""
    from feelies.execution.market_fill import FillBeforeLiveError

    clock = SimulatedClock(start_ns=5000)
    router = BacktestOrderRouter(clock, cost_model=ZeroCostModel(), latency_ns=1000)
    router.on_quote(_market_quote("AAPL", "100.00", "100.10", 1000))
    router.submit(_market_order("AAPL"))
    acks = router.poll_acks()
    assert [ack.status for ack in acks] == [OrderAckStatus.ACKNOWLEDGED]
    assert router._deferred_markets[0].ack_timestamp_ns == 6000
    assert clock.now_ns() == 5000
    with pytest.raises(FillBeforeLiveError, match="fill published before the order is live"):
        router.on_quote(_market_quote("AAPL", "100.00", "100.10", 6500))


def test_passive_fill_published_before_live_raises() -> None:
    """Row 4: a resting through-fill while the clock is still before arrival."""
    from feelies.execution.market_fill import FillBeforeLiveError

    clock = SimulatedClock(start_ns=0)
    router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel())
    router.on_quote(_passive_quote())
    router.submit(_buy_limit())
    router.poll_acks()
    pending = router._resting_orders["p1"]
    assert pending.ack_timestamp_ns == 1000
    assert clock.now_ns() == 0
    with pytest.raises(FillBeforeLiveError, match="fill published before the order is live"):
        router.on_quote(_passive_quote(ask="100.04", ask_size=30, ts=2000, seq=2))


def test_fill_at_exactly_live_time_is_allowed() -> None:
    """Clock equal to arrival is live. The fill stamp is that clock."""
    from feelies.execution.market_fill import FillBeforeLiveError

    clock = SimulatedClock(start_ns=5000)
    router = BacktestOrderRouter(clock, cost_model=ZeroCostModel(), latency_ns=1000)
    router.on_quote(_market_quote("AAPL", "100.00", "100.10", 1000))
    router.submit(_market_order("AAPL"))
    assert router.poll_acks()[0].status == OrderAckStatus.ACKNOWLEDGED
    assert router._deferred_markets[0].ack_timestamp_ns == 6000
    clock.set_time(6000)
    router.on_quote(_market_quote("AAPL", "100.00", "100.10", 6500))
    fills = router.poll_acks()
    assert len(fills) == 1
    assert fills[0].status == OrderAckStatus.FILLED
    assert fills[0].timestamp_ns == clock.now_ns() == 6000
    assert issubclass(FillBeforeLiveError, BaseException)
