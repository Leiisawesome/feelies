"""Battery member 9, held-price integrity (battery.md; D-201). P-39."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from feelies.core.events import MarkRailUpdate, NBBOQuote
from tests.position_engine.scenarios import T0, Records, nonvacuous, run_synthetic
from tests.position_engine.tapes import force_class, make_tape

_CARRY = pytest.mark.battery_member(member=9, green_from="C", red_reason="CAP:rail_carry")
_ABSENT = pytest.mark.battery_member(member=9, green_from="C", red_reason="UNUSABLE_SIDE")
_SIDES = (
    ("long", "paying"),
    ("long", "valuation"),
    ("short", "paying"),
    ("short", "valuation"),
)
_FORCED = (200, 201, 202)


def _tape() -> list[NBBOQuote]:
    tape = make_tape(seed=11, n=420, symbol="SYN", start_ns=T0, interval_ns=100_000_000, size=1000)
    for index in _FORCED:
        tape = force_class(tape, index, "NONPOS_BID")
    return tape


def _run() -> Records:
    return run_synthetic(_tape(), symbols=("SYN",))


def _body(canonical: str) -> dict[str, object]:
    parsed = json.loads(canonical[canonical.index("{") :])
    if not isinstance(parsed, dict):
        raise AssertionError("NONVACUOUS: MarkRailUpdate body in m9")
    return parsed


def _updates(records: Records) -> list[dict[str, object]]:
    nonvacuous(records, MarkRailUpdate, scenario="m9")
    bodies: list[dict[str, object]] = []
    for row in records:
        if row.type_name != "MarkRailUpdate":
            continue
        body = _body(row.canonical)
        long = body["long"]
        short = body["short"]
        assert isinstance(long, dict) and isinstance(short, dict)
        bodies.append(body)
    return bodies


def _orient(body: dict[str, object], orientation: str) -> dict[str, object]:
    side = body[orientation]
    assert isinstance(side, dict)
    return side


def _precondition_bids(tape: list[NBBOQuote]) -> None:
    for index in _FORCED:
        quote = tape[index]
        if quote.bid != Decimal("0"):
            raise AssertionError(f"PRECONDITION: quote {quote.sequence} bid {quote.bid} != 0")


def _precondition_held_pair(tape: list[NBBOQuote]) -> None:
    forced = set(_FORCED)
    for index in range(len(tape) - 1):
        if index in forced or index + 1 in forced:
            continue
        left = tape[index]
        right = tape[index + 1]
        if left.bid == right.bid and left.ask == right.ask:
            return
    raise AssertionError(
        "PRECONDITION: no consecutive pair outside the forced quotes with equal bid and equal ask"
    )


def _unchanged_held(updates: list[dict[str, object]]) -> bool:
    for prev, cur in zip(updates, updates[1:]):
        for orientation, role in _SIDES:
            cur_side = _orient(cur, orientation)
            prev_side = _orient(prev, orientation)
            price = cur_side[f"{role}_mark_cents"]
            if price is not None and price == prev_side[f"{role}_mark_cents"]:
                return True
    return False


def _require_bid_absent(tape: list[NBBOQuote], updates: list[dict[str, object]]) -> None:
    found: dict[int, dict[str, object]] = {}
    for body in updates:
        sequence = body["quote_sequence"]
        if isinstance(sequence, int) and not isinstance(sequence, bool):
            found[sequence] = body
    for index in _FORCED:
        sequence = tape[index].sequence
        body = found.get(sequence)
        if body is None:
            raise AssertionError(f"UNUSABLE_SIDE: bid side not absent at quote {sequence} (long)")
        long = _orient(body, "long")
        short = _orient(body, "short")
        if long["valuation_side_absent"] is not True:
            raise AssertionError(f"UNUSABLE_SIDE: bid side not absent at quote {sequence} (long)")
        if short["paying_side_absent"] is not True:
            raise AssertionError(f"UNUSABLE_SIDE: bid side not absent at quote {sequence} (short)")


def _assert_ages(updates: list[dict[str, object]]) -> None:
    for prev, cur in zip(updates, updates[1:]):
        prev_ts = prev["event_timestamp_ns"]
        cur_ts = cur["event_timestamp_ns"]
        assert isinstance(prev_ts, int) and not isinstance(prev_ts, bool)
        assert isinstance(cur_ts, int) and not isinstance(cur_ts, bool)
        elapsed = cur_ts - prev_ts
        sequence = cur["quote_sequence"]
        for orientation, role in _SIDES:
            cur_side = _orient(cur, orientation)
            price = cur_side[f"{role}_mark_cents"]
            if price is None:
                continue
            prev_side = _orient(prev, orientation)
            age = cur_side[f"{role}_age_ns"]
            if prev_side[f"{role}_mark_cents"] == price:
                prev_age = prev_side[f"{role}_age_ns"]
                if isinstance(prev_age, bool) or not isinstance(prev_age, int):
                    raise AssertionError(
                        f"CAP:rail_carry: {orientation} {role} age {age} at quote {sequence}, "
                        f"expected {prev_age}+{elapsed}"
                    )
                want = prev_age + elapsed
                if age != want:
                    raise AssertionError(
                        f"CAP:rail_carry: {orientation} {role} age {age} at quote {sequence}, "
                        f"expected {want}"
                    )
            elif age != 0:
                raise AssertionError(
                    f"CAP:rail_carry: {orientation} {role} age {age} at a price change, "
                    f"quote {sequence}"
                )


def _assert_held_price(updates: list[dict[str, object]]) -> None:
    last_present: dict[tuple[str, str], object] = {}
    for body in updates:
        sequence = body["quote_sequence"]
        for orientation, role in _SIDES:
            side = _orient(body, orientation)
            price = side[f"{role}_mark_cents"]
            key = (orientation, role)
            if side[f"{role}_side_absent"] is not True:
                last_present[key] = price
                continue
            if key not in last_present or last_present[key] is None:
                continue
            want = last_present[key]
            if price != want:
                raise AssertionError(
                    f"CAP:rail_carry: {orientation} {role} published {price} while absent "
                    f"at quote {sequence}, last present {want}"
                )


def _assert_absent_for(updates: list[dict[str, object]]) -> None:
    for orientation, role in _SIDES:
        seen = False
        prev_absent = False
        prev_span = 0
        for body in updates:
            side = _orient(body, orientation)
            absent = side[f"{role}_side_absent"] is True
            span = side[f"{role}_absent_for_ns"]
            sequence = body["quote_sequence"]
            if not seen:
                if not absent:
                    seen = True
                    if span != 0:
                        raise AssertionError(
                            f"CAP:rail_carry: {orientation} {role} absent_for {span} "
                            f"!= 0 while present at quote {sequence}"
                        )
                continue
            if not absent:
                if span != 0:
                    raise AssertionError(
                        f"CAP:rail_carry: {orientation} {role} absent_for {span} "
                        f"!= 0 while present at quote {sequence}"
                    )
                prev_absent = False
                continue
            if isinstance(span, bool) or not isinstance(span, int) or span <= 0:
                raise AssertionError(
                    f"CAP:rail_carry: {orientation} {role} absent_for {span} "
                    f"not > 0 while absent at quote {sequence}"
                )
            if prev_absent and span <= prev_span:
                raise AssertionError(
                    f"CAP:rail_carry: {orientation} {role} absent_for {span} "
                    f"did not increase through absence at quote {sequence}"
                )
            prev_absent = True
            prev_span = span


@_CARRY
def test_m9_age_grows_while_price_held() -> None:
    tape = _tape()
    _precondition_bids(tape)
    _precondition_held_pair(tape)
    updates = _updates(_run())
    if not _unchanged_held(updates):
        raise AssertionError("NONVACUOUS: no update pair with an unchanged held price")
    _assert_ages(updates)


@_ABSENT
def test_m9_absent_side_holds_price() -> None:
    tape = _tape()
    _precondition_bids(tape)
    updates = _updates(_run())
    _require_bid_absent(tape, updates)
    _assert_held_price(updates)


@_ABSENT
def test_m9_absent_for_grows_through_absence() -> None:
    tape = _tape()
    _precondition_bids(tape)
    updates = _updates(_run())
    _require_bid_absent(tape, updates)
    _assert_absent_for(updates)
