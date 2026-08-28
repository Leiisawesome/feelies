"""Engine-9 order policy: edge-vs-cost gates, routing, and order construction."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

from feelies.core.events import (
    AlertSeverity,
    NBBOQuote,
    OrderRequest,
    OrderType,
    RiskAction,
    RiskVerdict,
    Side,
    Signal,
    SizedPositionIntent,
)
from feelies.core.identifiers import derive_order_id
from feelies.execution.intent import OrderIntent, TradingIntent
from feelies.execution.order_admission import (
    BLOCK_BELOW_MIN_ORDER_SHARES,
    ExposureDelta,
    admission_block_reason,
    blocks_for_min_size,
    exposure_delta_from_intent,
)
from feelies.execution.position_manager import (
    DesiredPosition,
    ExecStyle,
    PositionManagerConfig,
    PositionPlan,
    desired_from_signal,
    entry_edge_clears_cost,
    reversal_edge_gate,
    round_trip_cost_bps,
)
from feelies.execution.regulatory.borrow_availability import BorrowTier, htb_fee_applies
from feelies.kernel.macro import MacroState
from feelies.kernel.micro import MicroState
from feelies.portfolio.position_store import Position
from feelies.risk.engine import _escalate_risk
from feelies.risk.post_exit_position_view import PostExitPositionView


def _round_trip_cost_bps(
    self: Any,
    *,
    symbol: str,
    entry_side: Side,
    quantity: int,
    quote: NBBOQuote,
    is_taker_entry: bool,
    is_short_entry: bool,
) -> float:
    """Model entry plus taker-exit cost using current quote and impact settings."""
    assert self._cost_model is not None
    return round_trip_cost_bps(
        self._cost_model,
        symbol=symbol,
        entry_side=entry_side,
        quantity=quantity,
        mid_price=(quote.bid + quote.ask) / Decimal("2"),
        half_spread=(quote.ask - quote.bid) / Decimal("2"),
        is_taker_entry=is_taker_entry,
        is_short_entry=is_short_entry,
        bid_size=quote.bid_size,
        ask_size=quote.ask_size,
        market_impact_factor=self._market_context.market_impact_factor,
        max_impact_half_spreads=self._market_context.max_impact_half_spreads,
        within_l1_impact_factor=self._market_context.within_l1_impact_factor,
        permanent_impact_coefficient=(self._market_context.permanent_impact_coefficient),
    )


def _edge_clears_round_trip_cost(
    self: Any,
    *,
    strategy_id: str,
    edge_estimate_bps: float,
    symbol: str,
    entry_side: Side,
    quantity: int,
    quote: NBBOQuote,
    is_taker_entry: bool,
    is_short_entry: bool,
) -> tuple[bool, float, float]:
    """Inv-12 B4 in one place: does calibrated edge clear modelled cost?

    Returns ``(passes, effective_edge_bps, realization_factor)`` so callers
    can report *why* without re-deriving the arithmetic.  Both order paths
    run this: the SIGNAL path via
    :meth:`_signal_passes_edge_cost_gate` (which owns the forensic alert),
    the PORTFOLIO path via :meth:`_portfolio_leg_clears_edge_gate`, whose
    legs carry ``TargetPosition.expected_edge_bps`` instead of a ``Signal``.
    """
    if self._signal_min_edge_cost_ratio <= 0 or self._cost_model is None:
        return True, edge_estimate_bps, 1.0
    rt_cost_bps = _round_trip_cost_bps(self,
        symbol=symbol,
        entry_side=entry_side,
        quantity=quantity,
        quote=quote,
        is_taker_entry=is_taker_entry,
        is_short_entry=is_short_entry,
    )
    # Gate on realization-calibrated edge; missing factors default to one.
    factor = self._edge_calibration_factors.get(strategy_id, 1.0)
    effective_edge_bps = edge_estimate_bps * factor
    passes = entry_edge_clears_cost(
        edge_bps=effective_edge_bps,
        rt_cost_bps=rt_cost_bps,
        min_ratio=self._signal_min_edge_cost_ratio,
        basis=self._signal_edge_cost_basis,
    )
    return passes, effective_edge_bps, factor


def _signal_passes_edge_cost_gate(
    self: Any,
    signal: Signal,
    *,
    symbol: str,
    entry_side: Side,
    quantity: int,
    quote: NBBOQuote,
    is_taker_entry: bool,
    is_short_entry: bool,
    correlation_id: str,
    detail: str,
) -> bool:
    """Return whether calibrated edge clears modeled round-trip cost."""
    passes, effective_edge_bps, factor = _edge_clears_round_trip_cost(self,
        strategy_id=signal.strategy_id,
        edge_estimate_bps=signal.edge_estimate_bps,
        symbol=symbol,
        entry_side=entry_side,
        quantity=quantity,
        quote=quote,
        is_taker_entry=is_taker_entry,
        is_short_entry=is_short_entry,
    )
    if passes:
        return True
    gate_detail = (
        detail
        if factor >= 1.0
        else f"{detail}; realization factor={factor:.3f} "
        f"(disclosed {signal.edge_estimate_bps:.2f} -> {effective_edge_bps:.2f} bps)"
    )
    self._emit_signal_edge_gate_suppression_alert(
        signal,
        symbol,
        correlation_id,
        detail=gate_detail,
    )
    return False


def _reversal_passes_combined_edge_gate(
    self: Any,
    *,
    edge_estimate_bps: float,
    symbol: str,
    exit_side: Side,
    exit_qty: int,
    entry_side: Side,
    entry_qty: int,
    quote: NBBOQuote,
    is_short_entry: bool,
) -> tuple[float, float, bool]:
    """Return whether reversal edge clears the combined exit and entry cost."""
    if self._reversal_min_edge_cost_multiplier <= 0 or self._cost_model is None:
        return 0.0, 0.0, True
    # The aggressive close is a taker but never a new short.
    exit_roundtrip_cost_bps = _round_trip_cost_bps(self,
        symbol=symbol,
        entry_side=exit_side,
        quantity=exit_qty,
        quote=quote,
        is_taker_entry=True,
        is_short_entry=False,
    )
    # Price the new-direction entry on the same basis as the entry gate.
    entry_roundtrip_cost_bps = _round_trip_cost_bps(self,
        symbol=symbol,
        entry_side=entry_side,
        quantity=entry_qty,
        quote=quote,
        is_taker_entry=(not self._use_passive_entries or self._min_cost_policy is not None),
        is_short_entry=is_short_entry,
    )
    return reversal_edge_gate(
        edge_bps=edge_estimate_bps,
        exit_cost_bps=exit_roundtrip_cost_bps,
        entry_cost_bps=entry_roundtrip_cost_bps,
        multiplier=self._reversal_min_edge_cost_multiplier,
    )


def _plan_for_signal(
    self: Any,
    signal: Signal,
    current_position: Position,
    target_qty: int | None,
    quote: NBBOQuote,
    *,
    desired: DesiredPosition | None = None,
) -> PositionPlan:
    """Build the planner's ``PositionPlan`` for a signal.

    Shared by shadow comparison and the active planner path.
    Resolves the ``None`` sizer target via the translator default so
    the planner sees the translator's effective magnitude.
    ``desired`` overrides the per-signal target with a net target.
    """
    assert self._position_manager is not None
    if desired is None:
        default_target = getattr(
            self._intent_translator,
            "_default_target",
            100,
        )
        desired = desired_from_signal(
            signal,
            target_qty,
            default_target_quantity=default_target,
        )
    plan: PositionPlan = self._position_manager.plan(
        desired=desired,
        current=current_position,
        market=replace(
            self._market_context,
            quote=quote,
            cost_model=self._cost_model,
        ),
        config=PositionManagerConfig(
            shadow=False,
            enabled=True,
            enable_trim=self._position_manager_enable_trim,
            trim_edge_gate_multiplier=(self._position_manager_trim_edge_gate_multiplier),
            urgency_exec=self._position_manager_urgency_exec,
        ),
    )
    return plan


def _resolve_order_route(
    self: Any,
    *,
    strategy_id: str,
    symbol: str,
    side: Side,
    quantity: int,
    quote: NBBOQuote | None,
    is_short: bool,
    is_exit_or_stop: bool,
    edge_bps: float,
    exec_style: ExecStyle | None = None,
) -> tuple[OrderType, Decimal | None, bool]:
    """Resolve order type, limit price, and MOC flag from execution policy."""
    is_moc = (
        strategy_id in self._moc_strategy_ids
        and self._moc_bounds_configured
        and not is_exit_or_stop
    )
    if is_moc:
        return OrderType.MARKET, None, True

    if exec_style is ExecStyle.PASSIVE and quote is not None:
        limit_price = quote.bid if side == Side.BUY else quote.ask
        return OrderType.LIMIT, limit_price, False

    if not self._use_passive_entries or quote is None:
        return OrderType.MARKET, None, False

    use_passive = True
    if self._min_cost_policy is not None:
        use_passive = (
            self._min_cost_policy.decide(
                symbol=symbol,
                side=side,
                quantity=quantity,
                mid_price=(quote.bid + quote.ask) / Decimal("2"),
                half_spread=(quote.ask - quote.bid) / Decimal("2"),
                is_short=is_short,
                force_aggressive=is_exit_or_stop,
                bid_size=quote.bid_size,
                ask_size=quote.ask_size,
                edge_bps=edge_bps,
            )
            == "passive"
        )
    if use_passive:
        return (
            OrderType.LIMIT,
            quote.bid if side == Side.BUY else quote.ask,
            False,
        )
    return OrderType.MARKET, None, False


def _filter_portfolio_orders_for_admission(
    self: Any,
    orders: list[OrderRequest],
    *,
    intent: SizedPositionIntent,
    correlation_id: str,
    quote: NBBOQuote | None = None,
) -> list[OrderRequest]:
    """Drop PORTFOLIO legs refused by the shared Inv-11 admission gates.

    Until this filter existed the composition path reached
    ``order_router.submit`` without passing the halt blackout, the
    session-flatten window, SSR, locate availability or the minimum-order
    floor — every one of which the standalone SIGNAL path applies.  The
    policy is :func:`~feelies.execution.order_admission.admission_block_reason`;
    this method only supplies the environment and the per-leg exposure
    delta.

    The delta is re-read from the live book rather than carried from
    ``plan_leg``: a leg is admitted against the book as it stands now, not
    as it stood when the intent was priced.

    Reducing legs are exempt from every gate by construction (the policy
    conditions each one on the order adding exposure), so a PORTFOLIO
    unwind can never be refused by a halt or an SSR flag.
    """
    filtered: list[OrderRequest] = []
    for order in orders:
        current = self._positions.get(order.symbol).quantity
        signed = order.quantity if order.side is Side.BUY else -order.quantity
        delta = ExposureDelta(current_quantity=current, signed_quantity=signed)
        block = admission_block_reason(
            opens_exposure=delta.opens_or_increases_exposure,
            opens_short=delta.opens_or_increases_short,
            in_halt_blackout=self._in_halt_blackout(order.symbol, intent.timestamp_ns),
            in_session_flatten_window=self._in_session_flatten_window_at(intent.timestamp_ns),
            ssr_active=order.symbol.upper() in self._ssr_active,
            locate_unavailable=(self._borrow_tier_for(order.symbol) == BorrowTier.UNAVAILABLE),
            quantity=order.quantity,
            min_order_shares=self._min_order_shares,
            exempt_from_min_size=not delta.opens_or_increases_exposure,
        )
        if block is None:
            block = self._portfolio_leg_edge_block(
                order,
                intent=intent,
                delta=delta,
                quote=quote,
            )
        if block is None:
            filtered.append(order)
            continue
        self._publish_alert(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            severity=AlertSeverity.WARNING,
            alert_name="portfolio_leg_admission_blocked",
            message=f"PORTFOLIO leg refused by {block}: {order.symbol!r} {order.side.name} {order.quantity} (strategy={intent.strategy_id!r}, position={current}).",
            context={
                "order_id": order.order_id,
                "symbol": order.symbol,
                "strategy_id": intent.strategy_id,
                "block_reason": block,
                "side": order.side.name,
                "quantity": order.quantity,
                "position_quantity": current,
            },
        )
    return filtered


def _try_build_order_from_intent(
    self: Any,
    intent: OrderIntent,
    verdict: RiskVerdict,
    correlation_id: str,
    quote: NBBOQuote | None = None,
    *,
    exec_style: ExecStyle | None = None,
) -> tuple[OrderRequest | None, str | None]:
    """Construct an order and return a stable failure token on suppression.

    When ``exec_style`` is ``ExecStyle.PASSIVE``, a discretionary working
    leg posts near the BBO regardless of the static
    ``_use_passive_entries`` flag. ``None`` uses default routing.
    Stop-exits and MOC orders always short-circuit to MARKET and ignore
    the hint (Inv-11).
    """
    side = self._side_from_intent(intent)
    seq = self._seq.next()
    order_id = derive_order_id(f"{correlation_id}:{seq}")

    # Exits bypass minimum size and risk scaling so any position can close.
    is_exit_or_stop = (
        intent.intent == TradingIntent.EXIT or intent.signal.strategy_id == "__stop_exit__"
    )
    quantity = (
        intent.target_quantity
        if is_exit_or_stop
        else round(intent.target_quantity * verdict.scaling_factor)
    )
    if quantity <= 0:
        return None, "rounded_quantity_after_risk_scaling_le_zero"
    if blocks_for_min_size(quantity, self._min_order_shares, exempt=is_exit_or_stop):
        return None, BLOCK_BELOW_MIN_ORDER_SHARES

    # Only hard-tier short sales carry the HTB fee flag;
    # ``OrderRequest.is_short``; ``available`` omits HTB even when
    # cost_htb_borrow_annual_bps is configured.
    short_sale = exposure_delta_from_intent(intent).opens_or_increases_short
    tier = self._borrow_tier_for(intent.symbol)
    is_short = htb_fee_applies(tier, short_sale)

    if (
        not is_exit_or_stop
        and quote is not None
        and not _signal_passes_edge_cost_gate(self,
            intent.signal,
            symbol=intent.symbol,
            entry_side=side,
            quantity=quantity,
            quote=quote,
            is_taker_entry=(
                not self._use_passive_entries or self._min_cost_policy is not None
            ),
            is_short_entry=is_short,
            correlation_id=correlation_id,
            detail="standalone_intent_suppressed",
        )
    ):
        return None, "signal_edge_below_min_edge_cost_ratio_gate"

    order_type, limit_price, is_moc = _resolve_order_route(self,
        strategy_id=intent.strategy_id,
        symbol=intent.symbol,
        side=side,
        quantity=quantity,
        quote=quote,
        is_short=is_short,
        is_exit_or_stop=is_exit_or_stop,
        edge_bps=intent.signal.edge_estimate_bps,
        exec_style=exec_style,
    )

    return (
        OrderRequest(
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            sequence=seq,
            order_id=order_id,
            symbol=intent.symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            strategy_id=intent.strategy_id,
            is_short=is_short,
            is_moc=is_moc,
            reason="",
            g12_disclosed_cost_total_bps=(intent.signal.disclosed_cost_total_bps),
        ),
        None,
    )


def _execute_reverse(
    self: Any,
    intent: OrderIntent,
    verdict: RiskVerdict,
    cid: str,
    quote: NBBOQuote,
    t_wall_start: int,
) -> None:
    """Execute a REVERSE intent as EXIT(MARKET) + ENTRY(LIMIT).

    H2/H3/H7: Decomposes reversals so the closing leg is aggressive
    (guaranteed fill) and the entry leg is passive (spread savings).
    Prevents position-trapping where a combined passive order sits
    in the queue while the position is stuck in the wrong direction.

    The EXIT leg is always MARKET and bypasses min_order_shares
    (you must be able to close any position).  The ENTRY leg uses
    the normal passive/active mode and is subject to all gates.
    """
    close_qty = abs(intent.current_quantity)
    entry_qty_raw = intent.target_quantity - close_qty

    # ── Cancel any resting orders for this symbol ──────────────
    self._cancel_resting_for_symbol(intent.symbol, cid)

    # ── EXIT leg: aggressive MARKET close ──────────────────────
    exit_side = Side.SELL if intent.current_quantity > 0 else Side.BUY
    seq_exit = self._seq.next()
    exit_order_id = derive_order_id(f"{cid}:{seq_exit}:exit")

    exit_order = OrderRequest(
        timestamp_ns=self._clock.now_ns(),
        correlation_id=cid,
        sequence=seq_exit,
        order_id=exit_order_id,
        symbol=intent.symbol,
        side=exit_side,
        order_type=OrderType.MARKET,
        quantity=close_qty,
        strategy_id=intent.strategy_id,
        is_short=False,
    )

    # Shared exposure and drawdown checks cannot block or resize a full close.
    exit_verdict = self._risk_engine.check_order(
        exit_order,
        self._positions,
    )
    self._bus.publish(exit_verdict)
    if exit_verdict.action == RiskAction.FORCE_FLATTEN:
        if self._macro.can_transition(MacroState.RISK_LOCKDOWN):
            # Same global halt as standalone SIGNAL/order gates —
            # _emergency_flatten_all() closes this leg (and every other
            # open position) directly with a properly-tagged flatten,
            # so defer to it here rather than also submitting this leg.
            _escalate_risk(self, cid)
            self._finalize_tick(t_wall_start, cid, "reverse_exit_force_flatten_escalation")
            return
        # BACKTEST_MODE has no reachable lockdown transition, so there
        # is no compensating flatten to rely on — normalize to ALLOW so
        # this reduce still submits instead of stranding the position.
        exit_verdict = replace(exit_verdict, action=RiskAction.ALLOW, scaling_factor=1.0)
    elif exit_verdict.action != RiskAction.ALLOW:
        exit_verdict = replace(exit_verdict, action=RiskAction.ALLOW, scaling_factor=1.0)

    # ── ENTRY leg: passive LIMIT (or MARKET if passive disabled) ─
    #
    # Risk-check entry against the position expected after the exit leg.
    entry_order: OrderRequest | None = None
    entry_qty = round(entry_qty_raw * verdict.scaling_factor)
    # Attach combined reversal cost only when the entry leg is evaluated.
    reverse_signal: Signal = intent.signal

    # Signed adjustment: the exit leg removes close_qty from position.
    exit_signed_adj = -close_qty if exit_side == Side.SELL else close_qty
    post_exit_positions = PostExitPositionView(
        self._positions,
        intent.symbol,
        exit_signed_adj,
    )

    if entry_qty >= self._min_order_shares:
        entry_side = exit_side  # same direction for both legs
        short_sale = intent.intent == TradingIntent.REVERSE_LONG_TO_SHORT
        tier = self._borrow_tier_for(intent.symbol)
        is_short = htb_fee_applies(tier, short_sale)

        # The reversal entry must cover both legs using the same calibrated
        # edge as the ordinary entry gate. The exit always submits.
        edge_calibration_factor: float = self._edge_calibration_factors.get(
            intent.signal.strategy_id, 1.0
        )
        effective_edge_bps: float = intent.signal.edge_estimate_bps * edge_calibration_factor
        (
            reversal_cost_bps,
            reversal_required_bps,
            reversal_edge_passes,
        ) = _reversal_passes_combined_edge_gate(self,
            edge_estimate_bps=effective_edge_bps,
            symbol=intent.symbol,
            exit_side=exit_side,
            exit_qty=close_qty,
            entry_side=entry_side,
            entry_qty=entry_qty,
            quote=quote,
            is_short_entry=is_short,
        )
        # Expose combined cost to traces and alerts.
        reverse_signal = replace(
            intent.signal,
            reversal_cost_estimate_bps=reversal_cost_bps,
        )

        if not reversal_edge_passes:
            deficit_bps = reversal_required_bps - effective_edge_bps
            calibration_note = (
                ""
                if edge_calibration_factor >= 1.0
                else f"; realization factor={edge_calibration_factor:.3f} "
                f"(disclosed {intent.signal.edge_estimate_bps:.2f} -> "
                f"{effective_edge_bps:.2f} bps)"
            )
            self._publish_alert(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=cid,
                severity=AlertSeverity.WARNING,
                alert_name="reversal_edge_insufficient",
                message=f"Reversal entry suppressed (flatten-only): edge_bps={effective_edge_bps:.4f} below required {reversal_required_bps:.4f} ({self._reversal_min_edge_cost_multiplier}× combined round-trip cost {reversal_cost_bps:.4f}); deficit={deficit_bps:.4f} bps (symbol={intent.symbol!r}, strategy_id={intent.strategy_id!r}){calibration_note}.",
                context={
                    "edge_bps": effective_edge_bps,
                    "required_bps": reversal_required_bps,
                    "deficit_bps": deficit_bps,
                    "symbol": intent.symbol,
                    "strategy_id": intent.strategy_id,
                    "order_id": exit_order.order_id,
                },
            )

        # Check entry edge against cost unless the reversal guard already
        # suppressed the flip.
        entry_passes_edge_gate = reversal_edge_passes and _signal_passes_edge_cost_gate(self,
            intent.signal,
            symbol=intent.symbol,
            entry_side=entry_side,
            quantity=entry_qty,
            quote=quote,
            is_taker_entry=(
                not self._use_passive_entries or self._min_cost_policy is not None
            ),
            is_short_entry=is_short,
            correlation_id=cid,
            detail="reverse_entry_leg_suppressed",
        )

        if entry_passes_edge_gate:
            seq_entry = self._seq.next()
            entry_order_id = derive_order_id(f"{cid}:{seq_entry}:entry")

            order_type, limit_price, entry_is_moc = _resolve_order_route(self,
                strategy_id=intent.strategy_id,
                symbol=intent.symbol,
                side=entry_side,
                quantity=entry_qty,
                quote=quote,
                is_short=is_short,
                is_exit_or_stop=False,
                edge_bps=intent.signal.edge_estimate_bps,
            )

            entry_order = OrderRequest(
                timestamp_ns=self._clock.now_ns(),
                correlation_id=cid,
                sequence=seq_entry,
                order_id=entry_order_id,
                symbol=intent.symbol,
                side=entry_side,
                order_type=order_type,
                quantity=entry_qty,
                limit_price=limit_price,
                strategy_id=intent.strategy_id,
                is_short=is_short,
                is_moc=entry_is_moc,
                g12_disclosed_cost_total_bps=(intent.signal.disclosed_cost_total_bps),
            )

            # Risk check entry leg against post-exit position view.
            entry_rv = self._risk_engine.check_order(
                entry_order,
                post_exit_positions,
            )
            self._bus.publish(entry_rv)
            if entry_rv.action in (
                RiskAction.REJECT,
                RiskAction.FORCE_FLATTEN,
            ):
                entry_order = None
            elif entry_rv.action == RiskAction.SCALE_DOWN:
                scaled = self._compose_scaled_quantity(
                    entry_qty_raw,
                    verdict.scaling_factor,
                    entry_rv.scaling_factor,
                )
                if scaled < self._min_order_shares:
                    entry_order = None
                elif scaled != entry_order.quantity:
                    entry_order = replace(
                        entry_order,
                        quantity=scaled,
                    )

    # ── M6 → M7: ORDER_SUBMIT ─────────────────────────────────
    self._micro.transition(
        MicroState.ORDER_SUBMIT,
        trigger="reverse_orders_constructed",
        correlation_id=cid,
    )

    # Attribute the reversal to its exit leg; stamp the new entry separately.
    self._track_order(
        exit_order.order_id,
        exit_order.side,
        exit_order,
        trading_intent=intent.intent.name,
    )
    exit_submit_error = self._submit_tracked_order(exit_order)
    if exit_submit_error is not None:
        self._micro.transition(
            MicroState.ORDER_ACK,
            trigger="reverse_exit_submit_failed",
            correlation_id=cid,
        )
        self._settle_router_acks(
            cid,
            expected_order_ids={exit_order.order_id},
            position_update_trigger="reverse_acks_after_failed_exit_submit",
        )
        self._finalize_tick(t_wall_start, cid, "reverse_aborted_exit_submit_failed")
        return

    self._bus.publish(exit_order)

    entry_submitted_ok = False
    if entry_order is not None:
        entry_intent_name = (
            TradingIntent.ENTRY_SHORT.name
            if intent.intent == TradingIntent.REVERSE_LONG_TO_SHORT
            else TradingIntent.ENTRY_LONG.name
        )
        self._track_order(
            entry_order.order_id,
            entry_order.side,
            entry_order,
            trading_intent=entry_intent_name,
        )
        if self._submit_tracked_order(entry_order) is None:
            self._bus.publish(entry_order)
            entry_submitted_ok = True

    # ── M7 → M8: ORDER_ACK ────────────────────────────────────
    self._micro.transition(
        MicroState.ORDER_ACK,
        trigger="reverse_orders_submitted",
        correlation_id=cid,
    )
    expected_order_ids = {exit_order.order_id}
    if entry_order is not None and entry_submitted_ok:
        expected_order_ids.add(entry_order.order_id)
    # ── M8 → M9: POSITION_UPDATE ──────────────────────────────
    self._settle_router_acks(
        cid,
        expected_order_ids=expected_order_ids,
        position_update_trigger="reverse_acks_received",
    )

    if self._signal_order_trace_sink is not None:
        leg = (
            "exit_plus_entry"
            if entry_order is not None and entry_submitted_ok
            else "exit_only"
        )
        self._append_signal_order_trace(
            quote,
            reverse_signal,
            outcome="ORDER_SUBMITTED",
            reasons=(
                f"reverse_{leg}_submitted",
                f"exit_order_id={exit_order.order_id}",
            ),
            trading_intent=intent.intent.name,
        )

    # ── M9 → M10: LOG_AND_METRICS ─────────────────────────────
    self._finalize_tick(t_wall_start, cid, "reverse_position_updated")
