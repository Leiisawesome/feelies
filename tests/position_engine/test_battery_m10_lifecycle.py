"""Battery member 10, lifecycle (battery.md; D-210). P-49."""

from __future__ import annotations

import json
from typing import NamedTuple

import pytest

from feelies.core.events import NBBOQuote, OrderAck, OrderAckStatus, SlicePositionUpdate
from feelies.core.platform_config import DEFAULT_BACKTEST_FILL_LATENCY_NS
from feelies.core.quote_quality import QuoteQuality, classify
from tests.position_engine.scenarios import (
    T0,
    Records,
    assert_no_risk_rejects,
    fixture_variant,
    require_entry_fills,
    run_synthetic,
)
from tests.position_engine.tapes import excise, force_class, hold, make_tape

_MARK = pytest.mark.battery_member(
    member=10,
    green_from="D",
    red_reason=r"^(CAP:lifecycle|NONVACUOUS)",
)

# 20ms cadence is inside the 50ms fill latency, so an exit stays EXITING
# across rail events. Boundary 1 is 30s; the entry fills 100ms later
# (index 1505). T = 1s puts that deadline on index 1555. Excising
# 1553..1555 leaves the deadline inside the hole, and the next quote is
# forced unusable on the bid. Boundary 3 is 90s; the same delay plus T
# is index 4555, and the tape ends at 4557, inside one fill latency.
_INTERVAL_NS = 20_000_000
_T_NS = 1_000_000_000
_N = 4558
_EXCISE_AT = 1553
_EXCISE_COUNT = 3
_AFTER = frozenset({"PositionSnapshot", "GateDecision", "DeRiskRequirement", "PositionClosed"})


class _Birth(NamedTuple):
    update: SlicePositionUpdate
    cell_id: str
    side: str


def _tape() -> list[NBBOQuote]:
    tape = make_tape(seed=3, n=_N, symbol="SYN", start_ns=T0, interval_ns=_INTERVAL_NS, size=1000)
    tape = hold(tape, 0, _N - 1)
    tape = excise(tape, _EXCISE_AT, _EXCISE_COUNT)
    return force_class(tape, _EXCISE_AT, "ZERO_SZ_BID")


def _variant() -> dict[str, object]:
    return fixture_variant(
        horizon_seconds=30,
        T_seconds=1,
        fee_round_trip_ticks=0,
        centre_ticks=11,
        band_ticks=0,
        lo_ticks=2,
        target_ticks=6,
    )


def _run(tape: list[NBBOQuote]) -> Records:
    return run_synthetic(tape, symbols=("SYN",), variant=_variant())


def _body(canonical: str) -> dict[str, object]:
    parsed = json.loads(canonical[canonical.index("{") :])
    if not isinstance(parsed, dict):
        raise AssertionError(f"record body is not an object: {canonical[:80]!r}")
    return parsed


def _int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AssertionError(f"{label} {value!r} is not an int")
    return value


def _births(records: Records) -> list[_Birth]:
    found: list[_Birth] = []
    for update in records.slice_updates:
        if update.fill_quantity == 0 or update.quantity != update.fill_quantity:
            continue
        side = "LONG" if update.fill_quantity > 0 else "SHORT"
        cell_id = f"{update.symbol}|{update.strategy_id}|{update.fill_timestamp_ns}|{side}"
        found.append(_Birth(update, cell_id, side))
    return found


def _cell_of(order_id: str) -> str:
    marker = "|EXIT|"
    if marker not in order_id:
        return ""
    return order_id.split(marker, 1)[0]


def _exit_filled(records: Records, cell_id: str) -> bool:
    prefix = cell_id + "|EXIT|"
    return any(
        update.order_id.startswith(prefix) and update.fill_quantity != 0
        for update in records.slice_updates
    )


def _span(tape: list[NBBOQuote], deadline: int) -> tuple[NBBOQuote | None, NBBOQuote | None]:
    previous: NBBOQuote | None = None
    for quote in tape:
        if quote.exchange_timestamp_ns < deadline:
            previous = quote
            continue
        return previous, quote
    return previous, None


def _exit_unusable(quote: NBBOQuote, side: str) -> bool:
    crossed = quote.bid >= quote.ask
    if side == "LONG":
        return crossed or quote.bid_size <= 0 or quote.bid <= 0
    return crossed or quote.ask_size <= 0 or quote.ask <= 0


def _rails(records: Records) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    for row in records:
        if row.type_name != "MarkRailUpdate":
            continue
        body = _body(row.canonical)
        found.append(
            (
                _int(body.get("quote_sequence"), "quote_sequence"),
                _int(body.get("event_timestamp_ns"), "event_timestamp_ns"),
                str(body.get("symbol")),
            )
        )
    return found


def _first_rail(records: Records, deadline: int) -> int:
    for sequence, timestamp, _symbol in _rails(records):
        if timestamp >= deadline:
            return sequence
    raise AssertionError(f"NONVACUOUS: no rail at or after {deadline}")


def _precondition_gap(tape: list[NBBOQuote], birth: _Birth) -> NBBOQuote:
    deadline = birth.update.fill_timestamp_ns + _T_NS
    previous, first = _span(tape, deadline)
    if previous is None or first is None:
        raise AssertionError(f"PRECONDITION: gap spans the deadline of {birth.cell_id}")
    gap = first.exchange_timestamp_ns - previous.exchange_timestamp_ns
    if gap <= _INTERVAL_NS:
        raise AssertionError(f"PRECONDITION: gap spans the deadline of {birth.cell_id}")
    if not _exit_unusable(first, birth.side):
        raise AssertionError(
            f"PRECONDITION: first quote {first.sequence} is unusable on the exit side "
            f"of {birth.cell_id}"
        )
    seen = False
    for quote in tape:
        if quote.sequence == first.sequence:
            seen = True
            continue
        if not seen:
            continue
        quality = classify(quote.bid, quote.ask, quote.bid_size, quote.ask_size)
        if quality is not QuoteQuality.VALID:
            raise AssertionError(
                f"PRECONDITION: a usable quote follows {first.sequence} for {birth.cell_id}"
            )
        return first
    raise AssertionError(
        f"PRECONDITION: a usable quote follows {first.sequence} for {birth.cell_id}"
    )


def _precondition_continues(tape: list[NBBOQuote], birth: _Birth) -> None:
    deadline = birth.update.fill_timestamp_ns + _T_NS
    if tape[-1].exchange_timestamp_ns <= deadline + DEFAULT_BACKTEST_FILL_LATENCY_NS:
        raise AssertionError(f"PRECONDITION: quotes continue after the horizon of {birth.cell_id}")


def _precondition_dense(tape: list[NBBOQuote], cell_id: str) -> None:
    if len(tape) < 3:
        raise AssertionError(f"PRECONDITION: cadence spans two rails before a fill for {cell_id}")
    step = tape[1].exchange_timestamp_ns - tape[0].exchange_timestamp_ns
    if step * 2 >= DEFAULT_BACKTEST_FILL_LATENCY_NS:
        raise AssertionError(f"PRECONDITION: cadence spans two rails before a fill for {cell_id}")


def _precondition_tail(tape: list[NBBOQuote], births: list[_Birth]) -> None:
    if len(births) < 2:
        raise AssertionError(f"PRECONDITION: at least two entry fills ({len(births)})")
    later = births[1].update.fill_timestamp_ns + _T_NS
    last = tape[-1].exchange_timestamp_ns
    if last < later:
        raise AssertionError(
            f"PRECONDITION: tape reaches the later deadline of {births[1].cell_id}"
        )
    if last >= later + DEFAULT_BACKTEST_FILL_LATENCY_NS:
        raise AssertionError(
            f"PRECONDITION: later deadline of {births[1].cell_id} is inside one fill latency "
            "of the last quote"
        )


def _timeline(records: Records) -> list[tuple[int, str, object]]:
    items: list[tuple[int, str, object]] = [(row.bus_ordinal, "row", row) for row in records]
    items.extend(
        (ordinal, "ack", ack)
        for ack, ordinal in zip(records.order_acks, records.ack_ordinals, strict=True)
    )
    items.sort(key=lambda item: item[0])
    return items


@_MARK
def test_m10_horizon_fires_on_first_event_past_deadline() -> None:
    """HORIZON is attributed to the first rail at or after the deadline (§2:264-265)."""
    tape = _tape()
    records = _run(tape)
    assert_no_risk_rejects(records)
    require_entry_fills(records)
    births = _births(records)
    if not births:
        raise AssertionError("PRECONDITION: an entry fill")
    first_quote = _precondition_gap(tape, births[0])
    cell_id = births[0].cell_id
    deadline = births[0].update.fill_timestamp_ns + _T_NS
    requirements = []
    for row in records:
        if row.type_name != "DeRiskRequirement":
            continue
        body = _body(row.canonical)
        order_id = str(body.get("order_id"))
        if body.get("reason") == "HORIZON" and _cell_of(order_id) == cell_id:
            requirements.append(row)
    if not requirements:
        raise AssertionError(f"NONVACUOUS: no HORIZON requirement for {cell_id}")
    sequence = _first_rail(records, deadline)
    attributed = requirements[0].attributed_quote_sequence
    if attributed != sequence or sequence != first_quote.sequence:
        raise AssertionError(
            f"CAP:lifecycle: {cell_id} HORIZON requirement at rail {attributed}, "
            f"first rail at or after the deadline is {sequence}"
        )


@_MARK
def test_m10_closed_cell_is_deaf() -> None:
    """No record carries a cell_id after its PositionClosed (§2:155)."""
    tape = _tape()
    records = _run(tape)
    assert_no_risk_rejects(records)
    require_entry_fills(records)
    births = _births(records)
    if not births:
        raise AssertionError("PRECONDITION: an entry fill")
    _precondition_gap(tape, births[0])
    _precondition_continues(tape, births[0])
    horizon: list[tuple[int, str]] = []
    for index, row in enumerate(records):
        if row.type_name != "PositionClosed":
            continue
        body = _body(row.canonical)
        if body.get("exit_reason") == "HORIZON":
            horizon.append((index, str(body.get("cell_id"))))
    if not horizon:
        raise AssertionError("NONVACUOUS: no HORIZON close")
    for index, cell_id in horizon:
        later = [
            item
            for item in records[index + 1 :]
            if item.type_name == "MarkRailUpdate" and _body(item.canonical).get("symbol") == "SYN"
        ]
        if not later:
            raise AssertionError(
                f"NONVACUOUS: no MarkRailUpdate after the HORIZON close of {cell_id}"
            )
        for item in records[index + 1 :]:
            if item.type_name not in _AFTER:
                continue
            body = _body(item.canonical)
            carries = (
                body.get("cell_id") == cell_id or _cell_of(str(body.get("order_id"))) == cell_id
            )
            if carries:
                raise AssertionError(
                    f"CAP:lifecycle: {cell_id} {item.type_name} after PositionClosed"
                )


@_MARK
def test_m10_one_live_requirement_in_exiting() -> None:
    """One live requirement; the next follows a REJECTED ack (§2:157-161, G11, D-106)."""
    tape = _tape()
    records = _run(tape)
    assert_no_risk_rejects(records)
    require_entry_fills(records)
    births = _births(records)
    if not births:
        raise AssertionError("PRECONDITION: an entry fill")
    _precondition_dense(tape, births[0].cell_id)
    _precondition_gap(tape, births[0])
    exiting: dict[str, int] = {}
    for row in records:
        if row.type_name != "PositionSnapshot":
            continue
        body = _body(row.canonical)
        if body.get("state") != "EXITING":
            continue
        exiting[str(body.get("cell_id"))] = _int(body.get("rail_sequence"), "rail_sequence")
    rail_sequences = {sequence for sequence, _timestamp, _symbol in _rails(records)}
    witnessed = False
    for row in records:
        if row.type_name != "DeRiskRequirement":
            continue
        cell_id = _cell_of(str(_body(row.canonical).get("order_id")))
        if cell_id in exiting and exiting[cell_id] in rail_sequences:
            witnessed = True
    if not witnessed:
        raise AssertionError("NONVACUOUS: no requirement with a rail while EXITING")
    live: dict[str, str] = {}
    last: dict[str, str] = {}
    rejected: set[str] = set()
    for _ordinal, kind, item in _timeline(records):
        if kind == "ack":
            if not isinstance(item, OrderAck) or "|EXIT|" not in item.order_id:
                continue
            cell_id = _cell_of(item.order_id)
            if item.status is OrderAckStatus.REJECTED:
                rejected.add(item.order_id)
                if live.get(cell_id) == item.order_id:
                    del live[cell_id]
            elif item.status is OrderAckStatus.FILLED and live.get(cell_id) == item.order_id:
                del live[cell_id]
            continue
        if getattr(item, "type_name", "") != "DeRiskRequirement":
            continue
        order_id = str(_body(getattr(item, "canonical")).get("order_id"))
        cell_id = _cell_of(order_id)
        if not cell_id:
            raise AssertionError(f"CAP:lifecycle: requirement {order_id} has no cell")
        current = live.get(cell_id)
        if current is not None:
            raise AssertionError(
                f"CAP:lifecycle: {cell_id} requirement {order_id} is live while {current} is live"
            )
        previous = last.get(cell_id)
        if previous is not None and previous not in rejected:
            raise AssertionError(
                f"CAP:lifecycle: {cell_id} requirement {order_id} follows {previous} "
                "without a REJECTED ack"
            )
        live[cell_id] = order_id
        last[cell_id] = order_id


@_MARK
def test_m10_every_opened_cell_closes() -> None:
    """Every born cell closes; a cell still open at tape end uses END_OF_TAPE (§2:177-183)."""
    tape = _tape()
    records = _run(tape)
    assert_no_risk_rejects(records)
    require_entry_fills(records)
    births = _births(records)
    _precondition_tail(tape, births)
    open_ids = {birth.cell_id for birth in births if not _exit_filled(records, birth.cell_id)}
    witnessed = False
    for row in records:
        if row.type_name != "DeRiskRequirement":
            continue
        if _cell_of(str(_body(row.canonical).get("order_id"))) in open_ids:
            witnessed = True
    if not witnessed:
        raise AssertionError("NONVACUOUS: no requirement whose cell has no exit fill by tape end")
    closed: dict[str, list[tuple[object, str]]] = {}
    for row in records:
        if row.type_name != "PositionClosed":
            continue
        body = _body(row.canonical)
        closed.setdefault(str(body.get("cell_id")), []).append((row, str(body.get("exit_reason"))))
    inside = False
    for birth in births:
        rows = closed.get(birth.cell_id, [])
        if len(rows) != 1:
            raise AssertionError(f"CAP:lifecycle: {birth.cell_id} has {len(rows)} PositionClosed")
        row, reason = rows[0]
        if _exit_filled(records, birth.cell_id):
            inside = True
            if getattr(row, "replay_index") is not None:
                raise AssertionError(
                    f"CAP:lifecycle: {birth.cell_id} exit filled but its PositionClosed "
                    f"is attributed after the tape (replay {getattr(row, 'replay_index')})"
                )
            continue
        replay = getattr(row, "replay_index")
        cursor = getattr(row, "attributed_quote_sequence")
        if reason != "END_OF_TAPE" or cursor != "EOT" or not isinstance(replay, int):
            raise AssertionError(
                f"CAP:lifecycle: {birth.cell_id} tape-end close {reason} "
                f"replay {replay} cursor {cursor}"
            )
        if replay <= len(tape) - 1:
            raise AssertionError(
                f"CAP:lifecycle: {birth.cell_id} END_OF_TAPE replay {replay} "
                f"is not after {len(tape) - 1}"
            )
    if not inside:
        names = ", ".join(birth.cell_id for birth in births)
        raise AssertionError(f"CAP:lifecycle: {names} none closed inside the tape")
