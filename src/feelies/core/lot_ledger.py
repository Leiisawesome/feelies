"""Per-symbol FIFO open-lot ledger for observability.

The position store (`MemoryPositionStore`) keeps a single **average-cost**
``avg_entry_price`` and realizes PnL against it.  That is the parity-bearing
book and is intentionally left unchanged.  This ledger sits *beside* it and
tracks the individual open lots (price, open timestamp, originating
strategy/intent) with **FIFO** matching, giving:

  - per-lot holding age (the oldest open lot, FIFO front),
  - per-lot strategy/intent provenance,
  - an honest **FIFO realized PnL** view, distinct from the average-cost
    realized PnL the position store reports.

It is pure observability: it publishes nothing, touches no position/journal,
and is never read by the parity hash, so maintaining it is parity-neutral.
FIFO and average-cost realized PnL legitimately differ on partial reduces —
that difference is the point (honest per-lot accounting), not a bug.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal


@dataclass(frozen=True, kw_only=True)
class Lot:
    """One open lot.  ``quantity`` is signed: ``> 0`` long, ``< 0`` short.

    All lots for a symbol share the position's sign until a cross-through-
    zero opens a lot on the other side.
    """

    quantity: int
    price: Decimal
    opened_at_ns: int
    strategy_id: str = ""
    intent: str = ""


def _same_sign(a: int, b: int) -> bool:
    return (a > 0 and b > 0) or (a < 0 and b < 0)


class LotLedger:
    """FIFO open-lot book per symbol (additive to the avg-cost store)."""

    def __init__(self) -> None:
        self._book: dict[str, list[Lot]] = {}
        self._realized_fifo: dict[str, Decimal] = {}

    def apply_fill(
        self,
        symbol: str,
        signed_qty: int,
        price: Decimal,
        *,
        timestamp_ns: int,
        strategy_id: str = "",
        intent: str = "",
    ) -> None:
        """Apply a signed fill (``+`` buy / ``-`` sell), matching FIFO.

        Adds a lot when the fill extends the position (or opens it); consumes
        lots front-first when it reduces, realizing FIFO PnL; opens a fresh
        opposite-side lot for any residual that crosses through zero.
        """
        if signed_qty == 0:
            return
        lots = self._book.setdefault(symbol, [])
        net = sum(lot.quantity for lot in lots)

        # Extend / open → append a new lot.
        if net == 0 or _same_sign(net, signed_qty):
            lots.append(
                Lot(
                    quantity=signed_qty,
                    price=price,
                    opened_at_ns=timestamp_ns,
                    strategy_id=strategy_id,
                    intent=intent,
                )
            )
            return

        # Reduce → consume FIFO front-first, realizing per matched share.
        to_reduce = signed_qty  # opposite sign to the book
        realized = Decimal("0")
        while lots and to_reduce != 0 and not _same_sign(lots[0].quantity, to_reduce):
            front = lots[0]
            matched = min(abs(front.quantity), abs(to_reduce))
            if front.quantity > 0:
                realized += (price - front.price) * matched
            else:
                realized += (front.price - price) * matched
            if abs(front.quantity) <= abs(to_reduce):
                to_reduce += front.quantity  # opposite signs → toward 0
                lots.pop(0)
            else:
                lots[0] = replace(front, quantity=front.quantity + to_reduce)
                to_reduce = 0
        if realized != 0:
            self._realized_fifo[symbol] = self._realized_fifo.get(symbol, Decimal("0")) + realized

        # Cross-through-zero residual opens a lot on the other side.
        if to_reduce != 0:
            lots.append(
                Lot(
                    quantity=to_reduce,
                    price=price,
                    opened_at_ns=timestamp_ns,
                    strategy_id=strategy_id,
                    intent=intent,
                )
            )

    # ── Queries ──────────────────────────────────────────────────────

    def lots(self, symbol: str) -> tuple[Lot, ...]:
        """Open lots for ``symbol``, oldest first (FIFO order)."""
        return tuple(self._book.get(symbol, ()))

    def open_lot_count(self, symbol: str) -> int:
        return len(self._book.get(symbol, ()))

    def net_quantity(self, symbol: str) -> int:
        """Sum of lot quantities — mirrors the position store's quantity."""
        return sum(lot.quantity for lot in self._book.get(symbol, ()))

    def oldest_open_age_ns(self, symbol: str, now_ns: int) -> int | None:
        """Age of the oldest open lot (FIFO front), or ``None`` when flat."""
        lots = self._book.get(symbol)
        if not lots:
            return None
        return now_ns - lots[0].opened_at_ns

    def realized_pnl_fifo(self, symbol: str) -> Decimal:
        """Cumulative FIFO realized PnL (distinct from avg-cost realized)."""
        return self._realized_fifo.get(symbol, Decimal("0"))

    def symbols(self) -> tuple[str, ...]:
        return tuple(s for s, lots in self._book.items() if lots)
