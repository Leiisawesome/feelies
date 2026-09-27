"""Member 4: side correctness. Rail half green from A (D-37); birth from D."""

from __future__ import annotations

import json

import pytest

from feelies.core.events import MarkRailUpdate, PositionSnapshot
from feelies.core.quote_quality import QuoteQuality, classify
from tests.position_engine.scenarios import (
    T0,
    Records,
    check_unusable_side,
    nonvacuous,
    run_real,
    run_synthetic,
)
from tests.position_engine.tapes import force_class, make_tape

_RAIL = pytest.mark.battery_member(member=4, green_from="A", red_reason="^NONVACUOUS: ")
_BIRTH = pytest.mark.battery_member(member=4, green_from="D", red_reason="^NONVACUOUS: ")
_UNUSABLE = pytest.mark.battery_member(member=4, green_from="C", red_reason="UNUSABLE_SIDE")
_REAL = pytest.mark.battery_real
_UNUSABLE_CLASSES = (
    "NONPOS_BID",
    "NONPOS_ASK",
    "CROSSED",
    "LOCKED",
    "ZERO_SZ_BID",
    "ZERO_SZ_ASK",
)


def _body(canonical: str) -> dict[str, object]:
    return json.loads(canonical[canonical.index("{") :])


def _cents(price: object) -> int:
    scaled = price * 100  # type: ignore[operator]
    return int(scaled)


def _rail(records: Records, scenario: str) -> None:
    nonvacuous(records, MarkRailUpdate, scenario=scenario)
    for row in records:
        if row.type_name != "MarkRailUpdate":
            continue
        body = _body(row.canonical)
        quote = records.quotes[int(body["quote_sequence"])]  # type: ignore[arg-type]
        long = body["long"]
        short = body["short"]
        assert isinstance(long, dict) and isinstance(short, dict)
        if classify(quote.bid, quote.ask, quote.bid_size, quote.ask_size) is QuoteQuality.VALID:
            spread = _cents(quote.ask) - _cents(quote.bid)
            assert long["paying_mark_cents"] - long["valuation_mark_cents"] == spread
            assert short["valuation_mark_cents"] - short["paying_mark_cents"] == spread
        assert long["worst_side_mark_cents"] <= long["valuation_mark_cents"]
        assert long["forced_exit_mark_cents"] <= long["valuation_mark_cents"]
        assert short["worst_side_mark_cents"] >= short["valuation_mark_cents"]
        assert short["forced_exit_mark_cents"] >= short["valuation_mark_cents"]


def _birth(records: Records, scenario: str) -> None:
    nonvacuous(records, PositionSnapshot, scenario=scenario)
    first: dict[str, dict[str, object]] = {}
    closes: dict[str, dict[str, object]] = {}
    for row in records:
        body = _body(row.canonical)
        cell = body.get("cell_id")
        if not isinstance(cell, str):
            continue
        if row.type_name == "PositionSnapshot" and cell not in first:
            first[cell] = body
        elif row.type_name == "PositionClosed":
            closes[cell] = body
    touched = 0
    for cell, snap in first.items():
        rail = snap["rail"]
        assert isinstance(rail, dict)
        sign = 1 if snap["side"] == "LONG" else -1
        size = int(snap["size"])  # type: ignore[arg-type]
        expected = sign * (
            int(rail["valuation_mark_cents"]) * size - int(snap["entry_cost_cents"])
        )  # type: ignore[arg-type]
        assert snap["move_now_cents"] == expected
        closed = closes.get(cell)
        if closed is None:
            continue
        fills = closed["entry_fills"]
        assert isinstance(fills, list)
        paying = int(rail["paying_mark_cents"])
        if fills and all(int(fill["price_cents"]) == paying for fill in fills):
            touched += 1
            spread = int(snap["entry_spread_ticks"])
            assert snap["move_now_cents"] == -spread * size
    print(f"touch_clause_cells={touched}")


@_RAIL
def test_m4_rail_syn() -> None:
    tape = make_tape(seed=11, n=36000, symbol="SYN", start_ns=T0, size=1000)
    _rail(run_synthetic(tape, symbols=("SYN",)), "m4_rail_syn")


@_RAIL
def test_m4_rail_syn_spreads() -> None:
    tape = make_tape(seed=13, n=6000, symbol="SYN", start_ns=T0, spread_cents=3, size=1000)
    _rail(run_synthetic(tape, symbols=("SYN",)), "m4_rail_syn_spreads")


@_RAIL
@_REAL
def test_m4_rail_real() -> None:
    _rail(run_real(), "m4_rail_real")


@_BIRTH
def test_m4_birth_syn() -> None:
    tape = make_tape(seed=11, n=36000, symbol="SYN", start_ns=T0, size=1000)
    _birth(run_synthetic(tape, symbols=("SYN",)), "m4_birth_syn")


@_BIRTH
def test_m4_birth_syn_partial() -> None:
    tape = make_tape(seed=11, n=36000, symbol="SYN", start_ns=T0, size=100)
    _birth(run_synthetic(tape, symbols=("SYN",)), "m4_birth_syn_partial")


@_BIRTH
@_REAL
def test_m4_birth_real() -> None:
    _birth(run_real(), "m4_birth_real")


def _rail_for(records: Records, sequence: int) -> bool:
    for row in records:
        if row.type_name != "MarkRailUpdate":
            continue
        body = _body(row.canonical)
        if body.get("quote_sequence") == sequence:
            return True
    return False


@_UNUSABLE
@pytest.mark.parametrize("cls", _UNUSABLE_CLASSES)
def test_m4_unusable_side(cls: str) -> None:
    tape = make_tape(seed=11, n=8, symbol="SYN", start_ns=T0, size=1000)
    injected = force_class(tape, 3, cls)
    records = run_synthetic(injected, symbols=("SYN",))
    sequence = injected[3].sequence
    if not _rail_for(records, sequence):
        raise AssertionError(f"NONVACUOUS: no MarkRailUpdate for quote {sequence} in m4_{cls}")
    check_unusable_side(records, quote_sequence=sequence)
