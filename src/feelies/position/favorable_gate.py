"""Favorable-excursion gate as a pure function.
contracts.md §3 and §9; D-43, D-79, D-83, D-99, D-100, D-101; D-244. Not
wired until P-62 (D-241).
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import NamedTuple

REASONS: tuple[str, ...] = (
    "VALUATION_SIDE_ABSENT",
    "CROSSED",
    "FEED_GAP",
    "DWELL_NOT_CLEAN",
    "NOT_WARMED_UP",
    "SYMBOL_QUIET",
)


class FavorableDecision(NamedTuple):
    outcome: str
    reason: str
    suppressions: tuple[str, ...]
    form: str
    proposed_price_cents: int | None
    reference_ticks: int
    reference_sequence: int | None


def giveback_ticks(giveback_spread_multiple: float, entry_spread_ticks: int) -> int:
    return max(1, math.floor(Fraction(repr(giveback_spread_multiple)) * entry_spread_ticks))


def fixed_disarmed(
    target_ticks: int,
    entry_spread_ticks: int,
    fee_round_trip_ticks: int,
) -> bool:
    return target_ticks <= entry_spread_ticks + fee_round_trip_ticks


def evaluate_favorable(
    *,
    form: str,
    size: int,
    target_ticks: int | None,
    giveback_spread_multiple: float | None,
    ceiling_ticks: int | None,
    entry_spread_ticks: int,
    fee_round_trip_ticks: int,
    move_now_cents: int | None,
    best_clean_cents: int | None,
    best_clean_sequence: int | None,
    dwelled_exit_mark: int | None,
    valuation_side_absent: bool,
    crossed: bool,
    feed_gap_before: bool,
    dwell_window_clean: bool,
    warmed_up: bool,
    symbol_quiet_ns: int,
    quiet_limit_ns: int,
) -> FavorableDecision:
    """Blocks first (D-43, §3:328), then the form; None move is none (D-99);
    proposed price is always dwelled_exit_mark.
    """
    if ceiling_ticks is not None:
        raise ValueError("ceiling C is not defined (D-244)")

    if form == "fixed":
        if target_ticks is None:
            raise ValueError
        ref = target_ticks
        ref_seq = None
    elif form == "trailing":
        if giveback_spread_multiple is None:
            raise ValueError
        ref = giveback_ticks(giveback_spread_multiple, entry_spread_ticks)
        ref_seq = best_clean_sequence
    else:
        raise ValueError

    conditions = (
        valuation_side_absent,
        crossed,
        feed_gap_before,
        not dwell_window_clean,
        not warmed_up,
        symbol_quiet_ns > quiet_limit_ns,
    )
    failing = tuple(token for token, holds in zip(REASONS, conditions, strict=True) if holds)
    if failing:
        return FavorableDecision(
            "suppressed",
            failing[0],
            failing,
            form,
            dwelled_exit_mark,
            ref,
            ref_seq,
        )

    if move_now_cents is None:
        outcome = "none"
    elif form == "fixed":
        if fixed_disarmed(ref, entry_spread_ticks, fee_round_trip_ticks):
            outcome = "none"
        elif move_now_cents >= ref * size:
            outcome = "fire"
        else:
            outcome = "none"
    else:
        round_trip = entry_spread_ticks + fee_round_trip_ticks
        if best_clean_cents is None or best_clean_cents <= (ref + round_trip) * size:
            outcome = "none"
        elif move_now_cents <= best_clean_cents - ref * size:
            outcome = "fire"
        else:
            outcome = "none"

    return FavorableDecision(outcome, "", (), form, dwelled_exit_mark, ref, ref_seq)
