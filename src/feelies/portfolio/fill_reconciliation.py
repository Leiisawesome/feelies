"""Engine-7 fill accounting: slice ownership, journal legs, fill reconciliation."""

from __future__ import annotations

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
