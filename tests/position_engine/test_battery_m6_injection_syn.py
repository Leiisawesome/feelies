"""Member 6 synthetic injections. Red until stage E."""

from __future__ import annotations

import pytest

from feelies.core.events import PositionClosed
from tests.position_engine.scenarios import (
    T0,
    assert_no_risk_rejects,
    check_a1,
    check_a2,
    check_a3,
    check_a4,
    check_a5,
    check_a6,
    fixture_variant,
    nonvacuous,
    run_synthetic,
)
from tests.position_engine.tapes import cross, excise, make_tape, remove_side_run, shift_from

_MARK = pytest.mark.battery_member(member=6, green_from="E", red_reason="NONVACUOUS")
_QUIET_NS = 5_000_000_000
_A_NS = 30_000_000_000


def _v3a() -> dict[str, object]:
    return fixture_variant(
        horizon_seconds=30,
        fee_round_trip_ticks=0,
        T_seconds=16_000,
        centre_ticks=11,
        band_ticks=0,
        lo_ticks=2,
        hi_ticks=20,
        target_ticks=4,
    )


def _v5() -> dict[str, object]:
    return fixture_variant(
        horizon_seconds=30,
        archetype="informed_flow_following",
        form="trailing",
        giveback_spread_multiple=2,
        fee_round_trip_ticks=0,
        T_seconds=16_000,
        centre_ticks=11,
        band_ticks=0,
        lo_ticks=2,
        target_ticks=4,
    )


def _ready(records: object, scenario: str) -> None:
    nonvacuous(records, PositionClosed, scenario=scenario)  # type: ignore[arg-type]
    assert_no_risk_rejects(records)  # type: ignore[arg-type]
    check_a1(records, quiet_limit_ns=_QUIET_NS)  # type: ignore[arg-type]
    check_a3(records)  # type: ignore[arg-type]


def _cross_span(
    tape: list,
    start: int,
    stop: int,
    bid_cents: int,
    ask_cents: int,
) -> list:
    out = tape
    for index in range(start, stop):
        out = cross(out, index, bid_cents, ask_cents)
    return out


@_MARK
def test_m6_a4_gap_through() -> None:
    tape = make_tape(seed=11, n=800, symbol="SYN", start_ns=T0, size=1000)
    tape = shift_from(excise(tape, 302, 20), 302, -15)
    records = run_synthetic(tape, symbols=("SYN",), variant=_v3a())
    _ready(records, "m6_a4")
    check_a4(records, birth_sequence=302, centre=11, band=0)


def _quiet(n_excise: int) -> tuple[list, int, bool]:
    tape = make_tape(seed=11, n=302 + n_excise + 5, symbol="SYN", start_ns=T0, size=1000)
    out = excise(tape, 302, n_excise)
    gap = out[302].exchange_timestamp_ns - out[301].exchange_timestamp_ns
    return out, out[302].sequence, gap > _A_NS


@_MARK
@pytest.mark.parametrize("n_excise", [298, 299, 300])
def test_m6_a5_quiet(n_excise: int) -> None:
    tape, sequence, blind = _quiet(n_excise)
    records = run_synthetic(tape, symbols=("SYN",), variant=_v3a())
    _ready(records, f"m6_a5_quiet_{n_excise}")
    check_a5(records, expect_blind=blind, deciding_sequence=sequence if blind else None)


def _absent(count: int, side: str) -> tuple[list, int, bool]:
    tape = make_tape(seed=11, n=302 + count + 5, symbol="SYN", start_ns=T0, size=1000)
    out = remove_side_run(tape, 302, count, side)
    last = out[302 + count - 1]
    duration = last.exchange_timestamp_ns - out[301].exchange_timestamp_ns
    return out, last.sequence, duration > _A_NS


@_MARK
@pytest.mark.parametrize("count", [299, 300, 301])
def test_m6_a5_valuation_absent(count: int) -> None:
    tape, sequence, blind = _absent(count, "bid")
    records = run_synthetic(tape, symbols=("SYN",), variant=_v3a())
    _ready(records, f"m6_a5_valuation_{count}")
    check_a5(records, expect_blind=blind, deciding_sequence=sequence if blind else None)


@_MARK
@pytest.mark.parametrize("count", [299, 300, 301])
def test_m6_a5_paying_absent(count: int) -> None:
    tape, sequence, blind = _absent(count, "ask")
    records = run_synthetic(tape, symbols=("SYN",), variant=_v3a())
    _ready(records, f"m6_a5_paying_{count}")
    check_a5(records, expect_blind=blind, deciding_sequence=sequence if blind else None)


@_MARK
def test_m6_a6_short() -> None:
    tape = make_tape(seed=11, n=4_000, symbol="SYN", start_ns=T0, size=1000)
    tape = _cross_span(shift_from(tape, 3602, 51), 3602, 3901, 10_052, 10_042)
    records = run_synthetic(tape, symbols=("SYN",))
    _ready(records, "m6_a6_short")
    check_a6(records, birth_sequence=3602, kind="ADVERSE", deciding_sequence=3902)


@_MARK
def test_m6_a6_long() -> None:
    tape = make_tape(seed=11, n=1_800, symbol="SYN", start_ns=T0, size=1000)
    tape = _cross_span(shift_from(tape, 1202, -47), 1202, 1503, 9_978, 9_977)
    records = run_synthetic(tape, symbols=("SYN",))
    _ready(records, "m6_a6_long")
    check_a6(records, birth_sequence=1202, kind="BLIND", deciding_sequence=1503)


@_MARK
def test_m6_a2_v5() -> None:
    tape = make_tape(seed=11, n=2_000, symbol="SYN", start_ns=T0, size=1000)
    variant = _v5()
    clean = run_synthetic(tape, symbols=("SYN",), variant=variant)
    _ready(clean, "m6_a2_v5")
    injected = run_synthetic(cross(tape, 400, 10_040, 10_030), symbols=("SYN",), variant=variant)
    assert_no_risk_rejects(injected)
    check_a1(injected, quiet_limit_ns=_QUIET_NS)
    check_a3(injected)
    check_a2(clean, injected, feed_gap_sequences=set())
