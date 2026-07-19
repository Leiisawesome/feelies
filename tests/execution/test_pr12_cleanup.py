"""PR-12 cleanup roll-up tests (audit F-L-30, F-L-31, F-L-32, F-M-21, F-M-26, F-M-27)."""

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
from feelies.storage.trade_journal import TradeRecord

pytestmark = pytest.mark.backtest_validation


def _quote_with_depth(bid_size: int, ask_size: int, ts: int = 1000) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id="q",
        sequence=1,
        symbol="AAPL",
        bid=Decimal("99.00"),
        ask=Decimal("101.00"),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts,
    )


def _locked_quote() -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=1000,
        correlation_id="q",
        sequence=1,
        symbol="AAPL",
        bid=Decimal("100.00"),
        ask=Decimal("100.00"),  # locked
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=1000,
    )


def _market_order(qty: int = 50) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=0,
        correlation_id="c",
        sequence=1,
        order_id="o1",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=qty,
    )


class TestLockedQuoteMetric:
    """Audit F-M-26: reject counters expose router-side telemetry."""

    def test_backtest_router_increments_locked_quote_counter(self) -> None:
        router = BacktestOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=ZeroCostModel(),
        )
        router.on_quote(_locked_quote())
        router.submit(_market_order())
        assert router.locked_quote_reject_count == 1

    def test_passive_router_increments_locked_quote_counter(self) -> None:
        router = PassiveLimitOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=ZeroCostModel(),
        )
        router.on_quote(_locked_quote())
        router.submit(_market_order())
        assert router.locked_quote_reject_count == 1


class TestPartialFillDistinctTimestamps:
    """Audit F-M-27: partial vs final fill timestamps differ by ≥ 1 ns."""

    def test_partial_and_final_fill_have_distinct_timestamps(self) -> None:
        router = BacktestOrderRouter(
            SimulatedClock(start_ns=0),
            cost_model=ZeroCostModel(),
        )
        router.on_quote(_quote_with_depth(bid_size=100, ask_size=50))
        router.submit(_market_order(qty=200))
        acks = router.poll_acks()
        partial = next(a for a in acks if a.status == OrderAckStatus.PARTIALLY_FILLED)
        final = next(a for a in acks if a.status == OrderAckStatus.FILLED)
        assert final.timestamp_ns > partial.timestamp_ns


class TestExpiredTimeoutStatus:
    """Audit F-L-31: passive timeouts emit OrderAckStatus.EXPIRED."""

    def test_passive_timeout_emits_expired_not_cancelled(self) -> None:
        clock = SimulatedClock(start_ns=0)
        router = PassiveLimitOrderRouter(
            clock,
            cost_model=ZeroCostModel(),
            fill_delay_ticks=100,
            max_resting_ticks=2,
        )
        router.on_quote(
            NBBOQuote(
                timestamp_ns=1000,
                correlation_id="q",
                sequence=1,
                symbol="AAPL",
                bid=Decimal("100"),
                ask=Decimal("100.10"),
                bid_size=100,
                ask_size=100,
                exchange_timestamp_ns=1000,
            )
        )
        router.submit(
            OrderRequest(
                timestamp_ns=0,
                correlation_id="c",
                sequence=1,
                order_id="o1",
                symbol="AAPL",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=50,
                limit_price=Decimal("100"),
            )
        )
        router.poll_acks()
        # Move BBO away to keep us off-level, accumulating total_ticks.
        for ts in (2000, 3000, 4000):
            router.on_quote(
                NBBOQuote(
                    timestamp_ns=ts,
                    correlation_id="q",
                    sequence=ts,
                    symbol="AAPL",
                    bid=Decimal("100.05"),
                    ask=Decimal("100.10"),
                    bid_size=100,
                    ask_size=100,
                    exchange_timestamp_ns=ts,
                )
            )
        # After 3 quotes at off-level, total_ticks=3 > max=2 → EXPIRED.
        timeout_acks = [a for a in router.poll_acks() if a.status == OrderAckStatus.EXPIRED]
        assert len(timeout_acks) == 1


class TestTradeRecordNetPnl:
    """Audit F-M-21: TradeRecord.net_pnl property."""

    def test_net_pnl_subtracts_fees(self) -> None:
        tr = TradeRecord(
            order_id="o1",
            symbol="AAPL",
            strategy_id="s",
            side=Side.BUY,
            requested_quantity=100,
            filled_quantity=100,
            fill_price=Decimal("100"),
            signal_timestamp_ns=0,
            submit_timestamp_ns=0,
            fill_timestamp_ns=1000,
            cost_bps=Decimal("5"),
            fees=Decimal("0.50"),
            realized_pnl=Decimal("10.00"),
            correlation_id="c",
        )
        assert tr.net_pnl == Decimal("9.50")
