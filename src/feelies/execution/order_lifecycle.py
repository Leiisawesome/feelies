"""Engine-10 order lifecycle: SM transitions, acks, submit, cancel, drain."""

from __future__ import annotations

from typing import Any

from feelies.execution.order_state import OrderState


def _transition_order(
    self: Any,
    order_id: str,
    target: OrderState,
    trigger: str,
    *,
    correlation_id: str = "",
) -> None:
    """Transition an order's state machine."""
    if order_id in self._active_orders:
        sm = self._active_orders[order_id][0]
        sm.transition(
            target,
            trigger=trigger,
            correlation_id=correlation_id,
        )
