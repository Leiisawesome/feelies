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
    Side,
    Signal,
    SizedPositionIntent,
)
from feelies.execution.order_admission import ExposureDelta, admission_block_reason
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
from feelies.execution.regulatory.borrow_availability import BorrowTier
from feelies.portfolio.position_store import Position


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
    return self._position_manager.plan(
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
