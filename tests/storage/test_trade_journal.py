"""Unit tests for TradeRecord and TradeJournal."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import Side
from feelies.storage.trade_journal import TradeJournal, TradeRecord


def make_trade_record(
    order_id: str = "ord-001",
    symbol: str = "AAPL",
    strategy_id: str = "alpha1",
) -> TradeRecord:
    """Create a sample TradeRecord for tests."""
    return TradeRecord(
        order_id=order_id,
        symbol=symbol,
        strategy_id=strategy_id,
        side=Side.BUY,
        requested_quantity=100,
        filled_quantity=100,
        fill_price=Decimal("150.01"),
        signal_timestamp_ns=1_700_000_000_000_000_000,
        submit_timestamp_ns=1_700_000_000_000_100_000,
        fill_timestamp_ns=1_700_000_000_000_200_000,
        slippage_bps=Decimal("0.5"),
        fees=Decimal("0"),
        realized_pnl=Decimal("10.50"),
        correlation_id="AAPL:1700000000000000000:1",
    )


class TestTradeRecord:
    """Tests for TradeRecord dataclass."""

    def test_creates_with_required_fields(self) -> None:
        rec = make_trade_record()
        assert rec.order_id == "ord-001"
        assert rec.symbol == "AAPL"
        assert rec.strategy_id == "alpha1"
        assert rec.side == Side.BUY
        assert rec.filled_quantity == 100
        assert rec.fill_price == Decimal("150.01")
        assert rec.realized_pnl == Decimal("10.50")

    def test_metadata_default_empty(self) -> None:
        rec = make_trade_record()
        assert rec.metadata == {}

    def test_is_frozen(self) -> None:
        rec = make_trade_record()
        with pytest.raises(AttributeError):
            rec.order_id = "other"


class TestTradeJournalProtocol:
    """Tests that verify TradeJournal protocol contract."""

    def test_in_memory_impl_satisfies_protocol(self) -> None:
        """Minimal in-memory impl for protocol structural check."""
        records: list[TradeRecord] = []

        class InMemoryTradeJournal:
            def record(self, trade: TradeRecord) -> None:
                records.append(trade)

            def query(
                self,
                *,
                symbol: str | None = None,
                strategy_id: str | None = None,
                start_ns: int | None = None,
                end_ns: int | None = None,
            ):
                for r in records:
                    if symbol is not None and r.symbol != symbol:
                        continue
                    if strategy_id is not None and r.strategy_id != strategy_id:
                        continue
                    if start_ns is not None and (r.fill_timestamp_ns or 0) < start_ns:
                        continue
                    if end_ns is not None and (r.fill_timestamp_ns or 0) > end_ns:
                        continue
                    yield r

        journal: TradeJournal = InMemoryTradeJournal()

        rec = make_trade_record()
        journal.record(rec)
        journal.record(make_trade_record(order_id="ord-002", symbol="MSFT"))

        results = list(journal.query(symbol="AAPL"))
        assert len(results) == 1
        assert results[0].order_id == "ord-001"

        results_all = list(journal.query())
        assert len(results_all) == 2
