"""P-12: post-exit hypothetical unrealized uses the executable side."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.kernel.orchestrator import _PostExitPositionView
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.post_exit_position_view import PostExitPositionView

_VIEWS = [PostExitPositionView, _PostExitPositionView]


def _sided_book() -> MemoryPositionStore:
    store = MemoryPositionStore()
    store.update("AAPL", 100, Decimal("100.00"))
    store.update_mark(
        "AAPL",
        Decimal("101.05"),
        bid=Decimal("101.00"),
        ask=Decimal("101.10"),
    )
    return store


def test_t1_valuation_mark_uses_the_executable_side() -> None:
    store = MemoryPositionStore()
    assert store.valuation_mark("NONE", 1) is None
    store.update("AAPL", 100, Decimal("100.00"))
    store.update_mark(
        "AAPL",
        Decimal("101.05"),
        bid=Decimal("101.00"),
        ask=Decimal("101.10"),
    )
    assert store.valuation_mark("AAPL", 10) == Decimal("101.00")
    assert store.valuation_mark("AAPL", -10) == Decimal("101.10")
    assert store.valuation_mark("AAPL", 0) is None
    store.update_mark("AAPL", Decimal("5.00"), bid=Decimal("0"), ask=Decimal("9.00"))
    assert store.valuation_mark("AAPL", 10) == Decimal("101.00")
    assert store.valuation_mark("AAPL", -10) == Decimal("101.10")


@pytest.mark.parametrize("view_cls", _VIEWS, ids=lambda cls: cls.__name__)
def test_t2_partial_exit_marks_long_at_the_bid(view_cls: type) -> None:
    view = view_cls(_sided_book(), "AAPL", -40)
    assert view.get("AAPL").unrealized_pnl == Decimal("60.00")


@pytest.mark.parametrize("view_cls", _VIEWS, ids=lambda cls: cls.__name__)
def test_t3_flip_marks_short_at_the_ask(view_cls: type) -> None:
    view = view_cls(_sided_book(), "AAPL", -150)
    assert view.get("AAPL").unrealized_pnl == Decimal("-55.00")


@pytest.mark.parametrize("view_cls", _VIEWS, ids=lambda cls: cls.__name__)
def test_t4_missing_side_values_unrealized_at_zero(view_cls: type) -> None:
    store = MemoryPositionStore()
    store.update("AAPL", 100, Decimal("100.00"))
    store.update_mark("AAPL", Decimal("101.05"))
    view = view_cls(store, "AAPL", -40)
    assert view.get("AAPL").unrealized_pnl == Decimal("0")


@pytest.mark.parametrize("view_cls", _VIEWS, ids=lambda cls: cls.__name__)
def test_t5_exposure_stays_on_reference_mid(view_cls: type) -> None:
    store = _sided_book()
    view = view_cls(store, "AAPL", -40)
    mark = store.reference_mid("AAPL")
    assert mark is not None
    position = store.get("AAPL")
    old = abs(position.quantity) * mark
    new = abs(position.quantity - 40) * mark
    assert view.total_exposure() == store.total_exposure() - old + new


@pytest.mark.parametrize("view_cls", _VIEWS, ids=lambda cls: cls.__name__)
def test_t6_flat_hypothetical_unrealized_is_zero(view_cls: type) -> None:
    view = view_cls(_sided_book(), "AAPL", -100)
    assert view.get("AAPL").unrealized_pnl == Decimal("0")
