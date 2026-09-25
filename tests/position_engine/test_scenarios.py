"""Harness self-tests. Ordinary tests; no battery marker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal

import pytest

from feelies.core.events import (
    GateDecision,
    MarkRailUpdate,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    PositionExtreme,
    PositionSnapshot,
    RailOrientation,
)
from tests.position_engine.scenarios import (
    T0,
    attribute,
    canonical,
    format_line,
    nonvacuous,
    project_for_multiname,
    run_synthetic,
)
from tests.position_engine.tapes import make_tape


def _quote() -> NBBOQuote:
    return make_tape(seed=1, n=1, symbol="SYN", start_ns=T0, size=1000)[0]


def test_t1_canonical_is_deterministic_and_key_sorted() -> None:
    quote = _quote()
    first = canonical(quote)
    second = canonical(quote)
    assert first == second
    payload = json.loads(first[first.index("{") :])
    keys = list(payload)
    assert keys == sorted(keys)


def test_t2_project_drops_nested_sequence_and_cell_id() -> None:
    text = (
        'Demo{"cell_id":"c","keep":1,"nested":{"cell_id":"d","quote_sequence":3,"z":1},'
        '"sequence":9}'
    )
    projected = project_for_multiname(text)
    payload = json.loads(projected[projected.index("{") :])
    assert "cell_id" not in payload
    assert "sequence" not in payload
    nested = payload["nested"]
    assert "cell_id" not in nested
    assert "quote_sequence" not in nested
    assert nested["z"] == 1
    assert payload["keep"] == 1


def test_t3_mark_rail_attributed_to_its_quote() -> None:
    tape = make_tape(seed=11, n=50, symbol="SYN", start_ns=T0, size=1000)
    records = run_synthetic(tape, symbols=("SYN",))
    updates = [row for row in records if row.type_name == "MarkRailUpdate"]
    assert updates
    for row in updates:
        body = json.loads(row.canonical[row.canonical.index("{") :])
        assert row.attributed_quote_sequence == body["quote_sequence"]


def test_t4_nonvacuous_message_prefix() -> None:
    with pytest.raises(AssertionError, match="^NONVACUOUS: "):
        nonvacuous([], PositionSnapshot, scenario="t4")


def test_t5_syn_m1_entry_exits_zero() -> None:
    tape = make_tape(seed=11, n=36000, symbol="SYN", start_ns=T0, size=1000)
    records = run_synthetic(tape, symbols=("SYN",))
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    proc = subprocess.run(
        [sys.executable, "-m", "tests.position_engine.scenarios", "syn_m1"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line]
    assert lines == [format_line(row) for row in records]
    assert len(lines) == len(records)


def test_t6_nonvacuous_precedes_perturbation() -> None:
    reached = False

    def _member(baseline: list[object]) -> None:
        nonlocal reached
        nonvacuous(baseline, PositionSnapshot, scenario="t6")
        reached = True
        raise TypeError("perturbation")

    with pytest.raises(AssertionError, match="^NONVACUOUS: "):
        _member([])
    assert reached is False


def _orientation() -> RailOrientation:
    return RailOrientation(
        paying_mark_cents=1,
        valuation_mark_cents=1,
        worst_side_mark_cents=1,
        forced_exit_mark_cents=1,
        dwelled_exit_mark_cents=1,
        paying_size=1,
        valuation_size=1,
        paying_age_ns=0,
        valuation_age_ns=0,
        paying_absent_for_ns=0,
        valuation_absent_for_ns=0,
        paying_side_absent=False,
        valuation_side_absent=False,
        dwell_window_clean=True,
    )


def _extreme() -> PositionExtreme:
    return PositionExtreme(
        cents=0,
        sequence=0,
        valuation_age_ns=0,
        valuation_side_absent=False,
        crossed=False,
        feed_gap_before=False,
    )


def _rail(quote_sequence: int) -> MarkRailUpdate:
    side = _orientation()
    return MarkRailUpdate(
        timestamp_ns=1,
        correlation_id=f"rail-{quote_sequence}",
        sequence=quote_sequence,
        symbol="SYN",
        quote_sequence=quote_sequence,
        event_timestamp_ns=1,
        long=side,
        short=side,
        symbol_quiet_ns=0,
        locked=False,
        crossed=False,
        feed_gap_before=False,
        warmed_up=False,
    )


def _snapshot(name: str, sequence: int) -> PositionSnapshot:
    rail = _orientation()
    extreme = _extreme()
    return PositionSnapshot(
        timestamp_ns=1,
        correlation_id=name,
        sequence=sequence,
        cell_id=name,
        symbol="SYN",
        strategy_id="sig",
        state="OPEN",
        side="LONG",
        declared_archetype="MARKET",
        rail_sequence=sequence,
        size=1,
        entry_cost_cents=1,
        entry_spread_ticks=1,
        horizon_deadline_ns=1,
        move_now_cents=0,
        move_worst_cents=0,
        move_forced_cents=0,
        best=extreme,
        worst=extreme,
        best_clean=extreme,
        rail=rail,
        symbol_quiet_ns=0,
        locked=False,
        crossed=False,
        feed_gap_before=False,
        warmed_up=False,
    )


def _gate(name: str, sequence: int) -> GateDecision:
    return GateDecision(
        timestamp_ns=1,
        correlation_id=name,
        sequence=sequence,
        cell_id=name,
        rail_sequence=sequence,
        gate="FAVORABLE",
        outcome="HOLD",
        reason="",
        form="",
        proposed_price_cents=0,
        reference_ticks=0,
        reference_sequence=0,
        drawn_level_ticks=0,
    )


def _nbbo(sequence: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=1,
        correlation_id=f"q-{sequence}",
        sequence=sequence,
        symbol="SYN",
        bid=Decimal("1"),
        ask=Decimal("1.01"),
        bid_size=1,
        ask_size=1,
        exchange_timestamp_ns=1,
    )


def _fill(name: str, sequence: int) -> OrderAck:
    return OrderAck(
        timestamp_ns=1,
        correlation_id=name,
        sequence=sequence,
        order_id=name,
        symbol="SYN",
        status=OrderAckStatus.FILLED,
    )


def test_t7_attribution_cursor_on_a_hand_built_stream() -> None:
    rail_1 = _rail(1)
    snap_a = _snapshot("S_a", 10)
    quote_1 = _nbbo(1)
    fill_b = _fill("Fill_b", 11)
    rail_2 = _rail(2)
    snap_c = _snapshot("S_c", 12)
    gate_d = _gate("G_d", 13)
    quote_2 = _nbbo(2)
    fill_e = _fill("Fill_e", 14)
    stream = [rail_1, snap_a, quote_1, fill_b, rail_2, snap_c, gate_d, quote_2, fill_e]
    rows = attribute(stream)
    assert [(cursor, type_name) for cursor, type_name, _text in rows] == [
        (1, "MarkRailUpdate"),
        (1, "PositionSnapshot"),
        (2, "MarkRailUpdate"),
        (2, "PositionSnapshot"),
        (2, "GateDecision"),
    ]
    assert all(text.startswith(type_name) for _cursor, type_name, text in rows)
