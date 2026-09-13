"""Engine-10 order lifecycle: cancel remains; other helpers live in kernel."""

from __future__ import annotations

from typing import Any

from feelies.core.events import AlertSeverity
from feelies.execution.order_state import OrderState


def cancel_order(self: Any, order_id: str, *, reason: str = "operator") -> bool:
    """Request cancellation of an active order.

    Valid kernel transitions into ``CANCEL_REQUESTED`` follow the
    ``OrderState`` table (typically from ``ACKNOWLEDGED`` or
    ``PARTIALLY_FILLED``).

    When ``order_router.cancel_order`` exists it is invoked and the
    resulting acks are reconciled.  Routers without cancel support
    emit ``cancel_order_router_unsupported`` and immediately resolve
    the SM to ``CANCELLED`` (no broker ack is possible in backtest).

    Returns True if the SM accepted ``CANCEL_REQUESTED``, False when
    the order is missing or cannot cancel from its current state.
    """
    if order_id not in self._active_orders:
        return False
    sm = self._active_orders[order_id][0]
    if not sm.can_transition(OrderState.CANCEL_REQUESTED):
        return False
    order = self._active_orders[order_id][2]
    sm.transition(
        OrderState.CANCEL_REQUESTED,
        trigger=f"cancel_requested:{reason}",
        correlation_id=order.correlation_id,
    )
    cancel_fn = getattr(self._backend.order_router, "cancel_order", None)
    if cancel_fn is None:
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=order.correlation_id,
            severity=AlertSeverity.WARNING,
            alert_name="cancel_order_router_unsupported",
            message=f"cancel_order requested for {order_id!r} but {type(self._backend.order_router).__name__} has no cancel_order(...) — resolving SM to CANCELLED locally (Inv-4 shutdown hygiene).",
            context={"order_id": order_id},
        )
        sm2 = self._active_orders[order_id][0]
        if sm2.can_transition(OrderState.CANCELLED):
            sm2.transition(
                OrderState.CANCELLED,
                trigger="cancel_router_unsupported_local_terminal",
                correlation_id=order.correlation_id,
            )
        self._prune_terminal_orders()
        return True
    accepted = cancel_fn(order_id)
    self._settle_router_acks(order.correlation_id, expected_order_ids={order_id})
    # Accepted broker cancels resolve asynchronously; rejected ones resolve locally.
    if not accepted and order_id in self._active_orders:
        sm_post = self._active_orders[order_id][0]
        if sm_post.state == OrderState.CANCEL_REQUESTED:
            if sm_post.can_transition(OrderState.CANCELLED):
                sm_post.transition(
                    OrderState.CANCELLED,
                    trigger="cancel_no_broker_ack_local_terminal",
                    correlation_id=order.correlation_id,
                )
    self._prune_terminal_orders()
    return True
