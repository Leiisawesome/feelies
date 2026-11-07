"""Battery member 8, decision record completeness (battery.md). P-59.

Member 6 synthetic builders imported from test_battery_m6_injection_syn:
``_absent``, ``_cross_span``, ``_quiet``, ``_v3a``, ``_v5``. The a4, a6 and
a2 tapes are inlined in that file, so those lines are copied. Member 6
synthetic runs pass no rail wrapper.
"""

from __future__ import annotations

import functools
import json
from typing import NamedTuple, cast

import pytest

from feelies.core.events import NBBOQuote
from tests.position_engine.scenarios import (
    T0,
    Records,
    _resolution_key,
    require_adverse_level,
    require_entry_fills,
    run_synthetic,
)
from tests.position_engine.tapes import cross, excise, make_tape, shift_from
from tests.position_engine.test_battery_m6_injection_syn import (
    _absent,
    _cross_span,
    _quiet,
    _v3a,
    _v5,
)

_ADVERSE = pytest.mark.battery_member(
    member=8,
    green_from="E",
    red_reason=r"^(CAP:gate_fire|NONVACUOUS)",
)
_FAVORABLE = pytest.mark.battery_member(
    member=8,
    green_from="E",
    red_reason=r"^NONVACUOUS",
)
_FAVORABLE_REASONS = frozenset(
    {
        "VALUATION_SIDE_ABSENT",
        "CROSSED",
        "FEED_GAP",
        "DWELL_NOT_CLEAN",
        "NOT_WARMED_UP",
        "SYMBOL_QUIET",
    }
)


class Run(NamedTuple):
    """One battery run. ``injected`` is set where the run is built."""

    name: str
    records: Records
    injected: bool
    origin: str


def _body(canonical: str) -> dict[str, object]:
    parsed = json.loads(canonical[canonical.index("{") :])
    if not isinstance(parsed, dict):
        raise AssertionError(f"record body is not an object: {canonical[:80]!r}")
    return cast(dict[str, object], parsed)


def _quotes(tape: list[object]) -> list[NBBOQuote]:
    return cast(list[NBBOQuote], tape)


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    return str(value)


def _whole(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _stamp_ordinal(cell_id: str) -> tuple[int, int]:
    parts = cell_id.split("|")
    ordinal = 0
    if len(parts) >= 2 and parts[-1].isdigit() and parts[-2] in {"LONG", "SHORT"}:
        ordinal = int(parts[-1])
        parts = parts[:-1]
    return int(parts[-2]), ordinal


def _birth_ordinal(records: Records, closed: dict[str, object]) -> int:
    """Bus ordinal of the birth fill. Slice updates carry that attribution."""
    symbol = _text(closed.get("symbol"))
    strategy = _text(closed.get("strategy_id"))
    side = _text(closed.get("side"))
    entries = closed.get("entry_fills")
    stamp: int | None = None
    if isinstance(entries, list) and entries and isinstance(entries[0], dict):
        stamp = _whole(entries[0].get("timestamp_ns"))
    if stamp is None:
        stamp, _ordinal = _stamp_ordinal(_text(closed.get("cell_id")))
    _id_stamp, ordinal = _stamp_ordinal(_text(closed.get("cell_id")))
    del _id_stamp
    matches: list[int] = []
    for index, update in enumerate(records.slice_updates):
        if update.symbol != symbol or update.strategy_id != strategy:
            continue
        if int(update.fill_timestamp_ns) != stamp:
            continue
        update_side = "LONG" if update.fill_quantity > 0 else "SHORT"
        if update_side != side:
            continue
        matches.append(index)
    if ordinal >= len(matches):
        return -1
    return int(records.slice_ordinals[matches[ordinal]])


def _rails(records: Records) -> list[tuple[int, str, int]]:
    """(bus ordinal, symbol, quote sequence) for each MarkRailUpdate, in bus order."""
    found: list[tuple[int, str, int]] = []
    for row in records:
        if row.type_name != "MarkRailUpdate":
            continue
        body = _body(row.canonical)
        sequence = _whole(body.get("quote_sequence"))
        if sequence is None:
            continue
        found.append((row.bus_ordinal, _text(body.get("symbol")), sequence))
    return found


def cell_events(records: Records) -> list[tuple[str, tuple[int, ...]]]:
    """E(cell) quote sequences for each PositionClosed, in bus order.

    The window is the rail events of the cell's symbol strictly after the
    birth fill and strictly before PositionClosed. PositionSnapshot rows
    do not choose the window.
    """
    rails = _rails(records)
    lives: list[tuple[str, tuple[int, ...]]] = []
    for row in records:
        if row.type_name != "PositionClosed":
            continue
        closed = _body(row.canonical)
        cell_id = _text(closed.get("cell_id"))
        symbol = _text(closed.get("symbol"))
        birth = _birth_ordinal(records, closed)
        close = row.bus_ordinal
        if birth < 0:
            lives.append((cell_id, ()))
            continue
        sequences = tuple(
            sequence
            for ordinal, rail_symbol, sequence in rails
            if rail_symbol == symbol and birth < ordinal < close
        )
        lives.append((cell_id, sequences))
    return lives


def _states(records: Records) -> dict[tuple[str, int], str]:
    found: dict[tuple[str, int], str] = {}
    for row in records:
        if row.type_name != "PositionSnapshot":
            continue
        body = _body(row.canonical)
        cell_id = body.get("cell_id")
        sequence = _whole(body.get("rail_sequence"))
        if not isinstance(cell_id, str) or sequence is None:
            continue
        found[(cell_id, sequence)] = _text(body.get("state"))
    return found


def _gate_rows(records: Records) -> list[dict[str, object]]:
    return [_body(row.canonical) for row in records if row.type_name == "GateDecision"]


def _has_adverse(records: Records) -> bool:
    return any(body.get("gate") == "ADVERSE" for body in _gate_rows(records))


def _has_suppressed_favorable(records: Records) -> bool:
    return any(
        body.get("gate") == "FAVORABLE" and body.get("outcome") == "suppressed"
        for body in _gate_rows(records)
    )


def exiting_rail_count(records: Records) -> int:
    """|E(cell)| events whose PositionSnapshot at that rail is EXITING."""
    states = _states(records)
    total = 0
    for cell_id, sequences in cell_events(records):
        total += sum(1 for sequence in sequences if states.get((cell_id, sequence)) == "EXITING")
    return total


def favorable_outcomes(records: Records) -> dict[str, int]:
    counts: dict[str, int] = {}
    for body in _gate_rows(records):
        if body.get("gate") != "FAVORABLE":
            continue
        outcome = _text(body.get("outcome"))
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


def _run(name: str, records: Records, injected: bool, origin: str) -> Run:
    return Run(name, records, injected, origin)


def _build_synthetic_runs() -> list[Run]:
    # Injected (battery.md:19-23) only when the tape or rail is edited by hold,
    # remove_side, remove_side_run, cross, force_class of a non-VALID class, or
    # the feed-gap rail seam. excise and shift_from alone leave the flag false.
    runs: list[Run] = []
    variant = _v3a()
    gap = shift_from(
        excise(make_tape(seed=11, n=800, symbol="SYN", start_ns=T0, size=1000), 302, 20), 302, -15
    )
    runs.append(_run("a4", run_synthetic(gap, symbols=("SYN",), variant=variant), False, "m6"))
    for n_excise in (298, 299, 300):
        tape, _sequence, _blind = _quiet(n_excise)
        runs.append(
            _run(
                f"a5-quiet-{n_excise}",
                run_synthetic(_quotes(tape), symbols=("SYN",), variant=variant),
                False,
                "m6",
            )
        )
    for count in (299, 300, 301):
        tape, _sequence, _blind = _absent(count, "bid")
        runs.append(
            _run(
                f"a5-valuation-{count}",
                run_synthetic(_quotes(tape), symbols=("SYN",), variant=variant),
                True,
                "m6",
            )
        )
    for count in (299, 300, 301):
        tape, _sequence, _blind = _absent(count, "ask")
        runs.append(
            _run(
                f"a5-paying-{count}",
                run_synthetic(_quotes(tape), symbols=("SYN",), variant=variant),
                True,
                "m6",
            )
        )
    short = _cross_span(
        shift_from(make_tape(seed=11, n=4_000, symbol="SYN", start_ns=T0, size=1000), 3602, 51),
        3602,
        3901,
        10_052,
        10_042,
    )
    runs.append(_run("a6-short", run_synthetic(_quotes(short), symbols=("SYN",)), True, "m6"))
    long = _cross_span(
        shift_from(make_tape(seed=11, n=1_800, symbol="SYN", start_ns=T0, size=1000), 1202, -47),
        1202,
        1503,
        9_978,
        9_977,
    )
    runs.append(_run("a6-long", run_synthetic(_quotes(long), symbols=("SYN",)), True, "m6"))
    clean = make_tape(seed=11, n=2_000, symbol="SYN", start_ns=T0, size=1000)
    trailing = _v5()
    runs.append(
        _run("a2-clean", run_synthetic(clean, symbols=("SYN",), variant=trailing), False, "m6")
    )
    runs.append(
        _run(
            "a2-cross",
            run_synthetic(cross(clean, 400, 10_040, 10_030), symbols=("SYN",), variant=trailing),
            True,
            "m6",
        )
    )
    return runs


@functools.lru_cache(maxsize=4)
def _cached_synthetic_runs(resolution: str) -> tuple[Run, ...]:
    del resolution
    return tuple(_build_synthetic_runs())


def synthetic_runs() -> tuple[Run, ...]:
    return _cached_synthetic_runs(_resolution_key())


def _births_known(run: Run) -> None:
    for row in run.records:
        if row.type_name != "PositionClosed":
            continue
        closed = _body(row.canonical)
        if _birth_ordinal(run.records, closed) < 0:
            cell_id = _text(closed.get("cell_id"))
            raise AssertionError(f"M8: adverse {run.name} {cell_id} rail -: missing")


def _property_adverse(run: Run) -> None:
    _births_known(run)
    states = _states(run.records)
    adverse: dict[tuple[str, int], list[str]] = {}
    for body in _gate_rows(run.records):
        if body.get("gate") != "ADVERSE":
            continue
        cell_id = body.get("cell_id")
        sequence = _whole(body.get("rail_sequence"))
        if not isinstance(cell_id, str) or sequence is None:
            continue
        adverse.setdefault((cell_id, sequence), []).append(_text(body.get("outcome")))
    for cell_id, sequences in cell_events(run.records):
        for sequence in sequences:
            outcomes = adverse.get((cell_id, sequence), [])
            state = states.get((cell_id, sequence), "ABSENT")
            if not outcomes:
                raise AssertionError(f"M8: adverse {run.name} {cell_id} rail {sequence}: missing")
            for outcome in outcomes:
                allowed = outcome in {"fire", "hold"} or (
                    outcome == "ESCALATION_NOOP" and state == "EXITING"
                )
                if not allowed:
                    raise AssertionError(
                        f"M8: adverse {run.name} {cell_id} rail {sequence}: "
                        f"outcome {outcome} in state {state}"
                    )


def _property_favorable(run: Run) -> None:
    for body in _gate_rows(run.records):
        if body.get("gate") != "FAVORABLE" or body.get("outcome") != "suppressed":
            continue
        reason = _text(body.get("reason"))
        if reason in _FAVORABLE_REASONS:
            continue
        cell_id = _text(body.get("cell_id"))
        sequence = _whole(body.get("rail_sequence"))
        rail = "-" if sequence is None else str(sequence)
        raise AssertionError(f"M8: favorable {run.name} {cell_id} rail {rail}: reason {reason}")


def check_adverse_records(runs: tuple[Run, ...] | list[Run]) -> None:
    """Entry fills, adverse level, injected ADVERSE record, then the property."""
    for run in runs:
        require_entry_fills(run.records)
    for run in runs:
        require_adverse_level(run.records)
    for run in runs:
        if run.injected and not _has_adverse(run.records):
            raise AssertionError(f"NONVACUOUS: m8 adverse {run.name}")
    for run in runs:
        _property_adverse(run)


def check_favorable_reasons(runs: tuple[Run, ...] | list[Run]) -> None:
    """Entry fills, injected suppressed FAVORABLE, then the reason set."""
    for run in runs:
        require_entry_fills(run.records)
    for run in runs:
        if run.injected and not _has_suppressed_favorable(run.records):
            raise AssertionError(f"NONVACUOUS: m8 favorable {run.name}")
    for run in runs:
        _property_favorable(run)


@_ADVERSE
def test_m8_adverse_record() -> None:
    check_adverse_records(synthetic_runs())


@_FAVORABLE
def test_m8_favorable_reasons() -> None:
    check_favorable_reasons(synthetic_runs())
