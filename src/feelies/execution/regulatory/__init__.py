"""Backtest-modeled regulatory / structural fill constraints.

This package houses the regulatory constraints the platform models
*inside the backtest fill/risk path* rather than as pre-route live gates.
Each constraint can only raise simulated cost or suppress simulated
fills — never the reverse (Inv-11, fail-safe default).

Current members:

- :mod:`feelies.execution.regulatory.pdt_constraint` — PDT round-trip tracking
  and the $25k minimum-equity gate.
- :mod:`feelies.execution.regulatory.borrow_availability` — static
  per-symbol borrow tiers and short-sale classification.
"""

from feelies.execution.regulatory.borrow_availability import (
    BorrowTier,
    build_borrow_table,
    htb_fee_applies,
    is_short_sale_intent,
)
from feelies.execution.regulatory.pdt_constraint import (
    AccountType,
    PDTConfig,
    PDTConstraint,
)

__all__ = [
    "AccountType",
    "BorrowTier",
    "PDTConfig",
    "PDTConstraint",
    "build_borrow_table",
    "htb_fee_applies",
    "is_short_sale_intent",
]
