"""In-memory position store for backtest and testing.

Satisfies the ``PositionStore`` protocol.  Positions are tracked
per-symbol with FIFO cost-basis for PnL calculation.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.portfolio.position_store import Position


class MemoryPositionStore:
    """Thread-unsafe, in-memory position store.

    Suitable for single-threaded backtest and unit tests.
    """

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}

    def get(self, symbol: str) -> Position:
        pos = self._positions.get(symbol)
        if pos is None:
            return Position(symbol=symbol)
        return pos

    def update(
        self,
        symbol: str,
        quantity_delta: int,
        fill_price: Decimal,
    ) -> Position:
        pos = self._positions.get(symbol)
        if pos is None:
            pos = Position(symbol=symbol)
            self._positions[symbol] = pos

        old_qty = pos.quantity
        new_qty = old_qty + quantity_delta

        if old_qty == 0:
            pos.avg_entry_price = fill_price
        elif _same_sign(old_qty, quantity_delta):
            total_cost = pos.avg_entry_price * abs(old_qty) + fill_price * abs(quantity_delta)
            pos.avg_entry_price = total_cost / abs(new_qty) if new_qty != 0 else Decimal("0")
        else:
            closed_qty = min(abs(quantity_delta), abs(old_qty))
            if old_qty > 0:
                pnl = (fill_price - pos.avg_entry_price) * closed_qty
            else:
                pnl = (pos.avg_entry_price - fill_price) * closed_qty
            pos.realized_pnl += pnl

            if abs(quantity_delta) > abs(old_qty):
                pos.avg_entry_price = fill_price

        pos.quantity = new_qty
        if new_qty == 0:
            pos.avg_entry_price = Decimal("0")

        return pos

    def all_positions(self) -> dict[str, Position]:
        return dict(self._positions)

    def total_exposure(self) -> Decimal:
        total = Decimal("0")
        for pos in self._positions.values():
            total += abs(pos.quantity) * pos.avg_entry_price
        return total


def _same_sign(a: int, b: int) -> bool:
    return (a > 0 and b > 0) or (a < 0 and b < 0)
