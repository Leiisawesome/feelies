"""Every simulated fill price must lie on the Reg NMS tick grid."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter
from feelies.execution.tick_size import is_on_tick_grid

pytestmark = pytest.mark.backtest_validation


def _quote(
    bid: str,
    ask: str,
    *,
    bid_size: int = 100,
    ask_size: int = 50,
) -> NBBOQuote:
    ts = 1_000_000
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id="q",
        sequence=1,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts,
    )


def _market_buy(qty: int) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=2_000_000,
        correlation_id="o",
        sequence=2,
        order_id="m1",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=qty,
    )


def _limit_buy(price: str, qty: int = 50) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=2_000_000,
        correlation_id="o",
        sequence=2,
        order_id="l1",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=qty,
        limit_price=Decimal(price),
    )


def _fill_prices(acks) -> list[Decimal]:
    out: list[Decimal] = []
    for ack in acks:
        if (
            ack.status
            in (
                OrderAckStatus.FILLED,
                OrderAckStatus.PARTIALLY_FILLED,
            )
            and ack.fill_price is not None
        ):
            out.append(ack.fill_price)
    return out


def test_market_partial_fill_impact_leg_snaps_to_tick() -> None:
    """Snap an off-tick impact price against the taker."""
    clock = SimulatedClock(start_ns=5_000)
    router = BacktestOrderRouter(
        clock,
        market_impact_factor=Decimal("0.25"),
    )
    router.on_quote(_quote("100.01", "100.02", ask_size=50))
    router.submit(_market_buy(100))

    for px in _fill_prices(router.poll_acks()):
        assert is_on_tick_grid(px), f"off-grid fill price {px}"


def test_passive_limit_resting_price_snapped_on_post() -> None:
    clock = SimulatedClock(start_ns=5_000)
    router = PassiveLimitOrderRouter(clock, fill_delay_ticks=100)
    router.on_quote(_quote("100.00", "100.05"))
    router.submit(_limit_buy("100.015"))

    ack = router.poll_acks()[0]
    assert ack.status == OrderAckStatus.ACKNOWLEDGED
    pending = router._resting_orders["l1"]
    assert pending.limit_price == Decimal("100.01")
