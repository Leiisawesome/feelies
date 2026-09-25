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
    RiskAction,
    RiskVerdict,
)
from tests.position_engine.scenarios import (
    T0,
    Records,
    Record,
    assert_no_risk_rejects,
    attribute,
    canonical,
    displacement_identity,
    drawn_adverse_level,
    exit_reason_at_collision,
    format_line,
    mean_within_se,
    nonvacuous,
    project_for_multiname,
    run_synthetic,
)
from tests.position_engine.tapes import make_tape, set_quote


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


def _canon(type_name: str, body: dict[str, object]) -> str:
    return type_name + json.dumps(body, sort_keys=True, separators=(",", ":"))


def _closed(
    cell: str,
    *,
    side: str,
    entry_px: int,
    exit_px: int,
    qty: int,
    entry_seq: int,
    exit_seq: int,
    reason: str,
    paths: list[tuple[str, int]],
    proposed: int,
) -> Record:
    body: dict[str, object] = {
        "cell_id": cell,
        "symbol": "SYN",
        "strategy_id": "sig_position_fixture_v1",
        "side": side,
        "entry_fills": [
            {
                "price_cents": entry_px,
                "quantity": qty,
                "sequence": entry_seq,
                "timestamp_ns": entry_seq,
            }
        ],
        "exit_fills": [
            {
                "price_cents": exit_px,
                "quantity": qty,
                "sequence": exit_seq,
                "timestamp_ns": exit_seq,
            }
        ],
        "exit_reason": reason,
        "proposed_price_cents": proposed,
        "triggered_paths": [
            {"path": path, "proposed_price_cents": price} for path, price in paths
        ],
    }
    return Record(exit_seq, "PositionClosed", _canon("PositionClosed", body))


def _requirement(cell_ts: int) -> Record:
    body = {
        "symbol": "SYN",
        "strategy_id": "sig_position_fixture_v1",
        "timestamp_ns": cell_ts,
        "reason": "ADVERSE_EXCURSION",
        "source_layer": "POSITION",
    }
    return Record(cell_ts, "DeRiskRequirement", _canon("DeRiskRequirement", body))


def _quotes() -> dict[int, NBBOQuote]:
    tape = make_tape(seed=1, n=4, symbol="SYN", start_ns=T0, size=1000)
    tape[1] = set_quote(tape, 1, bid_cents=10_000, ask_cents=10_001)[1]
    tape[2] = set_quote(tape, 2, bid_cents=10_010, ask_cents=10_011)[2]
    return {quote.sequence: quote for quote in tape}


def test_t8_displacement_identity_holds_on_tape_quotes() -> None:
    quotes = _quotes()
    row = _closed(
        "C",
        side="LONG",
        entry_px=10_001,
        exit_px=10_011,
        qty=10,
        entry_seq=2,
        exit_seq=3,
        reason="FAVORABLE",
        paths=[("FAVORABLE", 10_010)],
        proposed=10_010,
    )
    displacement_identity(Records([row], quotes, ()))


def test_t8_displacement_identity_missing_quote() -> None:
    row = _closed(
        "C",
        side="LONG",
        entry_px=10_001,
        exit_px=10_011,
        qty=10,
        entry_seq=2,
        exit_seq=9,
        reason="FAVORABLE",
        paths=[("FAVORABLE", 10_010)],
        proposed=10_010,
    )
    with pytest.raises(
        AssertionError,
        match=r"^displacement identity: cell C exit fill sequence 9 is not on the tape$",
    ):
        displacement_identity(Records([row], _quotes(), ()))


def test_t8_mean_within_se_balanced_passes() -> None:
    mean_within_se([1.0, -1.0, 1.0, -1.0], 0.0, label="displacement")


def test_t8_mean_within_se_rejects_a_shift() -> None:
    with pytest.raises(
        AssertionError,
        match=r"^mean displacement 10\.0 outside 4 SE of 0\.0 \(bound 0\.0\)$",
    ):
        mean_within_se([10.0, 10.0, 10.0, 10.0], 0.0, label="displacement")


def test_t8_exit_reason_picks_adverse_over_favorable() -> None:
    row = _closed(
        "C",
        side="LONG",
        entry_px=10_001,
        exit_px=9_990,
        qty=10,
        entry_seq=2,
        exit_seq=3,
        reason="ADVERSE",
        paths=[("FAVORABLE", 10_020), ("ADVERSE", 9_990)],
        proposed=9_990,
    )
    exit_reason_at_collision(Records([row, _requirement(3)], _quotes(), ()))


def _verdict(action: RiskAction, reason: str) -> RiskVerdict:
    return RiskVerdict(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="SYN",
        action=action,
        reason=reason,
    )


def test_t8_no_risk_rejects_on_a_clean_stream() -> None:
    clean = Records([], {}, (), (_verdict(RiskAction.ALLOW, "within limits"),))
    assert_no_risk_rejects(clean)


def test_t8_no_risk_rejects_names_a_drawdown() -> None:
    reason = "per-alpha drawdown 5.05% >= limit 5.0% — alpha should be quarantined"
    records = Records([], {}, (), (_verdict(RiskAction.REJECT, reason),))
    with pytest.raises(
        AssertionError,
        match=(
            r"^CONFOUND: risk rejected 1 signals \(per-alpha drawdown 5\.05% >= "
            r"limit 5\.0% — alpha should be quarantined:1\)$"
        ),
    ):
        assert_no_risk_rejects(records)


def test_t8_drawn_level_band_zero_is_the_centre() -> None:
    assert drawn_adverse_level("SYN|sig_position_fixture_v1|2|LONG", 11, 0) == 11
    level = drawn_adverse_level("SYN|sig_position_fixture_v1|2|LONG", 11, 8)
    assert 7 <= level <= 15


def test_t8_exit_reason_rejects_the_flattering_tie() -> None:
    row = _closed(
        "C",
        side="LONG",
        entry_px=10_001,
        exit_px=9_990,
        qty=10,
        entry_seq=2,
        exit_seq=3,
        reason="FAVORABLE",
        paths=[("ADVERSE", 9_990), ("FAVORABLE", 10_020)],
        proposed=10_020,
    )
    with pytest.raises(
        AssertionError,
        match=r"^exit reason FAVORABLE != ADVERSE cell C candidates \['ADVERSE', 'FAVORABLE'\]$",
    ):
        exit_reason_at_collision(Records([row, _requirement(3)], _quotes(), ()))
