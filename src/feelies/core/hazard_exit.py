"""Hazard-exit signature constants.

The constants live in core so kernel can name them without importing
the risk package.
"""

from __future__ import annotations

HAZARD_EXIT_SOURCE_LAYER: str = "RISK"
HAZARD_EXIT_REASONS: frozenset[str] = frozenset({"HAZARD_SPIKE", "HARD_EXIT_AGE"})
