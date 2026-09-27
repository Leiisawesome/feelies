"""Member 11 audit reconstruction, plus hand-built self-tests (D-85, D-104)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote
from tests.position_engine.scenarios import (
    T0,
    Record,
    audit_m11,
    check_m11_extremes,
    check_m11_gross,
    check_m11_moves,
    check_m11_proposed,
    nonvacuous,
    run_synthetic,
)
from tests.position_engine.tapes import make_tape

_MARK = pytest.mark.battery_member(member=11, green_from="E", red_reason="NONVACUOUS")


def _quote(sequence: int, bid_cents: int, ask_cents: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=sequence,
        correlation_id=f"m11-{sequence}",
        sequence=sequence,
        symbol="SYN",
        bid=Decimal(bid_cents) / 100,
        ask=Decimal(ask_cents) / 100,
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=sequence * 1_000_000,
    )


def _rail(valuation: int, worst: int, forced: int) -> dict[str, object]:
    return {
        "paying_mark_cents": valuation + 1,
        "valuation_mark_cents": valuation,
        "worst_side_mark_cents": worst,
        "forced_exit_mark_cents": forced,
        "dwelled_exit_mark_cents": valuation,
        "valuation_side_absent": False,
    }


def _extreme(cents: int, sequence: int) -> dict[str, object]:
    return {
        "cents": cents,
        "sequence": sequence,
        "valuation_age_ns": 0,
        "valuation_side_absent": False,
        "crossed": False,
        "feed_gap_before": False,
    }


def _snapshot(
    *,
    move_now: int,
    move_worst: int,
    move_forced: int,
    best: int,
    rail_sequence: int = 20,
) -> dict[str, object]:
    return {
        "cell_id": "SYN|sig|10|LONG",
        "side": "LONG",
        "size": 10,
        "entry_cost_cents": 100_000,
        "rail_sequence": rail_sequence,
        "move_now_cents": move_now,
        "move_worst_cents": move_worst,
        "move_forced_cents": move_forced,
        "best": _extreme(best, rail_sequence),
        "worst": _extreme(best, rail_sequence),
        "best_clean": _extreme(best, rail_sequence),
        "rail": _rail(10_010, 10_005, 10_005),
        "crossed": False,
        "feed_gap_before": False,
    }


def _closed(*, proposed: int | None) -> dict[str, object]:
    return {
        "cell_id": "SYN|sig|10|LONG",
        "side": "LONG",
        "exit_reason": "FAVORABLE",
        "entry_fills": [
            {"price_cents": 10_000, "quantity": 10, "timestamp_ns": 10, "sequence": 10}
        ],
        "exit_fills": [
            {"price_cents": 10_010, "quantity": 10, "timestamp_ns": 20, "sequence": 20}
        ],
        "proposed_price_cents": proposed,
        "closed_on_stale_data": False,
    }


def _row(body: dict[str, object]) -> Record:
    text = "PositionClosed" + json.dumps(body, sort_keys=True, separators=(",", ":"))
    return Record(20, "PositionClosed", text)


def _quotes() -> dict[int, NBBOQuote]:
    return {10: _quote(10, 10_000, 10_001), 20: _quote(20, 10_010, 10_011)}


def test_m11_satisfying_stream() -> None:
    snap = _snapshot(move_now=100, move_worst=50, move_forced=50, best=100)
    closed = _closed(proposed=10_010)
    check_m11_moves(snap)
    check_m11_extremes([snap])
    check_m11_proposed(closed, [snap], _quotes())
    check_m11_gross(_row(closed), _quotes())


def test_m11_accumulated_drift_fails() -> None:
    snap = _snapshot(move_now=101, move_worst=50, move_forced=50, best=100)
    with pytest.raises(AssertionError, match=r"^M11:"):
        check_m11_moves(snap)


def test_m11_zero_seed_fails() -> None:
    snap = _snapshot(move_now=100, move_worst=50, move_forced=50, best=0)
    with pytest.raises(AssertionError, match=r"^M11:"):
        check_m11_extremes([snap])


def test_m11_level_priced_proposal_fails() -> None:
    snap = _snapshot(move_now=100, move_worst=50, move_forced=50, best=100)
    closed = _closed(proposed=9_900)
    with pytest.raises(AssertionError, match=r"^M11:"):
        check_m11_proposed(closed, [snap], _quotes())


@_MARK
def test_m11_synthetic() -> None:
    tape = make_tape(seed=11, n=400, symbol="SYN", start_ns=T0, size=1000)
    records = run_synthetic(tape, symbols=("SYN",))
    nonvacuous(records, "PositionClosed", scenario="m11")
    audit_m11(records)
