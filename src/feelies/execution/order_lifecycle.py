"""Engine-10 order lifecycle: SM transitions, acks, submit, cancel, drain."""

from __future__ import annotations

from typing import Any

from feelies.core.events import (
    AlertSeverity,
    OrderAck,
    OrderAckStatus,
)
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


def _apply_ack_to_order(self: Any, ack: OrderAck) -> None:
    """Update an order's SM based on a broker acknowledgement.

    Uses typed ``OrderAckStatus`` enum — exhaustive matching ensures
    every status is handled explicitly (invariant 7, hard rule 2).
    When a valid status cannot be applied because the order SM is
    in an incompatible state, an alert is emitted instead of
    silently dropping the ack (invariant 13: full provenance).
    """
    cid = ack.correlation_id
    if ack.order_id not in self._active_orders:
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=cid,
            severity=AlertSeverity.WARNING,
            alert_name="ack_for_unknown_order",
            message=f"Ack for unknown order_id={ack.order_id}, status={ack.status.name}",
            context={"order_id": ack.order_id, "status": ack.status.name},
        )
        return
    sm = self._active_orders[ack.order_id][0]

    if ack.status == OrderAckStatus.REJECTED:
        if sm.can_transition(OrderState.REJECTED):
            sm.transition(
                OrderState.REJECTED,
                trigger=f"broker_reject:{ack.reason}",
                correlation_id=cid,
            )
        else:
            self._emit_ack_drop_alert(ack, sm)
        return

    if ack.status == OrderAckStatus.ACKNOWLEDGED:
        if sm.state == OrderState.SUBMITTED:
            sm.transition(
                OrderState.ACKNOWLEDGED,
                trigger="broker_ack",
                correlation_id=cid,
            )
        return

    # Ensure ACKNOWLEDGED before any fill/cancel/expiry transition.
    if sm.state == OrderState.SUBMITTED:
        sm.transition(
            OrderState.ACKNOWLEDGED,
            trigger="broker_ack",
            correlation_id=cid,
        )

    if ack.status == OrderAckStatus.FILLED:
        if sm.state == OrderState.FILLED:
            self._publish_alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=cid,
                severity=AlertSeverity.WARNING,
                alert_name="duplicate_terminal_fill_ack",
                message=f"Ignoring duplicate FILLED ack for order_id={ack.order_id} (already terminal FILLED).",
                context={"order_id": ack.order_id},
            )
            return
        if sm.can_transition(OrderState.FILLED):
            sm.transition(
                OrderState.FILLED,
                trigger="fill_complete",
                correlation_id=cid,
            )
        else:
            self._emit_ack_drop_alert(ack, sm)
        return

    if ack.status == OrderAckStatus.PARTIALLY_FILLED:
        if sm.can_transition(OrderState.PARTIALLY_FILLED):
            sm.transition(
                OrderState.PARTIALLY_FILLED,
                trigger="partial_fill",
                correlation_id=cid,
            )
        else:
            self._emit_ack_drop_alert(ack, sm)
        return

    if ack.status == OrderAckStatus.CANCELLED:
        if sm.can_transition(OrderState.CANCELLED):
            sm.transition(
                OrderState.CANCELLED,
                trigger="broker_cancel",
                correlation_id=cid,
            )
        else:
            self._emit_ack_drop_alert(ack, sm)
        return

    if ack.status == OrderAckStatus.EXPIRED:
        if sm.can_transition(OrderState.EXPIRED):
            sm.transition(
                OrderState.EXPIRED,
                trigger="order_expired",
                correlation_id=cid,
            )
        else:
            self._emit_ack_drop_alert(ack, sm)
        return

    raise ValueError(
        f"Unhandled OrderAckStatus: {ack.status!r}. "
        f"Fail-safe: all enum members must be explicitly handled."
    )


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
