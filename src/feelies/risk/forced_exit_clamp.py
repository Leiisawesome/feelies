"""Engine-8 forced-exit clamp: a mandated exit may shrink, never grow."""

from __future__ import annotations

from feelies.core.events import Side


def _closable_quantity(position_qty: int, side: Side) -> int:
    """Return shares that side can close without crossing through zero."""
    if side is Side.SELL:
        return max(position_qty, 0)
    return max(-position_qty, 0)
