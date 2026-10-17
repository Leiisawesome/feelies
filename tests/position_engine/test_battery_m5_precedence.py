"""Member 5: precedence. Red until stage E.

One live requirement at a time; a re-emission only after a REJECTED ack for the
previous attempt (G11, D-106).
"""

from __future__ import annotations

import pytest

from feelies.core.events import NBBOQuote, PositionClosed
from tests.position_engine.scenarios import (
    T0,
    assert_no_risk_rejects,
    arrival_entry_cents,
    assert_triggered_tie,
    exit_reason_at_collision,
    first_horizon_index,
    fixture_variant,
    nonvacuous,
    require_entry_fills,
    require_favorable_tie,
    run_real,
    run_synthetic,
)
from tests.position_engine.tapes import hold, make_tape, set_quote

_MARK = pytest.mark.battery_member(member=5, green_from="E", red_reason="^NONVACUOUS: ")
_REAL = pytest.mark.battery_real

_N = 4_000
_SEED = 29
# Boundary 1 fills on quote index 301. The opposing SHORT is boundary 3
# (index 900); invalidation resolves on the next rail, index 901 (§2:247-251).
_ENTRY_FILL = 301
_INVALIDATION = 900
_SPREAD = 1
_TARGET = 4
_ADVERSE = 11


def _v3a(**overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "horizon_seconds": 30,
        "fee_round_trip_ticks": 0,
        "T_seconds": 16_000,
        "centre_ticks": 11,
        "band_ticks": 0,
        "lo_ticks": 2,
        "target_ticks": _TARGET,
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


def _tie(tape: list[NBBOQuote], *, higher: str, form: str, horizon_s: int) -> None:
    """Tape-only. FAVORABLE and ``higher`` on the first favorable quote (§2:265-274)."""
    resolution = None
    if higher == "INVALIDATION":
        resolution = _INVALIDATION + 1
    require_favorable_tie(
        tape,
        higher=higher,
        birth_index=_ENTRY_FILL,
        target_ticks=_TARGET,
        adverse_ticks=11,
        horizon_ns=horizon_s * 1_000_000_000,
        form=form,
        giveback_multiple=2 if form == "trailing" else None,
        spread_ticks=_SPREAD,
        fee_ticks=0,
        quiet_limit_ns=5_000_000_000,
        resolution_index=resolution,
    )


@_MARK
def test_m5_invalidation_at_take_profit() -> None:
    """FAVORABLE and INVALIDATION on the rail after the opposing signal (§2:265-274)."""
    tape = make_tape(seed=_SEED, n=_N, symbol="SYN", start_ns=T0, size=1000)
    entry = arrival_entry_cents(tape, _ENTRY_FILL)
    tape = hold(tape, _ENTRY_FILL, _INVALIDATION - _ENTRY_FILL)
    tape = set_quote(
        tape,
        _INVALIDATION + 1,
        bid_cents=entry + _TARGET,
        ask_cents=entry + _TARGET + 1,
    )
    _tie(tape, higher="INVALIDATION", form="fixed", horizon_s=16_000)
    records = run_synthetic(tape, symbols=("SYN",), variant=_v3a())
    require_entry_fills(records)
    nonvacuous(records, PositionClosed, scenario="m5_invalidation")
    assert_no_risk_rejects(records)
    exit_reason_at_collision(records)
    assert_triggered_tie(records, "INVALIDATION")


@_MARK
def test_m5_deadline_beyond_stop() -> None:
    """FAVORABLE and HORIZON on the deadline quote (§2:260, §2:265-274)."""
    tape = make_tape(seed=_SEED, n=_N, symbol="SYN", start_ns=T0, size=1000)
    entry = arrival_entry_cents(tape, _ENTRY_FILL)
    horizon_ns = 10 * 1_000_000_000
    deadline = first_horizon_index(tape, _ENTRY_FILL, horizon_ns)
    tape = hold(tape, _ENTRY_FILL, deadline - _ENTRY_FILL - 1)
    tape = set_quote(
        tape,
        deadline,
        bid_cents=entry + _TARGET,
        ask_cents=entry + _TARGET + 1,
    )
    _tie(tape, higher="HORIZON", form="fixed", horizon_s=10)
    records = run_synthetic(tape, symbols=("SYN",), variant=_v3a(T_seconds=10))
    require_entry_fills(records)
    nonvacuous(records, PositionClosed, scenario="m5_deadline")
    assert_no_risk_rejects(records)
    exit_reason_at_collision(records)
    assert_triggered_tie(records, "HORIZON")


@_MARK
def test_m5_gap_through_trail_and_stop() -> None:
    """One quote jumps through the trail line and the adverse level (§2:265-274)."""
    tape = make_tape(seed=_SEED, n=_N, symbol="SYN", start_ns=T0, size=1000)
    birth = _bid(tape[_ENTRY_FILL])
    entry_ask = birth + _SPREAD
    ramp = _ENTRY_FILL + 1
    steps = 9
    for step in range(steps):
        bid = birth + step + 1
        tape = set_quote(tape, ramp + step, bid_cents=bid, ask_cents=bid + 1)
    drop = ramp + steps
    drop_bid = entry_ask - _ADVERSE
    tape = set_quote(tape, drop, bid_cents=drop_bid, ask_cents=drop_bid + 1)
    _tie(tape, higher="ADVERSE", form="trailing", horizon_s=16_000)
    records = run_synthetic(tape, symbols=("SYN",), variant=_v5())
    require_entry_fills(records)
    nonvacuous(records, PositionClosed, scenario="m5_gap")
    assert_no_risk_rejects(records)
    exit_reason_at_collision(records)
    assert_triggered_tie(records, "ADVERSE")


@_MARK
@_REAL
def test_m5_real() -> None:
    records = run_real()
    require_entry_fills(records)
    nonvacuous(records, PositionClosed, scenario="m5_real")
    exit_reason_at_collision(records)
