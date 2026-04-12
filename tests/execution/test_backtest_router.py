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


def _quote_with_depth(
    bid: str, ask: str, bid_size: int, ask_size: int, ts: int = 1000
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id="q1",
        sequence=1,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts,
    )


def _order_qty(
    qty: int, side: Side = Side.BUY, is_short: bool = False, order_id: str = "ord1"
) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=2000,
        correlation_id="o1",
        sequence=2,
        order_id=order_id,
        symbol="AAPL",
        side=side,
        order_type=OrderType.MARKET,
        quantity=qty,
        is_short=is_short,
    )


class TestPartialFillAndSlippage:
    """D14: partial fill model. 2d: walk-the-book slippage for excess."""

    def test_full_fill_when_qty_within_depth(self) -> None:
        """Order qty ≤ available depth → single FILLED ack, no slippage."""
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote_with_depth("99.00", "101.00", bid_size=200, ask_size=200))
        router.submit(_order_qty(100, side=Side.BUY))

        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].filled_quantity == 100
        assert acks[0].fill_price == Decimal("100.00")  # mid

    def test_partial_fill_emits_two_acks(self) -> None:
        """Order qty > ask_size → PARTIALLY_FILLED + FILLED acks."""
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote_with_depth("99.00", "101.00", bid_size=200, ask_size=50))
        router.submit(_order_qty(150, side=Side.BUY))

        acks = router.poll_acks()
        assert len(acks) == 2

        partial, filled = acks
        assert partial.status == OrderAckStatus.PARTIALLY_FILLED
        assert partial.filled_quantity == 50
        assert partial.fill_price == Decimal("100.00")  # mid-price for L1 depth

        assert filled.status == OrderAckStatus.FILLED
        assert filled.filled_quantity == 100  # excess = 150 - 50
        assert filled.order_id == partial.order_id

    def test_excess_price_raised_for_buy(self) -> None:
        """Excess qty for a BUY is filled above mid (market-impact premium)."""
        clock = SimulatedClock(start_ns=5000)
        # impact = 0.5 * (excess/depth) * half_spread = 0.5 * (100/50) * 1 = 1.0
        router = BacktestOrderRouter(clock, market_impact_factor=0.5)

        router.on_quote(_quote_with_depth("98.00", "102.00", bid_size=200, ask_size=50))
        router.submit(_order_qty(150, side=Side.BUY))

        acks = router.poll_acks()
        partial, filled = acks
        mid = Decimal("100.00")
        half_spread = Decimal("2.00")
        expected_impact = Decimal("0.5") * (Decimal("100") / Decimal("50")) * half_spread
        assert filled.fill_price == mid + expected_impact

    def test_excess_price_lowered_for_sell(self) -> None:
        """Excess qty for a SELL is filled below mid (receiver gets less)."""
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock, market_impact_factor=0.5)

        router.on_quote(_quote_with_depth("98.00", "102.00", bid_size=50, ask_size=200))
        router.submit(_order_qty(150, side=Side.SELL))

        acks = router.poll_acks()
        _, filled = acks
        mid = Decimal("100.00")
        half_spread = Decimal("2.00")
        expected_impact = Decimal("0.5") * (Decimal("100") / Decimal("50")) * half_spread
        assert filled.fill_price == mid - expected_impact

    def test_zero_depth_falls_through_to_full_fill(self) -> None:
        """quote with zero depth to not trigger partial model (edge case)."""
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote_with_depth("99.00", "101.00", bid_size=0, ask_size=0))
        router.submit(_order_qty(100, side=Side.BUY))

        acks = router.poll_acks()
        # available_depth==0 → single FILLED at mid
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED

    def test_two_acks_share_same_order_id(self) -> None:
        """Partial + final fill acks must reference the same order_id."""
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote_with_depth("99.00", "101.00", bid_size=200, ask_size=30))
        router.submit(_order_qty(100, order_id="my-order"))

        acks = router.poll_acks()
        assert all(a.order_id == "my-order" for a in acks)


class TestHTBFeeRouting:
    """2g: short-locate / HTB borrow fees."""

    def test_is_short_flag_propagated_in_order_request(self) -> None:
        req = _order_qty(100, side=Side.SELL, is_short=True)
        assert req.is_short is True

    def test_is_short_default_false(self) -> None:
        req = _order_qty(100, side=Side.SELL)
        assert req.is_short is False
