"""Cross-router parity tests.

Both BacktestOrderRouter and PassiveLimitOrderRouter share a single
aggressive-fill helper.  For an equivalent MARKET order against the
same quote, both routers must produce identical fill economics
(price, quantity, fees, cost_bps).
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
from feelies.execution.cost_model import DefaultCostModel, DefaultCostModelConfig
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter

pytestmark = pytest.mark.backtest_validation


def _quote(symbol: str = "AAPL", *, bid_size: int = 50, ask_size: int = 50) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=1000,
        correlation_id="q",
        sequence=1,
        symbol=symbol,
        bid=Decimal("99.00"),
        ask=Decimal("101.00"),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=1000,
    )


def _market_order(qty: int, order_id: str = "o1") -> OrderRequest:
    return OrderRequest(
        timestamp_ns=500,
        correlation_id="c",
        sequence=1,
        order_id=order_id,
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=qty,
    )


def _fills_only(acks):
    return [
        a
        for a in acks
        if a.status
        in (
            OrderAckStatus.PARTIALLY_FILLED,
            OrderAckStatus.FILLED,
        )
    ]


class TestAggressiveFillParity:
    def test_full_l1_fill_parity(self) -> None:
        cfg = DefaultCostModelConfig()
        clock_a = SimulatedClock(start_ns=0)
        clock_b = SimulatedClock(start_ns=0)
        a = BacktestOrderRouter(clock_a, cost_model=DefaultCostModel(cfg))
        b = PassiveLimitOrderRouter(clock_b, cost_model=DefaultCostModel(cfg))
        a.on_quote(_quote(ask_size=100))
        b.on_quote(_quote(ask_size=100))
        a.submit(_market_order(50))
        b.submit(_market_order(50))
        fa = _fills_only(a.poll_acks())
        fb = _fills_only(b.poll_acks())
        assert len(fa) == len(fb) == 1
        assert fa[0].fill_price == fb[0].fill_price
        assert fa[0].filled_quantity == fb[0].filled_quantity
        assert fa[0].fees == fb[0].fees

    def test_walk_the_book_parity(self) -> None:
        """Passive aggressive fallback walks the book just
        like BacktestOrderRouter for orders > L1 depth."""
        cfg = DefaultCostModelConfig()
        clock_a = SimulatedClock(start_ns=0)
        clock_b = SimulatedClock(start_ns=0)
        a = BacktestOrderRouter(
            clock_a,
            cost_model=DefaultCostModel(cfg),
            market_impact_factor=Decimal("0.5"),
        )
        b = PassiveLimitOrderRouter(
            clock_b,
            cost_model=DefaultCostModel(cfg),
            market_impact_factor=Decimal("0.5"),
        )
        a.on_quote(_quote(ask_size=50))
        b.on_quote(_quote(ask_size=50))
        # 200 shares vs 50 L1 depth → 150 excess walks the book.
        a.submit(_market_order(200))
        b.submit(_market_order(200))
        fa = _fills_only(a.poll_acks())
        fb = _fills_only(b.poll_acks())
        assert len(fa) == len(fb) == 2
        assert fa[0].filled_quantity == fb[0].filled_quantity
        assert fa[0].fill_price == fb[0].fill_price
        assert fa[0].fees == fb[0].fees
        assert fa[1].filled_quantity == fb[1].filled_quantity
        assert fa[1].fill_price == fb[1].fill_price
        assert fa[1].fees == fb[1].fees

    def test_zero_depth_rejection_parity(self) -> None:
        cfg = DefaultCostModelConfig()
        clock_a = SimulatedClock(start_ns=0)
        clock_b = SimulatedClock(start_ns=0)
        a = BacktestOrderRouter(clock_a, cost_model=DefaultCostModel(cfg))
        b = PassiveLimitOrderRouter(clock_b, cost_model=DefaultCostModel(cfg))
        a.on_quote(_quote(ask_size=0))
        b.on_quote(_quote(ask_size=0))
        a.submit(_market_order(100))
        b.submit(_market_order(100))
        rejects_a = [x for x in a.poll_acks() if x.status == OrderAckStatus.REJECTED]
        rejects_b = [x for x in b.poll_acks() if x.status == OrderAckStatus.REJECTED]
        assert len(rejects_a) == 1
        assert len(rejects_b) == 1
