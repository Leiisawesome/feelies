"""Engine-9 order policy: edge-vs-cost gates, routing, and order construction."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

from feelies.core.events import NBBOQuote, Side, Signal
from feelies.execution.position_manager import (
    DesiredPosition,
    PositionManagerConfig,
    PositionPlan,
    desired_from_signal,
    entry_edge_clears_cost,
    reversal_edge_gate,
    round_trip_cost_bps,
)
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
