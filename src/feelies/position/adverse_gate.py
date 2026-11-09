"""Adverse-excursion gate as a pure function. contracts.md §4 and §9; D-42, D-44, D-83, D-99; D-243. Not wired until P-62 (D-241)."""

from __future__ import annotations

import hashlib
from typing import NamedTuple


class AdverseDecision(NamedTuple):
    outcome: str
    trigger: str
    drawn_level_ticks: int
    proposed_price_cents: int | None


def drawn_level(cell_id: str, centre: int, band: int) -> int:
    h = int.from_bytes(hashlib.sha256(cell_id.encode("utf-8")).digest()[:8], "big")
    return (centre - band // 2) + (h % (band + 1))


def evaluate_adverse(
    *,
    cell_id: str,
    centre: int,
    band: int,
    blind_limit_ns: int,
    size: int,
    move_worst: int | None,
    forced_exit_mark: int | None,
    paying_absent_ns: int,
    valuation_absent_ns: int,
    quiet_ns: int,
) -> AdverseDecision:
    """BLIND first (§4:369, D-243), then LEVEL (§4:363), else hold; None move_worst is absent (D-99)."""
    level = drawn_level(cell_id, centre, band)
    if (
        paying_absent_ns > blind_limit_ns
        or valuation_absent_ns > blind_limit_ns
        or quiet_ns > blind_limit_ns
    ):
        return AdverseDecision("fire", "BLIND", level, forced_exit_mark)
    if move_worst is not None and move_worst <= -level * size:
        return AdverseDecision("fire", "LEVEL", level, forced_exit_mark)
    return AdverseDecision("hold", "", level, forced_exit_mark)
