"""Fill attribution ledger — maps net fills back to per-alpha contributions.

When multiple alphas generate orders for the same symbol in the same
tick, the exit-priority aggregation collapses them into net orders.
When those orders fill, the ledger distributes the fill back to the
contributing alphas proportionally for per-strategy position tracking.

Allocation uses largest-remainder method for integer rounding so that
the sum of per-alpha allocations equals the total fill exactly.

Invariants preserved:
  - Inv 5 (deterministic): proportional allocation is deterministic
  - Inv 13 (provenance): every fill traceable to contributing alphas
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from feelies.core.events import Side


@dataclass(frozen=True)
class AlphaContribution:
    """One alpha's contribution to a net order."""

    strategy_id: str
    signed_quantity: int
    proportion: float


@dataclass(frozen=True)
class AttributionRecord:
    """Maps a net order to the per-alpha intents that produced it."""

    order_id: str
    symbol: str
    net_side: Side
    net_quantity: int
    contributions: tuple[AlphaContribution, ...]


class FillAttributionLedger:
    """Records net-order provenance and allocates fills back to alphas.

    Usage:
      1. Orchestrator calls ``record()`` when building each net order.
      2. After fill, orchestrator calls ``allocate_fill()`` to get
         per-alpha (strategy_id, symbol, signed_qty, price) tuples
         for StrategyPositionStore updates.
    """

    def __init__(self) -> None:
        self._records: dict[str, AttributionRecord] = {}

    def record(self, record: AttributionRecord) -> None:
        """Store an attribution record keyed by order_id."""
        self._records[record.order_id] = record

    def allocate_fill(
        self,
        order_id: str,
        filled_quantity: int,
        fill_price: Decimal,
        total_fees: Decimal = Decimal("0"),
    ) -> list[tuple[str, str, int, Decimal, Decimal]]:
        """Distribute a fill across contributing alphas.

        Returns list of ``(strategy_id, symbol, signed_qty, fill_price, fees)``
        tuples.  Uses largest-remainder method for integer rounding.
        Fees are allocated proportionally to each alpha's share of the fill.

        If the order_id is unknown (e.g. emergency flatten), returns
        an empty list — the caller handles aggregate position updates.
        """
        record = self._records.pop(order_id, None)
        if record is None:
            return []

        if not record.contributions:
            return []

        sign = 1 if record.net_side == Side.BUY else -1
        allocations = _largest_remainder_allocate(
            filled_quantity, record.contributions,
        )

        total_allocated = sum(a for a in allocations if a > 0)
        result: list[tuple[str, str, int, Decimal, Decimal]] = []
        fee_remainder = total_fees
        for idx, (contrib, alloc_qty) in enumerate(zip(
            record.contributions, allocations, strict=True,
        )):
            if alloc_qty == 0:
                continue
            contrib_sign = 1 if contrib.signed_quantity >= 0 else -1
            effective_sign = sign if contrib_sign >= 0 else -sign
            if total_allocated > 0:
                alloc_fee = (total_fees * alloc_qty / total_allocated).quantize(Decimal("0.01"))
            else:
                alloc_fee = Decimal("0")
            fee_remainder -= alloc_fee
            result.append((
                contrib.strategy_id,
                record.symbol,
                effective_sign * alloc_qty,
                fill_price,
                alloc_fee,
            ))

        if result and fee_remainder != Decimal("0"):
            last = result[-1]
            result[-1] = (last[0], last[1], last[2], last[3], last[4] + fee_remainder)

        return result


def _largest_remainder_allocate(
    total: int,
    contributions: tuple[AlphaContribution, ...],
) -> list[int]:
    """Allocate *total* across contributions proportionally.

    Largest-remainder method: compute exact fractional allocation,
    floor each, then distribute remaining units one at a time to
    contributions with the largest fractional remainders.
    """
    if not contributions:
        return []

    total_proportion = sum(abs(c.proportion) for c in contributions)
    if total_proportion <= 0:
        n = len(contributions)
        base = total // n
        remainder = total - base * n
        return [base + (1 if i < remainder else 0) for i in range(n)]

    exact = [
        total * abs(c.proportion) / total_proportion for c in contributions
    ]
    floors = [int(e) for e in exact]
    remainders = [e - f for e, f in zip(exact, floors)]

    deficit = total - sum(floors)

    indices = sorted(range(len(remainders)), key=lambda i: -remainders[i])
    for i in range(deficit):
        floors[indices[i]] += 1

    return floors
