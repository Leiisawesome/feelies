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
        cost_bps=Decimal("0.5"),
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


class TestInMemoryTradeJournal:
    """Tests for the concrete InMemoryTradeJournal query filters."""

    def _make_journal(self):
        from feelies.storage.memory_trade_journal import InMemoryTradeJournal
        journal = InMemoryTradeJournal()
        journal.record(TradeRecord(
            order_id="ord-1", symbol="AAPL", strategy_id="alpha1",
            side=Side.BUY, requested_quantity=100, filled_quantity=100,
            fill_price=Decimal("150.01"),
            signal_timestamp_ns=1_000_000_000, submit_timestamp_ns=1_000_100_000,
            fill_timestamp_ns=1_000_200_000,
            cost_bps=Decimal("0.5"), fees=Decimal("0"),
            realized_pnl=Decimal("10.50"),
            correlation_id="AAPL:1000000000:1",
        ))
        journal.record(TradeRecord(
            order_id="ord-2", symbol="MSFT", strategy_id="alpha2",
            side=Side.SELL, requested_quantity=50, filled_quantity=50,
            fill_price=Decimal("350.00"),
            signal_timestamp_ns=2_000_000_000, submit_timestamp_ns=2_000_100_000,
            fill_timestamp_ns=2_000_200_000,
            cost_bps=Decimal("0.3"), fees=Decimal("1.00"),
            realized_pnl=Decimal("-5.00"),
            correlation_id="MSFT:2000000000:2",
        ))
        journal.record(TradeRecord(
            order_id="ord-3", symbol="AAPL", strategy_id="alpha2",
            side=Side.BUY, requested_quantity=75, filled_quantity=75,
            fill_price=Decimal("151.00"),
            signal_timestamp_ns=3_000_000_000, submit_timestamp_ns=3_000_100_000,
            fill_timestamp_ns=3_000_200_000,
            cost_bps=Decimal("0.2"), fees=Decimal("0.50"),
            realized_pnl=Decimal("7.25"),
            correlation_id="AAPL:3000000000:3",
        ))
        return journal

    def test_query_all(self) -> None:
        journal = self._make_journal()
        assert len(list(journal.query())) == 3

    def test_query_by_symbol(self) -> None:
        journal = self._make_journal()
        aapl = list(journal.query(symbol="AAPL"))
        assert len(aapl) == 2
        assert all(r.symbol == "AAPL" for r in aapl)

        msft = list(journal.query(symbol="MSFT"))
        assert len(msft) == 1

    def test_query_by_strategy_id(self) -> None:
        journal = self._make_journal()
        alpha1 = list(journal.query(strategy_id="alpha1"))
        assert len(alpha1) == 1
        assert alpha1[0].strategy_id == "alpha1"

        alpha2 = list(journal.query(strategy_id="alpha2"))
        assert len(alpha2) == 2

    def test_query_by_start_ns(self) -> None:
        journal = self._make_journal()
        results = list(journal.query(start_ns=2_000_200_000))
        assert len(results) == 2
        for r in results:
            assert (r.fill_timestamp_ns or 0) >= 2_000_200_000

    def test_query_by_end_ns(self) -> None:
        journal = self._make_journal()
        results = list(journal.query(end_ns=2_000_200_000))
        assert len(results) == 2
        for r in results:
            assert (r.fill_timestamp_ns or 0) <= 2_000_200_000

    def test_query_combined_filters(self) -> None:
        journal = self._make_journal()
        results = list(journal.query(symbol="AAPL", strategy_id="alpha2"))
        assert len(results) == 1
        assert results[0].order_id == "ord-3"

    def test_query_no_matches(self) -> None:
        journal = self._make_journal()
        results = list(journal.query(symbol="GOOG"))
        assert len(results) == 0

    def test_len(self) -> None:
        journal = self._make_journal()
        assert len(journal) == 3

    def test_results_ordered_by_fill_timestamp(self) -> None:
        journal = self._make_journal()
        results = list(journal.query())
        timestamps = [r.fill_timestamp_ns or 0 for r in results]
        assert timestamps == sorted(timestamps)


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
