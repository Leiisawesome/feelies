"""Engine-8 forced-exit clamp: a mandated exit may shrink, never grow."""

from __future__ import annotations

import logging
from typing import Any

from feelies.core.events import AlertSeverity, OrderRequest, OrderType, Side
from feelies.core.identifiers import derive_order_id
from feelies.kernel.forced_exit_reasons import (
    _RISK_FORCED_EXIT_REASONS,
    _SLICE_SCOPED_FORCED_EXIT_REASONS,
)
from feelies.kernel.order_states import _TERMINAL_ORDER_STATES
from feelies.risk.hazard_exit import HAZARD_EXIT_SOURCE_LAYER

logger = logging.getLogger(__name__)


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
    return _forced_exit_closable_quantity(self, order) > 0


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


def _forced_exit_closable_quantity(self: Any, order: OrderRequest) -> int:
    """Shares *order* can close right now without crossing into new exposure.

    Magnitude shrinkage is **not** the test.  ``abs(current + signed) <
    abs(current)`` is true for any reduction, including one that crosses zero:
    a mandated ``SELL 100`` into a book a resting cover has already taken to
    long 70 shrinks the magnitude while flipping to short 30.  That is a
    fail-safe control opening exposure, which is exactly what Inv-11 forbids,
    so the clamp is on the closable side only.

    Slice-scoped authors (composer, deferral cap) may legitimately exceed
    symbol-net: another strategy holding the opposite side can leave the net
    flat while the mandated slice is still open, and flattening that slice
    moves the net through zero on purpose (design §3.3).  So they take the
    larger of the two bases rather than being clamped to net.
    """
    net = self._positions.get(order.symbol).quantity
    closable = _closable_quantity(net, order.side)
    if order.reason in _SLICE_SCOPED_FORCED_EXIT_REASONS and (
        self._strategy_positions is not None
    ):
        slice_qty = self._strategy_positions.get(order.strategy_id, order.symbol).quantity
        closable = max(closable, _closable_quantity(slice_qty, order.side))
    return min(order.quantity, closable)


def _emit_forced_exit_resized_alert(self: Any, order: OrderRequest, closable: int) -> None:
    """Publish a marker when a mandated exit is clamped to the settled book.

    The resting-order cancel settled a *partial* fill, so the exit's original
    quantity would now cross zero into opposite exposure.  It is resized to
    the residual rather than stood down, but an operator needs to see that the
    submitted size differs from what the controller authored (Inv-13).
    """
    self._publish_alert(
        timestamp_ns=self._clock.now_ns(),
        correlation_id=order.correlation_id,
        severity=AlertSeverity.WARNING,
        alert_name="forced_exit_resized_after_cancel",
        message=f"Forced exit {order.reason!r} on {order.symbol!r} resized {order.quantity} -> {closable}: cancelling resting orders settled a partial fill, and the original quantity would have crossed zero into opposite exposure (strategy_id={order.strategy_id!r}).",
        context={
            "symbol": order.symbol,
            "strategy_id": order.strategy_id,
            "order_id": order.order_id,
            "reason": order.reason,
            "original_quantity": order.quantity,
            "submitted_quantity": closable,
            "position_quantity": self._positions.get(order.symbol).quantity,
        },
    )


def _emit_forced_exit_stood_down_alert(self: Any, order: OrderRequest) -> None:
    """Publish a marker when a mandated exit stands down post-cancel.

    The resting-order cancel settled a fill that already closed the book, so
    submitting the exit's now-stale quantity would open the opposite side.
    Standing down is the fail-safe branch (Inv-11), but it is *not* routine —
    an operator needs to see that a mandated exit did not reach the router,
    and forensics needs it to explain the missing order (Inv-13).
    """
    self._publish_alert(
        timestamp_ns=self._clock.now_ns(),
        correlation_id=order.correlation_id,
        severity=AlertSeverity.WARNING,
        alert_name="forced_exit_stood_down_after_cancel",
        message=f"Forced exit {order.reason!r} on {order.symbol!r} stood down: cancelling resting orders settled a fill that already closed the book, so the exit's quantity ({order.quantity}) no longer reduces exposure (strategy_id={order.strategy_id!r}).",
        context={
            "symbol": order.symbol,
            "strategy_id": order.strategy_id,
            "order_id": order.order_id,
            "reason": order.reason,
            "order_quantity": order.quantity,
            "position_quantity": self._positions.get(order.symbol).quantity,
        },
    )


def _emit_forced_exit_supersedes_pending_alert(
    self: Any,
    order: OrderRequest,
    correlation_id: str,
) -> None:
    """Publish a forensic marker when a forced MARKET exit supersedes a
    stale resting order.

    Operator visibility (Inv-11): a hard-stop / session-flat MARKET exit
    cancelled a pending passive order for the symbol so the aggressive
    close could cross immediately.  Distinct from a duplicate-exit
    suppression so post-trade forensics can attribute the cancel-and-cross
    to the safety control rather than to alpha behaviour.
    """
    self._publish_alert(
        timestamp_ns=self._clock.now_ns(),
        correlation_id=correlation_id,
        severity=AlertSeverity.WARNING,
        alert_name="forced_exit_supersedes_pending_order",
        message=f"Forced MARKET exit {order.strategy_id!r} on {order.symbol!r}: cancelling resting order(s) so the aggressive close can cross immediately (Inv-11).",
        context={
            "symbol": order.symbol,
            "strategy_id": order.strategy_id,
            "order_id": order.order_id,
        },
    )


def _force_flatten_symbol_on_degrade(
    self: Any,
    symbol: str,
    correlation_id: str,
    *,
    reason: str,
) -> None:
    """Submit a market exit for one symbol during data-health degradation."""
    pos = self._positions.get(symbol)
    if pos.quantity == 0:
        return
    side = Side.SELL if pos.quantity > 0 else Side.BUY
    qty = abs(pos.quantity)
    seq = self._seq.next()
    order_id = derive_order_id(f"degrade_flatten:{reason}:{symbol}:{seq}")
    order = OrderRequest(
        timestamp_ns=self._clock.now_ns(),
        correlation_id=correlation_id,
        sequence=seq,
        order_id=order_id,
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=qty,
        strategy_id="degrade_flatten",
        reason=reason,
    )
    try:
        self._track_order(order_id, side, order)
        if order_id in self._active_orders:
            sm = self._active_orders[order_id][0]
            sm.transition(
                getattr(type(sm.state), "SUBMITTED"),
                trigger=f"degrade_flatten:{reason}",
                correlation_id=correlation_id,
            )
        self._submit_to_router(order, triggering_quote=self._in_flight_quote)
        self._bus.publish(order)
        self._settle_router_acks(correlation_id, expected_order_ids={order_id})
    except Exception as exc:  # noqa: BLE001 — fail-safe; never raise
        logger.exception(
            "Force-flatten on %s failed for symbol=%s (qty=%d, side=%s); "
            "position remains open and will require manual intervention.",
            reason,
            symbol,
            qty,
            side.name,
        )
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            severity=AlertSeverity.CRITICAL,
            alert_name="degrade_flatten_failed",
            message=f"Force-flatten on {reason} failed for symbol={symbol!r} (qty={qty}, side={side.name}). Position remains open.",
            context={"symbol": symbol, "reason": reason, "exception": repr(exc)},
        )
