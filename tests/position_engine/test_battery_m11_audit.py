"""Member 11 audit reconstruction, plus hand-built self-tests (D-85, D-104).

The hand-built streams (satisfying, drift, zero seed, level-priced) have no run
precondition: they are not engine output.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from feelies.core.events import NBBOQuote
from tests.position_engine.scenarios import (
    T0,
    Record,
    Records,
    audit_m11,
    check_m11_extremes,
    check_m11_gross,
    check_m11_moves,
    check_m11_proposed,
    fixture_variant,
    nonvacuous,
    require_barrier_differs,
    require_entry_fills,
    run_synthetic,
)
from tests.position_engine.tapes import excise, make_tape, shift_from

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


def _v3a() -> dict[str, object]:
    return fixture_variant(
        horizon_seconds=30,
        fee_round_trip_ticks=0,
        T_seconds=16_000,
        centre_ticks=11,
        band_ticks=0,
        lo_ticks=2,
        target_ticks=4,
    )


@_MARK
def test_m11_synthetic() -> None:
    """Seed 11, n=2200 (220 s at 100 ms). V3a horizon 30.

    Odd boundaries 1, 3, 5 and 7 alternate LONG and SHORT. That span closes at
    least three cells with at least two exit reasons once an engine finalizes
    (measured on the reference engine: 4 cells, ADVERSE, INVALIDATION, END_OF_TAPE).
    """
    tape = make_tape(seed=11, n=2200, symbol="SYN", start_ns=T0, size=1000)
    records = run_synthetic(tape, symbols=("SYN",), variant=_v3a())
    require_entry_fills(records)
    nonvacuous(records, "PositionClosed", scenario="m11")
    audit_m11(records)


@_MARK
def test_m11_gap_through() -> None:
    """A4 V3a gap. The proposed price is the executable side of q_g+1 (J2)."""
    tape = make_tape(seed=11, n=800, symbol="SYN", start_ns=T0, size=1000)
    tape = shift_from(excise(tape, 302, 20), 302, -15)
    require_barrier_differs(tape, birth_index=301, landing_index=302, centre=11, band=0)
    records = run_synthetic(tape, symbols=("SYN",), variant=_v3a())
    require_entry_fills(records)
    adverse = [
        row
        for row in records
        if row.type_name == "PositionClosed" and '"exit_reason":"ADVERSE"' in row.canonical
    ]
    if not adverse:
        raise AssertionError("NONVACUOUS: no ADVERSE close in m11_gap")
    audit_m11(records)


def test_m11_later_exiting_snapshot_is_not_the_deciding_quote() -> None:
    """Decision at rail k, EXITING snapshot and fill at k+1.

    contracts.md §2:269-279, §2:287, §2:294-295. The proposed price is the
    executable side of the deciding quote. The later EXITING snapshot is not it.
    """
    deciding = 20
    later = deciding + 1
    close = _closed(proposed=10_010)
    close["exit_reason"] = "ADVERSE"
    close["triggered_paths"] = [
        {
            "path": "ADVERSE",
            "proposed_price_cents": 10_010,
            "trigger": "LEVEL",
            "rail_sequence": deciding,
        }
    ]
    close["exit_fills"] = [
        {"price_cents": 9_979, "quantity": 10, "timestamp_ns": later, "sequence": later}
    ]
    snapshots = [
        _snapshot(move_now=100, move_worst=50, move_forced=50, best=100, rail_sequence=deciding),
        _snapshot(move_now=90, move_worst=50, move_forced=50, best=100, rail_sequence=later),
    ]
    quotes = {
        deciding: _quote(deciding, 10_010, 10_011),
        later: _quote(later, 9_979, 9_980),
    }
    check_m11_proposed(close, snapshots, quotes)


def _golden_records() -> Records:
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "m11_cell_302_long.json").read_text(encoding="utf-8")
    )
    quotes = {int(raw["sequence"]): _quote_from_golden(raw) for raw in payload["quotes"]}
    rows = [
        Record(raw["attributed_quote_sequence"], raw["type_name"], raw["canonical"])
        for raw in payload["rows"]
    ]
    return Records(rows, quotes, ())


def _quote_from_golden(raw: dict[str, object]) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=int(raw["timestamp_ns"]),  # type: ignore[arg-type]
        correlation_id=str(raw["correlation_id"]),
        sequence=int(raw["sequence"]),  # type: ignore[arg-type]
        symbol=str(raw["symbol"]),
        bid=Decimal(str(raw["bid"])),
        ask=Decimal(str(raw["ask"])),
        bid_size=int(raw["bid_size"]),  # type: ignore[arg-type]
        ask_size=int(raw["ask_size"]),  # type: ignore[arg-type]
        exchange_timestamp_ns=int(raw["exchange_timestamp_ns"]),  # type: ignore[arg-type]
    )


def test_m11_golden_cell_302_deciding_quote() -> None:
    """Golden SYN|sig_position_fixture_v1|302|LONG from the reference run.

    contracts.md §2:269-279, §2:287, §2:294-295. The path entries carry no rail
    sequence, so the deciding event is the first triggering gate outcome.
    """
    audit_m11(_golden_records())
