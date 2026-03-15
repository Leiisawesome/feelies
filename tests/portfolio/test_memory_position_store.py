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
