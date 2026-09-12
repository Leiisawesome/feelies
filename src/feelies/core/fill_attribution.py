"""Fill attribution types and FillAttributionLedger protocol.

AttributionRecord, AlphaContribution, largest_remainder_split, and
split_fees live in core so kernel can name them without importing
portfolio. The concrete ledger stays in feelies.portfolio.fill_attribution.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
import math
from typing import Protocol

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


class FillAttributionLedger(Protocol):
    """Injected fill ledger. Kernel names record and allocate_fill."""

    def record(self, record: AttributionRecord) -> None:
        """Store an attribution record keyed by order_id."""
        ...

    def allocate_fill(
        self,
        order_id: str,
        filled_quantity: int,
        fill_price: Decimal,
        total_fees: Decimal = Decimal("0"),
        is_final: bool = True,
    ) -> list[tuple[str, str, int, Decimal, Decimal]]:
        """Distribute a fill across contributing alphas."""
        ...


def largest_remainder_split(total: int, weights: Sequence[float]) -> list[int]:
    """Split *total* integer units across *weights* proportionally.

    Largest-remainder method: floor each exact share, then hand the leftover
    units one at a time to the largest fractional remainders.  The result sums to
    *total* exactly, which is what keeps a per-alpha split reconciling against the
    fill it came from.

    Two callers share this: the ledger splits by each alpha's declared
    contribution to a netted order, and the kernel's symbol-net fallback splits by
    each slice's current position.  The *basis* differs by design; the rounding
    must not, or the same fill would round differently depending on which path
    attributed it — and per-alpha PnL feeds the promotion gates.

    All-zero (or non-positive) weights fall back to an even split so a fill is
    never silently dropped.

    Determinism (Inv-5): ties break by index via a stable sort, so the caller's
    ordering — not dict or set iteration order — decides who gets the odd unit.
    """
    n = len(weights)
    if n == 0:
        return []

    total_weight = math.fsum(abs(w) for w in weights)
    if total_weight <= 0:
        base = total // n
        remainder = total - base * n
        return [base + (1 if i < remainder else 0) for i in range(n)]

    exact = [total * abs(w) / total_weight for w in weights]
    floors = [int(e) for e in exact]
    remainders = [e - f for e, f in zip(exact, floors)]

    deficit = total - sum(floors)
    indices = sorted(range(len(remainders)), key=lambda i: -remainders[i])
    for i in range(deficit):
        floors[indices[i]] += 1

    return floors


def split_fees(total_fees: Decimal, allocations: Sequence[int]) -> list[Decimal]:
    """Split *total_fees* in proportion to *allocations*, to the cent.

    Quantising each share loses a residue, so the remainder is handed to the last
    non-zero allocation.  The returned list sums to ``total_fees`` exactly — a
    caller reconciling per-alpha fees against the ack's fees must not find a gap.

    Zero allocations receive zero.  An all-zero allocation vector returns all
    zeros, leaving the caller to account for the fee itself.
    """
    out = [Decimal("0")] * len(allocations)
    total_allocated = sum(a for a in allocations if a > 0)
    if total_allocated <= 0:
        return out

    remainder = total_fees
    last_nonzero = -1
    for idx, alloc in enumerate(allocations):
        if alloc <= 0:
            continue
        share = (total_fees * alloc / total_allocated).quantize(Decimal("0.01"))
        out[idx] = share
        remainder -= share
        last_nonzero = idx
    if remainder != Decimal("0") and last_nonzero >= 0:
        out[last_nonzero] += remainder
    return out
