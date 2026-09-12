"""Position sizer — compute target quantity from risk budget and regime.

The sizer is called by the IntentTranslator to determine how many
shares to target for a given signal, considering the alpha's declared
risk budget, account equity, current price, and regime state.

Invariants preserved:
  - Inv 5 (deterministic): same inputs → same target quantity
  - Inv 11 (fail-safe): regime scaling only reduces, never increases
    beyond the 1.0 baseline
  - Inv 12 (transaction cost realism): the sizer caps quantity so
    that the alpha never exceeds its declared budget
"""

from __future__ import annotations

from feelies.core.position_sizer import (
    BudgetBasedSizer as BudgetBasedSizer,
    PositionSizer as PositionSizer,
)
