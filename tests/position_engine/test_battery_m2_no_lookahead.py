"""Member 2: no lookahead. Red from stage A until B (D-18)."""

from __future__ import annotations

import json

import pytest

from feelies.core.events import Event, PositionSnapshot
from tests.position_engine.scenarios import (
    T0,
    Widened,
    assert_widened_prefix,
    decision_cut_indices,
    decision_trigger_indexes,
    nonvacuous,
    rth_replay,
    run_real,
    run_real_prefixes,
    run_synthetic,
    session_digest,
)
from tests.position_engine.tapes import force_class, make_tape

_MARK = pytest.mark.battery_member(member=2, green_from="B", red_reason="^NONVACUOUS: ")
_DWELL = pytest.mark.battery_member(member=2, green_from="C", red_reason="NONVACUOUS")
_REAL = pytest.mark.battery_real
_SYN_FRACTIONS = (0.20, 0.45, 0.70, 0.90)
_REAL_FRACTIONS = (0.15, 0.30, 0.45)


def _assert_decision_cuts(
    events: tuple[Event, ...] | list[Event],
    widened: tuple[Widened, ...],
    cuts: tuple[int, ...],
    fractions: tuple[float, ...],
) -> None:
    assert list(cuts) == sorted(cuts)
    assert all(cuts[i] < cuts[i + 1] for i in range(len(cuts) - 1))
    triggers = decision_trigger_indexes(events, widened)
    n = len(events)
    for cut, fraction in zip(cuts, fractions, strict=True):
        target = int(n * fraction)
        assert cut in triggers
        assert cut >= target
        assert not any(target <= index < cut for index in triggers)


@_MARK
def test_m2_syn() -> None:
    n = 36000
    tape = make_tape(seed=11, n=n, symbol="SYN", start_ns=T0, size=1000)
    full = run_synthetic(tape, symbols=("SYN",))
    rows = session_digest("syn-11-36000", full.widened)
    cuts = decision_cut_indices(tape, rows, _SYN_FRACTIONS)
    print(f"syn cuts {list(cuts)}")
    _assert_decision_cuts(tape, rows, cuts, _SYN_FRACTIONS)
    for cut in cuts:
        truncated = run_synthetic(tape[: cut + 1], symbols=("SYN",))
        assert_widened_prefix(truncated.widened, rows, tape[cut].sequence)
    nonvacuous(full, PositionSnapshot, scenario="m2_syn")


def _real() -> None:
    full = run_real()
    events = rth_replay()
    rows = session_digest("real-app-2026-03-26", full.widened)
    cuts = decision_cut_indices(events, rows, _REAL_FRACTIONS)
    print(f"real cuts {list(cuts)}")
    _assert_decision_cuts(events, rows, cuts, _REAL_FRACTIONS)
    for cut, truncated in zip(cuts, run_real_prefixes(cuts), strict=True):
        assert_widened_prefix(truncated, rows, events[cut].sequence)
    nonvacuous(full, PositionSnapshot, scenario="m2_real")


@_MARK
@_REAL
def test_m2_real() -> None:
    _real()


@_DWELL
def test_m2_dwell_favorable_ignores_stale_cross(monkeypatch: pytest.MonkeyPatch) -> None:
    """A crossed quote older than t-D does not block a favorable decision at t."""
    dwell = 2_000_000_000
    monkeypatch.setenv("FEELIES_RAIL_DWELL_NS", str(dwell))
    gap = dwell + 100_000_000
    tape = make_tape(seed=11, n=2, symbol="SYN", start_ns=T0, interval_ns=gap, size=1000)
    crossed = force_class(tape, 0, "CROSSED")
    current = crossed[1]
    records = run_synthetic(crossed, symbols=("SYN",))
    nonvacuous(records, "GateDecision", scenario="m2_dwell")
    hits = [
        json.loads(row.canonical[row.canonical.index("{") :])
        for row in records
        if row.type_name == "GateDecision"
    ]
    assert any(
        body.get("gate") == "FAVORABLE" and body.get("rail_sequence") == current.sequence
        for body in hits
    ), f"no favorable decision at {current.sequence}"
