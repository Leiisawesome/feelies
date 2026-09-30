"""Harness self-tests. Ordinary tests; no battery marker."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from decimal import Decimal
from functools import partial
from pathlib import Path

import pytest
import yaml

from feelies.alpha.loader import AlphaLoader
from feelies.portfolio.mark_rail import MarkRail as _ProductionRail
from feelies.position.engine import PositionEngine as _ProductionEngine
from feelies.core.events import (
    GateDecision,
    MarkRailUpdate,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    PositionClosed,
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
    assert_widened_prefix,
    attribute,
    canonical,
    displacement_identity,
    drawn_adverse_level,
    exit_reason_at_collision,
    fixture_variant,
    format_line,
    mean_within_se,
    nonvacuous,
    placement_rule,
    project_for_multiname,
    run_real,
    run_synthetic,
    CellSpan,
    check_a1,
    check_a2,
    check_a3,
    check_a4,
    check_a5,
    check_a6,
    check_unusable_side,
)
from tests.position_engine.tapes import cross, make_tape, set_quote


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
    symbol: str = "SYN",
) -> Record:
    body: dict[str, object] = {
        "cell_id": cell,
        "symbol": symbol,
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


def _requirement(cell_ts: int, order_id: str = "", ordinal: int = -1) -> Record:
    body = {
        "symbol": "SYN",
        "strategy_id": "sig_position_fixture_v1",
        "timestamp_ns": cell_ts,
        "reason": "ADVERSE_EXCURSION",
        "source_layer": "POSITION",
    }
    if order_id:
        body["order_id"] = order_id
    return Record(cell_ts, "DeRiskRequirement", _canon("DeRiskRequirement", body), None, ordinal)


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
    exit_reason_at_collision(
        Records(
            [
                row,
                _bus_record(
                    1,
                    "OrderAck",
                    {
                        "timestamp_ns": 2,
                        "order_id": "entry",
                        "status": "FILLED",
                        "symbol": "SYN",
                    },
                ),
                _requirement(3, "C|EXIT|1", 2),
                _bus_record(
                    3,
                    "OrderAck",
                    {
                        "timestamp_ns": 3,
                        "order_id": "C|EXIT|1",
                        "status": "FILLED",
                        "symbol": "SYN",
                    },
                ),
            ],
            _quotes(),
            (),
        )
    )


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


def _capture_loaded_specs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    seen: list[dict[str, object]] = []
    original = AlphaLoader.load_from_dict

    def _from_dict(
        self: AlphaLoader,
        spec: dict[str, object],
        param_overrides: dict[str, object] | None = None,
        source: str = "<dict>",
        manifest_hash: str | None = None,
    ) -> object:
        seen.append(spec)
        return original(self, spec, param_overrides, source, manifest_hash)

    monkeypatch.setattr(AlphaLoader, "load_from_dict", _from_dict)
    return seen


def _fixture_drawdown(specs: list[dict[str, object]]) -> float:
    matched = [spec for spec in specs if spec.get("alpha_id") == "sig_position_fixture_v1"]
    assert matched, "fixture alpha was not loaded"
    risk = matched[-1]["risk_budget"]
    assert isinstance(risk, dict)
    return float(risk["max_drawdown_pct"])  # type: ignore[arg-type]


def test_d6_synthetic_spec_carries_100(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture_loaded_specs(monkeypatch)
    tape = make_tape(seed=1, n=2, symbol="SYN", start_ns=T0, size=100)
    run_synthetic(tape, symbols=("SYN",))
    assert _fixture_drawdown(seen) == 100.0


def test_d6_explicit_variant_drawdown_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _capture_loaded_specs(monkeypatch)
    variant = fixture_variant()
    risk = variant["risk_budget"]
    assert isinstance(risk, dict)
    risk["max_drawdown_pct"] = 20.0
    tape = make_tape(seed=1, n=2, symbol="SYN", start_ns=T0, size=100)
    run_synthetic(tape, symbols=("SYN",), variant=variant)
    assert _fixture_drawdown(seen) == 20.0


def test_d6_fixture_file_and_real_spec_stay_at_5() -> None:
    fixture_path = Path("tests/position_engine/fixtures/sig_position_fixture_v1.alpha.yaml")
    fixture = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    assert fixture["risk_budget"]["max_drawdown_pct"] == 5.0
    app = yaml.safe_load(
        Path("configs/bt_position_arbitrary_not_calibrated.yaml").read_text(encoding="utf-8")
    )
    real = yaml.safe_load(Path(app["alpha_specs"][0]).read_text(encoding="utf-8"))
    assert real["risk_budget"]["max_drawdown_pct"] == 5.0


def _identity(events: list[object]) -> list[object]:
    return list(events)


def _cross_first(events: list[object]) -> list[object]:
    out = list(events)
    for index, event in enumerate(out):
        if type(event) is not NBBOQuote:
            continue
        ask_cents = int(event.ask * 100)
        bid_cents = ask_cents + 50
        out[index] = cross([event], 0, bid_cents, ask_cents)[0]
        return out
    raise AssertionError("quote_transform: no quote in the slice")


def _canonical_bytes(records: Records) -> bytes:
    return "\n".join(row.canonical for row in records).encode()


@pytest.mark.battery_real
def test_quote_transform_identity_matches_plain_run() -> None:
    same = run_real(quote_transform=_identity, fraction=0.5)
    plain = run_real(fraction=0.5)
    assert _canonical_bytes(same) == _canonical_bytes(plain)
    assert same.quotes.keys() == plain.quotes.keys()
    for sequence, quote in plain.quotes.items():
        assert same.quotes[sequence] == quote


@pytest.mark.battery_real
def test_quote_transform_cross_changes_exactly_one_quote() -> None:
    plain = run_real(fraction=0.5)
    changed = run_real(quote_transform=_cross_first, fraction=0.5)
    assert changed.quotes.keys() == plain.quotes.keys()
    diffs = [
        sequence for sequence, quote in plain.quotes.items() if changed.quotes[sequence] != quote
    ]
    assert diffs == [min(plain.quotes)]


def _row(type_name: str, body: dict[str, object], cursor: int | None = None) -> Record:
    return Record(cursor, type_name, _canon(type_name, body))


def _side_flags(*, absent: bool = False, dwell: bool = True) -> dict[str, object]:
    return {
        "valuation_side_absent": absent,
        "paying_side_absent": absent,
        "dwell_window_clean": dwell,
        "paying_absent_for_ns": 0,
        "valuation_absent_for_ns": 0,
    }


def _rail_row(
    sequence: int,
    *,
    crossed: bool = False,
    gap: bool = False,
    warm: bool = True,
    quiet: int = 0,
    absent: bool = False,
    dwell: bool = True,
    paying_absent: int = 0,
    valuation_absent: int = 0,
) -> Record:
    side = _side_flags(absent=absent, dwell=dwell)
    side["paying_absent_for_ns"] = paying_absent
    side["valuation_absent_for_ns"] = valuation_absent
    return _row(
        "MarkRailUpdate",
        {
            "quote_sequence": sequence,
            "crossed": crossed,
            "feed_gap_before": gap,
            "warmed_up": warm,
            "symbol_quiet_ns": quiet,
            "long": side,
            "short": dict(side),
        },
        sequence,
    )


def _fire_row(cell: str, sequence: int, gate: str) -> Record:
    return _row(
        "GateDecision",
        {
            "cell_id": cell,
            "rail_sequence": sequence,
            "gate": gate,
            "outcome": "fire",
            "reason": "",
        },
        sequence,
    )


def _priced_close(
    cell: str,
    *,
    side: str,
    reason: str,
    entry_seq: int,
    exit_seq: int,
    price: int,
    flag: bool = False,
    blind: bool = False,
) -> Record:
    return _row(
        "PositionClosed",
        {
            "cell_id": cell,
            "side": side,
            "exit_reason": reason,
            "entry_fills": [{"sequence": entry_seq, "price_cents": 1, "quantity": 1}],
            "exit_fills": [{"sequence": exit_seq, "price_cents": price, "quantity": 1}],
            "lived_through_feed_gap": flag,
            "exited_on_unusable_data": blind,
            "triggered_paths": [{"path": reason, "trigger": "BLIND" if blind else "LEVEL"}],
        },
        exit_seq,
    )


def _book(seq: int, bid_cents: int, ask_cents: int, ts: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q-{seq}",
        sequence=seq,
        symbol="SYN",
        bid=Decimal(bid_cents) / 100,
        ask=Decimal(ask_cents) / 100,
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts,
    )


def test_placement_picks_the_midpoint_when_it_is_free() -> None:
    assert placement_rule([CellSpan("c", 0, 10)], [10]) == (("c", 5),)


def test_placement_skips_an_exit_at_the_midpoint() -> None:
    assert placement_rule([CellSpan("c", 0, 10)], [5, 10]) == (("c", 6),)


def test_placement_skips_when_the_next_event_is_an_exit() -> None:
    assert placement_rule([CellSpan("c", 0, 10)], [6, 10]) == (("c", 7),)


def test_placement_drops_a_cell_with_no_eligible_event() -> None:
    assert placement_rule([CellSpan("c", 0, 1)], [0, 1]) == ()


def test_placement_ranks_by_sha256_and_keeps_five() -> None:
    import hashlib

    cells = [CellSpan(f"id-{index}", 0, 20) for index in range(7)]
    chosen = placement_rule(cells, [20])
    ranked = sorted(cells, key=lambda cell: hashlib.sha256(cell.cell_id.encode()).digest())
    assert [cell for cell, _event in chosen] == [cell.cell_id for cell in ranked[:5]]
    assert all(event == 10 for _cell, event in chosen)


def test_a1_clear_favorable_passes_and_crossed_names_the_prefix() -> None:
    close = _priced_close("C", side="LONG", reason="FAVORABLE", entry_seq=1, exit_seq=6, price=1)
    good = Records([_rail_row(5), _fire_row("C", 5, "FAVORABLE"), close], {}, ())
    check_a1(good, quiet_limit_ns=5_000_000_000)
    bad = Records(
        [_rail_row(5, crossed=True), _fire_row("C", 5, "FAVORABLE"), close],
        {},
        (),
    )
    with pytest.raises(AssertionError, match=r"^A1:"):
        check_a1(bad, quiet_limit_ns=5_000_000_000)


def _a2(price: int, *, suppress: bool) -> Records:
    rows = [
        _fire_row("A", 8, "ADVERSE"),
        _priced_close(
            "A", side="LONG", reason="ADVERSE", entry_seq=1, exit_seq=10, price=price, flag=True
        ),
        _fire_row("B", 28, "ADVERSE"),
        _priced_close(
            "B", side="LONG", reason="ADVERSE", entry_seq=20, exit_seq=30, price=100, flag=False
        ),
    ]
    if suppress:
        rows.append(
            _row(
                "GateDecision",
                {
                    "cell_id": "A",
                    "rail_sequence": 5,
                    "gate": "FAVORABLE",
                    "outcome": "suppressed",
                    "reason": "CROSSED",
                },
                5,
            )
        )
    verdict = _verdict(RiskAction.ALLOW, "within limits")
    return Records(rows, {}, (), (verdict,))


def test_a2_equal_streams_pass_and_a_moved_price_names_the_prefix() -> None:
    clean = _a2(50, suppress=True)
    check_a2(clean, _a2(50, suppress=True), feed_gap_sequences={5})
    with pytest.raises(AssertionError, match=r"^A2:"):
        check_a2(clean, _a2(51, suppress=True), feed_gap_sequences={5})


def test_a3_end_of_tape_uses_the_last_usable_side() -> None:
    """D-109. END_OF_TAPE is priced off the last usable rail, not a fill."""
    side = _side_flags()
    side["valuation_mark_cents"] = 10_010
    rail = _row(
        "MarkRailUpdate",
        {"quote_sequence": 5, "long": side, "short": dict(side)},
        5,
    )
    good = _row(
        "PositionClosed",
        {
            "cell_id": "C",
            "side": "LONG",
            "exit_reason": "END_OF_TAPE",
            "proposed_price_cents": 10_010,
            "closed_on_stale_data": False,
            "entry_fills": [],
            "exit_fills": [],
        },
        9,
    )
    check_a3(Records([rail, good], {}, ()))
    wrong = _row(
        "PositionClosed",
        {
            "cell_id": "C",
            "side": "LONG",
            "exit_reason": "END_OF_TAPE",
            "proposed_price_cents": 9_999,
            "closed_on_stale_data": False,
            "entry_fills": [],
            "exit_fills": [],
        },
        9,
    )
    with pytest.raises(AssertionError, match=r"^A3:"):
        check_a3(Records([rail, wrong], {}, ()))
    other = _row(
        "PositionClosed",
        {
            "cell_id": "C",
            "side": "LONG",
            "exit_reason": "ADVERSE",
            "proposed_price_cents": 10_010,
            "entry_fills": [{"sequence": 1, "price_cents": 1, "quantity": 1}],
            "exit_fills": [],
        },
        9,
    )
    with pytest.raises(AssertionError, match=r"^A3:"):
        check_a3(Records([other], {}, ()))


def _bus_record(ordinal: int, type_name: str, body: dict[str, object]) -> Record:
    return Record(None, type_name, _canon(type_name, body), None, ordinal)


def _golden_29043() -> Records:
    """Real cell 29043 with placeholder prices. The file has no tape prices or sizes."""
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "m5_real_29043.json").read_text(encoding="utf-8")
    )
    close = _closed(
        str(payload["cell_id"]),
        side=str(payload["side"]),
        entry_px=1,
        exit_px=1,
        qty=1,
        entry_seq=int(payload["entry_fill_timestamps_ns"][0]),
        exit_seq=int(payload["exit_fill_timestamps_ns"][0]),
        reason=str(payload["exit_reason"]),
        paths=[(str(path), 1) for path in payload["paths"]],
        proposed=1,
        symbol=str(payload["symbol"]),
    )
    rows = [close]
    for event in payload["events"]:
        ordinal = int(event["ordinal"])
        kind = str(event["type"])
        if kind == "OrderAck":
            rows.append(
                _bus_record(
                    ordinal,
                    kind,
                    {
                        "timestamp_ns": int(event["timestamp_ns"]),
                        "order_id": str(event["order_id"]),
                        "status": str(event["status"]),
                        "symbol": str(event["symbol"]),
                    },
                )
            )
        elif kind == "SlicePositionUpdate":
            rows.append(
                _bus_record(
                    ordinal,
                    kind,
                    {
                        "fill_timestamp_ns": int(event["fill_timestamp_ns"]),
                        "order_id": str(event["order_id"]),
                        "symbol": str(event["symbol"]),
                        "strategy_id": str(event["strategy_id"]),
                    },
                )
            )
        elif kind == "DeRiskRequirement":
            rows.append(
                _bus_record(
                    ordinal,
                    kind,
                    {
                        "timestamp_ns": int(event["timestamp_ns"]),
                        "order_id": str(event["order_id"]),
                        "reason": str(event["reason"]),
                        "symbol": str(event["symbol"]),
                        "strategy_id": str(event["strategy_id"]),
                    },
                )
            )
    return Records(rows, {}, ())


def test_m5_real_29043_requirement_is_inside_the_bus_window() -> None:
    """The cell's only requirement is ADVERSE on |EXIT|1, published after the entry fill."""
    records = _golden_29043()
    exit_reason_at_collision(records)
    requirements = [row for row in records if row.type_name == "DeRiskRequirement"]
    assert len(requirements) == 1
    body = json.loads(requirements[0].canonical[requirements[0].canonical.index("{") :])
    assert str(body["order_id"]).endswith("|EXIT|1")
    close = json.loads(records[0].canonical[records[0].canonical.index("{") :])
    assert close["exit_reason"] == "ADVERSE"


def test_requirement_exchange_ts_20ms_before_entry_clock_stays_in_window() -> None:
    """A requirement 20 ms before the entry fill's clock stamp is still after that ack."""
    entry_ts = 20_000_000
    exit_ts = 40_000_000
    cell = "C"
    closed = _closed(
        cell,
        side="LONG",
        entry_px=1,
        exit_px=1,
        qty=1,
        entry_seq=entry_ts,
        exit_seq=exit_ts,
        reason="ADVERSE",
        paths=[("ADVERSE", 1)],
        proposed=1,
    )
    rows = [
        closed,
        _bus_record(
            1,
            "OrderAck",
            {
                "timestamp_ns": entry_ts,
                "order_id": "entry",
                "status": "FILLED",
                "symbol": "SYN",
            },
        ),
        _bus_record(
            2,
            "SlicePositionUpdate",
            {
                "fill_timestamp_ns": entry_ts,
                "order_id": "entry",
                "symbol": "SYN",
                "strategy_id": "sig_position_fixture_v1",
            },
        ),
        _bus_record(
            3,
            "DeRiskRequirement",
            {
                "timestamp_ns": entry_ts - 20_000_000,
                "order_id": f"{cell}|EXIT|1",
                "symbol": "SYN",
                "strategy_id": "sig_position_fixture_v1",
                "reason": "ADVERSE_EXCURSION",
            },
        ),
        _bus_record(
            4,
            "OrderAck",
            {
                "timestamp_ns": exit_ts,
                "order_id": f"{cell}|EXIT|1",
                "status": "FILLED",
                "symbol": "SYN",
            },
        ),
    ]
    exit_reason_at_collision(Records(rows, _quotes(), ()))


def test_requirement_reemission_only_after_rejected() -> None:
    """D-106. A second requirement is legal only after a REJECTED ack."""
    closed = _closed(
        "C",
        side="LONG",
        entry_px=10_001,
        exit_px=9_990,
        qty=10,
        entry_seq=2,
        exit_seq=10,
        reason="ADVERSE",
        paths=[("ADVERSE", 9_990)],
        proposed=9_990,
    )

    def _req(ordinal: int, order_id: str, ts: int) -> Record:
        body = {
            "symbol": "SYN",
            "strategy_id": "sig_position_fixture_v1",
            "timestamp_ns": ts,
            "order_id": order_id,
            "reason": "ADVERSE_EXCURSION",
            "source_layer": "POSITION",
        }
        return Record(ts, "DeRiskRequirement", _canon("DeRiskRequirement", body), None, ordinal)

    def _reject(ordinal: int, order_id: str, ts: int) -> Record:
        body = {"timestamp_ns": ts, "order_id": order_id, "status": "REJECTED"}
        return Record(ts, "OrderAck", _canon("OrderAck", body), None, ordinal)

    entry_ack = _bus_record(
        1,
        "OrderAck",
        {"timestamp_ns": 2, "order_id": "entry", "status": "FILLED", "symbol": "SYN"},
    )
    exit_ack = _bus_record(
        9,
        "OrderAck",
        {"timestamp_ns": 10, "order_id": "C|EXIT|2", "status": "FILLED", "symbol": "SYN"},
    )
    with pytest.raises(AssertionError, match=r"^requirement re-emitted"):
        exit_reason_at_collision(
            Records(
                [closed, entry_ack, _req(3, "C|EXIT|1", 3), _req(6, "C|EXIT|2", 6), exit_ack],
                _quotes(),
                (),
            )
        )
    exit_reason_at_collision(
        Records(
            [
                closed,
                entry_ack,
                _req(3, "C|EXIT|1", 3),
                _reject(4, "C|EXIT|1", 4),
                _req(6, "C|EXIT|2", 6),
                exit_ack,
            ],
            _quotes(),
            (),
        )
    )


def test_precondition_names_a_zero_count_and_passes_an_opening_fill() -> None:
    from decimal import Decimal

    from feelies.core.events import SlicePositionUpdate

    from tests.position_engine.scenarios import require_entry_fills

    empty = Records([], {}, ())
    with pytest.raises(AssertionError, match=r"^PRECONDITION: run has ≥1 entry fill \(0\)$"):
        require_entry_fills(empty)
    opening = SlicePositionUpdate(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="SYN",
        strategy_id="sig",
        order_id="o",
        fill_price=Decimal("100.01"),
        fill_quantity=10,
        fill_ack_sequence=302,
        fill_timestamp_ns=1,
        quantity=10,
        avg_entry_price=Decimal("100.01"),
    )
    held = Records([], {}, (), slice_updates=(opening,))
    assert require_entry_fills(held) == 1


def test_a3a_rejects_a_level_price_that_is_not_the_fill() -> None:
    """A close priced at the level, rather than the exit fill ack, fails A3a."""
    close = _priced_close("C", side="LONG", reason="ADVERSE", entry_seq=1, exit_seq=2, price=50)
    fire = Record(
        2,
        "GateDecision",
        _canon(
            "GateDecision",
            {
                "cell_id": "C",
                "rail_sequence": 2,
                "gate": "ADVERSE",
                "outcome": "fire",
                "reason": "",
            },
        ),
        None,
        1,
    )
    ack = Record(
        2,
        "OrderAck",
        _canon(
            "OrderAck",
            {
                "order_id": "C|EXIT|1",
                "status": "FILLED",
                "symbol": "SYN",
                "timestamp_ns": 2,
                "price_cents": 40,
            },
        ),
        None,
        2,
    )
    records = Records([fire, close, ack], {2: _book(2, 40, 41, 2)}, ())
    with pytest.raises(AssertionError, match=r"^A3a:"):
        check_a3(records)


def test_a3b_rejects_a_fill_better_than_its_pricing_quote() -> None:
    """A fill better than the quote being processed fails A3b. A3b assumes the R2 model."""
    close = _priced_close("C", side="LONG", reason="ADVERSE", entry_seq=1, exit_seq=2, price=50)
    fire = Record(
        2,
        "GateDecision",
        _canon(
            "GateDecision",
            {
                "cell_id": "C",
                "rail_sequence": 2,
                "gate": "ADVERSE",
                "outcome": "fire",
                "reason": "",
            },
        ),
        None,
        1,
    )
    ack = Record(
        2,
        "OrderAck",
        _canon(
            "OrderAck",
            {
                "order_id": "C|EXIT|1",
                "status": "FILLED",
                "symbol": "SYN",
                "timestamp_ns": 2,
                "price_cents": 50,
            },
        ),
        None,
        2,
    )
    records = Records([fire, close, ack], {2: _book(2, 40, 41, 2)}, ())
    with pytest.raises(AssertionError, match=r"^A3b:"):
        check_a3(records)


def _exit_ack(cell: str, price: int, quote: int, ordinal: int) -> Record:
    return Record(
        quote,
        "OrderAck",
        _canon(
            "OrderAck",
            {
                "order_id": f"{cell}|EXIT|1",
                "status": "FILLED",
                "symbol": "SYN",
                "timestamp_ns": quote,
                "price_cents": price,
            },
        ),
        None,
        ordinal,
    )


def test_a3_fill_quote_passes_and_the_wrong_side_names_the_prefix() -> None:
    quotes = {2: _book(2, 10_010, 10_011, 2)}
    fire = _fire_row("C", 2, "ADVERSE")._replace(bus_ordinal=1)
    good = Records(
        [
            fire,
            _priced_close(
                "C", side="LONG", reason="ADVERSE", entry_seq=1, exit_seq=2, price=10_010
            ),
            _exit_ack("C", 10_010, 2, 2),
        ],
        quotes,
        (),
    )
    check_a3(good)
    bad = Records(
        [
            fire,
            _priced_close(
                "C", side="LONG", reason="ADVERSE", entry_seq=1, exit_seq=2, price=10_011
            ),
            _exit_ack("C", 10_011, 2, 2),
        ],
        quotes,
        (),
    )
    with pytest.raises(AssertionError, match=r"^A3b:"):
        check_a3(bad)


def test_a4_gap_through_passes_and_the_barrier_price_names_the_prefix() -> None:
    quotes = {
        2: _book(2, 10_000, 10_001, 2),
        4: _book(4, 9_970, 9_971, 4),
    }
    good = Records(
        [_priced_close("C", side="LONG", reason="ADVERSE", entry_seq=2, exit_seq=4, price=9_970)],
        quotes,
        (),
    )
    check_a4(good, birth_sequence=2, centre=11, band=0)
    barrier_book = {2: quotes[2], 4: _book(4, 9_989, 9_990, 4)}
    bad = Records(
        [_priced_close("C", side="LONG", reason="ADVERSE", entry_seq=2, exit_seq=4, price=9_989)],
        barrier_book,
        (),
    )
    with pytest.raises(AssertionError, match=r"^A4:"):
        check_a4(bad, birth_sequence=2, centre=11, band=0)


def test_a5_over_a_passes_and_an_early_blind_names_the_prefix() -> None:
    rows = [
        _fire_row("C", 10, "ADVERSE"),
        _priced_close(
            "C", side="LONG", reason="ADVERSE", entry_seq=1, exit_seq=11, price=1, blind=True
        ),
    ]
    records = Records(rows, {}, ())
    check_a5(records, expect_blind=True, deciding_sequence=10)
    with pytest.raises(AssertionError, match=r"^A5:"):
        check_a5(records, expect_blind=False)


def test_a6_adverse_reveal_passes_and_the_wrong_reason_names_the_prefix() -> None:
    good = Records(
        [
            _fire_row("C", 20, "ADVERSE"),
            _priced_close("C", side="SHORT", reason="ADVERSE", entry_seq=10, exit_seq=21, price=1),
        ],
        {},
        (),
    )
    check_a6(good, birth_sequence=10, kind="ADVERSE", deciding_sequence=20)
    bad = Records(
        [
            _fire_row("C", 20, "ADVERSE"),
            _priced_close("C", side="SHORT", reason="HORIZON", entry_seq=10, exit_seq=21, price=1),
        ],
        {},
        (),
    )
    with pytest.raises(AssertionError, match=r"^A6:"):
        check_a6(bad, birth_sequence=10, kind="ADVERSE", deciding_sequence=20)


def test_unusable_side_clocks_pass_and_a_present_side_names_the_prefix() -> None:
    gap = 100_000_000
    quotes = {1: _book(1, 10_000, 10_001, 0), 2: _book(2, 10_050, 10_000, gap)}
    clear = Records(
        [_rail_row(2, absent=True, quiet=gap, paying_absent=gap, valuation_absent=gap)],
        quotes,
        (),
    )
    check_unusable_side(clear, quote_sequence=2)
    present = Records([_rail_row(2, quiet=gap)], quotes, ())
    with pytest.raises(AssertionError, match=r"^UNUSABLE_SIDE:"):
        check_unusable_side(present, quote_sequence=2)


def test_feed_gap_seam_sets_chosen_sequences_only() -> None:
    from dataclasses import replace

    from feelies.core.identifiers import SequenceGenerator
    from feelies.portfolio.mark_rail import MarkRail
    from tests.position_engine.scenarios import _seams

    def wrapper(original: object, quote: NBBOQuote) -> object:
        update = original(quote)  # type: ignore[operator]
        if quote.sequence == 4:
            return replace(update, feed_gap_before=True)
        return update

    tape = make_tape(seed=1, n=6, symbol="SYN", start_ns=T0)
    rail = MarkRail(SequenceGenerator(thread_safe=False))
    with _seams(None, wrapper, True):
        flags = [rail.on_quote(quote).feed_gap_before for quote in tape]
    assert flags == [False, False, False, True, False, False]


_PROBE_ENGINE = "tests.position_engine.test_scenarios.ProbeEngine"
_PROBE_RAIL = "tests.position_engine.test_scenarios.ProbeRail"


def _probe_write(line: str) -> None:
    path = os.environ.get("FEELIES_PROBE_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


class ProbeEngine:
    """Resolution probe. Delegates so a resolved run still completes."""

    def __init__(
        self,
        bus: object,
        sequence_generator: object,
        policies: object = None,
        gate_order: object = None,
    ) -> None:
        _probe_write(f"engine {gate_order!r}")
        self._inner = _ProductionEngine(
            bus,  # type: ignore[arg-type]
            sequence_generator,  # type: ignore[arg-type]
            policies=policies,  # type: ignore[arg-type]
        )

    def attach(self) -> None:
        self._inner.attach()


class ProbeRail:
    """Resolution probe. Delegates to the production stub rail."""

    def __init__(self, sequence_generator: object) -> None:
        _probe_write("rail")
        self._inner = _ProductionRail(sequence_generator)  # type: ignore[arg-type]

    def on_quote(self, quote: NBBOQuote) -> MarkRailUpdate:
        return self._inner.on_quote(quote)


class AttrProbe:
    """Publishes a nested snapshot on quote 303 and an end record from finalize."""

    def __init__(
        self, bus: object, sequence_generator: object, policies: object = None, **kwargs: object
    ) -> None:
        del policies, kwargs
        self._bus = bus
        self._seq = sequence_generator

    def attach(self) -> None:
        self._bus.subscribe(MarkRailUpdate, self._on_mark)  # type: ignore[attr-defined]

    def _on_mark(self, event: MarkRailUpdate) -> None:
        if event.quote_sequence == 303:
            self._bus.publish(_snapshot("nested-303", 303))  # type: ignore[attr-defined]

    def finalize(self) -> None:
        self._bus.publish(_eot_close(self._seq.next()))  # type: ignore[attr-defined]


def _eot_close(sequence: int) -> PositionClosed:
    extreme = _extreme()
    return PositionClosed(
        timestamp_ns=1,
        correlation_id="eot",
        sequence=sequence,
        cell_id="EOT",
        symbol="SYN",
        strategy_id="sig",
        side="LONG",
        declared_archetype="MARKET",
        entry_fills=(),
        exit_fills=(),
        entry_spread_ticks=1,
        horizon_deadline_ns=1,
        drawn_level_ticks=0,
        exit_reason="END_OF_TAPE",
        triggered_paths=(),
        proposed_price_cents=0,
        best=extreme,
        worst=extreme,
        best_clean=extreme,
        closed_on_stale_data=False,
        exited_on_unusable_data=False,
        lived_through_feed_gap=False,
        first_event_exit=False,
        stop_inside_round_trip=False,
        target_inside_round_trip=False,
        uncalibrated=False,
        supersedes="",
    )


def _probe_env(log: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    env["FEELIES_PROBE_LOG"] = str(log)
    env["FEELIES_ENGINE"] = _PROBE_ENGINE
    env["FEELIES_RAIL"] = _PROBE_RAIL
    return env


def _assert_probe(log: Path) -> None:
    text = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert "engine" in text and "rail" in text, f"probe is not constructed: {text!r}"


def test_unset_resolution_matches_stub_records() -> None:
    tape = make_tape(seed=11, n=20, symbol="SYN", start_ns=T0, size=1000)
    records = run_synthetic(tape, symbols=("SYN",))
    digest = hashlib.sha256("\n".join(format_line(row) for row in records).encode()).hexdigest()
    assert digest == "00b7771e3c9b3718f21b313b208bf920bcf53e0c822c35fbb99be227c97eec57"


def test_resolution_in_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "probe.log"
    monkeypatch.setenv("FEELIES_PROBE_LOG", str(log))
    monkeypatch.setenv("FEELIES_ENGINE", _PROBE_ENGINE)
    monkeypatch.setenv("FEELIES_RAIL", _PROBE_RAIL)
    tape = make_tape(seed=11, n=4, symbol="SYN", start_ns=T0, size=1000)
    run_synthetic(tape, symbols=("SYN",))
    _assert_probe(log)


def test_resolution_fresh_child(tmp_path: Path) -> None:
    log = tmp_path / "probe.log"
    proc = subprocess.run(
        [sys.executable, "-m", "tests.position_engine.scenarios", "syn_m1"],
        check=False,
        capture_output=True,
        text=True,
        env=_probe_env(log),
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    _assert_probe(log)


def test_resolution_prefix_child(tmp_path: Path) -> None:
    log = tmp_path / "probe.log"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.position_engine.scenarios",
            "prefix",
            "12",
            str(tmp_path / "cut.bin"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=_probe_env(log),
    )
    del proc
    _assert_probe(log)


def test_resolution_m1_gates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "probe.log"
    monkeypatch.setenv("FEELIES_PROBE_LOG", str(log))
    monkeypatch.setenv("FEELIES_ENGINE", _PROBE_ENGINE)
    monkeypatch.setenv("FEELIES_RAIL", _PROBE_RAIL)
    from tests.position_engine.scenarios import engine_class

    tape = make_tape(seed=21, n=4, symbol="SYN", start_ns=T0, size=1000)
    run_synthetic(
        tape,
        symbols=("SYN",),
        engine_factory=partial(engine_class(), gate_order=("FAVORABLE", "ADVERSE")),
    )
    text = log.read_text(encoding="utf-8") if log.is_file() else ""
    assert "engine" in text and "rail" in text, f"probe is not constructed: {text!r}"
    assert "FAVORABLE" in text, text


def _attr_run() -> tuple[Records, list[NBBOQuote]]:
    tape = make_tape(seed=11, n=304, symbol="SYN", start_ns=T0, size=1000)
    records = run_synthetic(tape, symbols=("SYN",), engine_factory=AttrProbe)
    return records, tape


def test_attr_nested_cursor_is_the_causing_rail() -> None:
    records, _tape = _attr_run()
    snaps = [row for row in records if row.type_name == "PositionSnapshot"]
    assert snaps, "probe snapshot missing"
    assert snaps[0].attributed_quote_sequence == 303


def test_attr_eot_excluded_from_prefix() -> None:
    records, tape = _attr_run()
    eot = [row for row in records if row.attributed_quote_sequence == "EOT"]
    assert eot, "EOT cursor is a quote"
    assert eot[0].replay_index == len(tape)
    widened_eot = [row for row in records.widened if row.cursor == "EOT"]
    assert widened_eot, "EOT cursor is a quote"
    assert widened_eot[0].replay_index == len(tape)
    seq = tape[-1].sequence
    assert_widened_prefix(records.widened, records.widened, seq)
    kept = [row for row in records.widened if isinstance(row.cursor, int) and row.cursor <= seq]
    assert all(row.cursor != "EOT" for row in kept)


def test_favorable_tie_precondition_is_tape_computed() -> None:
    """The first favorable quote must also hold the higher path. Tape only."""
    from tests.position_engine.scenarios import require_favorable_tie
    from tests.position_engine.tapes import hold, make_tape, set_quote

    tape = make_tape(seed=1, n=20, symbol="SYN", start_ns=T0, size=100)
    birth = 2
    entry = int(tape[birth].ask * 100)
    kwargs: dict[str, object] = {
        "higher": "INVALIDATION",
        "birth_index": birth,
        "target_ticks": 4,
        "adverse_ticks": 11,
        "horizon_ns": 16_000 * 1_000_000_000,
        "form": "fixed",
        "giveback_multiple": None,
        "spread_ticks": 1,
        "fee_ticks": 0,
        "quiet_limit_ns": 5_000_000_000,
        "resolution_index": 8,
    }
    early = set_quote(tape, 5, bid_cents=entry + 4, ask_cents=entry + 5)
    with pytest.raises(AssertionError, match=r"^PRECONDITION: FAVORABLE"):
        require_favorable_tie(early, **kwargs)  # type: ignore[arg-type]
    pinned = set_quote(hold(tape, birth, 6), 8, bid_cents=entry + 4, ask_cents=entry + 5)
    assert require_favorable_tie(pinned, **kwargs) == 8  # type: ignore[arg-type]


def test_barrier_precondition_is_tape_computed() -> None:
    """The barrier level is not the executable side of the landing quote."""
    from tests.position_engine.scenarios import drawn_adverse_level, require_barrier_differs
    from tests.position_engine.tapes import make_tape, set_quote

    tape = make_tape(seed=1, n=10, symbol="SYN", start_ns=T0, size=100)
    birth = tape[2]
    cell = f"SYN|sig_position_fixture_v1|{birth.sequence}|LONG"
    barrier = int(birth.bid * 100) - drawn_adverse_level(cell, 11, 0)
    same = set_quote(tape, 3, bid_cents=barrier, ask_cents=barrier + 1)
    with pytest.raises(AssertionError, match=r"^PRECONDITION: barrier"):
        require_barrier_differs(same, birth_index=2, landing_index=3, centre=11, band=0)
    other = set_quote(tape, 3, bid_cents=barrier - 3, ask_cents=barrier - 2)
    require_barrier_differs(other, birth_index=2, landing_index=3, centre=11, band=0)


def test_session_digest_is_keyed_by_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """A digest stored under engine A is not returned under engine B, and is under A."""
    from tests.position_engine.scenarios import Widened, _SESSION_DIGESTS, session_digest

    saved = dict(_SESSION_DIGESTS)
    _SESSION_DIGESTS.clear()
    tape = "unit-tape"
    under_a = (Widened(1, "NBBOQuote", b"aaa"),)
    under_b = (Widened(1, "NBBOQuote", b"bbb"),)
    try:
        monkeypatch.setenv("FEELIES_ENGINE", "tests.position_engine.engine_a.Engine")
        assert session_digest(tape, under_a) == under_a
        monkeypatch.setenv("FEELIES_ENGINE", "tests.position_engine.engine_b.Engine")
        got = session_digest(tape, under_b)
        assert got == under_b
        monkeypatch.setenv("FEELIES_ENGINE", "tests.position_engine.engine_a.Engine")
        assert session_digest(tape, under_b) == under_a
    finally:
        _SESSION_DIGESTS.clear()
        _SESSION_DIGESTS.update(saved)


def _pack_spans(values: list[object]) -> tuple[list[bytes], set[tuple[object, ...]]]:
    from tests.position_engine.scenarios import _DEC_PACK, _feed_scalar

    saved = dict(_DEC_PACK)
    _DEC_PACK.clear()
    try:
        buf = bytearray()
        spans: list[bytes] = []
        for value in values:
            start = len(buf)
            assert _feed_scalar(buf, value)
            spans.append(bytes(buf[start:]))
        return spans, set(_DEC_PACK)
    finally:
        _DEC_PACK.clear()
        _DEC_PACK.update(saved)


def _decimal_text(packed: bytes) -> str:
    assert packed[:1] == b"D"
    length = int.from_bytes(packed[1:5], "little")
    return packed[5 : 5 + length].decode()


def test_decimal_pack_keeps_exact_text() -> None:
    """Decimal('1.00') keeps its own text after Decimal('1.0') was packed."""
    spans, _keys = _pack_spans([Decimal("1.0"), Decimal("1.00")])
    assert _decimal_text(spans[1]) == "1.00"


def test_float_pack_keeps_signed_zero() -> None:
    """-0.0 keeps its own encoding after 0.0 was packed."""
    spans, keys = _pack_spans([0.0, -0.0])
    assert (float, "-0.0") in keys
    cold, _cold_keys = _pack_spans([-0.0])
    assert spans[1] == cold[0]
    assert spans[1] != spans[0]


def test_numeric_pack_keeps_type() -> None:
    """1, True, and 1.0 each keep their own encoding."""
    spans, keys = _pack_spans([1, True, 1.0])
    assert (int, 1) in keys
    assert (bool, True) in keys
    assert (float, "1.0") in keys
    alone_int, _ = _pack_spans([1])
    alone_bool, _ = _pack_spans([True])
    alone_float, _ = _pack_spans([1.0])
    assert spans[0] == alone_int[0]
    assert spans[1] == alone_bool[0]
    assert spans[2] == alone_float[0]
    assert len({spans[0], spans[1], spans[2]}) == 3
