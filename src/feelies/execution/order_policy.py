"""Engine-9 order policy: edge-vs-cost gates, routing, and order construction."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from feelies.core.events import NBBOQuote, Side
from feelies.execution.position_manager import round_trip_cost_bps


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
