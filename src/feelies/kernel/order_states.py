"""Kernel-hosted terminal order-state set."""

from __future__ import annotations

from feelies.execution.order_state import OrderState

_TERMINAL_ORDER_STATES: frozenset[OrderState] = frozenset(
    {
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
    }
)
