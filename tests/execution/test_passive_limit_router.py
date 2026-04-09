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
from feelies.execution.cost_model import DefaultCostModel, DefaultCostModelConfig
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

    def test_market_order_fills_at_mid(self):
        """MARKET orders still fill immediately at mid-price."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock)

        router.on_quote(_quote("AAPL", "149.00", "151.00"))
        router.submit(_market_order("AAPL"))

        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].fill_price == Decimal("150.00")
        assert acks[0].filled_quantity == 50

    def test_reject_on_missing_quote(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock)

        router.submit(_limit_buy("MSFT"))

        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.REJECTED
        assert "no quote" in acks[0].reason.lower()

    def test_limit_order_acknowledged_not_filled(self):
        """LIMIT orders emit ACKNOWLEDGED on submit, not FILLED."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, fill_delay_ticks=5)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL"))

        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.ACKNOWLEDGED
        assert acks[0].fill_price is None
        assert acks[0].filled_quantity == 0
        assert router.resting_order_count == 1

    def test_limit_price_defaults_to_bid_for_buy(self):
        """BUY limit defaults to bid when no explicit price given."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL"))
        router.poll_acks()

        assert router.resting_order_count == 1
        assert "AAPL" in router.resting_symbols()

    def test_limit_price_defaults_to_ask_for_sell(self):
        """SELL limit defaults to ask when no explicit price given."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_sell("AAPL"))
        router.poll_acks()

        assert router.resting_order_count == 1


class TestThroughFill:
    """Test the through-fill condition: opposite BBO crosses our level."""

    def test_buy_fills_when_ask_drops_to_limit(self):
        """BUY limit fills when ask <= limit_price (through fill)."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, fill_delay_ticks=100)

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
        """BUY limit fills when ask < limit_price (price through)."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL"))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "149.95", "149.98", ts=6000))
        acks = router.poll_acks()

        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].fill_price == Decimal("150.00")

    def test_sell_fills_when_bid_rises_to_limit(self):
        """SELL limit fills when bid >= limit_price (through fill)."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, fill_delay_ticks=100)

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
        """SELL limit fills when bid > limit_price (price through)."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, fill_delay_ticks=100)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_sell("AAPL"))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "150.05", "150.07", ts=6000))
        acks = router.poll_acks()

        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].fill_price == Decimal("150.02")


class TestLevelFill:
    """Test the level-fill condition: N ticks at our level."""

    def test_buy_fills_after_delay_ticks_at_level(self):
        """BUY limit fills after fill_delay_ticks at bid level."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, fill_delay_ticks=3)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL"))
        router.poll_acks()

        # Tick 1: bid at our level — ticks_at_level = 1
        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6000))
        assert router.poll_acks() == []

        # Tick 2: bid at our level — ticks_at_level = 2
        clock.set_time(7000)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=7000))
        assert router.poll_acks() == []

        # Tick 3: bid at our level — ticks_at_level = 3 → FILL
        clock.set_time(8000)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=8000))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].fill_price == Decimal("150.00")

    def test_sell_fills_after_delay_ticks_at_level(self):
        """SELL limit fills after fill_delay_ticks at ask level."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, fill_delay_ticks=2)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_sell("AAPL"))
        router.poll_acks()

        # Tick 1
        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6000))
        assert router.poll_acks() == []

        # Tick 2 → FILL
        clock.set_time(7000)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=7000))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED
        assert acks[0].fill_price == Decimal("150.02")

    def test_level_counter_resets_when_price_moves_away(self):
        """ticks_at_level resets if price moves away from our level."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, fill_delay_ticks=3)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL"))
        router.poll_acks()

        # 2 ticks at level
        for i in range(2):
            clock.set_time(6000 + i * 1000)
            router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6000 + i * 1000))
            router.poll_acks()

        # Price moves up — our level no longer at BBO → reset
        clock.set_time(8000)
        router.on_quote(_quote("AAPL", "150.01", "150.03", ts=8000))
        router.poll_acks()

        # 2 more ticks at level (should NOT fill — counter was reset)
        for i in range(2):
            clock.set_time(9000 + i * 1000)
            router.on_quote(_quote("AAPL", "150.00", "150.02", ts=9000 + i * 1000))
            assert router.poll_acks() == []

        # 3rd tick at level after reset → FILL
        clock.set_time(11000)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=11000))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED

    def test_buy_fills_when_bid_below_limit(self):
        """BUY at $150.00: if bid drops to $149.99 we're still at level."""
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, fill_delay_ticks=2)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL", limit_price="150.00"))
        router.poll_acks()

        # bid < limit → bid <= limit_price is True → tick counts
        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "149.99", "150.01", ts=6000))
        assert router.poll_acks() == []

        clock.set_time(7000)
        router.on_quote(_quote("AAPL", "149.99", "150.01", ts=7000))
        acks = router.poll_acks()
        assert len(acks) == 1
        assert acks[0].status == OrderAckStatus.FILLED


class TestTimeout:
    """Test order cancellation after max_resting_ticks."""

    def test_limit_cancelled_after_timeout(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock, fill_delay_ticks=100, max_resting_ticks=5,
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
        assert acks[0].status == OrderAckStatus.CANCELLED
        assert "timeout" in acks[0].reason.lower()
        assert router.resting_order_count == 0


class TestCostModel:
    """Test cost calculation for passive vs aggressive fills."""

    def test_passive_fill_zero_spread_cost(self):
        """Passive fills charge zero spread cost."""
        clock = SimulatedClock(start_ns=5000)
        cost_model = DefaultCostModel(DefaultCostModelConfig())
        router = PassiveLimitOrderRouter(
            clock, cost_model=cost_model,
            fill_delay_ticks=1, rebate_per_share=Decimal("0"),
        )

        router.on_quote(_quote("AAPL", "150.00", "150.10"))
        router.submit(_limit_buy("AAPL", qty=100))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "150.00", "150.10", ts=6000))
        acks = router.poll_acks()

        assert len(acks) == 1
        fill = acks[0]
        assert fill.status == OrderAckStatus.FILLED
        # No spread cost — only commission
        assert fill.fees < Decimal("1.00")

    def test_aggressive_fill_charges_spread(self):
        """MARKET fills charge full spread cost."""
        clock = SimulatedClock(start_ns=5000)
        cost_model = DefaultCostModel(DefaultCostModelConfig())
        router = PassiveLimitOrderRouter(clock, cost_model=cost_model)

        router.on_quote(_quote("AAPL", "150.00", "150.10"))
        router.submit(_market_order("AAPL"))

        acks = router.poll_acks()
        fill = acks[0]
        assert fill.status == OrderAckStatus.FILLED
        # Spread cost = 0.05 * 50 = $2.50 + commission
        assert fill.fees > Decimal("2.00")

    def test_rebate_reduces_passive_fees(self):
        """Maker rebate reduces total fees on passive fills."""
        clock = SimulatedClock(start_ns=5000)
        cost_model = DefaultCostModel(DefaultCostModelConfig())

        router_no_rebate = PassiveLimitOrderRouter(
            clock, cost_model=cost_model,
            fill_delay_ticks=1, rebate_per_share=Decimal("0"),
        )
        router_with_rebate = PassiveLimitOrderRouter(
            SimulatedClock(start_ns=5000), cost_model=cost_model,
            fill_delay_ticks=1, rebate_per_share=Decimal("0.002"),
        )

        for r in [router_no_rebate, router_with_rebate]:
            r.on_quote(_quote("AAPL", "150.00", "150.02"))
            r.submit(_limit_buy("AAPL", qty=100))
            r.poll_acks()
            r._clock.set_time(6000)  # type: ignore[union-attr]
            r.on_quote(_quote("AAPL", "150.00", "150.02", ts=6000))

        fees_no = router_no_rebate.poll_acks()[0].fees
        fees_with = router_with_rebate.poll_acks()[0].fees
        assert fees_with < fees_no


class TestMultipleOrders:
    """Test multiple resting orders and symbol isolation."""

    def test_different_symbols_independent(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, fill_delay_ticks=100)

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

    def test_poll_acks_clears_queue(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_market_order("AAPL"))

        first = router.poll_acks()
        assert len(first) == 1

        second = router.poll_acks()
        assert second == []


class TestLatency:
    """Test fill timestamp latency injection."""

    def test_passive_fill_latency(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(
            clock, latency_ns=2000, fill_delay_ticks=1,
        )

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_limit_buy("AAPL"))
        router.poll_acks()

        clock.set_time(6000)
        router.on_quote(_quote("AAPL", "150.00", "150.02", ts=6000))

        acks = router.poll_acks()
        assert acks[0].timestamp_ns == 8000  # 6000 + 2000

    def test_market_fill_latency(self):
        clock = SimulatedClock(start_ns=5000)
        router = PassiveLimitOrderRouter(clock, latency_ns=1000)

        router.on_quote(_quote("AAPL", "150.00", "150.02"))
        router.submit(_market_order("AAPL"))

        acks = router.poll_acks()
        assert acks[0].timestamp_ns == 6000  # 5000 + 1000


class TestDeterminism:
    """Verify deterministic replay (invariant 5)."""

    def test_identical_inputs_produce_identical_outputs(self):
        """Two runs with same inputs produce same fills."""
        results = []
        for _ in range(2):
            clock = SimulatedClock(start_ns=5000)
            router = PassiveLimitOrderRouter(clock, fill_delay_ticks=2)

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
