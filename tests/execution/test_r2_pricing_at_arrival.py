"""Deferred aggressive fills are priced on the quote prevailing at arrival.

Eligibility, the fill stamp, and the RTH check stay on the flush quote.
Touch, depth, the crossed or locked check, and a marketable limit's mid
use the arrival quote: the flush quote when its exchange time equals
arrival, otherwise the previous quote of that symbol.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, OrderAck, OrderAckStatus, OrderRequest, OrderType, Side
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import ZeroCostModel
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter

pytestmark = pytest.mark.backtest_validation

_Router = BacktestOrderRouter | PassiveLimitOrderRouter


def _quote(
    symbol: str,
    bid: str,
    ask: str,
    ts: int,
    bid_size: int = 100,
    ask_size: int = 100,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q-{symbol}-{ts}",
        sequence=ts,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts,
    )


def _market(symbol: str, order_id: str = "m") -> OrderRequest:
    return OrderRequest(
        timestamp_ns=0,
        correlation_id="o",
        sequence=1,
        order_id=order_id,
        symbol=symbol,
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
    )


def _limit(symbol: str, limit_price: str, order_id: str = "lim") -> OrderRequest:
    return OrderRequest(
        timestamp_ns=0,
        correlation_id="o",
        sequence=1,
        order_id=order_id,
        symbol=symbol,
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        limit_price=Decimal(limit_price),
    )


def _router(kind: str, clock: SimulatedClock) -> _Router:
    if kind == "backtest":
        return BacktestOrderRouter(clock, latency_ns=1000, cost_model=ZeroCostModel())
    return PassiveLimitOrderRouter(clock, latency_ns=1000, cost_model=ZeroCostModel())


def _filled(acks: list[OrderAck]) -> list[OrderAck]:
    return [ack for ack in acks if ack.status == OrderAckStatus.FILLED]


@pytest.mark.parametrize("kind", ["backtest", "passive"])
def test_no_quote_in_window_prices_the_submit_quote(kind: str) -> None:
    clock = SimulatedClock(start_ns=5000)
    router = _router(kind, clock)
    router.on_quote(_quote("AAPL", "100.00", "100.10", 4000))
    router.submit(_market("AAPL"))
    router.poll_acks()
    clock.set_time(6500)
    router.on_quote(_quote("AAPL", "99.00", "99.10", 6500))
    fills = _filled(router.poll_acks())
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("100.10")
    assert fills[0].timestamp_ns == 6500


@pytest.mark.parametrize("kind", ["backtest", "passive"])
def test_flush_at_arrival_prices_the_flush_quote(kind: str) -> None:
    clock = SimulatedClock(start_ns=0)
    router = _router(kind, clock)
    router.on_quote(_quote("AAPL", "100.00", "100.10", 0))
    router.submit(_market("AAPL"))
    router.poll_acks()
    clock.set_time(1000)
    router.on_quote(_quote("AAPL", "101.00", "101.10", 1000))
    fills = _filled(router.poll_acks())
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("101.10")
    assert fills[0].timestamp_ns == 1000


@pytest.mark.parametrize("kind", ["backtest", "passive"])
def test_locked_arrival_quote_rejects(kind: str) -> None:
    clock = SimulatedClock(start_ns=5000)
    router = _router(kind, clock)
    router.on_quote(_quote("AAPL", "100.00", "100.10", 4000))
    router.submit(_market("AAPL"))
    router.poll_acks()
    clock.set_time(5500)
    router.on_quote(_quote("AAPL", "100.00", "100.00", 5500))
    clock.set_time(6500)
    router.on_quote(_quote("AAPL", "99.00", "99.10", 6500))
    acks = router.poll_acks()
    assert len(acks) == 1
    assert acks[0].status == OrderAckStatus.REJECTED
    assert "locked" in acks[0].reason.lower() or "crossed" in acks[0].reason.lower()


@pytest.mark.parametrize("kind", ["backtest", "passive"])
def test_locked_flush_quote_fills_at_arrival_quote(kind: str) -> None:
    clock = SimulatedClock(start_ns=5000)
    router = _router(kind, clock)
    router.on_quote(_quote("AAPL", "100.00", "100.10", 4000))
    router.submit(_market("AAPL"))
    router.poll_acks()
    clock.set_time(6500)
    router.on_quote(_quote("AAPL", "100.00", "100.00", 6500))
    fills = _filled(router.poll_acks())
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("100.10")


@pytest.mark.parametrize("kind", ["backtest", "passive"])
def test_other_symbol_does_not_price_the_order(kind: str) -> None:
    clock = SimulatedClock(start_ns=5000)
    router = _router(kind, clock)
    router.on_quote(_quote("AAPL", "100.00", "100.10", 4000))
    router.on_quote(_quote("MSFT", "50.00", "50.10", 4000))
    router.submit(_market("AAPL"))
    router.poll_acks()
    clock.set_time(5500)
    router.on_quote(_quote("MSFT", "51.00", "51.10", 5500))
    clock.set_time(6500)
    router.on_quote(_quote("AAPL", "100.00", "100.00", 6500))
    fills = _filled(router.poll_acks())
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("100.10")


@pytest.mark.parametrize("kind", ["backtest", "passive"])
def test_in_window_quote_prices_over_the_flush_quote(kind: str) -> None:
    clock = SimulatedClock(start_ns=5000)
    router = _router(kind, clock)
    router.on_quote(_quote("AAPL", "100.00", "100.10", 5000))
    router.submit(_market("AAPL"))
    router.poll_acks()
    clock.set_time(5500)
    router.on_quote(_quote("AAPL", "99.80", "99.90", 5500))
    assert _filled(router.poll_acks()) == []
    clock.set_time(6500)
    router.on_quote(_quote("AAPL", "99.90", "99.98", 6500))
    fills = _filled(router.poll_acks())
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("99.90")
    assert fills[0].timestamp_ns == 6500


@pytest.mark.parametrize("kind", ["backtest", "passive"])
def test_zero_depth_on_arrival_quote_rejects(kind: str) -> None:
    clock = SimulatedClock(start_ns=5000)
    router = _router(kind, clock)
    router.on_quote(_quote("AAPL", "150.00", "150.02", 1000, ask_size=0))
    router.submit(_market("AAPL"))
    assert [ack.status for ack in router.poll_acks()] == [OrderAckStatus.ACKNOWLEDGED]
    clock.set_time(6500)
    router.on_quote(_quote("AAPL", "150.00", "150.02", 6500))
    acks = router.poll_acks()
    assert len(acks) == 1
    assert acks[0].status == OrderAckStatus.REJECTED
    assert "depth" in acks[0].reason.lower()


@pytest.mark.parametrize("kind", ["backtest", "passive"])
def test_depth_on_arrival_quote_fills_when_flush_is_empty(kind: str) -> None:
    clock = SimulatedClock(start_ns=5000)
    router = _router(kind, clock)
    router.on_quote(_quote("AAPL", "100.00", "100.10", 1000))
    router.submit(_market("AAPL"))
    router.poll_acks()
    clock.set_time(6500)
    router.on_quote(_quote("AAPL", "100.00", "100.10", 6500, ask_size=0))
    fills = _filled(router.poll_acks())
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("100.10")


def test_marketable_limit_is_checked_on_the_arrival_mid() -> None:
    clock = SimulatedClock(start_ns=5000)
    router = PassiveLimitOrderRouter(clock, latency_ns=1000, cost_model=ZeroCostModel())
    router.on_quote(_quote("AAPL", "150.00", "150.02", 1000))
    router.submit(_limit("AAPL", "150.02"))
    assert [ack.status for ack in router.poll_acks()] == [OrderAckStatus.ACKNOWLEDGED]
    clock.set_time(6500)
    router.on_quote(_quote("AAPL", "151.00", "151.02", 6500))
    fills = _filled(router.poll_acks())
    assert len(fills) == 1
    assert fills[0].fill_price == Decimal("150.02")

    clock = SimulatedClock(start_ns=5000)
    router = PassiveLimitOrderRouter(clock, latency_ns=1000, cost_model=ZeroCostModel())
    router.on_quote(_quote("AAPL", "150.00", "150.02", 1000))
    router.submit(_limit("AAPL", "150.02", order_id="worse"))
    router.poll_acks()
    clock.set_time(5500)
    router.on_quote(_quote("AAPL", "151.00", "151.02", 5500))
    clock.set_time(6500)
    router.on_quote(_quote("AAPL", "150.00", "150.02", 6500))
    acks = router.poll_acks()
    assert len(acks) == 1
    assert acks[0].status == OrderAckStatus.REJECTED
    assert "limit" in acks[0].reason.lower()
