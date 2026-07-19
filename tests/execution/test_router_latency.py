"""Latency-queue tests for both routers (audit F-H-07).

Orders submitted with ``latency_ns > 0`` must defer their fill until a
quote arrives whose ``timestamp_ns >= submit_time + latency_ns``.  The
fill executes against that later quote — not the submit-time quote.

When ``latency_ns == 0`` the orders fill synchronously against the
submit-time quote (legacy fast path).
"""

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
from feelies.execution.cost_model import ZeroCostModel
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter

pytestmark = pytest.mark.backtest_validation


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
        correlation_id=f"q-{ts}",
        sequence=ts,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts,
    )


def _market_order(symbol: str, qty: int = 50, order_id: str = "ord1") -> OrderRequest:
    return OrderRequest(
        timestamp_ns=0,
        correlation_id="o1",
        sequence=2,
        order_id=order_id,
        symbol=symbol,
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=qty,
    )


class TestBacktestRouterLatencyQueue:
    def test_zero_latency_fast_path_fills_synchronously(self) -> None:
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(
            clock,
            latency_ns=0,
            cost_model=ZeroCostModel(),
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=4000))
        router.submit(_market_order("AAPL"))
        acks = router.poll_acks()
        # ACK + FILL on same tick.
        statuses = [a.status for a in acks]
        assert OrderAckStatus.FILLED in statuses

    def test_nonzero_latency_defers_fill_until_post_eligibility_quote(self) -> None:
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(
            clock,
            latency_ns=1000,
            cost_model=ZeroCostModel(),
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=4000))
        router.submit(_market_order("AAPL"))
        # eligible_at = 5000 + 1000 = 6000.  Initial poll: only the ACK.
        first_acks = router.poll_acks()
        statuses = [a.status for a in first_acks]
        assert OrderAckStatus.ACKNOWLEDGED in statuses
        assert OrderAckStatus.FILLED not in statuses

        # Quote at ts=5500 (still before eligibility) — no fill yet.
        clock.set_time(5500)
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=5500))
        assert OrderAckStatus.FILLED not in [a.status for a in router.poll_acks()]

        # Quote at ts=6500 (after eligibility) — fill against THIS quote.
        clock.set_time(6500)
        router.on_quote(_quote("AAPL", "99.00", "99.10", ts=6500))
        late_acks = router.poll_acks()
        fills = [a for a in late_acks if a.status == OrderAckStatus.FILLED]
        assert len(fills) == 1
        # Deferred MARKET orders still execute at the later quote's cross.
        assert fills[0].fill_price == Decimal("99.10")

    def test_fifo_eligibility_two_orders_same_symbol(self) -> None:
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(
            clock,
            latency_ns=1000,
            cost_model=ZeroCostModel(),
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=4000))
        router.submit(_market_order("AAPL", order_id="a"))
        clock.set_time(5100)
        router.submit(_market_order("AAPL", order_id="b"))
        # Quote at ts=6500 makes both eligible (6000 and 6100 ≤ 6500).
        clock.set_time(6500)
        router.on_quote(_quote("AAPL", "99.00", "99.10", ts=6500))
        acks = router.poll_acks()
        filled_order_ids = [a.order_id for a in acks if a.status == OrderAckStatus.FILLED]
        assert filled_order_ids == ["a", "b"]

    def test_eligibility_per_symbol(self) -> None:
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(
            clock,
            latency_ns=1000,
            cost_model=ZeroCostModel(),
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=4000))
        router.on_quote(_quote("MSFT", "200.00", "200.10", ts=4000))
        router.submit(_market_order("AAPL", order_id="a"))
        router.submit(_market_order("MSFT", order_id="m"))

        # MSFT quote at ts=6500 → fills MSFT but not AAPL.
        clock.set_time(6500)
        router.on_quote(_quote("MSFT", "200.05", "200.15", ts=6500))
        acks = router.poll_acks()
        filled = [a for a in acks if a.status == OrderAckStatus.FILLED]
        assert len(filled) == 1
        assert filled[0].order_id == "m"


class TestPassiveLimitRouterLatencyQueue:
    def test_zero_latency_market_fills_synchronously(self) -> None:
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            latency_ns=0,
            cost_model=ZeroCostModel(),
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=4000))
        router.submit(_market_order("AAPL"))
        acks = router.poll_acks()
        assert any(a.status == OrderAckStatus.FILLED for a in acks)

    def test_nonzero_latency_market_defers_to_later_quote(self) -> None:
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            latency_ns=1000,
            cost_model=ZeroCostModel(),
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=4000))
        router.submit(_market_order("AAPL"))
        first = router.poll_acks()
        assert not any(a.status == OrderAckStatus.FILLED for a in first)

        clock.set_time(6500)
        router.on_quote(_quote("AAPL", "99.00", "99.10", ts=6500))
        fills = [a for a in router.poll_acks() if a.status == OrderAckStatus.FILLED]
        assert len(fills) == 1
        assert fills[0].fill_price == Decimal("99.10")

    def test_resting_limit_fill_uses_post_eligibility_quote_too(self) -> None:
        """Resting LIMIT orders also wait for the latency window."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            latency_ns=0,
            cost_model=ZeroCostModel(),
            fill_delay_ticks=1,
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=4000))
        router.submit(
            OrderRequest(
                timestamp_ns=0,
                correlation_id="o",
                sequence=1,
                order_id="l",
                symbol="AAPL",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=50,
                limit_price=Decimal("100.00"),
            )
        )
        router.poll_acks()
        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=6000))
        # With fill_delay_ticks=1 and zero latency, fills on this quote.
        fills = [a for a in router.poll_acks() if a.status == OrderAckStatus.FILLED]
        assert len(fills) == 1

    def test_resting_limit_through_fill_deferred_until_latency_eligible(self) -> None:
        """A resting LIMIT order must not fill before ``latency_ns`` has
        elapsed in exchange time, even when the opposite BBO immediately
        crosses the resting level (a "through fill", which is otherwise a
        guaranteed, unconditional fill in :meth:`_evaluate_fill`)."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            latency_ns=1000,
            cost_model=ZeroCostModel(),
        )
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=4000))
        router.submit(
            OrderRequest(
                timestamp_ns=0,
                correlation_id="o",
                sequence=1,
                order_id="l",
                symbol="AAPL",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=50,
                limit_price=Decimal("100.00"),
            )
        )
        router.poll_acks()
        # eligible_at = 5000 + 1000 = 6000. A crossing quote at ts=5500 (still
        # before eligibility) must NOT fill the resting order.
        clock.set_time(5500)
        router.on_quote(_quote("AAPL", "99.00", "99.10", ts=5500))
        assert not any(a.status == OrderAckStatus.FILLED for a in router.poll_acks())

        # Quote at ts=6500 (after eligibility) — through-fill fires now.
        clock.set_time(6500)
        router.on_quote(_quote("AAPL", "98.00", "98.10", ts=6500))
        fills = [a for a in router.poll_acks() if a.status == OrderAckStatus.FILLED]
        assert len(fills) == 1
