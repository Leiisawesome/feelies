"""Book mark store contract (P-11, D-24).

The store rejects a non-positive side and keeps the last valid bid/ask.
It does not apply crossed/locked/zero-size quality. Mid is not a valuation input.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.kernel.orchestrator import _PostExitPositionView
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.post_exit_position_view import PostExitPositionView


def _valid(store: MemoryPositionStore) -> None:
    store.update("AAPL", quantity_delta=100, fill_price=Decimal("100"))
    store.update_mark(
        "AAPL",
        Decimal("10.01"),
        bid=Decimal("10.00"),
        ask=Decimal("10.02"),
    )


def test_nonpositive_side_retains_last_valid_and_sets_stale() -> None:
    store = MemoryPositionStore()
    _valid(store)
    before = store.get("AAPL").unrealized_pnl
    store.update_mark("AAPL", Decimal("5.01"), bid=Decimal("0"), ask=Decimal("10.02"))
    assert store.get("AAPL").unrealized_pnl == before
    assert store._bids["AAPL"] == Decimal("10.00")
    assert store._asks["AAPL"] == Decimal("10.02")
    assert store.reference_mid("AAPL") == Decimal("10.01")
    assert store.is_mark_stale("AAPL")


def test_locked_positive_pair_is_accepted_and_clears_stale() -> None:
    store = MemoryPositionStore()
    _valid(store)
    store.mark_stale("AAPL")
    assert store.is_mark_stale("AAPL")
    store.update_mark(
        "AAPL",
        Decimal("0.01"),
        bid=Decimal("0.01"),
        ask=Decimal("0.01"),
    )
    assert store.is_mark_stale("AAPL") is False
    assert store._bids["AAPL"] == Decimal("0.01")
    assert store._asks["AAPL"] == Decimal("0.01")
    assert store.reference_mid("AAPL") == Decimal("0.01")


def test_mid_only_update_is_not_a_valuation_input() -> None:
    store = MemoryPositionStore()
    store.update("AAPL", quantity_delta=100, fill_price=Decimal("100"))
    store.update_mark("AAPL", Decimal("101"))
    assert store.get("AAPL").unrealized_pnl == Decimal("0")
    assert store.reference_mid("AAPL") == Decimal("101")


def test_strategy_store_forwards_nonpositive_rejection() -> None:
    store = StrategyPositionStore()
    store.update("alpha_a", "AAPL", 100, Decimal("100"))
    store.update_mark(
        "AAPL",
        Decimal("10.01"),
        bid=Decimal("10.00"),
        ask=Decimal("10.02"),
    )
    before = store.get("alpha_a", "AAPL").unrealized_pnl
    store.update_mark("AAPL", Decimal("5.01"), bid=Decimal("0"), ask=Decimal("10.02"))
    assert store.get("alpha_a", "AAPL").unrealized_pnl == before
    assert store.reference_mid("AAPL") == Decimal("10.01")
    assert store.is_mark_stale("AAPL")


def test_views_delegate_mark_methods() -> None:
    base = MemoryPositionStore()
    _valid(base)
    for view in (
        PostExitPositionView(base, "AAPL", 0),
        _PostExitPositionView(base, "AAPL", 0),
    ):
        assert view.reference_mid("AAPL") == base.reference_mid("AAPL")
        assert view.is_mark_stale("AAPL") is base.is_mark_stale("AAPL")
        view.mark_stale("AAPL")
        assert base.is_mark_stale("AAPL")
        assert view.is_mark_stale("AAPL")
