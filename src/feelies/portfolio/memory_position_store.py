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
        fees: Decimal = Decimal("0"),
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
        pos.cumulative_fees += fees
        if new_qty == 0:
            pos.avg_entry_price = Decimal("0")

        return pos

    def debit_fees(self, symbol: str, fees: Decimal) -> None:
        """Record fees without a fill (e.g. cancel fees).

        Only updates positions that already exist (non-zero quantity).
        A cancel on a never-filled order produces no position entry —
        creating a ghost zero-qty position would pollute all_positions()
        and miscount open positions in downstream consumers.
        """
        pos = self._positions.get(symbol)
        if pos is not None:
            pos.cumulative_fees += fees

    def all_positions(self) -> dict[str, Position]:
        """Return all tracked positions, including fully-closed ones.

        Closed positions (qty=0) are included so that realized PnL and
        cumulative fees remain visible to downstream consumers (e.g. the
        drawdown guard in the risk engine).  Callers that care only about
        open positions must filter by ``pos.quantity != 0`` themselves.

        Ghost positions are prevented at the ``debit_fees`` level — a
        cancel fee on a symbol that was never filled produces no entry.
        """
        return dict(self._positions)

    def total_exposure(self) -> Decimal:
        total = Decimal("0")
        for pos in self._positions.values():
            total += abs(pos.quantity) * pos.avg_entry_price
        return total


def _same_sign(a: int, b: int) -> bool:
    return (a > 0 and b > 0) or (a < 0 and b < 0)
