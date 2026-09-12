"""Risk engine protocol — the sole gatekeeper between signal and execution.

The risk engine is independent and dominant.  It can veto any order
and trigger risk lockdown.  No strategy layer can bypass it (invariant 11).

Every order intent transits the risk engine; no direct
signal-to-execution path exists.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from feelies.core.events import (
    AlertSeverity,
    KillSwitchActivation,
    NBBOQuote,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
    Signal,
)
from feelies.core.identifiers import derive_order_id
from feelies.core.risk_protocol import RiskEngine as RiskEngine
from feelies.kernel.macro import MacroState
from feelies.risk.escalation import RiskLevel

logger = logging.getLogger(__name__)


def _compute_target_quantity(
    self: Any,
    signal: Signal,
    quote: NBBOQuote,
) -> int | None:
    """Use PositionSizer + AlphaRegistry to compute target quantity.

    Returns None if the registry is not available, letting the
    IntentTranslator fall back to its default.
    """
    if self._alpha_registry is None:
        return None

    try:
        alpha = self._alpha_registry.get(signal.strategy_id)
    except KeyError:
        return None

    risk_budget = alpha.manifest.risk_budget
    mid_price = (quote.bid + quote.ask) / Decimal(2)
    if mid_price <= 0:
        return 0

    # The alpha's declared risk budget is the sizing authority: this result
    # is never inflated.  ``platform_min_order_shares`` used to raise any
    # nonzero target up to the floor, which made the floor the binding
    # constraint and ``capital_allocation_pct`` inert — at 50k equity and
    # APP near $396 a 25% budget asks for 15-31 shares and every one of them
    # was raised to 50, so the platform traded 2.4x what the budget
    # sanctioned.  A control that autonomously *increases* exposure over a
    # declared budget is a loosening, and Inv-11 reserves those for a human.
    # The floor is now a venue lot-size veto only (see platform.yaml).
    qty: int = self._position_sizer.compute_target_quantity(
        signal=signal,
        risk_budget=risk_budget,
        symbol_price=mid_price,
        account_equity=self._account_equity,
    )
    return qty


def _maybe_flip_buying_power_at_rth_close(self: Any, quote: NBBOQuote) -> None:
    """Switch buying-power phase at each resolved RTH close.

    Multi-day replays re-arm the latch when the session date changes."""
    bounds = self._trading_session_bounds
    if bounds is None:
        return
    effective = bounds.resolve_for_timestamp(quote.exchange_timestamp_ns)
    set_phase = getattr(self._risk_engine, "set_buying_power_phase", None)

    # New NY session date → reopen on the intraday cap and re-arm the flip.
    if effective.session_date != self._rth_bp_session_date:
        self._rth_bp_session_date = effective.session_date
        if self._rth_close_bp_flipped:
            self._rth_close_bp_flipped = False
            if callable(set_phase):
                from feelies.risk.buying_power import BuyingPowerPhase

                set_phase(BuyingPowerPhase.INTRADAY)

    if self._rth_close_bp_flipped:
        return
    if quote.exchange_timestamp_ns < effective.rth_close_ns:
        return
    if not callable(set_phase):
        self._rth_close_bp_flipped = True
        return
    from feelies.risk.buying_power import BuyingPowerPhase

    set_phase(BuyingPowerPhase.OVERNIGHT)
    self._rth_close_bp_flipped = True


def _submit_tracked_order(
    self: Any,
    order: OrderRequest,
    *,
    trigger: str = "submitted",
) -> Exception | None:
    """Submit a tracked order and terminalize its state if routing fails."""
    order_id = order.order_id
    if order_id in self._active_orders:
        sm = self._active_orders[order_id][0]
        sm.transition(
            getattr(type(sm.state), "SUBMITTED"),
            trigger=trigger,
            correlation_id=order.correlation_id,
        )
    try:
        self._submit_to_router(order, triggering_quote=self._in_flight_quote)
    except Exception as exc:
        self._reject_order_after_submit_failure(order, exc)
        return exc
    return None


def _emergency_flatten_all(
    self: Any,
    correlation_id: str,
) -> tuple[dict[str, str], dict[str, int]]:
    """Cancel resting orders and submit market exits for every open position."""
    positions = self._positions.all_positions()
    failures: dict[str, str] = {}
    # Iterate in lexicographic symbol order so the emitted
    # OrderRequest stream is bit-identical across replays even
    # when the position store's insertion order differs (Inv-5).
    for symbol in sorted(positions):
        pos = positions[symbol]
        if pos.quantity == 0:
            continue
        side = Side.SELL if pos.quantity > 0 else Side.BUY
        qty = abs(pos.quantity)
        seq = self._seq.next()
        order_id = derive_order_id(f"emergency_flatten:{correlation_id}:{symbol}:{seq}")

        order = OrderRequest(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            sequence=seq,
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=qty,
            strategy_id="emergency_flatten",
            # Price lockdown fills with panic slippage and depleted depth.
            reason="FORCE_FLATTEN",
        )

        try:
            self._track_order(order_id, side, order)
            submit_exc = _submit_tracked_order(
                self, order, trigger="emergency_flatten"
            )
            if submit_exc is not None:
                failures[symbol] = f"submit_exception: {submit_exc!r}"
                continue

            self._bus.publish(order)
            acks = self._settle_router_acks(correlation_id, expected_order_ids={order_id})
            # A reject / zero-fill ack still leaves the position open.
            # Surface it as a failure so the residual alert sees it.
            non_fill_acks = [
                a
                for a in acks
                if a.order_id == order_id
                and (a.filled_quantity or 0) == 0
                and a.status in (OrderAckStatus.REJECTED, OrderAckStatus.CANCELLED)
            ]
            if non_fill_acks:
                failures[symbol] = (
                    f"{non_fill_acks[0].status.name}: {non_fill_acks[0].reason or 'no reason'}"
                )
        except Exception as exc:
            logger.exception(
                "Emergency flatten failed for %s (qty=%d) -- "
                "position may remain open at LOCKED",
                symbol,
                pos.quantity,
            )
            failures[symbol] = f"submit_exception: {exc!r}"
            if order_id in self._active_orders:
                self._force_order_terminal_after_pipeline_error(
                    order,
                    exc,
                    context="emergency_flatten",
                )

    residual: dict[str, int] = {
        sym: p.quantity
        for sym, p in self._positions.all_positions().items()
        if p.quantity != 0
    }
    if residual or failures:
        msg = (
            f"Emergency flatten incomplete — residual positions: "
            f"{residual}, total_exposure={self._positions.total_exposure()}, "
            f"failures={failures}"
        )
        logger.critical(msg)
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            severity=AlertSeverity.CRITICAL,
            alert_name="emergency_flatten_incomplete",
            message=msg,
        )
    return failures, residual


def _escalate_risk(self: Any, correlation_id: str) -> None:
    """Escalate through R0 → R1 → R2 → R3 → R4 → macro G8.

    Monotonically tightens safety (platform inv 11).  Once R1
    (WARNING) is entered, de-escalation is impossible without
    completing the full cycle to R4 and human unlock.

    At R3 (FORCED_FLATTEN) we attempt to close all non-zero
    positions via emergency market orders before transitioning
    to R4 (LOCKED).
    """
    level = self._risk_escalation.state

    if level == RiskLevel.NORMAL:
        self._risk_escalation.transition(
            RiskLevel.WARNING,
            trigger="risk_threshold_approaching",
            correlation_id=correlation_id,
        )
        level = RiskLevel.WARNING

    if level == RiskLevel.WARNING:
        self._risk_escalation.transition(
            RiskLevel.BREACH_DETECTED,
            trigger="risk_breach_confirmed",
            correlation_id=correlation_id,
        )
        level = RiskLevel.BREACH_DETECTED

    if level == RiskLevel.BREACH_DETECTED:
        self._risk_escalation.transition(
            RiskLevel.FORCED_FLATTEN,
            trigger="forced_flatten_initiated",
            correlation_id=correlation_id,
        )
        level = RiskLevel.FORCED_FLATTEN

    if level == RiskLevel.FORCED_FLATTEN:
        failures, residual = _emergency_flatten_all(self, correlation_id)
        flatten_clean = not failures and not residual
        self._risk_escalation.transition(
            RiskLevel.LOCKED,
            trigger=(
                "positions_zero_flatten_complete"
                if flatten_clean
                else "emergency_flatten_incomplete_residual_exposure"
            ),
            correlation_id=correlation_id,
        )

    if self._kill_switch is not None:
        self._kill_switch.activate(
            reason="risk_escalation_lockdown",
            activated_by="orchestrator",
        )
        self._bus.publish(
            KillSwitchActivation(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=correlation_id,
                sequence=self._seq.next(),
                reason="risk_escalation_lockdown",
                activated_by="orchestrator",
            )
        )

    self._macro.transition(
        MacroState.RISK_LOCKDOWN,
        trigger="RISK_BREACH",
        correlation_id=correlation_id,
    )
