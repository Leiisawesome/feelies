"""Tests for spread-aware liquidation marks on the position store.

Audit F-H-03 (4th pass): unrealized PnL was previously computed against
mid, overstating liquidation value by half-spread × |quantity| on every
open position.  The drawdown guard consumes unrealized PnL — the bias
made the gate fire late.

With the fix, ``update_mark(..., bid=..., ask=...)`` records the BBO and
``_recompute_unrealized`` uses bid for longs / ask for shorts.  Callers
that don't supply BBO retain legacy mid-mark behavior (backward compat).
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

    def test_legacy_update_mark_without_bbo_uses_mid(self) -> None:
        """Backward-compat: callers that don't supply bid/ask use mid."""
        store = MemoryPositionStore()
        store.update("AAPL", quantity_delta=100, fill_price=Decimal("100"))
        store.update_mark("AAPL", Decimal("101"))
        # (101 - 100) * 100 = $100 unrealized
        assert store.get("AAPL").unrealized_pnl == Decimal("100")

    def test_long_unrealized_less_with_bid_than_with_mid(self) -> None:
        """Spread-aware mark is strictly less optimistic for longs."""
        store_a = MemoryPositionStore()
        store_b = MemoryPositionStore()
        store_a.update("AAPL", 100, Decimal("100"))
        store_b.update("AAPL", 100, Decimal("100"))
        store_a.update_mark("AAPL", Decimal("101"))
        store_b.update_mark(
            "AAPL",
            Decimal("101"),
            bid=Decimal("100.95"),
            ask=Decimal("101.05"),
        )
        # Legacy (mid): $100 unrealized.  New (bid): $95 unrealized.
        assert store_a.get("AAPL").unrealized_pnl > store_b.get("AAPL").unrealized_pnl

    def test_short_unrealized_less_with_ask_than_with_mid(self) -> None:
        """Spread-aware mark is strictly less optimistic for shorts."""
        store_a = MemoryPositionStore()
        store_b = MemoryPositionStore()
        store_a.update("AAPL", -100, Decimal("100"))
        store_b.update("AAPL", -100, Decimal("100"))
        # mid below entry → short is profitable; ask is HIGHER than mid,
        # so close-at-ask is less profitable than close-at-mid.
        store_a.update_mark("AAPL", Decimal("99"))
        store_b.update_mark(
            "AAPL",
            Decimal("99"),
            bid=Decimal("98.95"),
            ask=Decimal("99.05"),
        )
        # Legacy (mid): (99 - 100) * -100 = $100.  New (ask): $95.
        assert store_a.get("AAPL").unrealized_pnl > store_b.get("AAPL").unrealized_pnl


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
