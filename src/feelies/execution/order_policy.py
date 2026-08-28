"""Engine-9 order policy: edge-vs-cost gates, routing, and order construction."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from feelies.core.events import NBBOQuote, Side
from feelies.execution.position_manager import entry_edge_clears_cost, round_trip_cost_bps


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
