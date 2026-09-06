"""Kernel-hosted terminal order-state set."""

from __future__ import annotations

_TERMINAL_ORDER_STATE_NAMES: frozenset[str] = frozenset(
    {
        "FILLED",
        "CANCELLED",
        "REJECTED",
        "EXPIRED",
    }
)


class _TerminalOrderStates:
    """Membership by ``OrderState`` member or name; no execution import."""

    def __contains__(self, item: object) -> bool:
        name = getattr(item, "name", item)
        return name in _TERMINAL_ORDER_STATE_NAMES


_TERMINAL_ORDER_STATES: _TerminalOrderStates = _TerminalOrderStates()
