"""Member harness.

Synthetic runs follow ``tests/position_engine/test_p10_contract_surface.py``
``_config`` / ``_replay``: ``InMemoryEventLog.append_batch``, ``PlatformConfig``,
``build_platform``, ``bus.subscribe_all``, ``boot``, ``run_backtest``.
"""

from __future__ import annotations

import copy
import dataclasses
import functools
import hashlib
import json
import math
import os
import struct
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import NamedTuple

import yaml

from feelies.alpha.loader import AlphaLoader
from feelies.bootstrap import build_platform
from feelies.core.events import (
    DeRiskRequirement,
    Event,
    GateDecision,
    MarkRailUpdate,
    MetricEvent,
    NBBOQuote,
    OrderRequest,
    RegimeState,
    SensorReading,
    PositionClosed,
    RiskAction,
    RiskVerdict,
    PositionSnapshot,
    StateTransition,
    Trade,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.position_engine.tapes import make_tape

T0 = 1_774_533_600_000_000_000
_FIXTURE = Path("tests/position_engine/fixtures/sig_position_fixture_v1.alpha.yaml")
_APP_CONFIG = Path("configs/bt_position_arbitrary_not_calibrated.yaml")
_NEEDED = frozenset({"ofi_ewma", "book_imbalance", "spread_z_30d", "realized_vol_30s"})
_CLOCK_FIXED = 946684800

RECORD_TYPES = (
    MarkRailUpdate,
    PositionSnapshot,
    GateDecision,
    PositionClosed,
    DeRiskRequirement,
)


class Record(NamedTuple):
    attributed_quote_sequence: int | None
    type_name: str
    canonical: str


class Widened(NamedTuple):
    """One kept bus event, reduced to a replay-index cursor and a sha256 digest."""

    cursor: int | None
    type_name: str
    digest: bytes


class Records(list[Record]):
    """Ordered bus records, plus the quotes and orders of that run."""

    quotes: dict[int, NBBOQuote]
    order_requests: tuple[OrderRequest, ...]
    risk_verdicts: tuple[RiskVerdict, ...]
    widened: tuple[Widened, ...]

    def __init__(
        self,
        rows: Sequence[Record],
        quotes: dict[int, NBBOQuote],
        order_requests: Sequence[OrderRequest],
        risk_verdicts: Sequence[RiskVerdict] = (),
    ) -> None:
        super().__init__(rows)
        self.quotes = quotes
        self.order_requests = tuple(order_requests)
        self.risk_verdicts = tuple(risk_verdicts)
        self.widened = ()


def canonical(event: Event) -> str:
    body = json.dumps(
        dataclasses.asdict(event),
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{type(event).__name__}{body}"


def _drop_keys(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _drop_keys(item)
            for key, item in value.items()
            if key != "sequence" and not str(key).endswith("_sequence") and key != "cell_id"
        }
    if isinstance(value, list):
        return [_drop_keys(item) for item in value]
    return value


def project_for_multiname(canonical_text: str) -> str:
    name, _, payload = canonical_text.partition("{")
    data = json.loads("{" + payload)
    return name + json.dumps(_drop_keys(data), sort_keys=True, separators=(",", ":"))


def assert_no_risk_rejects(records: Records) -> None:
    """Synthetic batteries must not be thinned by a risk-layer reject."""
    rejects = [
        verdict for verdict in records.risk_verdicts if verdict.action is not RiskAction.ALLOW
    ]
    if not rejects:
        return
    counts: dict[str, int] = {}
    for verdict in rejects:
        counts[verdict.reason] = counts.get(verdict.reason, 0) + 1
    detail = ", ".join(f"{reason}:{counts[reason]}" for reason in sorted(counts))
    raise AssertionError(f"CONFOUND: risk rejected {len(rejects)} signals ({detail})")


def nonvacuous(records: Sequence[Record], *type_names: type[Event] | str, scenario: str) -> None:
    present = {row.type_name for row in records}
    for type_name in type_names:
        label = type_name if isinstance(type_name, str) else type_name.__name__
        if label not in present:
            raise AssertionError(f"NONVACUOUS: no {label} records in {scenario}")


_EXIT_RANK = ("ADVERSE", "HORIZON", "INVALIDATION", "FAVORABLE")


def drawn_adverse_level(cell_id: str, centre: int, band: int) -> int:
    """contracts.md §9 band draw. ``band`` is even; the level is whole ticks."""
    offset = int.from_bytes(hashlib.sha256(cell_id.encode("utf-8")).digest()[:8], "big") % (
        band + 1
    )
    return (centre - band // 2) + offset


def _body(canonical_text: str) -> dict[str, object]:
    return json.loads(canonical_text[canonical_text.index("{") :])


def _cents(price: object) -> int:
    return int(price * 100)  # type: ignore[operator]


def _sign(side: str) -> int:
    if side == "LONG":
        return 1
    if side == "SHORT":
        return -1
    raise AssertionError(f"displacement identity: side {side} is not LONG or SHORT")


def _valuation_cents(quote: NBBOQuote, side: str) -> int:
    return _cents(quote.bid if side == "LONG" else quote.ask)


def cell_economics(row: Record, quotes: dict[int, NBBOQuote]) -> tuple[int, int, int]:
    """Return ``(result, displacement, cost)`` in cent-shares from the tape."""
    body = _body(row.canonical)
    cell = str(body["cell_id"])
    side = str(body["side"])
    sign = _sign(side)
    entries = body["entry_fills"]
    exits = body["exit_fills"]
    assert isinstance(entries, list) and isinstance(exits, list)
    entry = entries[0]
    exit_fill = exits[0]
    assert isinstance(entry, dict) and isinstance(exit_fill, dict)
    exit_seq = int(exit_fill["sequence"])
    entry_seq = int(entry["sequence"])
    if exit_seq not in quotes:
        raise AssertionError(
            f"displacement identity: cell {cell} exit fill sequence {exit_seq} is not on the tape"
        )
    if entry_seq not in quotes:
        raise AssertionError(
            f"displacement identity: cell {cell} entry fill sequence {entry_seq} is not on the tape"
        )
    qty = int(entry["quantity"])
    result = sign * (
        sum(int(fill["price_cents"]) * int(fill["quantity"]) for fill in exits)
        - sum(int(fill["price_cents"]) * int(fill["quantity"]) for fill in entries)
    )
    displacement = (
        sign
        * qty
        * (_valuation_cents(quotes[exit_seq], side) - _valuation_cents(quotes[entry_seq], side))
    )
    return result, displacement, displacement - result


def displacement_identity(records: Records) -> None:
    for row in records:
        if row.type_name != "PositionClosed":
            continue
        result, displacement, cost = cell_economics(row, records.quotes)
        if result + cost != displacement:
            cell = str(_body(row.canonical)["cell_id"])
            raise AssertionError(
                f"displacement identity failed for {cell}: cost {cost} != "
                f"displacement {displacement} - result {result}"
            )


def mean_within_se(samples: Sequence[float], expected: float, *, label: str) -> None:
    n = len(samples)
    if n < 2:
        raise AssertionError(f"mean {label}: need at least 2 samples, got {n}")
    mean = sum(samples) / n
    var = sum((sample - mean) ** 2 for sample in samples) / (n - 1)
    bound = 4 * math.sqrt(var / n)
    if abs(mean - expected) > bound:
        raise AssertionError(f"mean {label} {mean} outside 4 SE of {expected} (bound {bound})")


def exit_reason_at_collision(records: Records) -> None:
    requirements = [row for row in records if row.type_name == "DeRiskRequirement"]
    for row in records:
        if row.type_name != "PositionClosed":
            continue
        body = _body(row.canonical)
        cell = str(body["cell_id"])
        paths = body["triggered_paths"]
        assert isinstance(paths, list)
        names = [str(path["path"]) for path in paths if isinstance(path, dict)]
        ranked = [name for name in _EXIT_RANK if name in names]
        expected = ranked[0]
        got = str(body["exit_reason"])
        if got != expected:
            raise AssertionError(
                f"exit reason {got} != {expected} cell {cell} candidates {ranked}"
            )
        prices = [int(path["proposed_price_cents"]) for path in paths if isinstance(path, dict)]
        worst = min(prices) if body["side"] == "LONG" else max(prices)
        if int(body["proposed_price_cents"]) != worst:
            raise AssertionError(
                f"proposed price {body['proposed_price_cents']} != worst {worst} cell {cell}"
            )
        entries = body["entry_fills"]
        exits = body["exit_fills"]
        assert isinstance(entries, list) and isinstance(exits, list) and entries and exits
        assert isinstance(entries[0], dict) and isinstance(exits[0], dict)
        start = int(entries[0]["timestamp_ns"])
        end = int(exits[0]["timestamp_ns"])
        count = 0
        for req in requirements:
            req_body = _body(req.canonical)
            if req_body.get("symbol") != body["symbol"]:
                continue
            if req_body.get("strategy_id") != body["strategy_id"]:
                continue
            ts = int(req_body["timestamp_ns"])
            if start <= ts <= end:
                count += 1
        if count != 1:
            raise AssertionError(f"requirement count {count} != 1 cell {cell}")


def _clock_tag() -> str:
    return "fixed" if time.time() == _CLOCK_FIXED else "wall"


def _sensors() -> tuple[object, ...]:
    contra = PlatformConfig.from_yaml(Path("configs/bt_netting_contest.yaml"))
    return tuple(spec for spec in contra.sensor_specs if spec.sensor_id in _NEEDED)


def _keep(event: Event) -> bool:
    if type(event) is DeRiskRequirement:
        return event.source_layer == "POSITION"
    return type(event) in RECORD_TYPES


def attribute(stream: Sequence[Event]) -> list[tuple[int | None, str, str]]:
    """Attribute each recorded event to the quote cursor at publication.

    The cursor starts at None. A MarkRailUpdate sets it to ``quote_sequence``
    before that update is recorded. An NBBOQuote sets it to ``sequence``.
    """
    cursor: int | None = None
    rows: list[tuple[int | None, str, str]] = []
    for event in stream:
        if type(event) is MarkRailUpdate:
            cursor = event.quote_sequence
        elif type(event) is NBBOQuote:
            cursor = event.sequence
        if _keep(event):
            rows.append((cursor, type(event).__name__, canonical(event)))
    return rows


def _capture(bus: object) -> list[Event]:
    stream: list[Event] = []

    def keep(event: Event) -> None:
        # MetricEvent is telemetry. StateTransition includes the session-end
        # marker. Neither is part of the widened prefix.
        if type(event) is MetricEvent or type(event) is StateTransition:
            return
        stream.append(event)

    bus.subscribe_all(keep)  # type: ignore[attr-defined]
    return stream


_PIPELINE_END = frozenset({"BACKTEST_COMPLETE", "SESSION_FEED_COMPLETE", "CMD_SHUTDOWN"})
_MISSING = object()
_DC_FIELDS: dict[type, tuple[tuple[bytes, str], ...] | None] = {}
_ENUM_TYPES: dict[type, bool] = {}
_SESSION_DIGESTS: dict[str, tuple[Widened, ...]] = {}


def _dc_fields(value: object) -> tuple[tuple[bytes, str], ...] | None:
    cls = type(value)
    cached = _DC_FIELDS.get(cls, _MISSING)
    if cached is not _MISSING:
        return cached  # type: ignore[return-value]
    if not dataclasses.is_dataclass(value) or isinstance(value, type):
        _DC_FIELDS[cls] = None
        return None
    fields = tuple((item.name.encode(), item.name) for item in dataclasses.fields(value))
    _DC_FIELDS[cls] = fields
    return fields


def _is_enum(value: object) -> bool:
    cls = type(value)
    cached = _ENUM_TYPES.get(cls)
    if cached is None:
        cached = isinstance(value, Enum)
        _ENUM_TYPES[cls] = cached
    return cached


def _sort_token(key: object) -> bytes:
    kind = type(key)
    if kind is str:
        return b"s" + key.encode()
    if kind is int and not isinstance(key, bool):
        return b"i" + key.to_bytes(8, "little", signed=True)
    if kind is float:
        return b"d" + struct.pack("<d", key)
    return b"o" + kind.__name__.encode() + str(key).encode()


_PACK_I = bytearray(9)
_PACK_F = bytearray(9)
_PACK8 = bytearray(64)
_PACK4 = bytearray(32)
_STR_PACK: dict[str, bytes] = {}
_DEC_PACK: dict[Decimal, bytes] = {}
_PROV_PACK: dict[tuple[tuple[str, ...], tuple[str, ...]], bytes] = {}


def _feed_scalar(buf: bytearray, value: object) -> bool:
    kind = type(value)
    if kind is int:
        try:
            struct.pack_into("<bq", _PACK_I, 0, 0x69, value)
        except struct.error:
            raw = value.to_bytes((value.bit_length() // 8) + 2, "little", signed=True)
            buf.extend(b"I")
            buf.extend(len(raw).to_bytes(2, "little"))
            buf.extend(raw)
            return True
        buf.extend(_PACK_I)
        return True
    if kind is str:
        _feed_str(buf, value, cache=True)
        return True
    if kind is float:
        struct.pack_into("<bd", _PACK_F, 0, 0x64, value)
        buf.extend(_PACK_F)
        return True
    if kind is bool:
        buf.extend(b"t" if value else b"f")
        return True
    if kind is Decimal:
        packed = _DEC_PACK.get(value)
        if packed is None:
            raw = str(value).encode()
            packed = b"D" + len(raw).to_bytes(4, "little") + raw
            _DEC_PACK[value] = packed
        buf.extend(packed)
        return True
    if value is None:
        buf.extend(b"n")
        return True
    return False


def _feed_str(buf: bytearray, value: str, *, cache: bool) -> None:
    if cache:
        packed = _STR_PACK.get(value)
        if packed is None:
            raw = value.encode()
            packed = b"s" + len(raw).to_bytes(4, "little") + raw
            _STR_PACK[value] = packed
        buf.extend(packed)
        return
    raw = value.encode()
    buf.extend(b"s")
    buf.extend(len(raw).to_bytes(4, "little"))
    buf.extend(raw)


def _feed_opt_int(buf: bytearray, value: int | None) -> None:
    if value is None:
        buf.extend(b"n")
        return
    struct.pack_into("<bq", _PACK_I, 0, 0x69, value)
    buf.extend(_PACK_I)


def _provenance_bytes(provenance: object) -> bytes:
    ids = provenance.input_sensor_ids  # type: ignore[attr-defined]
    kinds = provenance.input_event_kinds  # type: ignore[attr-defined]
    key = (ids, kinds)
    packed = _PROV_PACK.get(key)
    if packed is None:
        tmp = bytearray()
        _feed(tmp, ids)
        _feed(tmp, kinds)
        packed = bytes(tmp)
        _PROV_PACK[key] = packed
    return packed


def _feed(buf: bytearray, value: object) -> None:
    """Compact encoding. Recurse only into nested dataclasses and containers."""
    if _feed_scalar(buf, value):
        return
    kind = type(value)
    if kind is tuple or kind is list:
        buf.extend(b"[")
        for item in value:
            if not _feed_scalar(buf, item):
                _feed(buf, item)
        buf.extend(b"]")
        return
    fields = _dc_fields(value)
    if fields is not None:
        buf.extend(kind.__name__.encode())
        for name_bytes, name in fields:
            buf.extend(b"\0")
            buf.extend(name_bytes)
            _feed(buf, getattr(value, name))
        return
    if isinstance(value, Mapping):
        buf.extend(b"{")
        for key, item in sorted(value.items(), key=lambda pair: _sort_token(pair[0])):
            if not _feed_scalar(buf, key):
                _feed(buf, key)
            if not _feed_scalar(buf, item):
                _feed(buf, item)
        buf.extend(b"}")
        return
    if _is_enum(value):
        raw = value.name.encode()  # type: ignore[attr-defined]
        buf.extend(b"e")
        buf.extend(len(raw).to_bytes(4, "little"))
        buf.extend(raw)
        return
    raise TypeError(f"digest has no encoding for {kind.__name__}")


_DIGEST_BUF = bytearray()
_TAG_SENSOR = b"SensorReading"
_TAG_QUOTE = b"NBBOQuote"
_TAG_RAIL = b"MarkRailUpdate"
_TAG_TRADE = b"Trade"
_TAG_REGIME = b"RegimeState"


def _pack_orientation(buf: bytearray, side: object) -> None:
    buf.extend(
        struct.pack(
            "<11q3B",
            side.paying_mark_cents,  # type: ignore[attr-defined]
            side.valuation_mark_cents,  # type: ignore[attr-defined]
            side.worst_side_mark_cents,  # type: ignore[attr-defined]
            side.forced_exit_mark_cents,  # type: ignore[attr-defined]
            side.dwelled_exit_mark_cents,  # type: ignore[attr-defined]
            side.paying_size,  # type: ignore[attr-defined]
            side.valuation_size,  # type: ignore[attr-defined]
            side.paying_age_ns,  # type: ignore[attr-defined]
            side.valuation_age_ns,  # type: ignore[attr-defined]
            side.paying_absent_for_ns,  # type: ignore[attr-defined]
            side.valuation_absent_for_ns,  # type: ignore[attr-defined]
            side.paying_side_absent,  # type: ignore[attr-defined]
            side.valuation_side_absent,  # type: ignore[attr-defined]
            side.dwell_window_clean,  # type: ignore[attr-defined]
        )
    )


def _pack_sensor(buf: bytearray, event: SensorReading) -> None:
    buf.extend(_TAG_SENSOR)
    struct.pack_into(
        "<3q",
        _PACK4,
        0,
        event.timestamp_ns,
        event.sequence,
        event.schema_version,
    )
    buf.extend(_PACK4[:24])
    _feed_str(buf, event.correlation_id, cache=False)
    _feed_str(buf, event.source_layer, cache=True)
    _feed_str(buf, event.symbol, cache=True)
    _feed_str(buf, event.sensor_id, cache=True)
    _feed_str(buf, event.sensor_version, cache=True)
    value = event.value
    if type(value) is float:
        struct.pack_into("<d", _PACK_F, 0, value)
        buf.extend(_PACK_F[:8])
    elif not _feed_scalar(buf, value):
        _feed(buf, value)
    struct.pack_into("<dB", _PACK_F, 0, event.confidence, event.warm)
    buf.extend(_PACK_F[:9])
    buf.extend(_provenance_bytes(event.provenance))


def _pack_quote(buf: bytearray, event: NBBOQuote) -> None:
    buf.extend(_TAG_QUOTE)
    struct.pack_into(
        "<6q",
        _PACK8,
        0,
        event.timestamp_ns,
        event.sequence,
        event.schema_version,
        event.bid_size,
        event.ask_size,
        event.exchange_timestamp_ns,
    )
    buf.extend(_PACK8[:48])
    struct.pack_into(
        "<4q",
        _PACK4,
        0,
        event.bid_exchange,
        event.ask_exchange,
        event.sequence_number,
        event.tape,
    )
    buf.extend(_PACK4[:32])
    _feed_str(buf, event.correlation_id, cache=False)
    _feed_str(buf, event.source_layer, cache=True)
    _feed_str(buf, event.symbol, cache=True)
    _feed_scalar(buf, event.bid)
    _feed_scalar(buf, event.ask)
    _feed(buf, event.conditions)
    _feed(buf, event.indicators)
    _feed_opt_int(buf, event.participant_timestamp_ns)
    _feed_opt_int(buf, event.trf_timestamp_ns)
    _feed_opt_int(buf, event.received_ns)


def _pack_rail(buf: bytearray, event: MarkRailUpdate) -> None:
    buf.extend(_TAG_RAIL)
    struct.pack_into(
        "<6q",
        _PACK8,
        0,
        event.timestamp_ns,
        event.sequence,
        event.schema_version,
        event.quote_sequence,
        event.event_timestamp_ns,
        event.symbol_quiet_ns,
    )
    buf.extend(_PACK8[:48])
    _feed_str(buf, event.correlation_id, cache=False)
    _feed_str(buf, event.source_layer, cache=True)
    _feed_str(buf, event.symbol, cache=True)
    _pack_orientation(buf, event.long)
    _pack_orientation(buf, event.short)
    buf.extend(
        bytes(
            (
                event.locked,
                event.crossed,
                event.feed_gap_before,
                event.warmed_up,
            )
        )
    )


def _pack_trade(buf: bytearray, event: Trade) -> None:
    buf.extend(_TAG_TRADE)
    struct.pack_into(
        "<8q",
        _PACK8,
        0,
        event.timestamp_ns,
        event.sequence,
        event.schema_version,
        event.size,
        event.exchange,
        event.exchange_timestamp_ns,
        event.sequence_number,
        event.tape,
    )
    buf.extend(_PACK8)
    _feed_str(buf, event.correlation_id, cache=False)
    _feed_str(buf, event.source_layer, cache=True)
    _feed_str(buf, event.symbol, cache=True)
    _feed_str(buf, event.trade_id, cache=False)
    _feed_scalar(buf, event.price)
    _feed(buf, event.conditions)
    if event.decimal_size is None:
        buf.extend(b"n")
    else:
        _feed_str(buf, event.decimal_size, cache=False)
    _feed_opt_int(buf, event.trf_id)
    _feed_opt_int(buf, event.trf_timestamp_ns)
    _feed_opt_int(buf, event.participant_timestamp_ns)
    _feed_opt_int(buf, event.correction)
    _feed_opt_int(buf, event.received_ns)


def _pack_regime(buf: bytearray, event: RegimeState) -> None:
    buf.extend(_TAG_REGIME)
    struct.pack_into(
        "<5q",
        _PACK8,
        0,
        event.timestamp_ns,
        event.sequence,
        event.schema_version,
        event.dominant_state,
        event.horizon_seconds,
    )
    buf.extend(_PACK8[:40])
    _feed_str(buf, event.correlation_id, cache=False)
    _feed_str(buf, event.source_layer, cache=True)
    _feed_str(buf, event.symbol, cache=True)
    _feed_str(buf, event.engine_name, cache=True)
    _feed_str(buf, event.dominant_name, cache=True)
    _feed(buf, event.state_names)
    _feed(buf, event.posteriors)
    struct.pack_into(
        "<ddB", _PACK4, 0, event.posterior_entropy_nats, event.discriminability, event.calibrated
    )
    buf.extend(_PACK4[:17])


def _event_digest(event: Event) -> bytes:
    buf = _DIGEST_BUF
    buf.clear()
    kind = type(event)
    if kind is SensorReading:
        _pack_sensor(buf, event)
    elif kind is NBBOQuote:
        _pack_quote(buf, event)
    elif kind is Trade:
        _pack_trade(buf, event)
    elif kind is MarkRailUpdate:
        _pack_rail(buf, event)
    elif kind is RegimeState:
        _pack_regime(buf, event)
    else:
        _feed(buf, event)
    return hashlib.sha256(buf).digest()


def widened_rows(stream: Sequence[Event]) -> tuple[Widened, ...]:
    """Per-event digests up to the replay boundary.

    MetricEvent is telemetry (wall-clock durations are not a causal prefix).
    StateTransition includes the session-end transition, which a truncated run
    emits at the cutoff. The cursor is the replay event index.
    """
    cursor: int | None = None
    rows: list[Widened] = []
    for event in stream:
        kind = type(event)
        if kind is StateTransition:
            if event.trigger in _PIPELINE_END:
                break
            continue
        if kind is MetricEvent:
            continue
        if kind is MarkRailUpdate:
            cursor = event.quote_sequence
        elif kind is NBBOQuote:
            cursor = event.sequence
        elif kind is Trade:
            cursor = event.sequence
        rows.append(Widened(cursor, kind.__name__, _event_digest(event)))
    return tuple(rows)


def assert_widened_prefix(
    truncated: Sequence[Widened],
    full: Sequence[Widened],
    seq_k: int,
) -> None:
    """Prefixes through replay index ``seq_k`` are the same sequence of digests."""
    left = [row for row in truncated if row.cursor is not None and row.cursor <= seq_k]
    right = [row for row in full if row.cursor is not None and row.cursor <= seq_k]
    limit = min(len(left), len(right))
    for index in range(limit):
        if left[index] != right[index]:
            row = left[index]
            raise AssertionError(f"prefix diverged at {row.type_name}, cursor {row.cursor}")
    if len(left) != len(right):
        row = left[limit] if len(left) > len(right) else right[limit]
        raise AssertionError(f"prefix diverged at {row.type_name}, cursor {row.cursor}")


def session_digest(key: str, rows: tuple[Widened, ...]) -> tuple[Widened, ...]:
    """Full-run digest sequence, computed once per session and reused for every cut."""
    cached = _SESSION_DIGESTS.get(key)
    if cached is not None:
        return cached
    _SESSION_DIGESTS[key] = rows
    return rows


def _replay_index(events: Sequence[Event]) -> dict[int, int]:
    index_of: dict[int, int] = {}
    for index, event in enumerate(events):
        if type(event) is not NBBOQuote and type(event) is not Trade:
            continue
        if event.sequence in index_of:
            raise AssertionError(f"replay sequence {event.sequence} is not unique")
        index_of[event.sequence] = index
    return index_of


def decision_trigger_indexes(
    events: Sequence[Event], widened: Sequence[Widened]
) -> tuple[int, ...]:
    """Replay indexes of the event that triggered each OrderRequest, in bus order."""
    index_of = _replay_index(events)
    triggers: list[int] = []
    for row in widened:
        if row.type_name != "OrderRequest" or row.cursor is None:
            continue
        index = index_of.get(row.cursor)
        if index is not None:
            triggers.append(index)
    return tuple(triggers)


def decision_cut_indices(
    events: Sequence[Event],
    widened: Sequence[Widened],
    fractions: Sequence[float],
) -> tuple[int, ...]:
    """First OrderRequest trigger at or after each target position in the replay."""
    triggers = decision_trigger_indexes(events, widened)
    n = len(events)
    cuts: list[int] = []
    for fraction in fractions:
        target = int(n * fraction)
        chosen = next((index for index in triggers if index >= target), None)
        if chosen is None:
            raise AssertionError(
                f"no OrderRequest at or after index {target} ({fraction:.0%} of {n})"
            )
        cuts.append(chosen)
    return tuple(cuts)


def _records_from(stream: Sequence[Event], *, digest_only: bool = False) -> Records:
    widened = widened_rows(stream)
    if digest_only:
        records = Records([], {}, (), ())
        records.widened = widened
        return records
    quotes = {event.sequence: event for event in stream if type(event) is NBBOQuote}
    orders = [event for event in stream if type(event) is OrderRequest]
    verdicts = [event for event in stream if type(event) is RiskVerdict]
    records = Records([Record(*row) for row in attribute(stream)], quotes, orders, verdicts)
    records.widened = widened
    return records


@contextmanager
def _seams(
    engine_factory: Callable[..., object] | None,
    rail_wrapper: Callable[..., object] | None,
    attach_sink: bool,
):
    import feelies.portfolio.mark_rail as rail_mod
    import feelies.position.engine as engine_mod

    saved_engine = engine_mod.PositionEngine
    saved_on_quote = rail_mod.MarkRail.on_quote
    saved_attach = engine_mod.PositionRecordSink.attach
    try:
        if engine_factory is not None:
            engine_mod.PositionEngine = engine_factory  # type: ignore[misc, assignment]
        if rail_wrapper is not None:
            original = saved_on_quote

            def on_quote(self: object, quote: NBBOQuote) -> object:
                return rail_wrapper(original.__get__(self, type(self)), quote)

            rail_mod.MarkRail.on_quote = on_quote  # type: ignore[method-assign]
        if not attach_sink:
            engine_mod.PositionRecordSink.attach = lambda self: None  # type: ignore[method-assign]
        yield
    finally:
        engine_mod.PositionEngine = saved_engine
        rail_mod.MarkRail.on_quote = saved_on_quote
        engine_mod.PositionRecordSink.attach = saved_attach


def fixture_variant(**overrides: object) -> dict[str, object]:
    """Pure in-memory edit of the position fixture. No YAML file is written."""
    spec = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    edited: dict[str, object] = copy.deepcopy(spec)
    if "horizon_seconds" in overrides:
        edited["horizon_seconds"] = overrides["horizon_seconds"]
    policy = edited["exit_policy"]
    assert isinstance(policy, dict)
    if "fee_round_trip_ticks" in overrides:
        policy["fee_round_trip_ticks"] = overrides["fee_round_trip_ticks"]
    horizon = policy["horizon"]
    adverse = policy["adverse"]
    favorable = policy["favorable"]
    assert isinstance(horizon, dict) and isinstance(adverse, dict) and isinstance(favorable, dict)
    if "T_seconds" in overrides:
        horizon["T_seconds"] = overrides["T_seconds"]
    for key in ("centre_ticks", "band_ticks", "lo_ticks", "hi_ticks"):
        if key in overrides:
            adverse[key] = overrides[key]
    if "target_ticks" in overrides:
        favorable["target_ticks"] = overrides["target_ticks"]
    if "archetype" in overrides:
        policy["archetype"] = overrides["archetype"]
    if "form" in overrides:
        favorable["form"] = overrides["form"]
    if "giveback_spread_multiple" in overrides:
        favorable["giveback_spread_multiple"] = overrides["giveback_spread_multiple"]
    return edited


def synthetic_alpha_spec(variant: dict[str, object] | None) -> dict[str, object]:
    """In-memory fixture for synthetic runs. Drawdown is 100 unless set explicitly."""
    on_disk = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)
    disk_risk = on_disk.get("risk_budget")
    disk_pct = disk_risk.get("max_drawdown_pct") if isinstance(disk_risk, dict) else None
    if variant is None:
        spec: dict[str, object] = copy.deepcopy(on_disk)
        explicit = False
    else:
        spec = copy.deepcopy(variant)
        caller_risk = variant.get("risk_budget")
        explicit = (
            isinstance(caller_risk, dict)
            and "max_drawdown_pct" in caller_risk
            and caller_risk.get("max_drawdown_pct") != disk_pct
        )
    if not explicit:
        risk = spec.get("risk_budget")
        if not isinstance(risk, dict):
            risk = {}
            spec["risk_budget"] = risk
        risk["max_drawdown_pct"] = 100.0
    return spec


def _execute_synthetic(
    tape: Sequence[NBBOQuote],
    symbols: tuple[str, ...],
    engine_factory: Callable[..., object] | None,
    rail_wrapper: Callable[..., object] | None,
    attach_sink: bool,
    variant: dict[str, object] | None,
) -> Records:
    log = InMemoryEventLog()
    log.append_batch(list(tape))
    config = PlatformConfig(
        symbols=frozenset(symbols),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_FIXTURE],
        sensor_specs=_sensors(),  # type: ignore[arg-type]
        regime_engine=None,
        enforce_trend_mechanism=False,
        session_open_ns=T0,
        risk_max_gross_exposure_pct=80.0,
    )
    original_load = AlphaLoader.load
    spec = synthetic_alpha_spec(variant)

    def _load(
        self: AlphaLoader,
        path: object,
        param_overrides: dict[str, object] | None = None,
    ) -> object:
        if Path(str(path)) == _FIXTURE:
            return self.load_from_dict(spec, source=str(_FIXTURE))
        return original_load(self, path, param_overrides)  # type: ignore[arg-type]

    AlphaLoader.load = _load  # type: ignore[method-assign]
    try:
        with _seams(engine_factory, rail_wrapper, attach_sink):
            orchestrator, resolved = build_platform(config, event_log=log)
            stream = _capture(orchestrator._bus)
            orchestrator.boot(resolved)
            import gc

            gc.disable()
            try:
                orchestrator.run_backtest()
            finally:
                gc.enable()
    finally:
        AlphaLoader.load = original_load  # type: ignore[method-assign]
    return _records_from(stream)


_TAPES: dict[tuple[tuple[int, int, str, str, str, int, int], ...], list[NBBOQuote]] = {}
_FACTORIES: dict[str, Callable[..., object]] = {}
_RAILS: dict[str, Callable[..., object]] = {}
_VARIANTS: dict[str, dict[str, object] | None] = {}


def _factory_key(factory: Callable[..., object] | None) -> str:
    if factory is None:
        return ""
    key = repr(factory)
    _FACTORIES[key] = factory
    return key


def _rail_key(wrapper: Callable[..., object] | None) -> str:
    if wrapper is None:
        return ""
    key = repr(wrapper)
    _RAILS[key] = wrapper
    return key


@functools.lru_cache(maxsize=None)
def _cached_synthetic(
    tape_key: tuple[tuple[int, int, str, str, str, int, int], ...],
    symbols: tuple[str, ...],
    factory_key: str,
    rail_key: str,
    attach_sink: bool,
    clock_tag: str,
    variant_key: str,
) -> Records:
    del clock_tag
    return _execute_synthetic(
        _TAPES[tape_key],
        symbols,
        _FACTORIES.get(factory_key),
        _RAILS.get(rail_key),
        attach_sink,
        _VARIANTS.get(variant_key),
    )


def run_synthetic(
    tape: Sequence[NBBOQuote],
    *,
    symbols: Sequence[str],
    engine_factory: Callable[..., object] | None = None,
    rail_wrapper: Callable[..., object] | None = None,
    attach_sink: bool = True,
    variant: dict[str, object] | None = None,
) -> Records:
    tape_key = tuple(
        (
            quote.sequence,
            quote.timestamp_ns,
            quote.symbol,
            str(quote.bid),
            str(quote.ask),
            quote.bid_size,
            quote.ask_size,
        )
        for quote in tape
    )
    _TAPES.setdefault(tape_key, list(tape))
    variant_key = "" if variant is None else json.dumps(variant, sort_keys=True, default=str)
    _VARIANTS[variant_key] = variant
    return _cached_synthetic(
        tape_key,
        tuple(symbols),
        _factory_key(engine_factory),
        _rail_key(rail_wrapper),
        attach_sink,
        _clock_tag(),
        variant_key,
    )


def _missing_cache(exc: Exception) -> None:
    import pytest

    hint = f"Disk cache miss for APP/2026-03-26 ({exc})"
    if os.environ.get("FEELIES_REQUIRE_BASELINE_CACHE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        pytest.fail(
            f"FEELIES_REQUIRE_BASELINE_CACHE is set, so the real session must run.\n{hint}"
        )
    pytest.skip(hint)


def _load_runner():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_position_scenarios_runner",
        Path("scripts/run_backtest.py").resolve(),
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_position_scenarios_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


@functools.lru_cache(maxsize=1)
def _real_bundle() -> tuple[tuple[Event, ...], tuple[object, ...]]:
    from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache

    try:
        event_log, ingest, day_meta = load_event_log_from_disk_cache(
            ["APP"], "2026-03-26", "2026-03-26"
        )
    except CacheReplayError as exc:
        _missing_cache(exc)
        raise
    return tuple(event_log.replay()), (ingest, tuple(day_meta))


@functools.lru_cache(maxsize=1)
def rth_replay() -> tuple[Event, ...]:
    """RTH events of the APP fixture session, in replay order."""
    events, _meta = _real_bundle()
    log = InMemoryEventLog()
    log.append_batch(list(events))
    from feelies.harness.backtest_prep import prepare_backtest_event_log

    config = PlatformConfig.from_yaml(_APP_CONFIG)
    prep = prepare_backtest_event_log(config, log)
    return tuple(prep.event_log.replay())


def _execute_real(
    end_index: int | None,
    engine_factory: Callable[..., object] | None,
    attach_sink: bool,
    digest_only: bool,
) -> Records:
    import argparse

    _raw, (ingest, day_meta) = _real_bundle()
    events: tuple[Event, ...] | list[Event] = rth_replay()
    if end_index is not None:
        events = events[: end_index + 1]
    log = InMemoryEventLog()
    log.append_batch(list(events))
    runner = _load_runner()
    from feelies.harness.backtest_prep import prepare_backtest_event_log

    config = PlatformConfig.from_yaml(_APP_CONFIG)
    symbols = sorted(config.symbols)
    day_sources = [
        runner.DaySource(
            symbol=meta.symbol,
            date=meta.date,
            source=meta.source,
            event_count=meta.event_count,
            ingestion_health=meta.ingestion_health,
        )
        for meta in day_meta
    ]
    prep = prepare_backtest_event_log(config, log)
    rc = runner._enforce_ingest_event_mix(
        config,
        prep.event_log,
        source_label="position battery",
        n_quotes=prep.n_quotes,
        n_trades=prep.n_trades,
    )
    if rc != 0:
        raise RuntimeError(f"ingest event mix rejected the real session ({rc})")
    config = runner._attach_day_source_provenance(config, symbols, day_sources)
    held: dict[str, object] = {}

    def factory(config: PlatformConfig, event_log: InMemoryEventLog, **kwargs: object):
        orchestrator, resolved = build_platform(config, event_log=event_log, **kwargs)  # type: ignore[arg-type]
        held["stream"] = _capture(orchestrator._bus)
        return orchestrator, resolved

    args = argparse.Namespace(
        trace_signal_orders=False,
        emit_fills_jsonl=False,
        emit_sensor_readings_jsonl=False,
        emit_horizon_ticks_jsonl=False,
        emit_snapshots_jsonl=False,
        emit_signals_jsonl=False,
        emit_hazard_spikes_jsonl=False,
        emit_cross_sectional_jsonl=False,
        emit_sized_intents_jsonl=False,
        emit_hazard_exits_jsonl=False,
    )
    with _seams(engine_factory, None, attach_sink):
        outcome = runner._run_backtest_phases_2_7(
            args,
            log,
            ingest,
            day_sources,
            config,
            symbols,
            "APP",
            "2026-03-26",
            time.monotonic(),
            platform_factory=factory,
            prep=prep,
        )
    if outcome.exit_code != 0:
        raise RuntimeError(f"real session exit {outcome.exit_code}")
    return _records_from(held["stream"], digest_only=digest_only)  # type: ignore[arg-type]


@functools.lru_cache(maxsize=None)
def _cached_real(
    end_index: int | None,
    factory_key: str,
    attach_sink: bool,
    clock_tag: str,
    digest_only: bool,
) -> Records:
    del clock_tag
    return _execute_real(end_index, _FACTORIES.get(factory_key), attach_sink, digest_only)


def run_real(
    *,
    end_index: int | None = None,
    engine_factory: Callable[..., object] | None = None,
    attach_sink: bool = True,
    digest_only: bool = False,
) -> Records:
    return _cached_real(
        end_index,
        _factory_key(engine_factory),
        attach_sink,
        _clock_tag(),
        digest_only,
    )


def format_line(row: Record) -> str:
    return f"{row.attributed_quote_sequence}\t{row.type_name}\t{row.canonical}"


def _dump_widened(path: str, rows: Sequence[Widened]) -> None:
    with open(path, "wb") as handle:
        handle.write(len(rows).to_bytes(4, "little"))
        for row in rows:
            name = row.type_name.encode()
            cursor = -1 if row.cursor is None else row.cursor
            handle.write(cursor.to_bytes(8, "little", signed=True))
            handle.write(len(name).to_bytes(2, "little"))
            handle.write(name)
            handle.write(row.digest)


def _load_widened(path: str) -> tuple[Widened, ...]:
    with open(path, "rb") as handle:
        (count,) = struct.unpack("<I", handle.read(4))
        rows: list[Widened] = []
        for _ in range(count):
            (cursor,) = struct.unpack("<q", handle.read(8))
            (name_len,) = struct.unpack("<H", handle.read(2))
            type_name = handle.read(name_len).decode()
            digest = handle.read(32)
            rows.append(Widened(None if cursor < 0 else cursor, type_name, digest))
    return tuple(rows)


def run_real_prefixes(cuts: Sequence[int]) -> tuple[tuple[Widened, ...], ...]:
    """Replay each decision-point prefix in its own process."""
    import subprocess
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="p13-prefix-"))
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    procs: list[tuple[int, subprocess.Popen[bytes], str]] = []
    for cut in cuts:
        err_path = str(tmp / f"{cut}.err")
        err = open(err_path, "wb")
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.position_engine.scenarios",
                "prefix",
                str(cut),
                str(tmp / f"{cut}.bin"),
            ],
            cwd=Path.cwd(),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=err,
        )
        procs.append((cut, proc, err_path))
        err.close()
    try:
        finished = [(cut, proc.wait(timeout=180), err_path) for cut, proc, err_path in procs]
        for cut, return_code, err_path in finished:
            if return_code != 0:
                detail = Path(err_path).read_text(encoding="utf-8", errors="replace")[-2000:]
                raise AssertionError(f"prefix {cut} exited {return_code}\n{detail}")
        return tuple(_load_widened(str(tmp / f"{cut}.bin")) for cut in cuts)
    finally:
        for path in tmp.iterdir():
            path.unlink(missing_ok=True)
        tmp.rmdir()


def _scenario(name: str) -> Records:
    if name == "syn_m1":
        tape = make_tape(seed=11, n=36000, symbol="SYN", start_ns=T0, size=1000)
        return run_synthetic(tape, symbols=("SYN",))
    if name == "real_m1":
        return run_real()
    raise SystemExit(f"unknown scenario {name}")


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    if len(args) == 4 and args[1] == "prefix":
        rows = run_real(end_index=int(args[2]), digest_only=True).widened
        _dump_widened(args[3], rows)
        return 0
    if len(args) != 2:
        raise SystemExit(
            "usage: python -m tests.position_engine.scenarios <syn_m1|real_m1|prefix>"
        )
    for row in _scenario(args[1]):
        print(format_line(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
