"""Engine-7 fill accounting: slice ownership, journal legs, fill reconciliation."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from feelies.core.events import OrderRequest, Side
from feelies.kernel.orchestrator import (
    _RISK_FORCED_EXIT_REASONS,
    _SELF_ATTRIBUTED_FORCED_EXIT_REASONS,
)
from feelies.portfolio.fill_attribution import largest_remainder_split, split_fees

logger = logging.getLogger(__name__)


def _order_owns_one_slice(order: OrderRequest) -> bool:
    """Return whether every fill belongs to the order strategy slice."""
    if not order.strategy_id:
        return False
    if order.reason in _SELF_ATTRIBUTED_FORCED_EXIT_REASONS:
        return True
    return order.reason not in _RISK_FORCED_EXIT_REASONS


@dataclass(frozen=True, kw_only=True)
class _TradeJournalLeg:
    """One trade-journal row's share of a single fill."""

    strategy_id: str
    filled_quantity: int
    fees: Decimal
    realized_pnl: Decimal
    metadata: dict[str, str]


def _trade_journal_legs(
    order: OrderRequest,
    *,
    filled_quantity: int,
    fees: Decimal,
    realized_pnl: Decimal,
    attributed_legs: Sequence[tuple[str, int, Decimal, Decimal]],
    announced_quantity: int | None = None,
) -> list[_TradeJournalLeg]:
    """Build per-strategy journal rows for one fill.

    Slice-owned orders keep one owner; symbol-net exits use attributed slice economics. Missing attribution falls back to one aggregate row."""
    base_metadata = {
        "order_reason": order.reason,
        "order_source_layer": order.source_layer,
    }
    if announced_quantity is not None:
        # Present only when the kernel clamped this exit, so its presence is
        # itself the signal that submitted size != announced size.
        base_metadata["forced_exit_announced_quantity"] = str(announced_quantity)
    if not attributed_legs:
        return [
            _TradeJournalLeg(
                strategy_id=order.strategy_id,
                filled_quantity=filled_quantity,
                fees=fees,
                realized_pnl=realized_pnl,
                metadata=base_metadata,
            )
        ]

    # Preserve each slice's realized PnL instead of blending aggregate basis.
    owns_one_slice = _order_owns_one_slice(order)
    metadata = (
        base_metadata
        if owns_one_slice
        else {**base_metadata, "forced_exit_strategy_id": order.strategy_id}
    )
    return [
        _TradeJournalLeg(
            strategy_id=strategy_id,
            filled_quantity=abs(qty),
            fees=leg_fees,
            realized_pnl=leg_realized,
            metadata=dict(metadata),
        )
        for strategy_id, qty, leg_fees, leg_realized in attributed_legs
    ]


def _record_fill_attribution(
    self: Any,
    order_id: str,
    side: Side,
    order: OrderRequest,
) -> None:
    """Record deterministic strategy allocations for an order.

    Single-slice orders self-attribute; symbol-net exits allocate across live slices."""
    if self._fill_ledger is None or not _order_owns_one_slice(order):
        return
    from feelies.portfolio.fill_attribution import AlphaContribution, AttributionRecord

    self._fill_ledger.record(
        AttributionRecord(
            order_id=order_id,
            symbol=order.symbol,
            net_side=side,
            net_quantity=order.quantity,
            contributions=(
                AlphaContribution(
                    strategy_id=order.strategy_id,
                    signed_quantity=order.quantity,
                    proportion=1.0,
                ),
            ),
        )
    )


def _distribute_fill_to_strategies(
    self: Any,
    symbol: str,
    signed_qty: int,
    fill_price: Decimal,
    fees: Decimal,
    timestamp_ns: int,
) -> list[tuple[str, int, Decimal, Decimal]]:
    """Distribute a fill proportionally across per-alpha strategy positions.

    Used when no fill-attribution record exists (emergency flatten,
    stop exit, or attribution failure).  Distributes ``signed_qty``
    proportionally to each strategy's current quantity for this
    symbol, keeping global and strategy position stores in sync.

    Uses largest-remainder rounding so the sum of per-alpha deltas
    equals ``signed_qty`` exactly.

    Returns the ``(strategy_id, signed_quantity, fees, realized_delta)`` legs it
    applied — ``realized_delta`` measured around each slice's own update, so the
    caller can journal a symbol-net forced exit against the slices it actually
    closed instead of the synthetic order's ``strategy_id`` (Inv-13).  Empty when
    no slice book is wired or no strategy holds the symbol.
    """
    if self._strategy_positions is None:
        return []

    # Inv-5: iterate strategies in a deterministic (sorted) order.
    # ``strategy_ids()`` returns a ``frozenset``; materialising it directly
    # would make the largest-remainder tie-break and per-alpha fee split
    # depend on hash-iteration order (process/seed dependent).
    strategy_ids = sorted(self._strategy_positions.strategy_ids())
    if not strategy_ids:
        return []

    # Reducing fills allocate only across slices on the closable side.
    strategy_qtys: list[tuple[str, int]] = []
    for sid in strategy_ids:
        q = self._strategy_positions.get(sid, symbol).quantity
        if q * signed_qty < 0:
            strategy_qtys.append((sid, q))
    if not strategy_qtys:
        # Increasing fills fall back across holders; warn only on store drift.
        strategy_qtys = [
            (sid, q)
            for sid in strategy_ids
            if (q := self._strategy_positions.get(sid, symbol).quantity) != 0
        ]
        if strategy_qtys:
            slice_book_net = sum(q for _sid, q in strategy_qtys)
            symbol_net = self._positions.get(symbol).quantity
            if slice_book_net + signed_qty != symbol_net:
                logger.warning(
                    "Fill attribution for %s: the slice book and the symbol-net "
                    "store have diverged (slices sum to %d, symbol-net %d after a "
                    "%d-share fill); falling back to a split across all %d holders.",
                    symbol,
                    slice_book_net,
                    symbol_net,
                    signed_qty,
                    len(strategy_qtys),
                )
    if not strategy_qtys:
        return []

    # Same rounding and fee convention the ledger uses, so a fill rounds
    # identically whichever path attributes it.
    abs_fill = abs(signed_qty)
    alloc_qtys = largest_remainder_split(abs_fill, [abs(q) for _sid, q in strategy_qtys])
    alloc_fees = split_fees(fees, alloc_qtys)

    applied: list[tuple[str, int, Decimal, Decimal]] = []
    alloc_sign = 1 if signed_qty > 0 else -1
    for (sid, _q), alloc_qty, alloc_fee in zip(
        strategy_qtys, alloc_qtys, alloc_fees, strict=True
    ):
        if alloc_qty == 0:
            continue
        prev_slice = self._strategy_positions.get(sid, symbol).realized_pnl
        slice_position = self._strategy_positions.update(
            sid,
            symbol,
            alloc_sign * alloc_qty,
            fill_price,
            fees=alloc_fee,
            timestamp_ns=timestamp_ns,
        )
        applied.append(
            (
                sid,
                alloc_sign * alloc_qty,
                alloc_fee,
                slice_position.realized_pnl - prev_slice,
            )
        )

    return applied
