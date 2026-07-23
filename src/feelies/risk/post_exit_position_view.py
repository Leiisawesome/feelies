"""Read-only position projection used to risk-check reversal entry legs."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from feelies.portfolio.position_store import Position, PositionStore


class PostExitPositionView:
    """Project one pending exit onto a position store without mutating it."""

    __slots__ = ("_inner", "_symbol", "_adjustment")

    def __init__(
        self,
        inner: PositionStore,
        symbol: str,
        quantity_adjustment: int,
    ) -> None:
        self._inner = inner
        self._symbol = symbol
        self._adjustment = quantity_adjustment

    def _adjusted(self, position: Position) -> Position:
        new_quantity = position.quantity + self._adjustment
        mark = self.latest_mark(position.symbol)
        unrealized_pnl = Decimal("0")
        if new_quantity != 0:
            if mark is not None and mark > 0:
                unrealized_pnl = (mark - position.avg_entry_price) * new_quantity
            else:
                unrealized_pnl = position.unrealized_pnl
        return Position(
            symbol=position.symbol,
            quantity=new_quantity,
            avg_entry_price=position.avg_entry_price,
            realized_pnl=position.realized_pnl,
            unrealized_pnl=unrealized_pnl,
            cumulative_fees=position.cumulative_fees,
        )

    def get(self, symbol: str) -> Position:
        position = self._inner.get(symbol)
        if symbol == self._symbol:
            return self._adjusted(position)
        return position

    def all_positions(self) -> dict[str, Position]:
        positions = dict(self._inner.all_positions())
        if self._symbol in positions:
            positions[self._symbol] = self._adjusted(positions[self._symbol])
        return positions

    def total_exposure(self) -> Decimal:
        total = self._inner.total_exposure()
        position = self._inner.get(self._symbol)
        mark = self.latest_mark(self._symbol)
        if mark is None or mark <= 0:
            mark = position.avg_entry_price
        old_contribution = abs(position.quantity) * mark
        new_contribution = abs(position.quantity + self._adjustment) * mark
        return total - old_contribution + new_contribution

    def update(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("PostExitPositionView is read-only")

    def debit_fees(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("PostExitPositionView is read-only")

    def update_mark(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("PostExitPositionView is read-only")

    def latest_mark(self, symbol: str) -> Decimal | None:
        return self._inner.latest_mark(symbol)

    def opened_at_ns(self, symbol: str) -> int | None:
        return self._inner.opened_at_ns(symbol)
