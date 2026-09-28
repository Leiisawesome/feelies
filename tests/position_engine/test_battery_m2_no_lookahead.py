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
    fixture_variant,
    nonvacuous,
    require_entry_fills,
    rth_replay,
    run_real,
    run_real_prefixes,
    run_synthetic,
    session_digest,
)
from tests.position_engine.tapes import force_class, make_tape, set_quote

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
    require_entry_fills(full)
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
    require_entry_fills(full)
    nonvacuous(full, PositionSnapshot, scenario="m2_real")


@_MARK
@_REAL
def test_m2_real() -> None:
    _real()


def _v3a() -> dict[str, object]:
    """Horizon 30 so boundary 1 births a LONG. The fill lands on quote sequence 302."""
    return fixture_variant(
        horizon_seconds=30,
        fee_round_trip_ticks=0,
        T_seconds=16_000,
        centre_ticks=11,
        band_ticks=0,
        lo_ticks=2,
        target_ticks=4,
    )


@_DWELL
def test_m2_dwell_favorable_ignores_stale_cross(monkeypatch: pytest.MonkeyPatch) -> None:
    """D > 0 (D-87). A cross older than t-D does not block the favorable condition at t.

    V3a, seed 11, 420 quotes at 100 ms. Birth fill is quote sequence 302.
    D = 2 s. The crossed quote is at t - D - 100 ms; t is quote sequence 401.
    """
    dwell = 2_000_000_000
    interval = 100_000_000
    monkeypatch.setenv("FEELIES_RAIL_DWELL_NS", str(dwell))
    t_index = 400
    tape = make_tape(seed=11, n=420, symbol="SYN", start_ns=T0, interval_ns=interval, size=1000)
    cross_index = t_index - (dwell + interval) // interval
    birth_ask = int(tape[301].ask * 100)
    bid = birth_ask + 8
    shaped = set_quote(
        force_class(tape, cross_index, "CROSSED"),
        t_index,
        bid_cents=bid,
        ask_cents=bid + 1,
    )
    current = shaped[t_index]
    records = run_synthetic(shaped, symbols=("SYN",), variant=_v3a())
    require_entry_fills(records)
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
