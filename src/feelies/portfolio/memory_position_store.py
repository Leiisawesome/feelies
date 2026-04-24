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
        self._marks: dict[str, Decimal] = {}
        # Phase-4-finalize: per-symbol "opened-at" shadow map used by
        # the hazard-exit min-age safeguard and optional hard-exit-age
        # reconciliation guard.  Set on flat→non-zero transitions in
        # ``update``; cleared when ``new_qty == 0`` so the next reopen
        # records a fresh open timestamp.
        self._opened_at_ns: dict[str, int] = {}
        # Most-recent fill timestamp per symbol — used to seed the
        # "opened" timestamp on flat→non-zero transitions.  Updated on
        # every ``update`` call, so callers passing ``timestamp_ns`` get
        # deterministic behaviour across replay.
        self._last_update_ns: dict[str, int] = {}

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
        timestamp_ns: int | None = None,
    ) -> Position:
        pos = self._positions.get(symbol)
        if pos is None:
            pos = Position(symbol=symbol)
            self._positions[symbol] = pos

        old_qty = pos.quantity
        new_qty = old_qty + quantity_delta

        # Phase-4-finalize: track flat→non-zero opens for hazard exits.
        # Only records when the caller supplies ``timestamp_ns`` —
        # legacy callers that omit it see no behavioural change.
        if timestamp_ns is not None:
            self._last_update_ns[symbol] = int(timestamp_ns)
            if old_qty == 0 and new_qty != 0:
                self._opened_at_ns[symbol] = int(timestamp_ns)
            elif new_qty == 0:
                self._opened_at_ns.pop(symbol, None)

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

        # Keep unrealized PnL current against the latest mark so the
        # drawdown guard and any MTM consumer read a fresh value.
        self._recompute_unrealized(pos)

        return pos

    def update_mark(self, symbol: str, mark_price: Decimal) -> None:
        if mark_price <= 0:
            return
        self._marks[symbol] = mark_price
        pos = self._positions.get(symbol)
        if pos is not None:
            self._recompute_unrealized(pos)

    def _recompute_unrealized(self, pos: Position) -> None:
        mark = self._marks.get(pos.symbol)
        if mark is None or pos.quantity == 0:
            pos.unrealized_pnl = Decimal("0")
            return
        pos.unrealized_pnl = (mark - pos.avg_entry_price) * pos.quantity

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

    def opened_at_ns(self, symbol: str) -> int | None:
        """Return the timestamp (ns) of the most recent flat→non-zero fill.

        Returns ``None`` when the symbol is currently flat or the
        opening fill did not pass ``timestamp_ns``.  See the
        :class:`PositionStore` protocol docstring for full semantics.
        """
        ts = self._opened_at_ns.get(symbol)
        if ts is None:
            return None
        pos = self._positions.get(symbol)
        if pos is None or pos.quantity == 0:
            return None
        return ts

    def latest_mark(self, symbol: str) -> Decimal | None:
        """Return the most recent mark recorded via :meth:`update_mark`."""
        return self._marks.get(symbol)

    def total_exposure(self) -> Decimal:
        """Gross notional using the latest mark per symbol.

        Falls back to ``avg_entry_price`` only when no mark has been
        recorded for the symbol — this is the boot-time case, before any
        quote has flowed through.  Once marks are present, exposure
        responds to price moves (a long that rallies tightens against
        the gross-exposure cap, as it should).
        """
        total = Decimal("0")
        for pos in self._positions.values():
            if pos.quantity == 0:
                continue
            price = self._marks.get(pos.symbol, pos.avg_entry_price)
            total += abs(pos.quantity) * price
        return total


def _same_sign(a: int, b: int) -> bool:
    return (a > 0 and b > 0) or (a < 0 and b < 0)
