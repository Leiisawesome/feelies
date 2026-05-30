"""Backtest-modeled regulatory / structural fill constraints.

This package houses the regulatory constraints the platform models
*inside the backtest fill/risk path* rather than as pre-route live gates.
Each constraint can only raise simulated cost or suppress simulated
fills — never the reverse (Inv-11, fail-safe default).

Current members:

- :mod:`feelies.execution.regulatory.pdt_constraint` — Pattern Day
  Trader (PDT) round-trip tracking + the $25k minimum-equity maintenance
  gate (BT-4).
"""

from feelies.execution.regulatory.pdt_constraint import (
    AccountType,
    PDTConfig,
    PDTConstraint,
)

__all__ = ["AccountType", "PDTConfig", "PDTConstraint"]
