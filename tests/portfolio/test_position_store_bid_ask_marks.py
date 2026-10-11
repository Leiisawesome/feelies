"""Tests for spread-aware liquidation marks on position stores.

Use the bid for longs and ask for shorts. Calls without a BBO retain
midpoint marking for compatibility.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore

pytestmark = pytest.mark.backtest_validation


class TestMemoryPositionStoreBidAskMarks:
    def test_long_unrealized_uses_bid_when_provided(self) -> None:
        store = MemoryPositionStore()
        store.update("AAPL", quantity_delta=100, fill_price=Decimal("100"))
        # mid = $101, bid = $100.95, ask = $101.05.  Long marks to
        # bid: (100.95 − 100) × 100 = $95 unrealized.
        store.update_mark(
            "AAPL",
            Decimal("101"),
            bid=Decimal("100.95"),
            ask=Decimal("101.05"),
        )
        assert store.get("AAPL").unrealized_pnl == Decimal("95.00")

    def test_long_unrealized_simple_bid_arithmetic(self) -> None:
        store = MemoryPositionStore()
        store.update("AAPL", quantity_delta=100, fill_price=Decimal("100"))
        # bid > entry: positive unrealized = (bid − entry) × qty
        store.update_mark(
            "AAPL",
            Decimal("101.00"),
            bid=Decimal("100.95"),
            ask=Decimal("101.05"),
        )
        # Long marks to bid: (100.95 - 100) * 100 = $95
        assert store.get("AAPL").unrealized_pnl == Decimal("95.00")

    def test_short_unrealized_uses_ask_when_provided(self) -> None:
        store = MemoryPositionStore()
        store.update("AAPL", quantity_delta=-100, fill_price=Decimal("100"))
        # mid = $99, bid = $98.95, ask = $99.05.  Short closes at ask:
        # (99.05 - 100) * -100 = -(-95) = wait let me compute:
        # unrealized = (mark - avg) * qty; qty = -100, avg = 100, mark = ask = 99.05
        # = (99.05 - 100) × -100 = -0.95 × -100 = $95 unrealized gain.
        store.update_mark(
            "AAPL",
            Decimal("99.00"),
            bid=Decimal("98.95"),
            ask=Decimal("99.05"),
        )
        assert store.get("AAPL").unrealized_pnl == Decimal("95.00")

    def test_mid_only_update_is_not_a_valuation_input(self) -> None:
        """A mid with no bid/ask is reference_mid only. Valuation stays at entry."""
        store = MemoryPositionStore()
        store.update("AAPL", quantity_delta=100, fill_price=Decimal("100"))
        store.update_mark("AAPL", Decimal("101"))
        assert store.get("AAPL").unrealized_pnl == Decimal("0")
        assert store.reference_mid("AAPL") == Decimal("101")

    def test_long_unrealized_uses_bid_mid_only_does_not_revalue(self) -> None:
        """A long marks to the bid. A later mid-only update does not revalue it."""
        store = MemoryPositionStore()
        store.update("AAPL", 100, Decimal("100"))
        store.update_mark(
            "AAPL",
            Decimal("101"),
            bid=Decimal("100.95"),
            ask=Decimal("101.05"),
        )
        assert store.get("AAPL").unrealized_pnl == Decimal("95.00")
        assert store.is_mark_stale("AAPL") is False
        store.update_mark("AAPL", Decimal("110"))
        assert store.get("AAPL").unrealized_pnl == Decimal("95.00")
        assert store.is_mark_stale("AAPL") is False
        assert store.reference_mid("AAPL") == Decimal("110")

    def test_short_unrealized_uses_ask_mid_only_does_not_revalue(self) -> None:
        """A short marks to the ask. A later mid-only update does not revalue it."""
        store = MemoryPositionStore()
        store.update("AAPL", -100, Decimal("100"))
        store.update_mark(
            "AAPL",
            Decimal("99"),
            bid=Decimal("98.95"),
            ask=Decimal("99.05"),
        )
        assert store.get("AAPL").unrealized_pnl == Decimal("95.00")
        assert store.is_mark_stale("AAPL") is False
        store.update_mark("AAPL", Decimal("90"))
        assert store.get("AAPL").unrealized_pnl == Decimal("95.00")
        assert store.is_mark_stale("AAPL") is False
        assert store.reference_mid("AAPL") == Decimal("90")


class TestStrategyPositionStoreBidAskMarks:
    def test_strategy_store_forwards_bid_ask(self) -> None:
        store = StrategyPositionStore()
        store.update("alpha_a", "AAPL", 100, Decimal("100"))
        store.update_mark(
            "AAPL",
            Decimal("101"),
            bid=Decimal("100.95"),
            ask=Decimal("101.05"),
        )
        pos = store.get("alpha_a", "AAPL")
        # Long marks to bid: (100.95 - 100) * 100 = $95.
        assert pos.unrealized_pnl == Decimal("95.00")
