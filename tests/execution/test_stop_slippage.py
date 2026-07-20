"""Tests for forced-exit panic slippage.

Stop / hazard / forced-flatten orders fill in depleted depth and
widened spread.  The cost model alone (using quoted half_spread)
under-charges this; the routers now inflate the spread component
when ``request.reason`` indicates a forced exit.
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


def _quote() -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=1000,
        correlation_id="q",
        sequence=1,
        symbol="AAPL",
        bid=Decimal("100.00"),
        ask=Decimal("100.10"),
        bid_size=500,
        ask_size=500,
        exchange_timestamp_ns=1000,
    )


def _order(reason: str = "") -> OrderRequest:
    return OrderRequest(
        timestamp_ns=0,
        correlation_id="c",
        sequence=1,
        order_id="o1",
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.MARKET,
        quantity=100,
        reason=reason,
    )


class TestStopSlippageBacktestRouter:
    def test_stop_exit_pays_more_than_normal_market(self) -> None:
        cfg = DefaultCostModelConfig(
            sell_regulatory_bps=Decimal("0"),
            finra_taf_per_share=Decimal("0"),
        )
        normal = BacktestOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=DefaultCostModel(cfg),
            stop_slippage_half_spreads=Decimal("2.0"),
        )
        stop = BacktestOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=DefaultCostModel(cfg),
            stop_slippage_half_spreads=Decimal("2.0"),
        )
        normal.on_quote(_quote())
        stop.on_quote(_quote())
        normal.submit(_order(reason=""))
        stop.submit(
            OrderRequest(
                timestamp_ns=0,
                correlation_id="c",
                sequence=2,
                order_id="o2",
                symbol="AAPL",
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=100,
                reason="STOP_EXIT",
            )
        )
        n_fills = [a for a in normal.poll_acks() if a.status == OrderAckStatus.FILLED]
        s_fills = [a for a in stop.poll_acks() if a.status == OrderAckStatus.FILLED]
        assert s_fills[0].fees > n_fills[0].fees

    def test_stop_slippage_multiplier_one_disables(self) -> None:
        """Multiplier of 1.0 means no panic slippage."""
        cfg = DefaultCostModelConfig(
            sell_regulatory_bps=Decimal("0"),
            finra_taf_per_share=Decimal("0"),
        )
        normal = BacktestOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=DefaultCostModel(cfg),
            stop_slippage_half_spreads=Decimal("1.0"),
        )
        stop = BacktestOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=DefaultCostModel(cfg),
            stop_slippage_half_spreads=Decimal("1.0"),
        )
        normal.on_quote(_quote())
        stop.on_quote(_quote())
        normal.submit(_order(reason=""))
        stop.submit(
            OrderRequest(
                timestamp_ns=0,
                correlation_id="c",
                sequence=2,
                order_id="o2",
                symbol="AAPL",
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=100,
                reason="STOP_EXIT",
            )
        )
        n_fills = [a for a in normal.poll_acks() if a.status == OrderAckStatus.FILLED]
        s_fills = [a for a in stop.poll_acks() if a.status == OrderAckStatus.FILLED]
        assert s_fills[0].fees == n_fills[0].fees


class TestStopSlippagePassiveRouter:
    def test_aggressive_fallback_stop_exit_pays_slippage(self) -> None:
        cfg = DefaultCostModelConfig(
            sell_regulatory_bps=Decimal("0"),
            finra_taf_per_share=Decimal("0"),
        )
        router = PassiveLimitOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=DefaultCostModel(cfg),
            stop_slippage_half_spreads=Decimal("2.0"),
        )
        router.on_quote(_quote())
        router.submit(_order(reason=""))
        router.submit(
            OrderRequest(
                timestamp_ns=0,
                correlation_id="c",
                sequence=2,
                order_id="o2",
                symbol="AAPL",
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=100,
                reason="HARD_EXIT_AGE",
            )
        )
        fills = [a for a in router.poll_acks() if a.status == OrderAckStatus.FILLED]
        assert len(fills) == 2
        assert fills[1].fees > fills[0].fees
