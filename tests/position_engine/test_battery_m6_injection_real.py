"""Member 6 real-session injections. Red until stage E."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest

from feelies.core.events import Event, NBBOQuote, PositionClosed
from tests.position_engine.scenarios import (
    CellSpan,
    Records,
    check_a1,
    check_a2,
    check_a3,
    nonvacuous,
    placement_rule,
    rth_replay,
    run_real,
    slice_real_events,
)
from tests.position_engine.tapes import cross, remove_side

_MARK = pytest.mark.battery_member(member=6, green_from="E", red_reason="NONVACUOUS")
_REAL = pytest.mark.battery_real
_FRACTION = 0.5
_QUIET_NS = 5_000_000_000


def _body(canonical: str) -> dict[str, object]:
    import json

    return json.loads(canonical[canonical.index("{") :])


def _sides(records: Records) -> dict[str, str]:
    sides: dict[str, str] = {}
    for row in records:
        if row.type_name != "PositionClosed":
            continue
        body = _body(row.canonical)
        sides[str(body["cell_id"])] = str(body["side"])
    return sides


def _spans(records: Records, events: Sequence[Event]) -> tuple[list[CellSpan], list[int]]:
    quote_index = {
        event.sequence: index for index, event in enumerate(events) if type(event) is NBBOQuote
    }
    exit_at: dict[str, int] = {}
    decisions: list[int] = []
    for row in records:
        if row.type_name != "GateDecision":
            continue
        body = _body(row.canonical)
        if str(body.get("outcome", "")).lower() != "fire":
            continue
        seq = int(body["rail_sequence"])  # type: ignore[arg-type]
        index = quote_index.get(seq)
        if index is None:
            continue
        cell = str(body["cell_id"])
        exit_at[cell] = max(exit_at.get(cell, -1), index)
        decisions.append(index)
    spans: list[CellSpan] = []
    for row in records:
        if row.type_name != "PositionClosed":
            continue
        body = _body(row.canonical)
        cell = str(body["cell_id"])
        if cell not in exit_at:
            continue
        entries = body["entry_fills"]
        if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
            continue
        birth = quote_index.get(int(entries[0]["sequence"]))
        if birth is None:
            continue
        spans.append(CellSpan(cell, birth, exit_at[cell]))
    return spans, decisions


def _quote_index(events: Sequence[Event], index: int, blocked: set[int]) -> int | None:
    cursor = index
    while cursor < len(events) and type(events[cursor]) is not NBBOQuote:
        cursor += 1
    if cursor >= len(events):
        return None
    if cursor in blocked or (cursor + 1) in blocked:
        return None
    return cursor


def _flatter(quote: NBBOQuote, side: str) -> NBBOQuote:
    bid_cents = int(quote.bid * 100)
    ask_cents = int(quote.ask * 100)
    if side == "LONG":
        bid_cents += 50
        if bid_cents <= ask_cents:
            ask_cents = bid_cents - 1
    else:
        ask_cents -= 50
        if ask_cents <= 0:
            ask_cents = 1
        if bid_cents <= ask_cents:
            bid_cents = ask_cents + 1
    return cross([quote], 0, bid_cents, ask_cents)[0]


def _transform(edits: dict[int, NBBOQuote]):
    def transform(events: Sequence[Event]) -> list[Event]:
        out = list(events)
        for index, quote in edits.items():
            out[index] = quote
        return out

    return transform


def _gap(sequences: set[int]):
    def wrapper(original: object, quote: NBBOQuote) -> object:
        update = original(quote)  # type: ignore[operator]
        if quote.sequence in sequences:
            return replace(update, feed_gap_before=True)
        return update

    return wrapper


@_MARK
@_REAL
def test_m6_real() -> None:
    clean = run_real(fraction=_FRACTION)
    nonvacuous(clean, PositionClosed, scenario="m6_real")
    events = slice_real_events(rth_replay(), fraction=_FRACTION)
    spans, decisions = _spans(clean, events)
    chosen = placement_rule(spans, decisions)
    if not chosen:
        raise AssertionError("A2: placement rule P found no eligible cell")
    blocked = set(decisions)
    sides = _sides(clean)
    crossed: dict[int, NBBOQuote] = {}
    removed: dict[int, NBBOQuote] = {}
    gap_sequences: set[int] = set()
    for cell_id, index in chosen:
        quote_index = _quote_index(events, index, blocked)
        if quote_index is None:
            continue
        quote = events[quote_index]
        assert type(quote) is NBBOQuote
        side = sides[cell_id]
        crossed[quote_index] = _flatter(quote, side)
        removed[quote_index] = remove_side([quote], 0, "bid" if side == "LONG" else "ask")[0]
        gap_sequences.add(quote.sequence)
    copies: list[tuple[str, Records, set[int]]] = [
        ("crossed", run_real(fraction=_FRACTION, quote_transform=_transform(crossed)), set()),
        ("removed", run_real(fraction=_FRACTION, quote_transform=_transform(removed)), set()),
        ("gap", run_real(fraction=_FRACTION, rail_wrapper=_gap(gap_sequences)), gap_sequences),
    ]
    check_a1(clean, quiet_limit_ns=_QUIET_NS)
    check_a3(clean)
    for name, records, gaps in copies:
        nonvacuous(records, PositionClosed, scenario=f"m6_real_{name}")
        check_a1(records, quiet_limit_ns=_QUIET_NS)
        check_a3(records)
        check_a2(clean, records, feed_gap_sequences=gaps)
