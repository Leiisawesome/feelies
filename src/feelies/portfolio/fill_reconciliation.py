"""Engine-7 fill accounting: slice ownership, journal legs, fill reconciliation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from feelies.core.events import OrderRequest
from feelies.kernel.orchestrator import (
    _RISK_FORCED_EXIT_REASONS,
    _SELF_ATTRIBUTED_FORCED_EXIT_REASONS,
)


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
