"""Harness self-tests. Ordinary tests; no battery marker."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from feelies.alpha.loader import AlphaLoader
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


def test_a3_fill_quote_passes_and_the_wrong_side_names_the_prefix() -> None:
    quotes = {2: _book(2, 10_010, 10_011, 2)}
    good = Records(
        [
            _fire_row("C", 2, "ADVERSE"),
            _priced_close(
                "C", side="LONG", reason="ADVERSE", entry_seq=1, exit_seq=2, price=10_010
            ),
        ],
        quotes,
        (),
    )
    check_a3(good)
    bad = Records(
        [
            _fire_row("C", 2, "ADVERSE"),
            _priced_close(
                "C", side="LONG", reason="ADVERSE", entry_seq=1, exit_seq=2, price=10_011
            ),
        ],
        quotes,
        (),
    )
    with pytest.raises(AssertionError, match=r"^A3:"):
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
