"""battery.md member 7, monotonicity. P-59. D-entries to come."""

from __future__ import annotations

import functools
import json
import math
from typing import cast

import pytest

from feelies.core.events import NBBOQuote
from tests.position_engine.scenarios import (
    T0,
    Record,
    Records,
    cell_economics,
    fixture_variant,
    require_adverse_level,
    require_entry_fills,
    run_synthetic,
)
from tests.position_engine.tapes import cross, make_tape

pytestmark = pytest.mark.battery_member(
    member=7,
    green_from="E",
    red_reason=r"^(CAP:gate_fire|NONVACUOUS)",
)

_SLIPPAGE = (0, 1, 2, 4)
_DWELL = (0, 1_000_000_000, 3_000_000_000, 10_000_000_000)
_GIVEBACK = (0.5, 1, 1.5, 2)
_BAND = (0, 2, 4, 8)
_REASONS = frozenset({"FAVORABLE", "ADVERSE", "HORIZON"})
_N_SHORT = 30_300
_N_BAND = 120_300


def _body(canonical: str) -> dict[str, object]:
    parsed = json.loads(canonical[canonical.index("{") :])
    if not isinstance(parsed, dict):
        raise AssertionError("M7: record body is not an object")
    return cast(dict[str, object], parsed)


def _whole(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _common(**overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "horizon_seconds": 30,
        "T_seconds": 50,
        "fee_round_trip_ticks": 0,
        "centre_ticks": 11,
        "band_ticks": 0,
        "lo_ticks": 2,
        "target_ticks": 4,
        "form": "fixed",
    }
    params.update(overrides)
    return fixture_variant(**params)


def _one(
    monkeypatch: pytest.MonkeyPatch,
    tape: tuple[NBBOQuote, ...],
    variant: dict[str, object],
    *,
    slippage: int,
    dwell: int,
) -> Records:
    monkeypatch.setenv("FEELIES_RAIL_SLIPPAGE_TICKS", str(slippage))
    monkeypatch.setenv("FEELIES_RAIL_DWELL_NS", str(dwell))
    return run_synthetic(tape, symbols=("SYN",), variant=variant)


@functools.lru_cache(maxsize=1)
def _crossed_tape() -> tuple[NBBOQuote, ...]:
    tape = make_tape(seed=29, n=_N_SHORT, symbol="SYN", start_ns=T0, size=1000)
    for index in range(25, len(tape)):
        if index % 50 != 25:
            continue
        quote = tape[index]
        tape = cross(tape, index, int(quote.ask * 100), int(quote.bid * 100))
    return tuple(tape)


@functools.lru_cache(maxsize=1)
def _giveback_tape() -> tuple[NBBOQuote, ...]:
    return tuple(
        make_tape(seed=31, n=_N_SHORT, symbol="SYN", start_ns=T0, size=1000, spread_cents=2)
    )


@functools.lru_cache(maxsize=1)
def _band_tape() -> tuple[NBBOQuote, ...]:
    return tuple(make_tape(seed=37, n=_N_BAND, symbol="SYN", start_ns=T0, size=1000))


def slippage_runs(monkeypatch: pytest.MonkeyPatch) -> list[Records]:
    tape = _crossed_tape()
    variant = _common()
    return [_one(monkeypatch, tape, variant, slippage=slippage, dwell=0) for slippage in _SLIPPAGE]


def dwell_runs(monkeypatch: pytest.MonkeyPatch) -> list[Records]:
    tape = _crossed_tape()
    variant = _common()
    return [_one(monkeypatch, tape, variant, slippage=0, dwell=dwell) for dwell in _DWELL]


def giveback_runs(monkeypatch: pytest.MonkeyPatch) -> list[Records]:
    """Trailing sweep. liquidity_provision rejects trailing, so the archetype is
    informed_flow_following for this sweep only.
    """
    tape = _giveback_tape()
    runs: list[Records] = []
    for multiple in _GIVEBACK:
        variant = _common(
            archetype="informed_flow_following",
            form="trailing",
            giveback_spread_multiple=multiple,
        )
        runs.append(_one(monkeypatch, tape, variant, slippage=0, dwell=0))
    return runs


def band_runs(monkeypatch: pytest.MonkeyPatch) -> list[Records]:
    tape = _band_tape()
    runs: list[Records] = []
    for band in _BAND:
        variant = _common(centre_ticks=11, lo_ticks=7, hi_ticks=15, band_ticks=band)
        runs.append(_one(monkeypatch, tape, variant, slippage=0, dwell=0))
    return runs


def _closed(records: Records) -> list[tuple[Record, dict[str, object]]]:
    return [(row, _body(row.canonical)) for row in records if row.type_name == "PositionClosed"]


def cell_count(records: Records) -> int:
    return len(_closed(records))


def reason_counts(records: Records) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _row, body in _closed(records):
        reason = str(body.get("exit_reason"))
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def favorable_count(records: Records) -> int:
    return reason_counts(records).get("FAVORABLE", 0)


def _result_map(records: Records) -> dict[str, int]:
    found: dict[str, int] = {}
    for row, body in _closed(records):
        found[str(body["cell_id"])] = cell_economics(row, records)[0]
    return found


def result_sum(records: Records) -> int:
    return sum(_result_map(records).values())


def band_effects(runs: list[Records]) -> list[tuple[float, float, int]]:
    """``(mean(d), se(d), n)`` for each band after 0. Sample variance uses n - 1."""
    maps = [_result_map(records) for records in runs]
    cells = list(maps[0])
    effects: list[tuple[float, float, int]] = []
    for other in maps[1:]:
        diffs = [other[cell] - maps[0][cell] for cell in cells]
        n = len(diffs)
        mean = sum(diffs) / n if n else 0.0
        if n < 2:
            effects.append((mean, 0.0, n))
            continue
        var = sum((item - mean) ** 2 for item in diffs) / (n - 1)
        effects.append((mean, math.sqrt(var / n), n))
    return effects


def _gate(runs: list[Records]) -> None:
    for records in runs:
        require_entry_fills(records)
    for records in runs:
        require_adverse_level(records)


def _population(runs: list[Records], knob: str) -> None:
    lists = [[str(body["cell_id"]) for _row, body in _closed(records)] for records in runs]
    if any(len(items) != len(set(items)) for items in lists):
        raise AssertionError(f"M7: {knob} population differs: duplicate cell_id")
    groups = [set(items) for items in lists]
    if any(group != groups[0] for group in groups[1:]):
        raise AssertionError(
            f"M7: {knob} population differs: cell_ids {[len(group) for group in groups]}"
        )
    bad = sorted(
        {
            str(body.get("exit_reason"))
            for records in runs
            for _row, body in _closed(records)
            if str(body.get("exit_reason")) not in _REASONS
        }
    )
    if bad:
        raise AssertionError(f"M7: {knob} population differs: exit reasons {bad}")


def _reached(ok: bool, knob: str, consumer: str) -> None:
    if not ok:
        raise AssertionError(f"NONVACUOUS: m7 {knob} knob did not reach {consumer}")


def _with_fills(body: dict[str, object]) -> bool:
    entries = body.get("entry_fills")
    exits = body.get("exit_fills")
    return isinstance(entries, list) and bool(entries) and isinstance(exits, list) and bool(exits)


def _snapshots(records: Records) -> dict[tuple[str, int], dict[str, object]]:
    found: dict[tuple[str, int], dict[str, object]] = {}
    for row in records:
        if row.type_name != "PositionSnapshot":
            continue
        body = _body(row.canonical)
        cell = body.get("cell_id")
        sequence = _whole(body.get("rail_sequence"))
        if isinstance(cell, str) and sequence is not None:
            found[(cell, sequence)] = body
    return found


def _mark(body: dict[str, object]) -> tuple[str, int | None]:
    side = body.get("side")
    rail = body.get("rail")
    if not isinstance(side, str) or not isinstance(rail, dict):
        return "", None
    return side, _whole(cast(dict[str, object], rail).get("forced_exit_mark_cents"))


def _slippage_reached(runs: list[Records]) -> bool:
    snaps = [_snapshots(records) for records in runs]
    for left, right in _pairs(len(runs)):
        delta = _SLIPPAGE[right] - _SLIPPAGE[left]
        shared = snaps[left].keys() & snaps[right].keys()
        for key in shared:
            side, low = _mark(snaps[left][key])
            other, high = _mark(snaps[right][key])
            if low is None or high is None or side != other:
                continue
            if side == "LONG" and high == low - delta:
                return True
            if side == "SHORT" and high == low + delta:
                return True
    return False


def _dwell_bits(body: dict[str, object]) -> tuple[bool, bool] | None:
    rail = body.get("rail")
    if not isinstance(rail, dict):
        return None
    clean = cast(dict[str, object], rail).get("dwell_window_clean")
    warm = body.get("warmed_up")
    if not isinstance(clean, bool) or not isinstance(warm, bool):
        return None
    return clean, warm


def _dwell_reached(runs: list[Records]) -> bool:
    snaps = [_snapshots(records) for records in runs]
    for left, right in _pairs(len(runs)):
        shared = snaps[left].keys() & snaps[right].keys()
        for key in shared:
            first = _dwell_bits(snaps[left][key])
            second = _dwell_bits(snaps[right][key])
            if first is not None and second is not None and first != second:
                return True
    return False


def _favorable_refs(records: Records) -> dict[tuple[str, int], int]:
    found: dict[tuple[str, int], int] = {}
    for row in records:
        if row.type_name != "GateDecision":
            continue
        body = _body(row.canonical)
        if body.get("gate") != "FAVORABLE":
            continue
        cell = body.get("cell_id")
        sequence = _whole(body.get("rail_sequence"))
        ticks = _whole(body.get("reference_ticks"))
        if isinstance(cell, str) and sequence is not None and ticks is not None:
            found[(cell, sequence)] = ticks
    return found


def _giveback_reached(runs: list[Records]) -> bool:
    gates = [_favorable_refs(records) for records in runs]
    for left, right in _pairs(len(runs)):
        shared = gates[left].keys() & gates[right].keys()
        for key in shared:
            if gates[left][key] != gates[right][key]:
                return True
    return False


def _adverse_levels(records: Records) -> dict[tuple[str, int], int]:
    found: dict[tuple[str, int], int] = {}
    for row in records:
        if row.type_name != "GateDecision":
            continue
        body = _body(row.canonical)
        if body.get("gate") != "ADVERSE":
            continue
        cell = body.get("cell_id")
        sequence = _whole(body.get("rail_sequence"))
        level = _whole(body.get("drawn_level_ticks"))
        if isinstance(cell, str) and sequence is not None and level is not None:
            found[(cell, sequence)] = level
    return found


def _band_reached(runs: list[Records]) -> bool:
    levels = [_adverse_levels(records) for records in runs]
    for other in levels[1:]:
        shared = levels[0].keys() & other.keys()
        for key in shared:
            if levels[0][key] != other[key]:
                return True
    return False


def _pairs(count: int) -> list[tuple[int, int]]:
    return [(left, right) for left in range(count) for right in range(left + 1, count)]


def _non_increasing(values: list[int], knob: str, label: str) -> None:
    for index in range(1, len(values)):
        if values[index] > values[index - 1]:
            raise AssertionError(
                f"M7: {knob} {label} increased {values[index - 1]} -> {values[index]}"
            )
    for value in values[1:]:
        if value > values[0]:
            raise AssertionError(f"M7: {knob} {label} {value} exceeds {values[0]}")


def _guard_run(monkeypatch: pytest.MonkeyPatch) -> Records:
    """Slippage baseline, S 0 / D 0. The run cache shares this record."""
    records = _one(monkeypatch, _crossed_tape(), _common(), slippage=0, dwell=0)
    require_entry_fills(records)
    require_adverse_level(records)
    return records


def test_m7_slippage(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _guard_run(monkeypatch)
    require_entry_fills(first)
    require_adverse_level(first)
    tape = _crossed_tape()
    variant = _common()
    rest = [
        _one(monkeypatch, tape, variant, slippage=slippage, dwell=0) for slippage in _SLIPPAGE[1:]
    ]
    _gate(rest)
    runs = [first, *rest]
    _population(runs, "slippage")
    filled = all(any(_with_fills(body) for _row, body in _closed(records)) for records in runs)
    _reached(filled, "slippage", "closed cell")
    _reached(_slippage_reached(runs), "slippage", "forced_exit_mark_cents")
    _non_increasing([result_sum(records) for records in runs], "slippage", "result")


def test_m7_dwell(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _guard_run(monkeypatch)
    require_entry_fills(first)
    require_adverse_level(first)
    tape = _crossed_tape()
    variant = _common()
    rest = [_one(monkeypatch, tape, variant, slippage=0, dwell=dwell) for dwell in _DWELL[1:]]
    _gate(rest)
    runs = [first, *rest]
    _population(runs, "dwell")
    _reached(favorable_count(runs[0]) >= 1, "dwell", "favorable exit")
    _reached(_dwell_reached(runs), "dwell", "dwell_window_clean or warmed_up")
    _non_increasing([favorable_count(records) for records in runs], "dwell", "favorable")


def test_m7_giveback(monkeypatch: pytest.MonkeyPatch) -> None:
    _guard_run(monkeypatch)
    tape = _giveback_tape()
    first = _one(
        monkeypatch,
        tape,
        _common(
            archetype="informed_flow_following",
            form="trailing",
            giveback_spread_multiple=_GIVEBACK[0],
        ),
        slippage=0,
        dwell=0,
    )
    require_entry_fills(first)
    require_adverse_level(first)
    rest = [
        _one(
            monkeypatch,
            tape,
            _common(
                archetype="informed_flow_following",
                form="trailing",
                giveback_spread_multiple=multiple,
            ),
            slippage=0,
            dwell=0,
        )
        for multiple in _GIVEBACK[1:]
    ]
    _gate(rest)
    runs = [first, *rest]
    _population(runs, "giveback")
    _reached(favorable_count(runs[0]) >= 1, "giveback", "favorable exit")
    _reached(_giveback_reached(runs), "giveback", "reference_ticks")
    counts = [favorable_count(records) for records in runs]
    _non_increasing(counts, "giveback", "favorable")
    closed = [cell_count(records) for records in runs]
    if any(count != closed[0] for count in closed[1:]):
        raise AssertionError(f"M7: giveback closed count {closed}")
    bad = sorted(
        {
            str(body.get("exit_reason"))
            for records in runs
            for _row, body in _closed(records)
            if str(body.get("exit_reason")) != "FAVORABLE"
            and str(body.get("exit_reason")) not in {"ADVERSE", "HORIZON"}
        }
    )
    if bad:
        raise AssertionError(f"M7: giveback exit {bad}")


def test_m7_band(monkeypatch: pytest.MonkeyPatch) -> None:
    _guard_run(monkeypatch)
    tape = _band_tape()
    first = _one(
        monkeypatch,
        tape,
        _common(centre_ticks=11, lo_ticks=7, hi_ticks=15, band_ticks=_BAND[0]),
        slippage=0,
        dwell=0,
    )
    require_entry_fills(first)
    require_adverse_level(first)
    rest = [
        _one(
            monkeypatch,
            tape,
            _common(centre_ticks=11, lo_ticks=7, hi_ticks=15, band_ticks=band),
            slippage=0,
            dwell=0,
        )
        for band in _BAND[1:]
    ]
    _gate(rest)
    runs = [first, *rest]
    _population(runs, "band")
    _reached(all(cell_count(records) >= 200 for records in runs), "band", "closed cells")
    _reached(_band_reached(runs), "band", "drawn_level_ticks")
    for band, (mean, se, n) in zip(_BAND[1:], band_effects(runs), strict=True):
        if se == 0:
            if mean > 0:
                raise AssertionError(f"M7: band B={band} mean {mean} with var 0")
            continue
        if mean > 4 * se:
            raise AssertionError(f"M7: band B={band} mean {mean} > 4 * SE {se} (n={n})")
