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

from decimal import Decimal

from feelies.core.events import Side
from feelies.core.fill_attribution import (
    AlphaContribution as AlphaContribution,
    AttributionRecord as AttributionRecord,
    largest_remainder_split as largest_remainder_split,
    split_fees as split_fees,
)


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
        # Cumulative largest-remainder allocation makes partial fills sum to
        # the same result as one fill of the final quantity.
        self._cumulative_allocations: dict[str, list[int]] = {}

    def record(self, record: AttributionRecord) -> None:
        """Store an attribution record keyed by order_id."""
        self._records[record.order_id] = record

    def allocate_fill(
        self,
        order_id: str,
        filled_quantity: int,
        fill_price: Decimal,
        total_fees: Decimal = Decimal("0"),
        is_final: bool = True,
    ) -> list[tuple[str, str, int, Decimal, Decimal]]:
        """Distribute a fill across contributing alphas.

        Returns list of ``(strategy_id, symbol, signed_qty, fill_price, fees)``
        tuples.  Uses largest-remainder method for integer rounding.
        Fees are allocated proportionally to each alpha's share of the fill.

        ``is_final=True`` pops the attribution record after allocation.
        ``is_final=False`` is used for ``PARTIALLY_FILLED`` acks so the
        record stays available for subsequent fills against the same
        order_id; per-contributor cumulative allocations are tracked so
        the largest-remainder split is computed over the cumulative
        filled quantity and the sum across partial fills equals the
        single-shot allocation for the same total (Inv-5 / Inv-13).

        If the order_id is unknown (e.g. emergency flatten), returns
        an empty list — the caller handles aggregate position updates.
        """
        record = self._records.get(order_id)
        if record is None:
            return []

        if not record.contributions:
            if is_final:
                self._records.pop(order_id, None)
                self._cumulative_allocations.pop(order_id, None)
            return []

        sign = 1 if record.net_side == Side.BUY else -1
        prev_cum = self._cumulative_allocations.get(order_id, [0] * len(record.contributions))
        prev_total = sum(prev_cum)
        new_cum = _largest_remainder_allocate(
            prev_total + filled_quantity,
            record.contributions,
        )
        allocations = [n - p for n, p in zip(new_cum, prev_cum, strict=True)]

        alloc_fees = split_fees(total_fees, allocations)
        result: list[tuple[str, str, int, Decimal, Decimal]] = []
        for contrib, alloc_qty, alloc_fee in zip(
            record.contributions,
            allocations,
            alloc_fees,
            strict=True,
        ):
            if alloc_qty == 0:
                continue
            contrib_sign = 1 if contrib.signed_quantity >= 0 else -1
            effective_sign = sign if contrib_sign >= 0 else -sign
            result.append(
                (
                    contrib.strategy_id,
                    record.symbol,
                    effective_sign * alloc_qty,
                    fill_price,
                    alloc_fee,
                )
            )

        if is_final:
            self._records.pop(order_id, None)
            self._cumulative_allocations.pop(order_id, None)
        else:
            self._cumulative_allocations[order_id] = new_cum

        return result


def _largest_remainder_allocate(
    total: int,
    contributions: tuple[AlphaContribution, ...],
) -> list[int]:
    """Allocate *total* across contributions by declared proportion."""
    return largest_remainder_split(total, [c.proportion for c in contributions])
