from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest

pytestmark = pytest.mark.backtest_validation

_SALT_COUNT = 32
_SALT_FLOOR = 8


def _assert_over_salts(scenario) -> None:
    """Run ``scenario`` under 32 salts of the installed drain uniform.

    ``scenario`` returns True when its precondition held and the property
    held, None when the precondition did not occur, and False when the
    property was violated. At least ``_SALT_FLOOR`` salts must meet the
    precondition.
    """
    original = PassiveLimitOrderRouter._seeded_uniform
    held = 0
    try:
        for salt in range(_SALT_COUNT):

            def _salted(self, pending, quote, _base=original, _salt=salt):  # type: ignore[no-untyped-def]
                uniform = _base(self, pending, quote)
                digest = hashlib.sha256(f"{uniform}|{_salt}".encode()).digest()
                value = int.from_bytes(digest[:8], "big")
                return Decimal(value) / Decimal(1 << 64)

            PassiveLimitOrderRouter._seeded_uniform = _salted  # type: ignore[method-assign]
            outcome = scenario()
            if outcome is False:
                raise AssertionError(f"property violated at salt {salt}")
            if outcome is True:
                held += 1
        assert held >= _SALT_FLOOR, f"precondition held on {held} of {_SALT_COUNT} salts"
    finally:
        PassiveLimitOrderRouter._seeded_uniform = original


from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.execution.cost_model import (
    DefaultCostModel,
    DefaultCostModelConfig,
    ZeroCostModel,
)
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter


def _quote(
    symbol: str,
    bid: str,
    ask: str,
    ts: int = 1000,
    bid_size: int = 100,
    ask_size: int = 100,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q-{ts}",
        sequence=1,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts,
    )


def _limit_buy(
    symbol: str,
    qty: int = 100,
    limit_price: str | None = None,
    order_id: str = "ord1",
) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=2000,
        correlation_id="o1",
        sequence=2,
        order_id=order_id,
        symbol=symbol,
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=qty,
        limit_price=Decimal(limit_price) if limit_price else None,
    )


def _limit_sell(
    symbol: str,
    qty: int = 100,
    limit_price: str | None = None,
    order_id: str = "ord1",
) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=2000,
        correlation_id="o1",
        sequence=2,
        order_id=order_id,
        symbol=symbol,
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        quantity=qty,
        limit_price=Decimal(limit_price) if limit_price else None,
    )


def _market_order(symbol: str, order_id: str = "mkt1") -> OrderRequest:
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


class TestPassiveLimitRouter:
    """Core passive limit order router tests."""

    def test_market_order_fills_at_cross(self):
        """A market buy fills immediately at the ask, not the midpoint."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel())

        router.on_quote(_quote("AAPL", "149.00", "151.00"))
        router.submit(_market_order("AAPL"))

        acks = router.poll_acks()
        assert [a.status for a in acks] == [
            OrderAckStatus.ACKNOWLEDGED,
            OrderAckStatus.FILLED,
        ]
        filled = acks[1]
        assert filled.fill_price == Decimal("151.00")
        assert filled.filled_quantity == 50

    def test_reject_on_missing_quote(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel())

        router.submit(_limit_buy("MSFT"))

        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.REJECTED
        assert "no quote" in acks[0].reason.lower()

    def test_limit_order_acknowledged_not_filled(self):
        """LIMIT orders emit ACKNOWLEDGED on submit, not FILLED."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=5)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL"))

        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.ACKNOWLEDGED
        assert acks[0].fill_price is None
        assert acks[0].filled_quantity == 0
        assert router.resting_order_count == 1

    def test_ack_sequences_are_monotonic_and_preserve_request_sequence(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)

        request = _limit_buy("AAPL")
        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(request)
        submit_acks = router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "149.98", "150.00", ts=6000))
        fill_acks = router.poll_acks()

        acks = [*submit_acks, *fill_acks]
        assert [a.sequence for a in acks] == [0, 1]
        assert [a.request_sequence for a in acks] == [request.sequence, request.sequence]

    def test_limit_price_defaults_to_bid_for_buy(self):
        """BUY limit defaults to bid when no explicit price given."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL"))
        router.poll_acks()

        assert router.resting_order_count == 1
        assert "AAPL" in router.resting_symbols()

    def test_limit_price_defaults_to_ask_for_sell(self):
        """SELL limit defaults to ask when no explicit price given."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_sell("AAPL"))
        router.poll_acks()

        assert router.resting_order_count == 1


class TestThroughFill:
    """Test the through-fill condition: opposite BBO crosses our level."""

    def test_buy_fills_when_ask_drops_to_limit(self):
        """BUY limit fills when ask <= limit_price (through fill)."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL"))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "149.98", "150.00", ts=6000))
        acks = router.poll_acks()

        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].fill_price == Decimal("150.00")
        assert acks[0].filled_quantity == 100
        assert router.resting_order_count == 0

    def test_buy_fills_when_ask_drops_below_limit(self):
        """BUY limit fills when ask < limit_price (price through).

        IBKR / Reg-NMS price improvement: a passive BUY at $150.00
        whose limit is crossed by an ask of $149.98 fills at the
        better price ($149.98), not at the resting limit.  See
        ``_check_resting_orders`` for the routing rule.
        """
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL"))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "149.95", "149.98", ts=6000))
        acks = router.poll_acks()

        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].fill_price == Decimal("149.98")

    def test_sell_fills_when_bid_rises_to_limit(self):
        """SELL limit fills when bid >= limit_price (through fill)."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_sell("AAPL"))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "150.02", "150.04", ts=6000))
        acks = router.poll_acks()

        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].fill_price == Decimal("150.02")
        assert acks[0].filled_quantity == 100

    def test_sell_fills_when_bid_rises_above_limit(self):
        """SELL limit fills when bid > limit_price → price improvement.

        Resting SELL at $150.02 with a new bid of $150.05 fills at the
        better price ($150.05), not the resting limit.
        """
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_sell("AAPL"))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "150.05", "150.07", ts=6000))
        acks = router.poll_acks()

        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].fill_price == Decimal("150.05")


class TestThroughFillPriceImprovement:
    """Through-fills receive the better price under limit-or-better.

    IBKR (and Reg-NMS) requires limit orders to fill at the limit
    price OR BETTER, never worse.  When the opposite-side BBO has
    gapped through our limit, the realistic execution price is the
    new opposite-side BBO, not the resting limit price.
    """

    def test_buy_through_fill_uses_lower_ask(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)
        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", limit_price="150.00"))
        router.poll_acks()

        clock.set_time(6000)
        # Ask gapped to $149.95 — buyer should fill at $149.95, not $150.
        router.on_quote(_quote("AAPL", "149.93", "149.95", ts=6000))
        acks = router.poll_acks()
        assert acks[0].fill_price == Decimal("149.95")

    def test_buy_at_limit_no_improvement(self):
        """If ask equals limit exactly, fill at the limit (no through)."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)
        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", limit_price="150.00"))
        router.poll_acks()
        clock.set_time(6000)
        # Ask drops to the limit — fills at limit.  No improvement.
        router.on_quote(_quote("AAPL", "149.98", "150.00", ts=6000))
        acks = router.poll_acks()
        assert acks[0].fill_price == Decimal("150.00")

    def test_sell_through_fill_uses_higher_bid(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)
        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_sell("AAPL", limit_price="150.02"))
        router.poll_acks()
        clock.set_time(6000)
        # Bid gapped to $150.10 — seller should fill at $150.10.
        router.on_quote(_quote("AAPL", "150.10", "150.12", ts=6000))
        acks = router.poll_acks()
        assert acks[0].fill_price == Decimal("150.10")

    def test_level_fill_stays_at_limit(self):
        """A drain fill at an uncrossed level fills at the resting limit."""

        def scenario() -> bool | None:
            clock = SimulatedClock(start_ns=5000)
            router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=1)
            router.on_quote(_quote("AAPL", "150.00", "150.02"))
            router.submit(_limit_buy("AAPL", limit_price="150.00"))
            router.poll_acks()
            clock.set_time(6000)
            router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6000))
            filled = [ack for ack in router.poll_acks() if ack.status == OrderAckStatus.FILLED]
            if not filled:
                return None
            return all(
                ack.fill_price == Decimal("150.00") and ack.reason == "FILLED_BY_DRAIN"
                for ack in filled
            )

        _assert_over_salts(scenario)


class TestLevelFill:
    """Test the level (queue-drain) fill: seeded-Bernoulli per quote tick.

    A balanced book (bid_size == ask_size) gives order-flow imbalance 0.5
    → aggression 1.0, so h = h0 = 1/fill_delay_ticks.  Setting
    fill_delay_ticks=1 with fill_hazard_max=1.0 forces h=1.0 → the level
    fill is guaranteed on the first at-level tick, making the fill price /
    outcome deterministic for assertion.
    """

    def test_buy_drain_fill_at_level(self):
        """BUY limit drain-fills at the bid level (h=1.0)."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            cost_model=ZeroCostModel(),
            fill_delay_ticks=1,
            fill_hazard_max=Decimal("1.0"),
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL"))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6000))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].fill_price == Decimal("150.00")
        assert acks[0].reason == "FILLED_BY_DRAIN"

    def test_sell_drain_fill_at_level(self):
        """SELL limit drain-fills at the ask level (h=1.0)."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            cost_model=ZeroCostModel(),
            fill_delay_ticks=1,
            fill_hazard_max=Decimal("1.0"),
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_sell("AAPL"))
        router.poll_acks()

        clock.set_time(7000)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=7000))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].fill_price == Decimal("150.02")
        assert acks[0].reason == "FILLED_BY_DRAIN"

    def test_no_drain_fill_while_off_level(self):
        """No drain fill while the BBO has moved away from our level.

        BUY at 150.00 with bid 150.01 is off the touch. The property is
        checked on salts where the order is still resting when that quote
        arrives.
        """

        def scenario() -> bool | None:
            clock = SimulatedClock(start_ns=5000)
            router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=3)
            router.on_quote(_quote("AAPL", "150.00", "150.02"))
            router.submit(_limit_buy("AAPL"))
            router.poll_acks()
            for i in range(2):
                clock.set_time(6000 + i * 1000)
                router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6000 + i * 1000))
                router.poll_acks()
            if "ord1" not in router._resting_orders:
                return None
            clock.set_time(8000)
            router.on_quote(_quote("AAPL", "150.01", "150.03", ts=8000))
            drained = [
                ack
                for ack in router.poll_acks()
                if ack.status == OrderAckStatus.FILLED and ack.reason == "FILLED_BY_DRAIN"
            ]
            return not drained

        _assert_over_salts(scenario)

    def test_buy_fills_when_bid_below_limit(self):
        """BUY at $150.00: if bid drops to $149.99 we're still at level."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            cost_model=ZeroCostModel(),
            fill_delay_ticks=1,
            fill_hazard_max=Decimal("1.0"),
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", limit_price="150.00"))
        router.poll_acks()

        # Off level (bid above our limit, ask above our limit → no through)
        for i in range(3):
            ts = 6000 + i * 1000
            clock.set_time(ts)
            router.on_quote(_quote("AAPL", "150.01", "150.03", ts=ts))
            assert router.poll_acks() == []

        # Back at level → guaranteed drain fill
        clock.set_time(9000)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=9000))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].reason == "FILLED_BY_DRAIN"

    def test_buy_at_level_when_bid_below_limit(self):
        """BUY at $150.00 with bid at $149.99 is still at the level → fills."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            fill_delay_ticks=1,
            fill_hazard_max=Decimal("1.0"),
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", limit_price="150.00"))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "149.99", "150.01", ts=6000))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].fill_price == Decimal("150.00")


class TestTimeout:
    """Test order cancellation after max_resting_ticks."""

    def test_limit_expired_after_timeout(self):
        """Passive timeouts emit EXPIRED."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            cost_model=ZeroCostModel(),
            fill_delay_ticks=100,
            max_resting_ticks=5,
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL"))
        router.poll_acks()

        # 5 ticks with price moving away (no fill)
        for i in range(5):
            ts = 6000 + i * 1000
            clock.set_time(ts)
            router.on_quote(
                _quote("AAPL", "150.01", "150.03", ts=ts),
            )

        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.EXPIRED
        assert "timeout" in acks[0].reason.lower()
        assert router.resting_order_count == 0


class TestCostModel:
    """Test cost calculation for passive vs aggressive fills."""

    def test_passive_fill_zero_spread_cost(self):
        """A passive drain fill charges commission only, not the spread."""

        def scenario() -> bool | None:
            clock = SimulatedClock(start_ns=5000)
            cost_model = DefaultCostModel(
                DefaultCostModelConfig(
                    adverse_selection_through_bps=Decimal("0"),
                    adverse_selection_drain_bps=Decimal("0"),
                )
            )
            router = PassiveLimitOrderRouter(clock, cost_model=cost_model, fill_delay_ticks=1)
            router.on_quote(_quote("AAPL", "150.00", "150.10"))
            router.submit(_limit_buy("AAPL", qty=100))
            router.poll_acks()
            clock.set_time(6000)
            router.on_quote(_quote("AAPL", "150.00", "150.10", ts=6000))
            filled = [ack for ack in router.poll_acks() if ack.status == OrderAckStatus.FILLED]
            if not filled:
                return None
            return all(
                ack.reason == "FILLED_BY_DRAIN" and ack.fees < Decimal("1.00") for ack in filled
            )

        _assert_over_salts(scenario)

    def test_aggressive_fill_crosses_spread_in_price(self):
        """Embed the crossed spread in fill price, not fees."""
        clock = SimulatedClock(start_ns=5000)
        cost_model = DefaultCostModel(DefaultCostModelConfig())
        router = PassiveLimitOrderRouter(clock, cost_model=cost_model)

        router.on_quote(_quote("AAPL", "150.00", "150.10"))
        router.submit(_market_order("AAPL"))

        acks = router.poll_acks()
        fill = next(a for a in acks if a.status == OrderAckStatus.FILLED)
        assert fill.status == OrderAckStatus.FILLED
        # Cross price = ask, not mid.
        assert fill.fill_price == Decimal("150.10")
        # Spread is in the price now; fees are commission + exchange only
        # (well below the old $2.50 spread_cost charge).
        assert fill.fees < Decimal("1.00")

    def test_maker_path_cheaper_than_taker_path(self):
        """A passive drain fill costs fewer bps than the aggressive fill."""

        def scenario() -> bool | None:
            clock = SimulatedClock(start_ns=5000)
            cost_model = DefaultCostModel(
                DefaultCostModelConfig(
                    adverse_selection_through_bps=Decimal("0"),
                    adverse_selection_drain_bps=Decimal("0"),
                )
            )
            router = PassiveLimitOrderRouter(clock, cost_model=cost_model, fill_delay_ticks=1)
            router.on_quote(_quote("AAPL", "150.00", "150.02"))
            router.submit(_limit_buy("AAPL", qty=1000))
            router.poll_acks()
            clock.set_time(6000)
            router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6000))
            passive = [ack for ack in router.poll_acks() if ack.status == OrderAckStatus.FILLED]
            clock.set_time(7000)
            router.on_quote(_quote("AAPL", "150.00", "150.02", ts=7000))
            router.submit(_market_order("AAPL"))
            aggressive = next(
                ack for ack in router.poll_acks() if ack.status == OrderAckStatus.FILLED
            )
            if not passive:
                return None
            return passive[0].cost_bps < aggressive.cost_bps

        _assert_over_salts(scenario)


class TestMarketabilityGuard:
    """Test D13: marketable limit orders redirect to aggressive fill."""

    def test_buy_at_or_above_ask_fills_aggressively(self):
        """BUY limit at or above the ask should redirect to aggressive fill."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        # BUY limit at $150.02 — equal to ask → marketable
        buy = _limit_buy("AAPL", qty=100, limit_price="150.02")
        router.submit(buy)
        acks = router.poll_acks()

        assert [a.status for a in acks] == [
            OrderAckStatus.ACKNOWLEDGED,
            OrderAckStatus.FILLED,
        ]
        assert acks[1].fill_price is not None
        # Not resting — was redirected to aggressive
        assert router.resting_order_count == 0

    def test_buy_below_ask_rests_as_passive(self):
        """BUY limit below the ask should rest normally."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        buy = _limit_buy("AAPL", qty=100, limit_price="150.00")
        router.submit(buy)
        acks = router.poll_acks()

        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.ACKNOWLEDGED
        assert router.resting_order_count == 1

    def test_sell_at_or_below_bid_fills_aggressively(self):
        """SELL limit at or below the bid should redirect to aggressive fill."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        # SELL limit at $150.00 — equal to bid → marketable
        sell = _limit_sell("AAPL", qty=100, limit_price="150.00")
        router.submit(sell)
        acks = router.poll_acks()

        assert [a.status for a in acks] == [
            OrderAckStatus.ACKNOWLEDGED,
            OrderAckStatus.FILLED,
        ]
        assert router.resting_order_count == 0

    def test_sell_above_bid_rests_as_passive(self):
        """SELL limit above the bid should rest normally."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        sell = _limit_sell("AAPL", qty=100, limit_price="150.02")
        router.submit(sell)
        acks = router.poll_acks()

        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.ACKNOWLEDGED
        assert router.resting_order_count == 1


class TestVolumeBasedQueueDrain:
    """Test D10: trade-volume-based queue-position fill model."""

    def _trade(self, symbol: str, price: str, size: int, ts: int = 6000) -> "Trade":
        from feelies.core.events import Trade

        return Trade(
            timestamp_ns=ts,
            exchange_timestamp_ns=ts,
            correlation_id=f"t-{ts}",
            sequence=99,
            symbol=symbol,
            price=Decimal(price),
            size=size,
        )

    def test_buy_fills_when_enough_volume_at_level(self):
        """BUY drain-fills once shares_traded_at_level >= queue_position_shares.

        Below the queue threshold the hazard is exactly 0 (deterministic
        no-fill); at the front it is the hazard cap, set to 1.0 here so the
        fill is guaranteed on the next at-level tick.
        """
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            cost_model=ZeroCostModel(),
            queue_position_shares=500,
            fill_delay_ticks=9999,
            fill_hazard_max=Decimal("1.0"),
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", qty=100))
        router.poll_acks()

        # 499 shares traded — not enough
        router.on_trade(self._trade("AAPL", "150.00", 499))
        clock.set_time(6001)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6001))
        assert router.poll_acks() == []

        # 1 more share → total 500 ≥ queue_position_shares → fill on next quote
        router.on_trade(self._trade("AAPL", "150.00", 1, ts=6002))
        clock.set_time(6003)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6003))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED

    def test_sell_fills_when_enough_volume_at_level(self):
        """SELL drain-fills once shares_traded_at_level >= queue_position_shares."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            cost_model=ZeroCostModel(),
            queue_position_shares=200,
            fill_delay_ticks=9999,
            fill_hazard_max=Decimal("1.0"),
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_sell("AAPL", qty=100))
        router.poll_acks()

        # Enough volume at the ask level
        router.on_trade(self._trade("AAPL", "150.02", 200))
        clock.set_time(6001)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6001))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED

    def test_trades_for_other_symbols_ignored(self):
        """Trade events for different symbols don't count toward our queue."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            cost_model=ZeroCostModel(),
            queue_position_shares=100,
            fill_delay_ticks=9999,
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", qty=100))
        router.poll_acks()

        # MSFT trade should not count toward AAPL order
        router.on_trade(self._trade("MSFT", "300.00", 500))
        clock.set_time(6001)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6001))
        assert router.poll_acks() == []

    def test_pre_eligibility_trade_does_not_count_toward_queue_drain(self):
        """Trades before exchange eligibility do not drain queue position."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            cost_model=ZeroCostModel(),
            latency_ns=2000,
            queue_position_shares=100,
            fill_delay_ticks=9999,
            fill_hazard_max=Decimal("1.0"),
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", qty=100))
        router.poll_acks()
        # ack_timestamp_ns = max(clock.now_ns()=5000, post-quote exchange_ts=1000)
        #                  + latency_ns=2000 = 7000 — order not live until then.

        # Pre-eligibility trade: prints at ts=6000 < ack_timestamp_ns=7000 and
        # alone would satisfy the 100-share queue threshold, but must not
        # count because the order wasn't resting at the exchange yet.
        router.on_trade(self._trade("AAPL", "150.00", 100, ts=6000))
        clock.set_time(7000)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=7000))
        assert router.poll_acks() == []

        # A trade of the same size *after* eligibility does count and fills.
        router.on_trade(self._trade("AAPL", "150.00", 100, ts=7001))
        clock.set_time(7002)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=7002))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED

    def test_volume_below_level_ignored_for_buy(self):
        """BUY: trades above our limit price don't count toward queue drain."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            cost_model=ZeroCostModel(),
            queue_position_shares=100,
            fill_delay_ticks=9999,
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", qty=100, limit_price="150.00"))
        router.poll_acks()

        # Trade at $150.01 — ABOVE our buy limit → doesn't count
        router.on_trade(self._trade("AAPL", "150.01", 200))
        clock.set_time(6001)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6001))
        assert router.poll_acks() == []

    def test_quote_imbalance_regime_when_queue_shares_zero(self):
        """With queue_position_shares=0 the hazard uses the quote-imbalance
        regime (no queue threshold): each at-level tick is a seeded Bernoulli
        trial against h = h0 * aggression.  At a balanced book h = h0 = 0.5,
        so the order fills at some tick (deterministically, per the seed)
        rather than after a fixed counter.  We loop until the seeded fill
        lands and assert it is a drain fill at the limit price.
        """
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            cost_model=ZeroCostModel(),
            fill_delay_ticks=2,
            queue_position_shares=0,
            max_resting_ticks=1000,
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", qty=100))
        router.poll_acks()

        fill_ack = None
        for i in range(40):
            ts = 6000 + i * 1000
            clock.set_time(ts)
            router.on_quote(_quote("AAPL", "150.00", "150.02", ts=ts))
            acks = router.poll_acks()
            if acks:
                assert len(acks) == 1
                fill_ack = acks[0]
                break

        assert fill_ack is not None, "balanced-book order should fill within 40 ticks"
        assert fill_ack.status == OrderAckStatus.FILLED
        assert fill_ack.fill_price == Decimal("150.00")
        assert fill_ack.reason == "FILLED_BY_DRAIN"

    def test_shares_traded_at_level_resets_on_price_away_buy(self):
        """Reset accumulated buy volume when the BBO leaves the limit price."""
        from feelies.core.events import Trade

        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            cost_model=ZeroCostModel(),
            queue_position_shares=200,
            fill_delay_ticks=9999,
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", qty=100, limit_price="150.00"))
        router.poll_acks()

        # Accumulate 190 shares — not enough to fill yet
        router.on_trade(
            Trade(
                timestamp_ns=5100,
                exchange_timestamp_ns=5100,
                correlation_id="t1",
                sequence=2,
                symbol="AAPL",
                price=Decimal("150.00"),
                size=190,
            )
        )

        # BBO moves up — bid is now above our limit, so we're off the level
        clock.set_time(5200)
        router.on_quote(_quote("AAPL", "150.05", "150.07", ts=5200))
        assert router.poll_acks() == []  # no fill yet

        # BBO returns to level — shares_traded_at_level must be 0 (was reset)
        # So 50 new shares should not be enough to fill (need 200)
        router.on_trade(
            Trade(
                timestamp_ns=5300,
                exchange_timestamp_ns=5300,
                correlation_id="t2",
                sequence=3,
                symbol="AAPL",
                price=Decimal("150.00"),
                size=50,
            )
        )
        clock.set_time(5400)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=5400))
        assert router.poll_acks() == []  # 50 < 200, must not fill

    def test_shares_traded_at_level_resets_on_price_away_sell(self):
        """F6: SELL — accumulated volume resets when BBO moves away from limit price."""
        from feelies.core.events import Trade

        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            cost_model=ZeroCostModel(),
            queue_position_shares=200,
            fill_delay_ticks=9999,
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_sell("AAPL", qty=100, limit_price="150.02"))
        router.poll_acks()

        # Accumulate 190 shares at the ask level
        router.on_trade(
            Trade(
                timestamp_ns=5100,
                exchange_timestamp_ns=5100,
                correlation_id="t1",
                sequence=2,
                symbol="AAPL",
                price=Decimal("150.02"),
                size=190,
            )
        )

        # BBO moves down — ask is now below our limit, we lose queue position
        clock.set_time(5200)
        router.on_quote(_quote("AAPL", "149.95", "149.97", ts=5200))
        assert router.poll_acks() == []

        # BBO returns — accumulated volume was reset, 50 new shares not enough
        router.on_trade(
            Trade(
                timestamp_ns=5300,
                exchange_timestamp_ns=5300,
                correlation_id="t2",
                sequence=3,
                symbol="AAPL",
                price=Decimal("150.02"),
                size=50,
            )
        )
        clock.set_time(5400)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=5400))
        assert router.poll_acks() == []  # 50 < 200, must not fill


class TestMultipleOrders:
    """Test multiple resting orders and symbol isolation."""

    def test_different_symbols_independent(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.on_quote(_quote("MSFT", "300.00", "300.04"))

        router.submit(_limit_buy("AAPL", order_id="aapl1"))
        router.submit(_limit_buy("MSFT", order_id="msft1"))
        router.poll_acks()

        assert router.resting_order_count == 2
        assert router.resting_symbols() == frozenset({"AAPL", "MSFT"})

        # Only AAPL gets a through fill
        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "149.98", "150.00", ts=6000))

        acks = router.poll_acks()
        filled = [a for a in acks if a.status == OrderAckStatus.FILLED]
        assert len(filled) == 1
        assert filled[0].symbol == "AAPL"
        assert router.resting_order_count == 1

    def test_same_symbol_fills_follow_submission_order(self):
        clock = SimulatedClock(start_ns=5000)
        # h_max=1.0 + fill_delay_ticks=1 forces both orders to drain-fill on
        # the first at-level tick, so the only ordering signal is the
        # insertion (submission) order the router iterates in.
        router = PassiveLimitOrderRouter(
            clock,
            cost_model=ZeroCostModel(),
            fill_delay_ticks=1,
            fill_hazard_max=Decimal("1.0"),
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", order_id="aapl_first"))
        router.submit(_limit_buy("AAPL", order_id="aapl_second"))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6000))

        acks = router.poll_acks()
        filled_ids = [ack.order_id for ack in acks if ack.status == OrderAckStatus.FILLED]

        assert filled_ids == ["aapl_first", "aapl_second"]

    def test_poll_acks_clears_queue(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel())

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_market_order("AAPL"))

        first = router.poll_acks()
        assert len(first) == 2

        second = router.poll_acks()
        assert second == []


class TestLatency:
    """Test fill timestamp latency injection."""

    def test_passive_fill_latency(self):
        """A resting limit becomes fill-eligible only after exchange latency.

        A fill on the eligible quote is stamped at that quote, with no
        second latency leg.
        """

        def scenario() -> bool | None:
            clock = SimulatedClock(start_ns=5000)
            router = PassiveLimitOrderRouter(
                clock,
                cost_model=ZeroCostModel(),
                latency_ns=2000,
                fill_delay_ticks=1,
            )
            router.on_quote(_quote("AAPL", "150.00", "150.02"))
            router.submit(_limit_buy("AAPL"))
            router.poll_acks()
            clock.set_time(6000)
            router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6000))
            if router.poll_acks():
                return False
            clock.set_time(7000)
            router.on_quote(_quote("AAPL", "150.00", "150.02", ts=7000))
            filled = [ack for ack in router.poll_acks() if ack.status == OrderAckStatus.FILLED]
            if not filled:
                return None
            return filled[0].timestamp_ns == 7000

        _assert_over_salts(scenario)

    def test_market_fill_latency(self):
        """Defer market fills until a quote reaches the latency deadline.

        Original pin: the ACK stamp was submit clock plus latency. T2
        publishes that ACK at the clock. Eligibility stays 6000.
        """
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), latency_ns=1000)

        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=1000))
        router.submit(_market_order("AAPL"))

        acks = router.poll_acks()
        assert acks[0].status == OrderAckStatus.ACKNOWLEDGED
        assert acks[0].timestamp_ns == 5000
        assert router._deferred_aggressive[0].ack_timestamp_ns == 6000

        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=5500))
        assert router.poll_acks() == []

        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6500))
        acks2 = router.poll_acks()
        assert acks2[0].status == OrderAckStatus.FILLED
        # Deferred FILLED uses max(ack_ts, clock.now_ns()) after the first
        # quote whose exchange timestamp reaches submit-time eligibility.
        assert acks2[0].timestamp_ns == 6000

    def test_deferred_aggressive_fill_ts_no_double_latency_when_clock_tracks_exchange(
        self,
    ) -> None:
        """ReplayFeed advances clock to each quote — FILLED must not add latency twice.

        Original pin: the ACK stamp was 2000. T2 publishes it at the
        clock (1000). Eligibility stays 2000.
        """
        clock = SimulatedClock(start_ns=1000)
        router = PassiveLimitOrderRouter(clock, latency_ns=1000)

        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=1000))
        router.submit(_market_order("AAPL"))
        assert router.poll_acks()[0].timestamp_ns == 1000
        assert router._deferred_aggressive[0].ack_timestamp_ns == 2000

        clock.set_time(2500)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=2500))
        fill = router.poll_acks()[0]
        assert fill.status == OrderAckStatus.FILLED
        assert fill.timestamp_ns == 2500

    def test_deferred_market_rejects_zero_depth_at_fill_quote(self):
        """Zero displayed depth rejects the arrival quote, not the flush quote.

        Original intent: a deferred market fill requires L1 depth, matching
        the backtest router. R2-1 checks that depth on the quote prevailing
        at arrival. Here that quote is the submit quote, which has size, so
        the empty flush quote still fills at 150.02.
        """
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, latency_ns=1000)

        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=1000))
        router.submit(_market_order("AAPL"))
        router.poll_acks()

        router.on_quote(
            _quote(
                "AAPL",
                "150.00",
                "150.02",
                ts=6500,
                bid_size=100,
                ask_size=0,
            )
        )
        acks2 = router.poll_acks()
        fills = [ack for ack in acks2 if ack.status == OrderAckStatus.FILLED]
        assert len(fills) == 1
        assert fills[0].fill_price == Decimal("150.02")

    def test_deferred_market_partial_fill_walk_the_book(self) -> None:
        """D14 parity with BacktestOrderRouter: excess qty pays walk-the-book impact."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            latency_ns=1000,
            market_impact_factor=Decimal("0.5"),
        )

        router.on_quote(
            _quote(
                "AAPL",
                "99.00",
                "101.00",
                ts=1000,
                bid_size=100,
                ask_size=50,
            )
        )
        large_buy = OrderRequest(
            timestamp_ns=2000,
            correlation_id="o1",
            sequence=2,
            order_id="big-mkt",
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=150,
        )
        router.submit(large_buy)
        assert [a.status for a in router.poll_acks()] == [
            OrderAckStatus.ACKNOWLEDGED,
        ]

        router.on_quote(
            _quote(
                "AAPL",
                "99.00",
                "101.00",
                ts=6500,
                bid_size=100,
                ask_size=50,
            )
        )
        acks = router.poll_acks()
        assert [a.status for a in acks] == [
            OrderAckStatus.PARTIALLY_FILLED,
            OrderAckStatus.FILLED,
        ]
        # The L1 leg crosses at ask=101; the excess walks
        # the book above the cross.
        cross = Decimal("101")
        half_spread = Decimal("1")
        assert acks[0].filled_quantity == 50
        assert acks[0].fill_price == cross
        expected_impact = Decimal("0.5") * (Decimal("100") / Decimal("50")) * half_spread
        assert acks[1].filled_quantity == 100
        assert acks[1].fill_price == cross + expected_impact

    def test_marketable_limit_walk_the_book_caps_excess_at_limit_price(self) -> None:
        """Aggressive LIMIT fills cannot execute the excess leg above ``limit_price``."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            latency_ns=0,
            market_impact_factor=Decimal("0.5"),
        )

        router.on_quote(
            _quote(
                "AAPL",
                "100.00",
                "100.50",
                bid_size=500,
                ask_size=50,
            )
        )
        lim = Decimal("100.50")
        router.submit(_limit_buy("AAPL", qty=550, limit_price="100.50"))

        acks = router.poll_acks()
        assert [a.status for a in acks] == [
            OrderAckStatus.ACKNOWLEDGED,
            OrderAckStatus.PARTIALLY_FILLED,
            OrderAckStatus.FILLED,
        ]
        # The L1 leg crosses at ask=100.50, which equals
        # the limit here; the excess would walk above the limit but is
        # capped at it.
        assert acks[1].fill_price == lim
        assert acks[1].filled_quantity == 50
        assert acks[2].filled_quantity == 500
        assert acks[2].fill_price == lim

    def test_deferred_market_queues_despite_zero_depth_on_submit_quote(self):
        """A vacuum submit quote still queues, and it is the arrival book.

        Original intent: zero depth at submit does not reject before the
        latency window. R2-1 then prices and depth-checks the quote
        prevailing at arrival. With no later quote inside the window, that
        is the empty submit quote, so the fill is rejected.
        """
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, latency_ns=1000)

        router.on_quote(
            _quote(
                "AAPL",
                "150.00",
                "150.02",
                ts=1000,
                bid_size=100,
                ask_size=0,
            )
        )
        router.submit(_market_order("AAPL"))
        acks = router.poll_acks()
        assert [a.status for a in acks] == [OrderAckStatus.ACKNOWLEDGED]

        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6500))
        acks2 = router.poll_acks()
        assert len(acks2) == 1
        assert acks2[0].status == OrderAckStatus.REJECTED
        assert "depth" in acks2[0].reason.lower()

    def test_deferred_marketable_limit_rejects_when_mid_exceeds_limit_after_latency(
        self,
    ) -> None:
        """A marketable limit's mid check uses the arrival quote.

        Original intent: a deferred marketable limit must not fill once the
        mid has traded through the limit. R2-1 reads that mid from the quote
        prevailing at arrival. The submit quote's mid is still inside 150.02,
        so the flush quote at 151 does not reject; the fill is 150.02.
        """
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, latency_ns=1000)

        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=1000))
        router.submit(_limit_buy("AAPL", limit_price="150.02"))
        assert [a.status for a in router.poll_acks()] == [
            OrderAckStatus.ACKNOWLEDGED,
        ]

        router.on_quote(_quote("AAPL", "151.00", "151.02", ts=6500))
        fills = [ack for ack in router.poll_acks() if ack.status == OrderAckStatus.FILLED]
        assert len(fills) == 1
        assert fills[0].fill_price == Decimal("150.02")

    def test_marketable_limit_same_order_id_retry_after_deferred_reject(
        self,
    ) -> None:
        """The old deferred mid-reject released the order id for a retry.

        Original intent: a REJECTED deferred marketable limit frees
        ``order_id`` so the same id can be submitted again. R2-1 checks the
        mid on the arrival quote, which is still inside the limit, so this
        order fills at 150.02 and there is no reject to retry.
        """
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, latency_ns=1000)
        oid = "marketable-limit-retry"

        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=1000))
        router.submit(_limit_buy("AAPL", limit_price="150.02", order_id=oid))
        assert [a.status for a in router.poll_acks()] == [
            OrderAckStatus.ACKNOWLEDGED,
        ]

        router.on_quote(_quote("AAPL", "151.00", "151.02", ts=6500))
        fills = [ack for ack in router.poll_acks() if ack.status == OrderAckStatus.FILLED]
        assert len(fills) == 1
        assert fills[0].fill_price == Decimal("150.02")

    def test_duplicate_still_rejected_when_passive_limit_resting(self) -> None:
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock)
        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", limit_price="150.00"))
        router.poll_acks()

        router.submit(_limit_buy("AAPL", limit_price="150.00"))
        dup = router.poll_acks()
        assert len(dup) == 1
        assert dup[0].status == OrderAckStatus.REJECTED
        assert "duplicate" in dup[0].reason.lower()

    def test_deferred_aggressive_rejects_after_max_ticks_without_eligible_exchange_time(
        self,
    ) -> None:
        """Stale exchange timestamps never reach latency deadline → timeout."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            latency_ns=1000,
            fill_delay_ticks=1,
            max_resting_ticks=3,
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=1000))
        router.submit(_market_order("AAPL"))
        acks0 = router.poll_acks()
        assert [a.status for a in acks0] == [OrderAckStatus.ACKNOWLEDGED]
        ack_ts = acks0[0].timestamp_ns

        for _ in range(3):
            router.on_quote(_quote("AAPL", "150.00", "150.02", ts=1000))

        rejects = [a for a in router.poll_acks() if a.status == OrderAckStatus.REJECTED]
        assert len(rejects) == 1
        assert "timeout" in rejects[0].reason.lower()
        assert "ticks" in rejects[0].reason.lower()
        assert rejects[0].timestamp_ns >= ack_ts

    def test_deferred_aggressive_timeout_reject_ts_not_before_ack_when_clock_tracks_exchange(
        self,
    ) -> None:
        """max_resting_ticks fires before latency deadline: REJECTED must not precede ACK.

        Original pin: the ACK stamp was 2000. T2 publishes it at the
        clock (1000). Eligibility stays 2000.
        """
        clock = SimulatedClock(start_ns=1000)
        router = PassiveLimitOrderRouter(
            clock,
            latency_ns=1000,
            fill_delay_ticks=1,
            max_resting_ticks=3,
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=1000))
        router.submit(_market_order("AAPL"))
        ack = router.poll_acks()[0]
        assert ack.status == OrderAckStatus.ACKNOWLEDGED
        assert ack.timestamp_ns == 1000
        assert router._deferred_aggressive[0].ack_timestamp_ns == 2000

        for _ in range(3):
            clock.set_time(1500)
            router.on_quote(_quote("AAPL", "150.00", "150.02", ts=1500))

        rej = router.poll_acks()[0]
        assert rej.status == OrderAckStatus.REJECTED
        assert rej.timestamp_ns >= ack.timestamp_ns

    def test_immediate_market_rejects_zero_depth(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, latency_ns=0)

        router.on_quote(
            _quote(
                "AAPL",
                "150.00",
                "150.02",
                bid_size=100,
                ask_size=0,
            )
        )
        router.submit(_market_order("AAPL"))
        acks = router.poll_acks()
        assert [a.status for a in acks] == [
            OrderAckStatus.ACKNOWLEDGED,
            OrderAckStatus.REJECTED,
        ]
        reject = acks[1]
        assert "depth" in reject.reason.lower()


class TestDeterminism:
    """Verify deterministic replay (invariant 5)."""

    def test_identical_inputs_produce_identical_outputs(self):
        """Two runs with same inputs produce same fills."""
        results = []
        for _ in range(2):
            clock = SimulatedClock(start_ns=5000)
            router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel(), fill_delay_ticks=2)

            router.on_quote(_quote("AAPL", "150.00", "150.02"))
            router.submit(_limit_buy("AAPL"))
            router.poll_acks()

            clock.set_time(6000)
            router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6000))
            router.poll_acks()

            clock.set_time(7000)
            router.on_quote(_quote("AAPL", "150.00", "150.02", ts=7000))
            acks = router.poll_acks()

            results.append(acks)

        assert len(results[0]) == len(results[1])
        for a, b in zip(results[0], results[1]):
            assert a.status == b.status
            assert a.fill_price == b.fill_price
            assert a.filled_quantity == b.filled_quantity
            assert a.fees == b.fees
            assert a.timestamp_ns == b.timestamp_ns

    def test_probabilistic_drain_fill_tick_is_deterministic(self):
        """A sub-certain hazard (balanced book, h=0.5) fills at the *same*
        seeded tick across two runs — the Bernoulli trial is reproducible.
        """
        fill_ticks = []
        for _ in range(2):
            clock = SimulatedClock(start_ns=5000)
            router = PassiveLimitOrderRouter(
                clock,
                fill_delay_ticks=2,
                max_resting_ticks=1000,
            )
            router.on_quote(_quote("AAPL", "150.00", "150.02"))
            router.submit(_limit_buy("AAPL"))
            router.poll_acks()
            tick = None
            for i in range(100):
                ts = 6000 + i * 1000
                clock.set_time(ts)
                router.on_quote(_quote("AAPL", "150.00", "150.02", ts=ts))
                if router.poll_acks():
                    tick = i
                    break
            fill_ticks.append(tick)

        assert fill_ticks[0] is not None
        assert fill_ticks[0] == fill_ticks[1]


class TestPassiveFillOutcomes:
    """Classify passive fills and aggregate their statistics."""

    def _trade(self, symbol: str, price: str, size: int, ts: int) -> "Trade":
        from feelies.core.events import Trade

        return Trade(
            timestamp_ns=ts,
            exchange_timestamp_ns=ts,
            correlation_id=f"t-{ts}",
            sequence=99,
            symbol=symbol,
            price=Decimal(price),
            size=size,
        )

    def test_empty_stats(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock)
        stats = router.passive_fill_stats()
        assert stats["filled"] == 0
        assert stats["cancelled"] == 0
        assert stats["passive_fill_rate"] == 0.0
        assert stats["mean_resting_ticks_to_fill"] == 0.0

    def test_through_fill_outcome_and_stats(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", limit_price="150.00"))
        router.poll_acks()

        # Ask gaps through our limit → through fill.
        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "149.98", "149.99", ts=6000))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].reason == "FILLED_BY_THROUGH"
        assert acks[0].fill_price == Decimal("149.99")

        stats = router.passive_fill_stats()
        assert stats["fills_by_through"] == 1
        assert stats["fills_by_drain"] == 0
        assert stats["passive_fill_rate"] == 1.0
        assert stats["mean_resting_ticks_to_fill"] == 1.0

    def test_drain_fill_outcome_and_stats(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            fill_delay_ticks=1,
            fill_hazard_max=Decimal("1.0"),
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL"))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6000))
        acks = router.poll_acks()
        assert acks[0].reason == "FILLED_BY_DRAIN"

        stats = router.passive_fill_stats()
        assert stats["fills_by_drain"] == 1
        assert stats["fills_by_through"] == 0
        assert stats["passive_fill_rate"] == 1.0

    def test_cancel_max_resting_ticks_outcome(self):
        """At the level but hazard 0 (never drains) → timeout while still
        competitive → CANCELLED_MAX_RESTING_TICKS / EXPIRED ack.
        """
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock,
            max_resting_ticks=3,
            fill_hazard_max=Decimal("0"),
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", limit_price="150.00"))
        router.poll_acks()

        acks: list = []
        for i in range(3):
            ts = 6000 + i * 1000
            clock.set_time(ts)
            router.on_quote(_quote("AAPL", "150.00", "150.02", ts=ts))
            acks = router.poll_acks()

        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.EXPIRED
        assert acks[0].reason.startswith("CANCELLED_MAX_RESTING_TICKS")

        stats = router.passive_fill_stats()
        assert stats["cancels_max_resting_ticks"] == 1
        assert stats["cancels_level_left_bbo"] == 0
        assert stats["passive_fill_rate"] == 0.0

    def test_cancel_level_left_bbo_outcome(self):
        """Off the BBO (behind the market) at timeout → CANCELLED_LEVEL_LEFT_BBO / EXPIRED ack."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, max_resting_ticks=3)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", limit_price="150.00"))
        router.poll_acks()

        acks: list = []
        for i in range(3):
            ts = 6000 + i * 1000
            clock.set_time(ts)
            # bid above our limit → off level, ask above → no through fill
            router.on_quote(_quote("AAPL", "150.01", "150.03", ts=ts))
            acks = router.poll_acks()

        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.EXPIRED
        assert acks[0].reason.startswith("CANCELLED_LEVEL_LEFT_BBO")

        stats = router.passive_fill_stats()
        assert stats["cancels_level_left_bbo"] == 1
        assert stats["cancels_max_resting_ticks"] == 0
