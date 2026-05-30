"""Unit tests for Reg NMS tick snapping (BT-14)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import Side
from feelies.execution.tick_size import (
    is_on_tick_grid,
    snap_fill_price,
    snap_limit_price,
    tick_size,
)

pytestmark = pytest.mark.backtest_validation


class TestTickSize:
    def test_penny_tick_at_or_above_one_dollar(self) -> None:
        assert tick_size(Decimal("1.00")) == Decimal("0.01")
        assert tick_size(Decimal("250.50")) == Decimal("0.01")

    def test_subpenny_tick_below_one_dollar(self) -> None:
        assert tick_size(Decimal("0.99")) == Decimal("0.0001")
        assert tick_size(Decimal("0.0001")) == Decimal("0.0001")


class TestSnapFillPrice:
    def test_buy_rounds_up_conservatively(self) -> None:
        assert snap_fill_price(Side.BUY, Decimal("100.015")) == Decimal("100.02")

    def test_sell_rounds_down_conservatively(self) -> None:
        assert snap_fill_price(Side.SELL, Decimal("100.015")) == Decimal("100.01")

    def test_on_grid_unchanged(self) -> None:
        assert snap_fill_price(Side.BUY, Decimal("100.02")) == Decimal("100.02")


class TestSnapLimitPrice:
    def test_buy_limit_floors_subpenny(self) -> None:
        assert snap_limit_price(Side.BUY, Decimal("100.015")) == Decimal("100.01")

    def test_sell_limit_ceils_subpenny(self) -> None:
        assert snap_limit_price(Side.SELL, Decimal("100.015")) == Decimal("100.02")


class TestIsOnTickGrid:
    @pytest.mark.parametrize(
        ("price", "expected"),
        [
            (Decimal("100.02"), True),
            (Decimal("100.015"), False),
            (Decimal("0.9999"), True),
            (Decimal("0.99995"), False),
        ],
    )
    def test_grid_membership(self, price: Decimal, expected: bool) -> None:
        assert is_on_tick_grid(price) is expected
