"""Stop-slippage reason set."""

from __future__ import annotations

from feelies.execution._fill_helpers import STOP_EXIT_REASONS


def test_adverse_excursion_joins_stop_slippage_reasons() -> None:
    """F2. ADVERSE_EXCURSION takes the same panic treatment as the existing stops."""
    assert "ADVERSE_EXCURSION" in STOP_EXIT_REASONS
