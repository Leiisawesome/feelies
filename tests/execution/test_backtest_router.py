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


def _fills(acks):
    """Return only non-ACKNOWLEDGED (fill/reject/cancel) acks."""
    return [a for a in acks if a.status != OrderAckStatus.ACKNOWLEDGED]


class TestBacktestOrderRouter:
    def test_fill_at_mid_price(self):
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote("AAPL", "149.00", "151.00"))
        router.submit(_order("AAPL"))

        acks = router.poll_acks()
        # ACKNOWLEDGED ack + FILLED ack (Inv 9 parity with live mode).
        assert [a.status for a in acks] == [
            OrderAckStatus.ACKNOWLEDGED,
            OrderAckStatus.FILLED,
        ]
        fill = acks[1]
        assert fill.fill_price == Decimal("150.00")
        assert fill.filled_quantity == 50
        assert fill.order_id == "ord1"
        assert fill.symbol == "AAPL"

    def test_reject_on_missing_quote(self):
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.submit(_order("MSFT"))

        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.REJECTED
        assert "no quote" in acks[0].reason.lower()

    def test_reject_on_duplicate_order_id(self):
        """Submitting the same order_id twice yields a REJECTED ack on the second."""
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote("AAPL", "100.00", "100.10"))
        router.submit(_order("AAPL"))
        router.poll_acks()

        router.submit(_order("AAPL"))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.REJECTED
        assert "duplicate" in acks[0].reason.lower()

    def test_reject_on_crossed_quote(self):
        """Bid >= ask produces a REJECTED ack rather than a dubious mid fill."""
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote("AAPL", "100.05", "100.00"))  # crossed
        router.submit(_order("AAPL"))

        acks = router.poll_acks()
        assert [a.status for a in acks] == [OrderAckStatus.REJECTED]
        assert "crossed" in acks[0].reason.lower() or "locked" in acks[0].reason.lower()

    def test_poll_acks_clears(self):
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote("AAPL", "100.00", "100.10"))
        router.submit(_order("AAPL"))

        first_poll = router.poll_acks()
        assert len(first_poll) == 2  # ACK + FILLED

        second_poll = router.poll_acks()
        assert second_poll == []

    def test_latency_injection(self):
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock, latency_ns=1000)

        router.on_quote(_quote("AAPL", "100.00", "100.10"))
        router.submit(_order("AAPL"))

        acks = router.poll_acks()
        # ACK and FILL both carry now + latency.
        assert acks[0].timestamp_ns == 6000
        assert acks[1].timestamp_ns == 6000

    def test_multiple_symbols_independent(self):
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote("AAPL", "149.00", "151.00"))
        router.on_quote(_quote("MSFT", "300.00", "302.00"))

        router.submit(_order("AAPL", order_id="o1"))
        router.submit(_order("MSFT", order_id="o2"))

        fills = [a for a in router.poll_acks() if a.status == OrderAckStatus.FILLED]
        assert len(fills) == 2
        by_id = {a.order_id: a for a in fills}
        assert by_id["o1"].fill_price == Decimal("150.00")
        assert by_id["o2"].fill_price == Decimal("301.00")

    def test_quote_update_uses_latest(self):
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote("AAPL", "100.00", "100.10"))
        router.on_quote(_quote("AAPL", "200.00", "200.20"))

        router.submit(_order("AAPL"))

        fills = [a for a in router.poll_acks() if a.status == OrderAckStatus.FILLED]
        assert fills[0].fill_price == Decimal("200.10")

    def test_fill_timestamp_without_latency(self):
        clock = SimulatedClock(start_ns=3000)
        router = BacktestOrderRouter(clock, latency_ns=0)

        router.on_quote(_quote("AAPL", "100.00", "100.10"))
        router.submit(_order("AAPL"))

        acks = router.poll_acks()
        assert acks[0].timestamp_ns == 3000
        assert acks[1].timestamp_ns == 3000


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
        """Order qty ≤ available depth → ACKNOWLEDGED + FILLED, no slippage."""
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote_with_depth("99.00", "101.00", bid_size=200, ask_size=200))
        router.submit(_order_qty(100, side=Side.BUY))

        acks = router.poll_acks()
        assert [a.status for a in acks] == [
            OrderAckStatus.ACKNOWLEDGED,
            OrderAckStatus.FILLED,
        ]
        fill = acks[1]
        assert fill.filled_quantity == 100
        assert fill.fill_price == Decimal("100.00")  # mid

    def test_partial_fill_emits_ack_partial_filled(self) -> None:
        """Order qty > ask_size → ACKNOWLEDGED + PARTIALLY_FILLED + FILLED acks."""
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote_with_depth("99.00", "101.00", bid_size=200, ask_size=50))
        router.submit(_order_qty(150, side=Side.BUY))

        acks = router.poll_acks()
        assert [a.status for a in acks] == [
            OrderAckStatus.ACKNOWLEDGED,
            OrderAckStatus.PARTIALLY_FILLED,
            OrderAckStatus.FILLED,
        ]
        _, partial, filled = acks
        assert partial.filled_quantity == 50
        assert partial.fill_price == Decimal("100.00")  # mid-price for L1 depth

        assert filled.filled_quantity == 100  # excess = 150 - 50
        assert filled.order_id == partial.order_id

    def test_excess_price_raised_for_buy(self) -> None:
        """Excess qty for a BUY is filled above mid (market-impact premium)."""
        clock = SimulatedClock(start_ns=5000)
        # impact = 0.5 * (excess/depth) * half_spread = 0.5 * (100/50) * 1 = 1.0
        router = BacktestOrderRouter(clock, market_impact_factor=Decimal("0.5"))

        router.on_quote(_quote_with_depth("98.00", "102.00", bid_size=200, ask_size=50))
        router.submit(_order_qty(150, side=Side.BUY))

        _, _, filled = router.poll_acks()
        mid = Decimal("100.00")
        half_spread = Decimal("2.00")
        expected_impact = Decimal("0.5") * (Decimal("100") / Decimal("50")) * half_spread
        assert filled.fill_price == mid + expected_impact

    def test_excess_price_lowered_for_sell(self) -> None:
        """Excess qty for a SELL is filled below mid (receiver gets less)."""
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock, market_impact_factor=Decimal("0.5"))

        router.on_quote(_quote_with_depth("98.00", "102.00", bid_size=50, ask_size=200))
        router.submit(_order_qty(150, side=Side.SELL))

        _, _, filled = router.poll_acks()
        mid = Decimal("100.00")
        half_spread = Decimal("2.00")
        expected_impact = Decimal("0.5") * (Decimal("100") / Decimal("50")) * half_spread
        assert filled.fill_price == mid - expected_impact

    def test_impact_is_capped(self) -> None:
        """Market-impact premium is capped at max_impact_half_spreads × half_spread."""
        clock = SimulatedClock(start_ns=5000)
        # excess/depth = 1000/1 = 1000; factor=0.5 → raw = 500 half-spreads.
        # Cap defaults to 10 half-spreads.
        router = BacktestOrderRouter(
            clock,
            market_impact_factor=Decimal("0.5"),
            max_impact_half_spreads=Decimal("10"),
        )

        router.on_quote(_quote_with_depth("98.00", "102.00", bid_size=200, ask_size=1))
        router.submit(_order_qty(1001, side=Side.BUY))

        _, _, filled = router.poll_acks()
        mid = Decimal("100.00")
        half_spread = Decimal("2.00")
        # Cap: 10 × 2 = 20
        assert filled.fill_price == mid + Decimal("10") * half_spread

    def test_zero_depth_rejects_order(self) -> None:
        """Zero L1 depth on the relevant side → REJECTED (no vacuum fills)."""
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote_with_depth("99.00", "101.00", bid_size=0, ask_size=0))
        router.submit(_order_qty(100, side=Side.BUY))

        acks = router.poll_acks()
        # ACKNOWLEDGED + REJECTED
        statuses = [a.status for a in acks]
        assert OrderAckStatus.REJECTED in statuses
        assert OrderAckStatus.FILLED not in statuses
        reject = next(a for a in acks if a.status == OrderAckStatus.REJECTED)
        assert "depth" in reject.reason.lower()

    def test_all_acks_share_same_order_id(self) -> None:
        """ACK + partial + final fill acks must reference the same order_id."""
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
