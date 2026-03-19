from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.backtest_validation

from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.execution.backtest_router import BacktestOrderRouter


def _quote(symbol: str, bid: str, ask: str, ts: int = 1000) -> NBBOQuote:
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


def _order(symbol: str, order_id: str = "ord1") -> OrderRequest:
    return OrderRequest(
        timestamp_ns=2000,
        correlation_id="o1",
        sequence=2,
        order_id=order_id,
        symbol=symbol,
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=50,
    )


class TestBacktestOrderRouter:
    def test_fill_at_mid_price(self):
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote("AAPL", "149.00", "151.00"))
        router.submit(_order("AAPL"))

        acks = router.poll_acks()
        assert len(acks) == 1
        ack = acks[0]
        assert ack.status == OrderAckStatus.FILLED
        assert ack.fill_price == Decimal("150.00")
        assert ack.filled_quantity == 50
        assert ack.order_id == "ord1"
        assert ack.symbol == "AAPL"

    def test_reject_on_missing_quote(self):
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.submit(_order("MSFT"))

        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.REJECTED
        assert "no quote" in acks[0].reason.lower()

    def test_poll_acks_clears(self):
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote("AAPL", "100.00", "100.10"))
        router.submit(_order("AAPL"))

        first_poll = router.poll_acks()
        assert len(first_poll) == 1

        second_poll = router.poll_acks()
        assert second_poll == []

    def test_latency_injection(self):
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock, latency_ns=1000)

        router.on_quote(_quote("AAPL", "100.00", "100.10"))
        router.submit(_order("AAPL"))

        acks = router.poll_acks()
        assert acks[0].timestamp_ns == 6000  # 5000 + 1000

    def test_multiple_symbols_independent(self):
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote("AAPL", "149.00", "151.00"))
        router.on_quote(_quote("MSFT", "300.00", "302.00"))

        router.submit(_order("AAPL", order_id="o1"))
        router.submit(_order("MSFT", order_id="o2"))

        acks = router.poll_acks()
        assert len(acks) == 2

        by_id = {a.order_id: a for a in acks}
        assert by_id["o1"].fill_price == Decimal("150.00")
        assert by_id["o2"].fill_price == Decimal("301.00")

    def test_quote_update_uses_latest(self):
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote("AAPL", "100.00", "100.10"))
        router.on_quote(_quote("AAPL", "200.00", "200.20"))

        router.submit(_order("AAPL"))

        acks = router.poll_acks()
        assert acks[0].fill_price == Decimal("200.10")

    def test_fill_timestamp_without_latency(self):
        clock = SimulatedClock(start_ns=3000)
        router = BacktestOrderRouter(clock, latency_ns=0)

        router.on_quote(_quote("AAPL", "100.00", "100.10"))
        router.submit(_order("AAPL"))

        acks = router.poll_acks()
        assert acks[0].timestamp_ns == 3000
