"""Tests for MemoryPositionStore — in-memory PositionStore implementation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.portfolio.memory_position_store import MemoryPositionStore


@pytest.fixture
def store() -> MemoryPositionStore:
    return MemoryPositionStore()


class TestGet:
    def test_unknown_symbol_returns_zero_position(self, store: MemoryPositionStore) -> None:
        pos = store.get("AAPL")
        assert pos.symbol == "AAPL"
        assert pos.quantity == 0
        assert pos.avg_entry_price == Decimal("0")
        assert pos.realized_pnl == Decimal("0")
        assert pos.unrealized_pnl == Decimal("0")


class TestUpdate:
    def test_buy_creates_position(self, store: MemoryPositionStore) -> None:
        pos = store.update("AAPL", 100, Decimal("150"))
        assert pos.quantity == 100
        assert pos.avg_entry_price == Decimal("150")

    def test_sell_reduces_position(self, store: MemoryPositionStore) -> None:
        store.update("AAPL", 100, Decimal("150"))
        pos = store.update("AAPL", -50, Decimal("155"))
        assert pos.quantity == 50
        assert pos.avg_entry_price == Decimal("150")

    def test_sell_to_zero_clears_avg_price(self, store: MemoryPositionStore) -> None:
        store.update("AAPL", 100, Decimal("150"))
        pos = store.update("AAPL", -100, Decimal("160"))
        assert pos.quantity == 0
        assert pos.avg_entry_price == Decimal("0")

    def test_adding_to_position_averages_cost(self, store: MemoryPositionStore) -> None:
        store.update("AAPL", 100, Decimal("10"))
        pos = store.update("AAPL", 100, Decimal("20"))
        assert pos.quantity == 200
        assert pos.avg_entry_price == Decimal("15")


class TestAllPositions:
    def test_returns_all_tracked_symbols(self, store: MemoryPositionStore) -> None:
        store.update("AAPL", 100, Decimal("150"))
        store.update("MSFT", 50, Decimal("300"))
        positions = store.all_positions()
        assert set(positions.keys()) == {"AAPL", "MSFT"}

    def test_empty_store_returns_empty_dict(self, store: MemoryPositionStore) -> None:
        assert store.all_positions() == {}


class TestTotalExposure:
    def test_sums_absolute_notional(self, store: MemoryPositionStore) -> None:
        store.update("AAPL", 100, Decimal("10"))
        store.update("MSFT", -50, Decimal("20"))
        exposure = store.total_exposure()
        # |100| * 10 + |-50| * 20 = 1000 + 1000 = 2000
        assert exposure == Decimal("2000")

    def test_empty_store_zero_exposure(self, store: MemoryPositionStore) -> None:
        assert store.total_exposure() == Decimal("0")


class TestCostBasisPnl:
    def test_buy_then_partial_sell_realized_pnl(self, store: MemoryPositionStore) -> None:
        """Buy 100@$10, sell 50@$12 → realized PnL = 50 * ($12 - $10) = $100."""
        store.update("AAPL", 100, Decimal("10"))
        pos = store.update("AAPL", -50, Decimal("12"))
        assert pos.realized_pnl == Decimal("100")
        assert pos.quantity == 50
        assert pos.avg_entry_price == Decimal("10")

    def test_short_position_pnl(self, store: MemoryPositionStore) -> None:
        """Short 100@$50, cover 50@$45 → realized PnL = 50 * ($50 - $45) = $250."""
        store.update("AAPL", -100, Decimal("50"))
        pos = store.update("AAPL", 50, Decimal("45"))
        assert pos.realized_pnl == Decimal("250")
        assert pos.quantity == -50

    def test_full_close_realized_pnl(self, store: MemoryPositionStore) -> None:
        """Buy 100@$10, sell 100@$15 → realized PnL = 100 * $5 = $500."""
        store.update("AAPL", 100, Decimal("10"))
        pos = store.update("AAPL", -100, Decimal("15"))
        assert pos.realized_pnl == Decimal("500")
        assert pos.quantity == 0


class TestDebitFees:
    """F7: debit_fees — cancel/expiry fees without a fill."""

    def test_debits_fees_when_position_exists(self, store: MemoryPositionStore) -> None:
        """Cancel fee accumulates against an existing filled position."""
        store.update("AAPL", 100, Decimal("150"))
        store.debit_fees("AAPL", Decimal("1.50"))
        assert store.get("AAPL").cumulative_fees == Decimal("1.50")

    def test_no_ghost_position_when_no_fill(self, store: MemoryPositionStore) -> None:
        """Cancel fee on a never-filled symbol must not create a ghost entry."""
        store.debit_fees("AAPL", Decimal("0.50"))
        # all_positions() should remain empty — no zero-qty ghost
        assert store.all_positions() == {}

    def test_fully_closed_position_visible_in_all_positions(
        self, store: MemoryPositionStore
    ) -> None:
        """Fully-closed positions remain in all_positions() for realized-PnL aggregation."""
        store.update("AAPL", 100, Decimal("150"))
        store.update("AAPL", -100, Decimal("155"))  # full close → qty=0, PnL=$500
        result = store.all_positions()
        # Position is retained so that realized_pnl is visible to the risk engine.
        assert "AAPL" in result
        assert result["AAPL"].quantity == 0
        assert result["AAPL"].realized_pnl == Decimal("500")

    def test_debit_fees_accumulate_on_closed_position(
        self, store: MemoryPositionStore
    ) -> None:
        """Cancel fees arriving after a full close accumulate on the existing entry."""
        store.update("AAPL", 100, Decimal("150"))
        store.update("AAPL", -100, Decimal("155"))  # qty → 0
        store.debit_fees("AAPL", Decimal("0.10"))
        pos = store.all_positions()["AAPL"]
        assert pos.cumulative_fees == Decimal("0.10")
