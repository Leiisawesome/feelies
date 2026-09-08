"""G12 validation for alpha cost disclosures.

SIGNAL and PORTFOLIO specs disclose edge, half-spread, impact, fee, and margin
ratio. Values must be finite with valid signs, the stated margin must match
``edge / total_cost`` within ``MARGIN_RATIO_TOLERANCE``, and it must clear
``MIN_MARGIN_RATIO``.

The default cost basis is one way: one spread crossing, impact, and fee. The
runtime B4 gate separately tests edge against modeled round-trip cost. Validated
totals are copied onto emitted signals for execution forensics.

The types live in :mod:`feelies.core.cost_arithmetic` so signals can read the
disclosure without importing the alpha package. This module re-exports them;
G12 authors and loaders keep importing from here.
"""

from __future__ import annotations

from feelies.core.cost_arithmetic import (
    MARGIN_RATIO_TOLERANCE,
    MIN_MARGIN_RATIO,
    CostArithmetic,
    CostArithmeticError,
    compute_margin_ratio,
)

__all__ = [
    "CostArithmetic",
    "CostArithmeticError",
    "MIN_MARGIN_RATIO",
    "MARGIN_RATIO_TOLERANCE",
    "compute_margin_ratio",
]
