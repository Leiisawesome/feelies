"""Engine-10 order lifecycle: SM transitions, acks, submit, cancel, drain."""

from __future__ import annotations

from typing import Any

from feelies.core.events import OrderAck
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


def _poll_order_router_acks(
    self: Any,
    expected_order_ids: set[str] | None = None,
) -> list[OrderAck]:
    """Drain router acks, buffering unrelated ones for the next caller.

    The execution backend exposes a single pending-ack queue shared by
    immediate submit/cancel acks and quote-driven fills from previously
    resting orders.  Callers that just submitted a specific order family
    must not steal unrelated pending acks and reconcile them under the
    wrong correlation lineage.
    """
    polled = self._backend.order_router.poll_acks()
    if self._deferred_router_acks:
        all_acks = [*self._deferred_router_acks, *polled]
        self._deferred_router_acks.clear()
    else:
        all_acks = polled

    if expected_order_ids is None:
        return all_acks

    matched: list[OrderAck] = []
    deferred: list[OrderAck] = []
    for ack in all_acks:
        if ack.order_id in expected_order_ids:
            matched.append(ack)
        else:
            deferred.append(ack)
    self._deferred_router_acks.extend(deferred)
    return matched
