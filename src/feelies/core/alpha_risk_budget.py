"""Per-alpha risk budget — Engine 5's declared operating envelope.

The type lives in core so Engine 8 can read it without importing alpha.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class AlphaRiskBudget:
    """Risk constraints scoped to a single alpha module.

    These feed into the risk engine's per-strategy budget allocation.
    The risk engine is free to enforce tighter limits than declared
    here; these are the alpha's self-declared operating envelope.
    """

    max_position_per_symbol: int
    max_gross_exposure_pct: float
    max_drawdown_pct: float
    capital_allocation_pct: float
