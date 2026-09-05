"""Engine-8 forced-exit clamp: a mandated exit may shrink, never grow."""

from __future__ import annotations

from feelies.core.events import OrderRequest, Side
from feelies.kernel.forced_exit_reasons import _RISK_FORCED_EXIT_REASONS
from feelies.risk.hazard_exit import HAZARD_EXIT_SOURCE_LAYER


def _closable_quantity(position_qty: int, side: Side) -> int:
    """Return shares that side can close without crossing through zero."""
    if side is Side.SELL:
        return max(position_qty, 0)
    return max(-position_qty, 0)


def _is_forced_market_exit(order: OrderRequest) -> bool:
    """Identify controller-authored aggressive exits routed through the risk bridge."""
    return (
        order.source_layer == HAZARD_EXIT_SOURCE_LAYER
        and order.reason in _RISK_FORCED_EXIT_REASONS
    )
