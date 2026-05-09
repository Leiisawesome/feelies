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

        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=1000))
        router.submit(_order("AAPL"))

        acks = router.poll_acks()
        assert [a.status for a in acks] == [OrderAckStatus.ACKNOWLEDGED]
        assert acks[0].timestamp_ns == 6000

        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=2000))
        acks2 = router.poll_acks()
        assert len(acks2) == 1
        assert acks2[0].status == OrderAckStatus.FILLED
        # Deferred FILLED uses max(ack_ts, fill_quote.exchange_timestamp_ns).
        # Here the injected clock stays at 5000 while exchange timestamps run
        # 1000 → 2000, so ack_ts=6000 dominates (tests ACK ≤ FILLED ordering).
        assert acks2[0].timestamp_ns == 6000

    def test_deferred_market_fill_ts_no_double_latency_when_clock_tracks_exchange(
        self,
    ) -> None:
        """ReplayFeed advances clock to each quote — FILLED must not add latency twice."""
        clock = SimulatedClock(start_ns=1000)
        router = BacktestOrderRouter(clock, latency_ns=1000)

        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=1000))
        router.submit(_order("AAPL"))
        assert router.poll_acks()[0].timestamp_ns == 2000

        clock.set_time(2500)
        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=2500))
        fill = router.poll_acks()[0]
        assert fill.status == OrderAckStatus.FILLED
        assert fill.timestamp_ns == 2500

    def test_deferred_market_rejects_after_max_ticks_without_eligible_exchange_time(
        self,
    ) -> None:
        """Stale/frozen exchange timestamps never reach latency deadline → timeout."""
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(
            clock,
            latency_ns=1000,
            max_resting_ticks=3,
        )

        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=1000))
        router.submit(_order("AAPL"))
        acks0 = router.poll_acks()
        assert [a.status for a in acks0] == [OrderAckStatus.ACKNOWLEDGED]
        ack_ts = acks0[0].timestamp_ns

        for _ in range(3):
            router.on_quote(_quote("AAPL", "100.00", "100.10", ts=1000))

        rejects = [a for a in router.poll_acks() if a.status == OrderAckStatus.REJECTED]
        assert len(rejects) == 1
        assert "timeout" in rejects[0].reason.lower()
        assert "ticks" in rejects[0].reason.lower()
        assert rejects[0].timestamp_ns >= ack_ts

    def test_deferred_market_timeout_reject_ts_not_before_ack_when_clock_tracks_exchange(
        self,
    ) -> None:
        """max_resting_ticks fires before latency deadline: REJECTED must not precede ACK."""
        clock = SimulatedClock(start_ns=1000)
        router = BacktestOrderRouter(clock, latency_ns=1000, max_resting_ticks=3)

        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=1000))
        router.submit(_order("AAPL"))
        ack = router.poll_acks()[0]
        assert ack.status == OrderAckStatus.ACKNOWLEDGED
        assert ack.timestamp_ns == 2000

        for _ in range(3):
            clock.set_time(1500)
            router.on_quote(_quote("AAPL", "100.00", "100.10", ts=1500))

        rej = router.poll_acks()[0]
        assert rej.status == OrderAckStatus.REJECTED
        assert rej.timestamp_ns >= ack.timestamp_ns

    def test_deferred_market_queues_despite_zero_depth_on_submit_quote(self):
        """Depth at submit is ignored when latency defers the fill (causal model)."""
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock, latency_ns=1000)

        router.on_quote(_quote_with_depth(
            "100.00", "100.10", bid_size=100, ask_size=0, ts=1000,
        ))
        router.submit(_order("AAPL"))
        assert [a.status for a in router.poll_acks()] == [
            OrderAckStatus.ACKNOWLEDGED,
        ]

        router.on_quote(_quote("AAPL", "100.00", "100.10", ts=2000))
        acks2 = router.poll_acks()
        assert len(acks2) == 1
        assert acks2[0].status == OrderAckStatus.FILLED

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

    def test_ack_sequences_are_monotonic_and_preserve_request_sequence(self):
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock)

        router.on_quote(_quote_with_depth("99.00", "101.00", bid_size=200, ask_size=50))
        request = _order_qty(150, side=Side.BUY)
        router.submit(request)

        acks = router.poll_acks()
        assert [a.sequence for a in acks] == [0, 1, 2]
        assert [a.request_sequence for a in acks] == [request.sequence] * 3


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


class TestExcessLegImpactNotDoubleCounted:
    """Audit fix F2: walk-the-book impact must not be double-charged.

    Before the fix, the cost model received ``half_spread + impact`` on
    the excess leg — the impact was already encoded in ``fill_price``,
    so this added an extra ``impact * qty`` to fees on top of the
    already-worse fill price.  After the fix, the model receives
    plain ``half_spread`` on both legs; the L1 leg fees and the
    excess leg fees scale linearly with their respective quantities
    instead of the excess leg paying a quadratic-ish premium.
    """

    def test_excess_leg_fees_per_share_match_l1_leg(self) -> None:
        from feelies.execution.cost_model import (
            DefaultCostModel,
            DefaultCostModelConfig,
        )

        clock = SimulatedClock(start_ns=5000)
        # Use a config with adverse_selection=0 and reg=0 so we can
        # compare the per-share fees component cleanly between the L1
        # and excess legs.  Both legs are taker (default).
        cfg = DefaultCostModelConfig(
            passive_adverse_selection_bps=Decimal("0"),
            sell_regulatory_bps=Decimal("0"),
        )
        router = BacktestOrderRouter(
            clock,
            cost_model=DefaultCostModel(cfg),
            market_impact_factor=Decimal("0.5"),
        )

        # 200-share order against 50 ask depth → 50 at L1, 150 excess.
        # Half-spread $1.00, impact = 0.5 * (150/50) * 1.00 = $1.50.
        router.on_quote(_quote_with_depth("99.00", "101.00", bid_size=200, ask_size=50))
        router.submit(_order_qty(200, side=Side.BUY))

        acks = router.poll_acks()
        partial = next(a for a in acks if a.status == OrderAckStatus.PARTIALLY_FILLED)
        filled = next(a for a in acks if a.status == OrderAckStatus.FILLED)

        # Spread-cost per share is $1.00 on both legs (the impact is
        # encoded in fill_price, NOT in fees).  Commission scales with
        # quantity only.  So fees-per-share should be approximately
        # equal on the two legs.  Before the fix, the excess leg
        # included an additional $1.50/share spread charge.
        l1_fee_per_share = partial.fees / partial.filled_quantity
        excess_fee_per_share = filled.fees / filled.filled_quantity

        # Equality is expected up to commission's per-share rate +
        # rounding.  The pre-fix bug produced excess_fee_per_share ≈
        # l1_fee_per_share + $1.50 — a 100%+ blowup.  Tolerance here
        # is set tight enough to catch that without flaking on
        # legitimate per-share rounding.
        assert abs(excess_fee_per_share - l1_fee_per_share) < Decimal("0.05")

    def test_excess_fill_price_still_includes_impact(self) -> None:
        """Sanity: the impact is still encoded in fill_price (Inv-12 realism)."""
        clock = SimulatedClock(start_ns=5000)
        router = BacktestOrderRouter(clock, market_impact_factor=Decimal("0.5"))
        router.on_quote(_quote_with_depth("98.00", "102.00", bid_size=200, ask_size=50))
        router.submit(_order_qty(150, side=Side.BUY))
        _, _, filled = router.poll_acks()
        # mid=$100, impact = 0.5 * (100/50) * $2 = $2.00.  Excess
        # leg fills at $102.00.  Unchanged from pre-fix behavior.
        assert filled.fill_price == Decimal("102.00")


class TestHTBFeeRouting:
    """2g: short-locate / HTB borrow fees."""

    def test_is_short_flag_propagated_in_order_request(self) -> None:
        req = _order_qty(100, side=Side.SELL, is_short=True)
        assert req.is_short is True

    def test_is_short_default_false(self) -> None:
        req = _order_qty(100, side=Side.SELL)
        assert req.is_short is False
