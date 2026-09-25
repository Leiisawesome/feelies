"""Member 5: precedence. Red until stage E."""

from __future__ import annotations

import pytest

from feelies.core.events import NBBOQuote, PositionClosed
from tests.position_engine.scenarios import (
    T0,
    fixture_variant,
    nonvacuous,
    run_real,
    run_synthetic,
    exit_reason_at_collision,
)
from tests.position_engine.tapes import excise, make_tape, set_quote

_MARK = pytest.mark.battery_member(member=5, green_from="E", red_reason="^NONVACUOUS: ")
_REAL = pytest.mark.battery_real

_N = 4_000
_SEED = 29
_INTERVAL_NS = 100_000_000
# First LONG is boundary 1 (quote 300); its fill is quote 301. The opposing
# SHORT is boundary 3 (quote 900); the barrier goes on quote 901 (C1, C2).
_ENTRY_FILL = 301
_INVALIDATION = 900
_SPREAD = 1
_U = 4 + _SPREAD
_D = 11 - _SPREAD


def _v3a(**overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "horizon_seconds": 30,
        "fee_round_trip_ticks": 0,
        "T_seconds": 16_000,
        "centre_ticks": 11,
        "band_ticks": 0,
        "lo_ticks": 2,
        "target_ticks": 4,
    }
    params.update(overrides)
    return fixture_variant(**params)


def _v5() -> dict[str, object]:
    return _v3a(
        archetype="informed_flow_following",
        form="trailing",
        giveback_spread_multiple=2,
    )


def _bid(quote: NBBOQuote) -> int:
    return int(quote.bid * 100)


@_MARK
def test_m5_invalidation_at_take_profit() -> None:
    tape = make_tape(seed=_SEED, n=_N, symbol="SYN", start_ns=T0, size=1000)
    birth = _bid(tape[_ENTRY_FILL])
    tape = set_quote(tape, _INVALIDATION + 1, bid_cents=birth + _U, ask_cents=birth + _U + 1)
    records = run_synthetic(tape, symbols=("SYN",), variant=_v3a())
    nonvacuous(records, PositionClosed, scenario="m5_invalidation")
    exit_reason_at_collision(records)


@_MARK
def test_m5_deadline_beyond_stop() -> None:
    tape = make_tape(seed=_SEED, n=_N, symbol="SYN", start_ns=T0, size=1000)
    birth = _bid(tape[_ENTRY_FILL])
    deadline = _ENTRY_FILL + (10 * 1_000_000_000) // _INTERVAL_NS
    tape = set_quote(tape, deadline, bid_cents=birth - _D, ask_cents=birth - _D + 1)
    records = run_synthetic(tape, symbols=("SYN",), variant=_v3a(T_seconds=10))
    nonvacuous(records, PositionClosed, scenario="m5_deadline")
    exit_reason_at_collision(records)


@_MARK
def test_m5_gap_through_trail_and_stop() -> None:
    tape = make_tape(seed=_SEED, n=_N, symbol="SYN", start_ns=T0, size=1000)
    birth = _bid(tape[_ENTRY_FILL])
    tape = excise(tape, _ENTRY_FILL + 1, 300)
    landed = _ENTRY_FILL + 1
    tape = set_quote(tape, landed, bid_cents=birth - _D - 20, ask_cents=birth - _D - 19)
    records = run_synthetic(tape, symbols=("SYN",), variant=_v5())
    nonvacuous(records, PositionClosed, scenario="m5_gap")
    exit_reason_at_collision(records)


@_MARK
@_REAL
def test_m5_real() -> None:
    records = run_real()
    nonvacuous(records, PositionClosed, scenario="m5_real")
    exit_reason_at_collision(records)
