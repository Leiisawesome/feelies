"""Order lifecycle state machine (Section V of the system diagram).

Each order has its own state machine instance.  Every transition
is triggered by an explicit event.  No inferred states.

The backtest engine must simulate this same state machine.
If live order transitions deviate from simulated expectations,
flag structural drift.
"""

from __future__ import annotations

from enum import Enum, auto

from feelies.core.clock import Clock
from feelies.core.state_machine import StateMachine


class OrderState(Enum):
    """Explicit order lifecycle states.  Terminal states have no outbound edges."""

    CREATED = auto()
    SUBMITTED = auto()
    ACKNOWLEDGED = auto()
    PARTIALLY_FILLED = auto()
    FILLED = auto()              # terminal
    CANCEL_REQUESTED = auto()
    CANCELLED = auto()           # terminal
    REJECTED = auto()            # terminal
    EXPIRED = auto()             # terminal


_ORDER_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.CREATED: frozenset({
        OrderState.SUBMITTED,
    }),
    OrderState.SUBMITTED: frozenset({
        OrderState.ACKNOWLEDGED,
        OrderState.REJECTED,
    }),
    OrderState.ACKNOWLEDGED: frozenset({
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCEL_REQUESTED,
        OrderState.EXPIRED,
    }),
    # Real brokers permit cancel-the-remainder and TIF expiry on a
    # partially-filled order.  Omitting these edges would silently drop
    # valid broker acks in live mode (kernel emits ack_inapplicable_to_order_state).
    OrderState.PARTIALLY_FILLED: frozenset({
        OrderState.PARTIALLY_FILLED,   # additional partial
        OrderState.FILLED,             # fully filled
        OrderState.CANCEL_REQUESTED,   # client cancels remainder
        OrderState.CANCELLED,          # broker-initiated cancel of remainder
        OrderState.EXPIRED,            # TIF timeout with partial fills booked
    }),
    OrderState.CANCEL_REQUESTED: frozenset({
        OrderState.CANCELLED,         # O5 → O6  cancel confirmed
        OrderState.FILLED,            # O5 → O4  fill beats cancel
    }),
    # Terminal states — no outbound edges
    OrderState.FILLED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.REJECTED: frozenset(),
    OrderState.EXPIRED: frozenset(),
}


def create_order_state_machine(
    order_id: str,
    clock: Clock,
) -> StateMachine[OrderState]:
    """Create a state machine for a single order, starting at CREATED."""
    return StateMachine(
        name=f"order:{order_id}",
        initial_state=OrderState.CREATED,
        transitions=_ORDER_TRANSITIONS,
        clock=clock,
    )
