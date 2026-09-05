"""Engine-8 forced-exit clamp: a mandated exit may shrink, never grow."""

from __future__ import annotations

from typing import Any

from feelies.core.events import OrderRequest, Side
from feelies.kernel.forced_exit_reasons import _RISK_FORCED_EXIT_REASONS
from feelies.kernel.order_states import _TERMINAL_ORDER_STATES
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


def _forced_exit_reduces(self: Any, order: OrderRequest) -> bool:
    """Whether *order* shrinks the live book it claims to close.

    A composer or deferral-cap exit is slice-scoped: another strategy holding
    the opposite side can leave symbol-net flat while the mandated slice is
    still open.  Treat the order as reducing when it shrinks *either* the
    symbol-net book or its own strategy slice, so a slice flatten is never
    stranded at the non-reducing REJECT branch.  Symbol-net is checked first,
    so a true symbol-net hazard exit (which always reduces net) never needs the
    slice fallback — this keeps the shared ``HARD_EXIT_AGE`` token correct for
    both authors without attributing it.

    Re-evaluated after any resting-order cancel, because the cancel reconciles
    whatever acks were already queued for those orders — including fills — so
    the book can move between the controller sizing the exit and the exit
    reaching the router.
    """
    return self._forced_exit_closable_quantity(order) > 0


def _has_pending_forced_exit_for_symbol(self: Any, symbol: str) -> bool:
    """True if a forced MARKET exit is already in flight for *symbol*.

    Distinguishes an aggressive exit already crossing the book from a
    merely-resting passive cover.  The resting-order guard cancels stale
    passive orders to let a forced MARKET exit through (Inv-11) but must
    not stack a second aggressive leg on top of one already pending —
    that would overshoot the position.

    Covers both mandated-exit authors — the kernel's synthetic stop /
    session-flat and the RISK-layer controllers routed through
    :meth:`_on_bus_derisk_requirement` — so neither can stack on the other.
    """
    return any(
        order.symbol == symbol
        and sm.state not in _TERMINAL_ORDER_STATES
        and _is_forced_market_exit(order)
        for sm, _, order in self._active_orders.values()
    )
