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
import re
import struct
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from decimal import Decimal
from enum import Enum
from fractions import Fraction
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
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    SlicePositionUpdate,
    RegimeState,
    SensorReading,
    PositionClosed,
    RiskAction,
    RiskVerdict,
    PositionSnapshot,
    StateTransition,
    Trade,
)
from feelies.core.platform_config import (
    DEFAULT_MARKET_DATA_LATENCY_NS,
    OperatingMode,
    PlatformConfig,
)
from feelies.core.quote_quality import QuoteQuality, classify
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
    attributed_quote_sequence: int | str | None
    type_name: str
    canonical: str
    replay_index: int | None = None
    bus_ordinal: int = -1


class Widened(NamedTuple):
    """One kept bus event, reduced to a replay-index cursor and a sha256 digest."""

    cursor: int | str | None
    type_name: str
    digest: bytes
    replay_index: int | None = None


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
        order_acks: Sequence[OrderAck] = (),
        slice_updates: Sequence[SlicePositionUpdate] = (),
        ack_ordinals: Sequence[int] = (),
        slice_ordinals: Sequence[int] = (),
        ack_pricing: Sequence[int | None] = (),
    ) -> None:
        super().__init__(rows)
        self.quotes = quotes
        self.order_requests = tuple(order_requests)
        self.risk_verdicts = tuple(risk_verdicts)
        self.order_acks = tuple(order_acks)
        self.slice_updates = tuple(slice_updates)
        self.ack_ordinals = tuple(ack_ordinals)
        self.slice_ordinals = tuple(slice_ordinals)
        self.ack_pricing = tuple(ack_pricing)
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


def _ack_name(status: object) -> str:
    text = str(status)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _opening_fill(fill_quantity: int, quantity: int) -> bool:
    """A slice fill that opened the slice from flat."""
    return fill_quantity != 0 and quantity == fill_quantity


def entry_fill_count(records: Records) -> int:
    """Opening fills from slice updates, else FILLED acks. Engine-independent."""
    updates = list(records.slice_updates)
    saw_slice = bool(updates)
    openings = sum(
        1 for update in updates if _opening_fill(int(update.fill_quantity), int(update.quantity))
    )
    for row in records:
        if row.type_name != "SlicePositionUpdate":
            continue
        saw_slice = True
        body = _body(row.canonical)
        if _opening_fill(int(body.get("fill_quantity") or 0), int(body.get("quantity") or 0)):
            openings += 1
    if saw_slice:
        return openings
    filled = sum(1 for ack in records.order_acks if ack.status is OrderAckStatus.FILLED)
    for row in records:
        if row.type_name != "OrderAck":
            continue
        body = _body(row.canonical)
        if _ack_name(body.get("status")) == "FILLED":
            filled += 1
    return filled


def require_entry_fills(records: Records) -> int:
    """PRECONDITION: the run contains at least one entry fill (D-107)."""
    count = entry_fill_count(records)
    if count < 1:
        raise AssertionError(f"PRECONDITION: run has ≥1 entry fill ({count})")
    return count


def require_run_quotes(records: Records) -> int:
    """PRECONDITION for a rail clause that does not need a cell."""
    count = len(records.quotes)
    if count < 1:
        raise AssertionError(f"PRECONDITION: run quotes present ({count})")
    return count


def require_quote_present(records: Records, sequence: int) -> None:
    """PRECONDITION: the injected quote is on the run, independent of the engine."""
    if sequence not in records.quotes:
        raise AssertionError(f"PRECONDITION: injected quote {sequence} present (0)")


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


def _skip_stale_end(body: Mapping[str, object]) -> bool:
    """N7: an end-of-tape close with no usable exit-side value is not priced."""
    return (
        body.get("exit_reason") == "END_OF_TAPE"
        and body.get("proposed_price_cents") is None
        and body.get("closed_on_stale_data") is True
    )


def check_m11_moves(snapshot: Mapping[str, object]) -> None:
    """Recompute the three moves from the snapshot's own marks (B5)."""
    rail = snapshot.get("rail")
    if not isinstance(rail, dict):
        raise AssertionError("M11: snapshot rail is not an object")
    sign = _sign(str(snapshot["side"]))
    size = int(snapshot["size"])  # type: ignore[arg-type]
    entry = int(snapshot["entry_cost_cents"])  # type: ignore[arg-type]
    pairs = (
        ("move_now_cents", "valuation_mark_cents"),
        ("move_worst_cents", "worst_side_mark_cents"),
        ("move_forced_cents", "forced_exit_mark_cents"),
    )
    for move_name, mark_name in pairs:
        mark = rail.get(mark_name)
        got = snapshot.get(move_name)
        if mark is None:
            if got is not None:
                raise AssertionError(f"M11: {move_name} is set while {mark_name} is None")
            continue
        expected = sign * (int(mark) * size - entry)
        if got != expected:
            raise AssertionError(f"M11: {move_name} {got} != recomputed {expected}")


def _m11_clean(snapshot: Mapping[str, object]) -> bool:
    rail = snapshot.get("rail")
    return (
        isinstance(rail, dict)
        and rail.get("valuation_side_absent") is False
        and snapshot.get("crossed") is False
        and snapshot.get("feed_gap_before") is False
    )


def check_m11_extremes(snapshots: Sequence[Mapping[str, object]]) -> None:
    """Extremes seed on the first CLEAN move and never at zero (B6, G4)."""
    seeded = False
    best: int | None = None
    worst: int | None = None
    best_clean: int | None = None
    for snapshot in snapshots:
        move = snapshot.get("move_now_cents")
        if not seeded:
            if not _m11_clean(snapshot):
                for key in ("best", "worst", "best_clean"):
                    if snapshot.get(key) is not None:
                        raise AssertionError(f"M11: {key} set before the first CLEAN reading")
                continue
            if move is None:
                raise AssertionError("M11: CLEAN reading has no move_now_cents")
            if int(move) == 0:
                unset = all(snapshot.get(key) is None for key in ("best", "worst", "best_clean"))
                if unset:
                    continue
                raise AssertionError("M11: extreme seeded at zero")
            for key in ("best", "worst", "best_clean"):
                extreme = snapshot.get(key)
                if not isinstance(extreme, dict) or int(extreme.get("cents", 0)) == 0:
                    raise AssertionError("M11: extreme seeded at zero")
                if int(extreme["cents"]) != int(move):
                    raise AssertionError(f"M11: {key} seed {extreme['cents']} != move {move}")
            seeded = True
            best = worst = best_clean = int(move)
            continue
        if best is None or worst is None or best_clean is None:
            raise AssertionError("M11: move_now_cents missing after seed")
        if move is None:
            for key, expected in (("best", best), ("worst", worst), ("best_clean", best_clean)):
                extreme = snapshot.get(key)
                got = extreme.get("cents") if isinstance(extreme, dict) else None
                if got != expected:
                    raise AssertionError("M11: move_now_cents missing after seed")
            continue
        move_i = int(move)
        best = move_i if move_i > best else best
        worst = move_i if move_i < worst else worst
        if _m11_clean(snapshot):
            best_clean = move_i if move_i > best_clean else best_clean
        for key, expected in (("best", best), ("worst", worst), ("best_clean", best_clean)):
            extreme = snapshot.get(key)
            got = extreme.get("cents") if isinstance(extreme, dict) else None
            if got != expected:
                raise AssertionError(f"M11: {key} {got} != recomputed {expected}")


def _last_usable_snapshot_mark(snapshots: Sequence[Mapping[str, object]]) -> int | None:
    """Executable exit side of the last usable snapshot rail (D-84)."""
    found: int | None = None
    for snapshot in snapshots:
        rail = snapshot.get("rail")
        if not isinstance(rail, dict) or rail.get("valuation_side_absent") is True:
            continue
        mark = rail.get("valuation_mark_cents")
        if mark is None:
            continue
        found = int(mark)
    return found


def _path_rail_sequence(closed: Mapping[str, object]) -> int | None:
    """Rail sequence carried on a triggered path, if the close recorded one.

    contracts.md §2:294-295. Every path on the close triggered on the deciding
    event. Prefer the path named by ``exit_reason``.
    """
    paths = closed.get("triggered_paths")
    if not isinstance(paths, list):
        return None
    reason = str(closed.get("exit_reason"))
    fallback: int | None = None
    for path in paths:
        if not isinstance(path, dict) or not isinstance(path.get("rail_sequence"), int):
            continue
        sequence = int(path["rail_sequence"])
        if str(path.get("path")) == reason:
            return sequence
        if fallback is None:
            fallback = sequence
    return fallback


def _first_triggering_gate(
    closed: Mapping[str, object],
    decisions: Sequence[Mapping[str, object]] | None,
) -> int | None:
    """First triggering gate outcome that is not ESCALATION_NOOP.

    contracts.md §2:287 and §2:294-295. A re-emission does not move the
    deciding event, and a later gate outcome while EXITING is ESCALATION_NOOP.
    HORIZON and INVALIDATION are resolve predicates (§2:259-263), not gate
    fires; their deciding rail is the last outcome that is not ESCALATION_NOOP.
    """
    if not decisions:
        return None
    cell = str(closed["cell_id"])
    reason = str(closed.get("exit_reason"))
    wanted = _EXIT_GATE.get(reason)
    first_fire: int | None = None
    last_live: int | None = None
    for body in decisions:
        if str(body.get("cell_id")) != cell:
            continue
        sequence = body.get("rail_sequence")
        if not isinstance(sequence, int):
            continue
        outcome = str(body.get("outcome"))
        if outcome != "ESCALATION_NOOP":
            last_live = sequence
        if outcome != "fire":
            continue
        if wanted in ("ADVERSE", "FAVORABLE") and str(body.get("gate")) != wanted:
            continue
        if first_fire is None:
            first_fire = sequence
    if first_fire is not None:
        return first_fire
    if reason in ("HORIZON", "INVALIDATION"):
        return last_live
    return None


def _triggered_prices(closed: Mapping[str, object]) -> list[int]:
    paths = closed.get("triggered_paths")
    if not isinstance(paths, list):
        return []
    prices: list[int] = []
    for path in paths:
        if isinstance(path, dict) and isinstance(path.get("proposed_price_cents"), int):
            prices.append(int(path["proposed_price_cents"]))
    return prices


def check_m11_proposed(
    closed: Mapping[str, object],
    snapshots: Sequence[Mapping[str, object]],
    quotes: Mapping[int, NBBOQuote],
    decisions: Sequence[Mapping[str, object]] | None = None,
) -> None:
    """Proposed price is the executable side of the deciding quote (B3).

    The deciding rail is the event on which ``exit_reason`` first triggered
    (contracts.md §2:269-279, §2:287, §2:294-295), not the last snapshot.
    END_OF_TAPE keeps the last usable rail mark (G9, N7).
    """
    if _skip_stale_end(closed):
        return
    if str(closed.get("exit_reason")) == "END_OF_TAPE":
        expected = _last_usable_snapshot_mark(snapshots)
        got = closed.get("proposed_price_cents")
        if got != expected:
            raise AssertionError(f"M11: proposed {got} != last usable executable {expected}")
        return
    sequence = _path_rail_sequence(closed)
    if sequence is None:
        sequence = _first_triggering_gate(closed, decisions)
    if sequence is None:
        if not snapshots:
            raise AssertionError("M11: no snapshot for the deciding quote")
        sequence = int(snapshots[-1]["rail_sequence"])  # type: ignore[arg-type]
    quote = quotes.get(sequence)
    if quote is None:
        raise AssertionError(f"M11: deciding quote {sequence} is not on the tape")
    side = str(closed["side"])
    prices = _triggered_prices(closed)
    if len(prices) > 1:
        executable = min(prices) if side == "LONG" else max(prices)
    else:
        executable = _cents(quote.bid if side == "LONG" else quote.ask)
    got = closed.get("proposed_price_cents")
    if got != executable:
        raise AssertionError(f"M11: proposed {got} != executable {executable} of quote {sequence}")


def rebuild_gross(body: Mapping[str, object]) -> int:
    """Gross from the legs alone. Independent of ``cell_economics``."""
    sign = _sign(str(body["side"]))
    entries = body["entry_fills"]
    exits = body["exit_fills"]
    if not isinstance(entries, list) or not isinstance(exits, list):
        raise AssertionError("M11: fills are not lists")
    return sign * (
        sum(int(fill["price_cents"]) * int(fill["quantity"]) for fill in exits)
        - sum(int(fill["price_cents"]) * int(fill["quantity"]) for fill in entries)
    )


def check_m11_gross(row: Record, quotes: dict[int, NBBOQuote]) -> None:
    """The leg rebuild and ``cell_economics`` are two computations and must agree."""
    body = _body(row.canonical)
    if _skip_stale_end(body):
        return
    exits = body.get("exit_fills")
    if str(body.get("exit_reason")) == "END_OF_TAPE" and (
        not isinstance(exits, list) or not exits
    ):
        return
    rebuilt = rebuild_gross(body)
    result, _displacement, _cost = cell_economics(row, quotes)
    if rebuilt != result:
        raise AssertionError(f"M11: gross {rebuilt} != cell_economics {result}")


def audit_m11(records: Records) -> int:
    """Rebuild moves, extremes, proposed price and gross. Returns the N7 skip count."""
    snapshots: dict[str, list[dict[str, object]]] = {}
    closed: list[tuple[Record, dict[str, object]]] = []
    for row in records:
        if row.type_name == "PositionSnapshot":
            body = _body(row.canonical)
            check_m11_moves(body)
            snapshots.setdefault(str(body["cell_id"]), []).append(body)
        elif row.type_name == "PositionClosed":
            closed.append((row, _body(row.canonical)))
    decisions = _gate_bodies(records)
    skipped = 0
    for row, body in closed:
        snaps = snapshots.get(str(body["cell_id"]), [])
        check_m11_extremes(snaps)
        if _skip_stale_end(body):
            skipped += 1
            continue
        check_m11_proposed(body, snaps, records.quotes, decisions)
        check_m11_gross(row, records.quotes)
    return skipped


def displacement_identity(records: Records) -> None:
    for row in records:
        if row.type_name != "PositionClosed":
            continue
        if str(_body(row.canonical).get("exit_reason")) == "END_OF_TAPE":
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


_EXIT_ORDER = re.compile(r"\|EXIT\|\d+$")


def _filled_acks(records: Records) -> list[tuple[int, str, int, str]]:
    """FILLED acks as (bus ordinal, order_id, timestamp_ns, symbol)."""
    found: list[tuple[int, str, int, str]] = []
    for index, ack in enumerate(records.order_acks):
        if _ack_name(ack.status) != "FILLED":
            continue
        ordinal = records.ack_ordinals[index] if index < len(records.ack_ordinals) else -1
        found.append((ordinal, str(ack.order_id), int(ack.timestamp_ns), str(ack.symbol)))
    for row in records:
        if row.type_name != "OrderAck":
            continue
        body = _body(row.canonical)
        if _ack_name(body.get("status")) != "FILLED":
            continue
        found.append(
            (
                row.bus_ordinal,
                str(body.get("order_id", "")),
                int(body["timestamp_ns"]),
                str(body.get("symbol", "")),
            )
        )
    return found


def _slice_marks(records: Records) -> list[tuple[int, str, str, str, int]]:
    """Slice updates as (ordinal, symbol, strategy_id, order_id, fill_timestamp_ns)."""
    found: list[tuple[int, str, str, str, int]] = []
    for index, update in enumerate(records.slice_updates):
        ordinal = records.slice_ordinals[index] if index < len(records.slice_ordinals) else -1
        found.append(
            (
                ordinal,
                str(update.symbol),
                str(update.strategy_id),
                str(update.order_id),
                int(update.fill_timestamp_ns),
            )
        )
    for row in records:
        if row.type_name != "SlicePositionUpdate":
            continue
        body = _body(row.canonical)
        found.append(
            (
                row.bus_ordinal,
                str(body.get("symbol", "")),
                str(body.get("strategy_id", "")),
                str(body.get("order_id", "")),
                int(body["fill_timestamp_ns"]),
            )
        )
    return found


def _rejected_ack_ordinals(records: Records) -> dict[str, int]:
    """order_id -> bus ordinal of a REJECTED ack, from the stream or record rows."""
    found: dict[str, int] = {}
    for index, ack in enumerate(records.order_acks):
        if _ack_name(ack.status) != "REJECTED":
            continue
        ordinal = records.ack_ordinals[index] if index < len(records.ack_ordinals) else -1
        found[str(ack.order_id)] = ordinal
    for row in records:
        if row.type_name != "OrderAck":
            continue
        body = _body(row.canonical)
        if _ack_name(body.get("status")) != "REJECTED":
            continue
        found[str(body.get("order_id"))] = row.bus_ordinal
    return found


def _entry_ack_ordinal(
    records: Records,
    *,
    symbol: str,
    strategy_id: str,
    entry_stamps: set[int],
) -> int | None:
    """First FILLED ack of an entry leg. Slice identity, else same stamp and symbol."""
    entry_ids = {
        order_id
        for _ordinal, sym, strat, order_id, fill_ts in _slice_marks(records)
        if sym == symbol
        and strat == strategy_id
        and fill_ts in entry_stamps
        and _EXIT_ORDER.search(order_id) is None
    }
    filled = _filled_acks(records)
    ordinals = [ordinal for ordinal, order_id, _ts, _sym in filled if order_id in entry_ids]
    if not ordinals:
        ordinals = [
            ordinal
            for ordinal, order_id, ts, sym in filled
            if sym == symbol and ts in entry_stamps and _EXIT_ORDER.search(order_id) is None
        ]
    if not ordinals:
        return None
    return min(ordinals)


def _giveback_ticks(multiple: float, spread: int) -> int:
    """contracts.md §9. Integer floor; at least 1. Tape-side, not engine output."""
    ratio = Fraction(repr(multiple))
    floored = (ratio.numerator * spread) // ratio.denominator
    if floored < 1:
        return 1
    return floored


def first_horizon_index(tape: Sequence[NBBOQuote], birth_index: int, horizon_ns: int) -> int:
    """First quote at or after birth exchange + market-data latency + T (§2:260)."""
    deadline = (
        tape[birth_index].exchange_timestamp_ns + DEFAULT_MARKET_DATA_LATENCY_NS + horizon_ns
    )
    for index, quote in enumerate(tape):
        if quote.exchange_timestamp_ns >= deadline:
            return index
    raise AssertionError("PRECONDITION: horizon deadline is off the tape")


def require_favorable_tie(
    tape: Sequence[NBBOQuote],
    *,
    higher: str,
    birth_index: int,
    target_ticks: int,
    adverse_ticks: int,
    horizon_ns: int,
    form: str,
    giveback_multiple: float | None,
    spread_ticks: int,
    fee_ticks: int,
    quiet_limit_ns: int,
    resolution_index: int | None = None,
) -> int:
    """PRECONDITION: FAVORABLE and ``higher`` hold on the same first quote.

    The walk uses the tape and the policy parameters only (contracts §2:265–274).
    The horizon quote is the first whose exchange time is at or after the birth
    quote's exchange time, plus the declared market-data latency, plus
    ``horizon_ns`` (§2:260). Invalidation is the rail after the opposing signal.
    """
    if higher not in ("ADVERSE", "HORIZON", "INVALIDATION"):
        raise AssertionError(f"PRECONDITION: unknown higher path {higher}")
    birth = tape[birth_index]
    entry = _cents(birth.ask)
    deadline = birth.exchange_timestamp_ns + DEFAULT_MARKET_DATA_LATENCY_NS + horizon_ns
    best: int | None = None
    giveback_ticks = 0
    if form == "trailing":
        if giveback_multiple is None:
            raise AssertionError("PRECONDITION: trailing form has no giveback")
        giveback_ticks = _giveback_ticks(giveback_multiple, spread_ticks)
    round_trip = spread_ticks + fee_ticks
    for index in range(birth_index + 1, len(tape)):
        quote = tape[index]
        valid = (
            classify(quote.bid, quote.ask, quote.bid_size, quote.ask_size) is QuoteQuality.VALID
        )
        gap = quote.exchange_timestamp_ns - tape[index - 1].exchange_timestamp_ns
        clean = valid and gap <= quiet_limit_ns
        move = _cents(quote.bid) - entry
        if clean and move != 0 and (best is None or move > best):
            best = move
        if form == "trailing":
            armed = best is not None and best > (giveback_ticks + round_trip)
            favorable = clean and armed and best is not None and move <= best - giveback_ticks
        else:
            favorable = clean and move >= target_ticks
        if not favorable:
            continue
        if higher == "ADVERSE":
            also = valid and move <= -adverse_ticks
        elif higher == "HORIZON":
            also = quote.exchange_timestamp_ns >= deadline
        else:
            also = index == resolution_index
        if not also:
            raise AssertionError(
                f"PRECONDITION: FAVORABLE at quote {quote.sequence} does not also "
                f"hold {higher} (contracts §2:265-274)"
            )
        return index
    raise AssertionError(
        f"PRECONDITION: no quote holds FAVORABLE and {higher} (contracts §2:265-274)"
    )


def assert_triggered_tie(records: Records, higher: str) -> None:
    """The close's reason is the higher path, and both paths are on the record."""
    found = False
    for row in records:
        if row.type_name != "PositionClosed":
            continue
        body = _body(row.canonical)
        paths = body.get("triggered_paths")
        if not isinstance(paths, list):
            continue
        names = [str(path["path"]) for path in paths if isinstance(path, dict)]
        if "FAVORABLE" not in names or higher not in names:
            continue
        found = True
        ranked = [name for name in _EXIT_RANK if name in names]
        expected = ranked[0]
        got = str(body.get("exit_reason"))
        if got != expected:
            raise AssertionError(
                f"M5: exit reason {got} != {expected} cell {body.get('cell_id')} paths {names}"
            )
    if not found:
        raise AssertionError(f"M5: no close carries FAVORABLE and {higher}")


def require_barrier_differs(
    tape: Sequence[NBBOQuote],
    *,
    birth_index: int,
    landing_index: int,
    centre: int,
    band: int,
    strategy_id: str = "sig_position_fixture_v1",
) -> None:
    """PRECONDITION: the adverse barrier is not the executable side of q_g+1."""
    birth = tape[birth_index]
    landing = tape[landing_index]
    cell = f"{birth.symbol}|{strategy_id}|{birth.sequence}|LONG"
    level = drawn_adverse_level(cell, centre, band)
    barrier = _cents(birth.bid) - level
    executable = _cents(landing.bid)
    if barrier == executable:
        raise AssertionError(
            f"PRECONDITION: barrier {barrier} equals executable {executable} "
            f"of quote {landing.sequence}"
        )


def exit_reason_at_collision(records: Records) -> None:
    requirements = [row for row in records if row.type_name == "DeRiskRequirement"]
    for row in records:
        if row.type_name != "PositionClosed":
            continue
        body = _body(row.canonical)
        cell = str(body["cell_id"])
        if str(body.get("exit_reason")) == "END_OF_TAPE":
            continue
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
        symbol = str(body["symbol"])
        strategy_id = str(body["strategy_id"])
        entry_stamps = {int(leg["timestamp_ns"]) for leg in entries if isinstance(leg, dict)}
        entry_ord = _entry_ack_ordinal(
            records, symbol=symbol, strategy_id=strategy_id, entry_stamps=entry_stamps
        )
        exit_re = re.compile(rf"^{re.escape(cell)}\|EXIT\|\d+$")
        exit_ords = [
            ordinal
            for ordinal, order_id, _ts, _sym in _filled_acks(records)
            if exit_re.fullmatch(order_id)
        ]
        exit_ord = min(exit_ords) if exit_ords else None
        window: list[tuple[int, str]] = []
        joined: list[tuple[int, str]] = []
        for req in requirements:
            req_body = _body(req.canonical)
            if req_body.get("symbol") != symbol or req_body.get("strategy_id") != strategy_id:
                continue
            order_id = str(req_body.get("order_id", ""))
            in_window = (
                entry_ord is not None
                and exit_ord is not None
                and entry_ord < req.bus_ordinal <= exit_ord
            )
            if in_window:
                window.append((req.bus_ordinal, order_id))
            if exit_re.fullmatch(order_id):
                joined.append((req.bus_ordinal, order_id))
        if {order_id for _ordinal, order_id in window} != {
            order_id for _ordinal, order_id in joined
        }:
            raise AssertionError(f"M5: window/id mismatch cell {cell}")
        matched = sorted(window)
        if not matched:
            raise AssertionError(f"requirement count 0 != 1 cell {cell}")
        rejected = _rejected_ack_ordinals(records)
        live_ord, live_id = matched[0]
        for ordinal, order_id in matched[1:]:
            ack_ord = rejected.get(live_id)
            if ack_ord is None or not (live_ord < ack_ord <= ordinal):
                raise AssertionError(
                    f"requirement re-emitted without REJECTED cell {cell} order {order_id}"
                )
            live_ord, live_id = ordinal, order_id


_SUPPRESSION = frozenset(
    {
        "VALUATION_SIDE_ABSENT",
        "CROSSED",
        "FEED_GAP",
        "DWELL_NOT_CLEAN",
        "NOT_WARMED_UP",
        "SYMBOL_QUIET",
    }
)
_EXIT_GATE = {
    "ADVERSE": "ADVERSE",
    "FAVORABLE": "FAVORABLE",
    "HORIZON": "HORIZON",
    "INVALIDATION": "INVALIDATION",
}


class CellSpan(NamedTuple):
    """One cell life, as inclusive replay indices."""

    cell_id: str
    birth_index: int
    exit_index: int


def placement_rule(
    cells: Sequence[CellSpan],
    exit_decisions: Sequence[int],
    *,
    limit: int = 5,
) -> tuple[tuple[str, int], ...]:
    """Rule P. First eligible index at or after each life's midpoint, then sha256 rank.

    An index is eligible when it lies inside the inclusive span and neither it nor
    the next index is an exit decision. Cells with no such index are dropped.
    """
    blocked = set(exit_decisions)
    chosen: list[tuple[str, int]] = []
    for cell in cells:
        if cell.exit_index < cell.birth_index:
            continue
        midpoint = cell.birth_index + (cell.exit_index - cell.birth_index) // 2
        event: int | None = None
        for index in range(midpoint, cell.exit_index + 1):
            if index in blocked or (index + 1) in blocked:
                continue
            event = index
            break
        if event is None:
            continue
        chosen.append((cell.cell_id, event))
    chosen.sort(key=lambda item: hashlib.sha256(item[0].encode("utf-8")).digest())
    return tuple(chosen[:limit])


def _gate_bodies(records: Sequence[Record]) -> list[dict[str, object]]:
    return [_body(row.canonical) for row in records if row.type_name == "GateDecision"]


def _closed_bodies(records: Sequence[Record]) -> list[dict[str, object]]:
    return [_body(row.canonical) for row in records if row.type_name == "PositionClosed"]


def _fires(records: Sequence[Record], cell: str, gate: str | None) -> list[int]:
    found: list[int] = []
    for body in _gate_bodies(records):
        if str(body.get("cell_id")) != cell:
            continue
        if str(body.get("outcome", "")).lower() != "fire":
            continue
        if gate is not None and str(body.get("gate")) != gate:
            continue
        found.append(int(body["rail_sequence"]))  # type: ignore[arg-type]
    return found


def _deciding_sequence(records: Sequence[Record], cell: str, gate: str | None) -> int | None:
    found = _fires(records, cell, gate)
    return found[-1] if found else None


def _is_blind(body: dict[str, object]) -> bool:
    if body.get("exited_on_unusable_data") is True:
        return True
    paths = body.get("triggered_paths")
    if not isinstance(paths, list):
        return False
    return any(isinstance(path, dict) and path.get("trigger") == "BLIND" for path in paths)


def _rail_body(records: Sequence[Record], sequence: int) -> dict[str, object] | None:
    for row in records:
        if row.type_name != "MarkRailUpdate":
            continue
        body = _body(row.canonical)
        if int(body["quote_sequence"]) == sequence:  # type: ignore[arg-type]
            return body
    return None


def _cell_born(records: Sequence[Record], birth_sequence: int) -> dict[str, object] | None:
    for body in _closed_bodies(records):
        entries = body.get("entry_fills")
        if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
            continue
        if int(entries[0]["sequence"]) == birth_sequence:
            return body
    return None


def _executable_exit_cents(quote: NBBOQuote, side: str) -> int:
    """Closing a long sells the bid. Closing a short buys the ask."""
    return _cents(quote.bid if side == "LONG" else quote.ask)


def _suppression_reason(
    rail: dict[str, object],
    orient: dict[str, object],
    quiet_limit_ns: int,
) -> str | None:
    if orient.get("valuation_side_absent") is not False:
        return "VALUATION_SIDE_ABSENT"
    if rail.get("crossed") is not False:
        return "CROSSED"
    if rail.get("feed_gap_before") is not False:
        return "FEED_GAP"
    if orient.get("dwell_window_clean") is not True:
        return "DWELL_NOT_CLEAN"
    if rail.get("warmed_up") is not True:
        return "NOT_WARMED_UP"
    quiet = rail.get("symbol_quiet_ns")
    if not isinstance(quiet, int) or quiet > quiet_limit_ns:
        return "SYMBOL_QUIET"
    return None


def check_a1(records: Records, *, quiet_limit_ns: int) -> None:
    """Every FAVORABLE exit is decided on an event with all six suppression reasons clear."""
    for body in _closed_bodies(records):
        if str(body.get("exit_reason")) != "FAVORABLE":
            continue
        cell = str(body["cell_id"])
        side = str(body["side"])
        decisions = _fires(records, cell, "FAVORABLE")
        if not decisions:
            raise AssertionError(f"A1: FAVORABLE cell {cell} has no deciding event")
        sequence = decisions[-1]
        rail = _rail_body(records, sequence)
        if rail is None:
            raise AssertionError(
                f"A1: FAVORABLE cell {cell} decided on {sequence} with no rail update"
            )
        orient = rail["long"] if side == "LONG" else rail["short"]
        if not isinstance(orient, dict):
            raise AssertionError(
                f"A1: FAVORABLE cell {cell} decided on {sequence} with no orientation"
            )
        reason = _suppression_reason(rail, orient, quiet_limit_ns)
        if reason is not None:
            raise AssertionError(f"A1: FAVORABLE cell {cell} decided on {sequence} with {reason}")


def _exit_tuples(records: Records) -> dict[str, tuple[str, int | None, int | None]]:
    tuples: dict[str, tuple[str, int | None, int]] = {}
    for body in _closed_bodies(records):
        cell = str(body["cell_id"])
        reason = str(body.get("exit_reason"))
        exits = body.get("exit_fills")
        if reason == "END_OF_TAPE" and (not isinstance(exits, list) or not exits):
            proposed = body.get("proposed_price_cents")
            price = None if proposed is None else int(proposed)
            tuples[cell] = (reason, None, price)
            continue
        if not isinstance(exits, list) or not exits or not isinstance(exits[0], dict):
            raise AssertionError(f"A2: cell {cell} has no exit fill")
        price = int(exits[0]["price_cents"])
        gate = _EXIT_GATE.get(reason)
        deciding = _deciding_sequence(records, cell, gate)
        tuples[cell] = (reason, deciding, price)
    return tuples


def _verdict_stream(records: Records) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            verdict.sequence,
            verdict.symbol,
            verdict.action.name,
            verdict.reason,
            verdict.scaling_factor,
        )
        for verdict in records.risk_verdicts
    )


def _alive_at_gap(body: dict[str, object], gaps: set[int]) -> bool:
    entries = body.get("entry_fills")
    exits = body.get("exit_fills")
    if str(body.get("exit_reason")) == "END_OF_TAPE" and (
        not isinstance(exits, list) or not exits
    ):
        if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
            return False
        entry = int(entries[0]["sequence"])
        return any(entry < gap for gap in gaps)
    if not isinstance(entries, list) or not isinstance(exits, list) or not entries or not exits:
        return False
    if not isinstance(entries[0], dict) or not isinstance(exits[0], dict):
        return False
    entry = int(entries[0]["sequence"])
    exit_seq = int(exits[0]["sequence"])
    return any(entry < gap < exit_seq for gap in gaps)


def _suppression_count(records: Sequence[Record]) -> int:
    count = 0
    for body in _gate_bodies(records):
        reason = str(body.get("reason") or "")
        outcome = str(body.get("outcome") or "").lower()
        if reason in _SUPPRESSION or outcome == "suppressed":
            count += 1
    return count


def check_a2(clean: Records, injected: Records, *, feed_gap_sequences: set[int]) -> None:
    """Ignorable injection: same exits, same risk verdicts, feed-gap flags, one suppression."""
    clean_tuples = _exit_tuples(clean)
    injected_tuples = _exit_tuples(injected)
    if clean_tuples != injected_tuples:
        raise AssertionError(f"A2: exit tuples {injected_tuples} != {clean_tuples}")
    if _verdict_stream(clean) != _verdict_stream(injected):
        raise AssertionError("A2: risk verdict streams differ")
    for body in _closed_bodies(injected):
        cell = str(body["cell_id"])
        alive = _alive_at_gap(body, feed_gap_sequences)
        flag = body.get("lived_through_feed_gap") is True
        if flag != alive:
            raise AssertionError(f"A2: lived_through_feed_gap {flag} != {alive} cell {cell}")
    if _suppression_count(injected) < 1:
        raise AssertionError("A2: no suppression record on the injected run")


def _last_usable_rail_mark(records: Records, side: str) -> int | None:
    """Executable exit side of the last usable MarkRailUpdate (D-109)."""
    key = "long" if side == "LONG" else "short"
    found: int | None = None
    for row in records:
        if row.type_name != "MarkRailUpdate":
            continue
        orient = _body(row.canonical).get(key)
        if not isinstance(orient, dict) or orient.get("valuation_side_absent") is True:
            continue
        mark = orient.get("valuation_mark_cents")
        if mark is None:
            continue
        found = int(mark)
    return found


_FILL_ACK = frozenset({"FILLED", "PARTIALLY_FILLED"})


class _FillAck(NamedTuple):
    ordinal: int
    price_cents: int
    pricing: int | None
    timestamp_ns: int


def _cents_exact(value: object) -> int:
    """§9:480-482. Same rule as reference ``whole_cents``: a fractional cent raises."""
    if isinstance(value, bool) or value is None:
        raise AssertionError(f"A3a: bad fill price {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = Decimal(value)
    if isinstance(value, Decimal):
        scaled = value * 100
        if scaled != scaled.to_integral_value():
            raise AssertionError(f"A3a: fractional cent {value}")
        return int(scaled)
    raise AssertionError(f"A3a: bad fill price {value!r}")


def _row_fill_cents(body: dict[str, object]) -> int | None:
    if "price_cents" in body:
        return _cents_exact(body["price_cents"])
    if body.get("fill_price") is None:
        return None
    return _cents_exact(body["fill_price"])


def _collect_fill_acks(
    records: Records,
    *,
    order_re: re.Pattern[str] | None,
    timestamps: set[int] | None,
) -> list[_FillAck]:
    """Fill-bearing acks in bus order. ``order_re`` selects |EXIT| attempts."""
    found: list[_FillAck] = []
    for index, ack in enumerate(records.order_acks):
        if _ack_name(ack.status) not in _FILL_ACK:
            continue
        order_id = str(ack.order_id)
        if order_re is not None and order_re.fullmatch(order_id) is None:
            continue
        if timestamps is not None and int(ack.timestamp_ns) not in timestamps:
            continue
        if ack.fill_price is None:
            continue
        ordinal = records.ack_ordinals[index] if index < len(records.ack_ordinals) else -1
        pricing = records.ack_pricing[index] if index < len(records.ack_pricing) else None
        found.append(
            _FillAck(ordinal, _cents_exact(ack.fill_price), pricing, int(ack.timestamp_ns))
        )
    for row in records:
        if row.type_name != "OrderAck":
            continue
        body = _body(row.canonical)
        if _ack_name(body.get("status")) not in _FILL_ACK:
            continue
        order_id = str(body.get("order_id", ""))
        if order_re is not None and order_re.fullmatch(order_id) is None:
            continue
        timestamp = int(body["timestamp_ns"]) if "timestamp_ns" in body else -1
        if timestamps is not None and timestamp not in timestamps:
            continue
        price = _row_fill_cents(body)
        if price is None:
            continue
        cursor = row.attributed_quote_sequence
        pricing = cursor if isinstance(cursor, int) else None
        found.append(_FillAck(row.bus_ordinal, price, pricing, timestamp))
    found.sort(key=lambda item: item.ordinal)
    return found


def _pair_exit_legs(
    legs: list[dict[str, object]],
    acks: list[_FillAck],
) -> list[tuple[dict[str, object], _FillAck]] | None:
    """Pair each close leg with the fill ack of that same fill."""
    if len(legs) != len(acks):
        return None
    if any("timestamp_ns" not in leg for leg in legs):
        return list(zip(legs, acks, strict=True))
    buckets: dict[int, list[_FillAck]] = {}
    for ack in acks:
        buckets.setdefault(ack.timestamp_ns, []).append(ack)
    paired: list[tuple[dict[str, object], _FillAck]] = []
    for leg in legs:
        bucket = buckets.get(int(leg["timestamp_ns"]))
        if not bucket:
            return None
        paired.append((leg, bucket.pop(0)))
    if any(buckets.values()):
        return None
    return paired


def _deciding_ordinal(records: Records, cell: str, gate: str | None) -> int | None:
    found: list[int] = []
    for row in records:
        if row.type_name != "GateDecision":
            continue
        body = _body(row.canonical)
        if str(body.get("cell_id")) != cell:
            continue
        if str(body.get("outcome", "")).lower() != "fire":
            continue
        if gate is not None and str(body.get("gate")) != gate:
            continue
        found.append(row.bus_ordinal)
    return found[-1] if found else None


def check_a3(records: Records) -> None:
    """EOT uses the last usable rail mark (D-109).

    Every other close: A3a, each exit-leg price equals the fill ack of that
    leg (§2:294-295; whole cents §9:480-482). A3b, the leg is published after
    the deciding gate and is no better than the executable side of the quote
    being processed when the fill is published. A3b assumes the current
    pricing model (R2): that quote, not the quote prevailing at arrival.
    """
    for body in _closed_bodies(records):
        cell = str(body["cell_id"])
        side = str(body["side"])
        if str(body.get("exit_reason")) == "END_OF_TAPE":
            if _skip_stale_end(body):
                continue
            expected = _last_usable_rail_mark(records, side)
            got = body.get("proposed_price_cents")
            if got != expected:
                raise AssertionError(
                    f"A3: cell {cell} proposed {got} != last usable executable {expected}"
                )
            continue
        exits = body.get("exit_fills")
        if not isinstance(exits, list) or not exits or not isinstance(exits[0], dict):
            raise AssertionError(f"A3: cell {cell} has no exit fill")
        legs = [leg for leg in exits if isinstance(leg, dict)]
        exit_re = re.compile(rf"^{re.escape(cell)}\|EXIT\|\d+$")
        acks = _collect_fill_acks(records, order_re=exit_re, timestamps=None)
        if not acks:
            stamps = {int(leg["timestamp_ns"]) for leg in legs if "timestamp_ns" in leg}
            if stamps:
                acks = _collect_fill_acks(records, order_re=None, timestamps=stamps)
        paired = _pair_exit_legs(legs, acks)
        if paired is None:
            raise AssertionError(
                f"A3a: cell {cell} exit legs {len(legs)} != fill acks {len(acks)}"
            )
        for leg, ack in paired:
            got = int(leg["price_cents"])
            if got != ack.price_cents:
                raise AssertionError(
                    f"A3a: cell {cell} exit price {got} != fill ack {ack.price_cents}"
                )
        gate = _EXIT_GATE.get(str(body.get("exit_reason")))
        decision = _deciding_ordinal(records, cell, gate) if gate is not None else None
        for leg, ack in paired:
            if decision is not None and ack.ordinal <= decision:
                raise AssertionError(
                    f"A3b: cell {cell} fill at {ack.ordinal} is not after decision {decision}"
                )
            if not isinstance(ack.pricing, int) or ack.pricing not in records.quotes:
                raise AssertionError(f"A3b: cell {cell} fill has no pricing quote")
            executable = _executable_exit_cents(records.quotes[ack.pricing], side)
            price = int(leg["price_cents"])
            better = price > executable if side == "LONG" else price < executable
            if better:
                raise AssertionError(
                    f"A3b: cell {cell} exit price {price} better than executable {executable}"
                )


def check_a4(records: Records, *, birth_sequence: int, centre: int, band: int) -> None:
    """Gap-through is ADVERSE, no better than q_g+1, and strictly past the barrier."""
    body = _cell_born(records, birth_sequence)
    if body is None:
        raise AssertionError(f"A4: no cell born at {birth_sequence}")
    cell = str(body["cell_id"])
    side = str(body["side"])
    reason = str(body.get("exit_reason"))
    if reason != "ADVERSE":
        raise AssertionError(f"A4: reason {reason} != ADVERSE cell {cell}")
    birth = records.quotes.get(birth_sequence)
    if birth is None:
        raise AssertionError(f"A4: birth sequence {birth_sequence} is not on the tape")
    level = drawn_adverse_level(cell, centre, band)
    valuation = _cents(birth.bid if side == "LONG" else birth.ask)
    barrier = valuation - level if side == "LONG" else valuation + level
    exits = body.get("exit_fills")
    if not isinstance(exits, list) or not exits or not isinstance(exits[0], dict):
        raise AssertionError(f"A4: cell {cell} has no exit fill")
    fill_seq = int(exits[0]["sequence"])
    price = int(exits[0]["price_cents"])
    fill = records.quotes.get(fill_seq)
    if fill is None:
        raise AssertionError(f"A4: q_g+1 sequence {fill_seq} is not on the tape")
    executable = _executable_exit_cents(fill, side)
    better = price > executable if side == "LONG" else price < executable
    if better:
        raise AssertionError(
            f"A4: exit price {price} better than executable {executable} of q_g+1 {fill_seq} cell {cell}"
        )
    worse = price < barrier if side == "LONG" else price > barrier
    if not worse:
        raise AssertionError(
            f"A4: exit price {price} is not strictly worse than barrier {barrier}"
        )


def check_a5(
    records: Records,
    *,
    expect_blind: bool,
    deciding_sequence: int | None = None,
) -> None:
    """BLIND is strict greater-than A, and the over-A case fires on the expected event."""
    blinds = [body for body in _closed_bodies(records) if _is_blind(body)]
    if not expect_blind:
        if blinds:
            raise AssertionError(f"A5: BLIND at or under A cell {blinds[0].get('cell_id')}")
        return
    if len(blinds) != 1:
        raise AssertionError(f"A5: expected one BLIND exit, found {len(blinds)}")
    cell = str(blinds[0]["cell_id"])
    got = _deciding_sequence(records, cell, "ADVERSE")
    if got != deciding_sequence:
        raise AssertionError(f"A5: BLIND on {got} != expected event {deciding_sequence}")


def check_a6(
    records: Records,
    *,
    birth_sequence: int,
    kind: str,
    deciding_sequence: int,
) -> None:
    """A concealed breach exits ADVERSE on the reveal, or BLIND once absence exceeds A."""
    body = _cell_born(records, birth_sequence)
    if body is None:
        raise AssertionError(f"A6: no cell born at {birth_sequence}")
    cell = str(body["cell_id"])
    blind = _is_blind(body)
    if kind == "ADVERSE":
        if str(body.get("exit_reason")) != "ADVERSE" or blind:
            raise AssertionError(
                f"A6: cell {cell} reason {body.get('exit_reason')} blind {blind} != ADVERSE"
            )
    elif kind == "BLIND":
        if not blind:
            raise AssertionError(f"A6: cell {cell} did not exit BLIND")
    else:
        raise AssertionError(f"A6: unknown kind {kind}")
    got = _deciding_sequence(records, cell, "ADVERSE")
    if got != deciding_sequence:
        raise AssertionError(f"A6: cell {cell} decided on {got} != {deciding_sequence}")


def check_unusable_side(records: Records, *, quote_sequence: int) -> None:
    """Both rail sides absent, absence clocks from the last usable quote, quiet resets."""
    rail = _rail_body(records, quote_sequence)
    if rail is None:
        raise AssertionError(f"UNUSABLE_SIDE: no MarkRailUpdate for quote {quote_sequence}")
    present: list[str] = []
    for name in ("long", "short"):
        side = rail.get(name)
        if not isinstance(side, dict):
            present.append(name)
            continue
        if side.get("paying_side_absent") is not True:
            present.append(f"{name}.paying")
        if side.get("valuation_side_absent") is not True:
            present.append(f"{name}.valuation")
    if present:
        raise AssertionError(
            f"UNUSABLE_SIDE: quote {quote_sequence} side present ({', '.join(present)})"
        )
    quote = records.quotes.get(quote_sequence)
    if quote is None:
        raise AssertionError(f"UNUSABLE_SIDE: quote {quote_sequence} is not on the tape")
    ordered = sorted(
        records.quotes.values(),
        key=lambda item: (item.exchange_timestamp_ns, item.sequence),
    )
    position = next(index for index, item in enumerate(ordered) if item.sequence == quote_sequence)
    if position == 0:
        raise AssertionError(f"UNUSABLE_SIDE: quote {quote_sequence} has no previous quote")
    previous = ordered[position - 1]
    quiet_gap = quote.exchange_timestamp_ns - previous.exchange_timestamp_ns
    if rail.get("symbol_quiet_ns") != quiet_gap:
        raise AssertionError(
            f"UNUSABLE_SIDE: symbol_quiet_ns {rail.get('symbol_quiet_ns')} != reset gap {quiet_gap}"
        )
    last_usable: NBBOQuote | None = None
    for item in reversed(ordered[:position]):
        if classify(item.bid, item.ask, item.bid_size, item.ask_size) is QuoteQuality.VALID:
            last_usable = item
            break
    if last_usable is None:
        raise AssertionError(f"UNUSABLE_SIDE: quote {quote_sequence} has no last usable value")
    absent_for = quote.exchange_timestamp_ns - last_usable.exchange_timestamp_ns
    for name in ("long", "short"):
        side = rail[name]
        assert isinstance(side, dict)
        for clock in ("paying_absent_for_ns", "valuation_absent_for_ns"):
            got = side.get(clock)
            if got != absent_for:
                raise AssertionError(
                    f"UNUSABLE_SIDE: {name}.{clock} {got} != absence {absent_for}"
                )


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


_MISSING = object()
_DC_FIELDS: dict[type, tuple[tuple[bytes, str], ...] | None] = {}
_ENUM_TYPES: dict[type, bool] = {}
_SESSION_DIGESTS: dict[tuple[str, ...], tuple[Widened, ...]] = {}


def _session_digest_key(tape: str) -> tuple[str, ...]:
    """Tape id plus every process-visible seam that changes a widened digest.

    ``tape`` is the caller tape id; its parameters are in that string.
    Unset engine and rail resolve to the production stub. Dwell and slippage
    resolve to ``0``, matching the rail. ``engine_factory``, ``rail_wrapper``,
    and ``attach_sink`` are per-call arguments of ``run_real`` and already key
    that cache; they are not process state here.
    """
    engine = (
        os.environ.get("FEELIES_ENGINE", "").strip() or "feelies.position.engine.PositionEngine"
    )
    rail = os.environ.get("FEELIES_RAIL", "").strip() or "feelies.portfolio.mark_rail.MarkRail"
    dwell = os.environ.get("FEELIES_RAIL_DWELL_NS", "").strip() or "0"
    slip = os.environ.get("FEELIES_RAIL_SLIPPAGE_TICKS", "").strip() or "0"
    return (tape, engine, rail, dwell, slip, _APP_CONFIG.as_posix())


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


def _pack_cents(value: object) -> int:
    """None is a sentinel. An int is packed unchanged, so stub digests stay put."""
    if value is None:
        return -1 << 62
    return value  # type: ignore[return-value]


def _pack_orientation(buf: bytearray, side: object) -> None:
    buf.extend(
        struct.pack(
            "<11q3B",
            _pack_cents(side.paying_mark_cents),  # type: ignore[attr-defined]
            _pack_cents(side.valuation_mark_cents),  # type: ignore[attr-defined]
            _pack_cents(side.worst_side_mark_cents),  # type: ignore[attr-defined]
            _pack_cents(side.forced_exit_mark_cents),  # type: ignore[attr-defined]
            _pack_cents(side.dwelled_exit_mark_cents),  # type: ignore[attr-defined]
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


def assert_widened_prefix(
    truncated: Sequence[Widened],
    full: Sequence[Widened],
    seq_k: int,
) -> None:
    """Prefixes through replay index ``seq_k`` are the same sequence of digests."""
    left = [row for row in truncated if isinstance(row.cursor, int) and row.cursor <= seq_k]
    right = [row for row in full if isinstance(row.cursor, int) and row.cursor <= seq_k]
    limit = min(len(left), len(right))
    for index in range(limit):
        if left[index] != right[index]:
            row = left[index]
            raise AssertionError(f"prefix diverged at {row.type_name}, cursor {row.cursor}")
    if len(left) != len(right):
        row = left[limit] if len(left) > len(right) else right[limit]
        raise AssertionError(f"prefix diverged at {row.type_name}, cursor {row.cursor}")


def session_digest(key: str, rows: tuple[Widened, ...]) -> tuple[Widened, ...]:
    """Full-run digest sequence, computed once per configuration and reused for every cut."""
    cache_key = _session_digest_key(key)
    cached = _SESSION_DIGESTS.get(cache_key)
    if cached is not None:
        return cached
    _SESSION_DIGESTS[cache_key] = rows
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
        if row.type_name != "OrderRequest" or not isinstance(row.cursor, int):
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


_RESOLUTION_ENV = (
    "FEELIES_ENGINE",
    "FEELIES_RAIL",
    "FEELIES_RAIL_DWELL_NS",
    "FEELIES_RAIL_SLIPPAGE_TICKS",
)


def _resolution_key() -> str:
    return "|".join(os.environ.get(name, "") for name in _RESOLUTION_ENV)


def _dotted(path: str) -> object:
    import importlib

    module_name, _, attr = path.rpartition(".")
    if not module_name:
        raise RuntimeError(f"not a dotted path: {path}")
    return getattr(importlib.import_module(module_name), attr)


def engine_class() -> type[object]:
    """Resolved engine. ``FEELIES_ENGINE`` when set, otherwise the production stub."""
    path = os.environ.get("FEELIES_ENGINE", "").strip()
    if not path:
        from feelies.position.engine import PositionEngine

        return PositionEngine
    loaded = _dotted(path)
    if not isinstance(loaded, type):
        raise RuntimeError(f"FEELIES_ENGINE {path} is not a class")
    return loaded


def _rail_from_env() -> type[object] | None:
    path = os.environ.get("FEELIES_RAIL", "").strip()
    if not path:
        return None
    loaded = _dotted(path)
    if not isinstance(loaded, type):
        raise RuntimeError(f"FEELIES_RAIL {path} is not a class")
    return loaded


class _Attribution:
    """Live cursor. The rail handler is registered before the engine attaches (N1)."""

    def __init__(self) -> None:
        self.attr_cursor: int | str | None = None
        self.wide_cursor: int | str | None = None
        self.rows: list[Record] = []
        self.widened: list[Widened] = []
        self.stream: list[Event] = []
        self.pricing: list[int | None] = []
        self._eot = False
        self._replay_index: int | None = None
        self._engine: object | None = None
        self._on_rail: Callable[[MarkRailUpdate], None] | None = None
        self._bus: object | None = None

    def bind(self, bus: object) -> None:
        def on_rail(event: MarkRailUpdate) -> None:
            self.attr_cursor = event.quote_sequence
            self.wide_cursor = event.quote_sequence

        bus.subscribe(MarkRailUpdate, on_rail)  # type: ignore[attr-defined]
        self._on_rail = on_rail
        self._bus = bus

    def attach_global(self, bus: object) -> None:
        self.attr_cursor = None
        self.wide_cursor = None
        bus.subscribe_all(self.observe)  # type: ignore[attr-defined]

    def observe(self, event: Event) -> None:
        kind = type(event)
        if kind is MetricEvent or kind is StateTransition:
            return
        if self._eot:
            attr_cursor: int | str | None = "EOT"
            wide_cursor: int | str | None = "EOT"
            replay_index = self._replay_index
        else:
            if kind is NBBOQuote:
                self.attr_cursor = event.sequence
                self.wide_cursor = event.sequence
            elif kind is Trade:
                self.wide_cursor = event.sequence
            attr_cursor = self.attr_cursor
            wide_cursor = self.wide_cursor
            replay_index = None
        ordinal = len(self.stream)
        pricing = attr_cursor if isinstance(attr_cursor, int) else None
        self.stream.append(event)
        self.pricing.append(pricing)
        if _keep(event):
            self._check(event, attr_cursor)
            self.rows.append(
                Record(attr_cursor, kind.__name__, canonical(event), replay_index, ordinal)
            )
        self.widened.append(
            Widened(wide_cursor, kind.__name__, _event_digest(event), replay_index)
        )

    def _check(self, event: Event, cursor: object) -> None:
        if cursor == "EOT":
            return
        if type(event) is not PositionSnapshot and type(event) is not GateDecision:
            return
        if event.rail_sequence != cursor:
            raise RuntimeError(
                f"attribution cursor {cursor} != rail_sequence {event.rail_sequence}"
            )

    def finalize(self, replay_length: int) -> None:
        engine = self._engine
        if engine is None:
            return
        impl = getattr(engine, "_impl", None)
        if not callable(getattr(impl, "finalize", None)):
            return
        self._eot = True
        self._replay_index = replay_length
        engine.finalize()  # type: ignore[attr-defined]


def _records_from_live(recorder: _Attribution, *, digest_only: bool = False) -> Records:
    widened = tuple(recorder.widened)
    if digest_only:
        records = Records([], {}, (), ())
        records.widened = widened
        return records
    stream = recorder.stream
    quotes = {event.sequence: event for event in stream if type(event) is NBBOQuote}
    orders = [event for event in stream if type(event) is OrderRequest]
    verdicts = [event for event in stream if type(event) is RiskVerdict]
    acks: list[OrderAck] = []
    ack_ordinals: list[int] = []
    ack_pricing: list[int | None] = []
    slices: list[SlicePositionUpdate] = []
    slice_ordinals: list[int] = []
    for ordinal, event in enumerate(stream):
        if type(event) is OrderAck:
            acks.append(event)
            ack_ordinals.append(ordinal)
            ack_pricing.append(
                recorder.pricing[ordinal] if ordinal < len(recorder.pricing) else None
            )
        elif type(event) is SlicePositionUpdate:
            slices.append(event)
            slice_ordinals.append(ordinal)
    records = Records(
        list(recorder.rows),
        quotes,
        orders,
        verdicts,
        acks,
        slices,
        ack_ordinals,
        slice_ordinals,
        ack_pricing,
    )
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
    saved_rail = rail_mod.MarkRail
    saved_attach = engine_mod.PositionRecordSink.attach
    recorder = _Attribution()
    resolved_rail = _rail_from_env()
    if resolved_rail is not None:
        rail_mod.MarkRail = resolved_rail  # type: ignore[misc, assignment]
    saved_on_quote = rail_mod.MarkRail.on_quote
    inner = engine_factory if engine_factory is not None else engine_class()

    class _Bound:
        def __init__(
            self,
            bus: object,
            sequence_generator: object,
            policies: object = None,
            **kwargs: object,
        ) -> None:
            recorder.bind(bus)
            self._bus = bus
            self._impl = inner(bus, sequence_generator, policies=policies, **kwargs)  # type: ignore[operator]
            recorder._engine = self

        def attach(self) -> None:
            handlers = self._bus._handlers[MarkRailUpdate]  # type: ignore[attr-defined]
            on_rail = recorder._on_rail
            cursor_at = handlers.index(on_rail)
            before = len(handlers)
            self._impl.attach()  # type: ignore[attr-defined]
            after = self._bus._handlers[MarkRailUpdate]  # type: ignore[attr-defined]
            if cursor_at >= before:
                raise AssertionError(
                    "attribution cursor handler is not registered before the engine attaches"
                )
            for index in range(before, len(after)):
                if cursor_at >= index:
                    raise AssertionError(
                        "attribution cursor handler is not registered before the engine attaches"
                    )

        def finalize(self) -> None:
            done = getattr(self._impl, "finalize", None)
            if callable(done):
                done()

    try:
        engine_mod.PositionEngine = _Bound  # type: ignore[misc, assignment]
        if rail_wrapper is not None:
            original = saved_on_quote

            def on_quote(self: object, quote: NBBOQuote) -> object:
                return rail_wrapper(original.__get__(self, type(self)), quote)

            rail_mod.MarkRail.on_quote = on_quote  # type: ignore[method-assign]
        if not attach_sink:
            engine_mod.PositionRecordSink.attach = lambda self: None  # type: ignore[method-assign, assignment]
        yield recorder
    finally:
        rail_mod.MarkRail.on_quote = saved_on_quote
        rail_mod.MarkRail = saved_rail
        engine_mod.PositionEngine = saved_engine
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
        with _seams(engine_factory, rail_wrapper, attach_sink) as recorder:
            orchestrator, resolved = build_platform(config, event_log=log)
            recorder.attach_global(orchestrator._bus)
            orchestrator.boot(resolved)
            import gc

            gc.disable()
            try:
                orchestrator.run_backtest()
            finally:
                gc.enable()
            recorder.finalize(len(tape))
            result = _records_from_live(recorder)
    finally:
        AlphaLoader.load = original_load  # type: ignore[method-assign]
    return result


_TAPES: dict[tuple[tuple[int, int, str, str, str, int, int], ...], list[NBBOQuote]] = {}
_FACTORIES: dict[str, Callable[..., object]] = {}
_RAILS: dict[str, Callable[..., object]] = {}
_TRANSFORMS: dict[str, Callable[[Sequence[Event]], Sequence[Event]]] = {}
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


def _transform_key(
    transform: Callable[[Sequence[Event]], Sequence[Event]] | None,
) -> str:
    if transform is None:
        return ""
    key = repr(transform)
    _TRANSFORMS[key] = transform
    return key


def slice_real_events(
    events: Sequence[Event],
    *,
    end_index: int | None = None,
    fraction: float | None = None,
) -> list[Event]:
    """Prefix of a prepared replay. Fraction is applied after ``end_index``."""
    sliced = list(events)
    if end_index is not None:
        sliced = sliced[: end_index + 1]
    if fraction is not None:
        if not 0 < fraction <= 1:
            raise ValueError(f"fraction must be in (0, 1], got {fraction}")
        sliced = sliced[: int(len(sliced) * fraction)]
    return sliced


@functools.lru_cache(maxsize=None)
def _cached_synthetic(
    tape_key: tuple[tuple[int, int, str, str, str, int, int], ...],
    symbols: tuple[str, ...],
    factory_key: str,
    rail_key: str,
    attach_sink: bool,
    clock_tag: str,
    variant_key: str,
    resolution_key: str,
) -> Records:
    del clock_tag, resolution_key
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
        _resolution_key(),
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
    fraction: float | None,
    engine_factory: Callable[..., object] | None,
    rail_wrapper: Callable[..., object] | None,
    quote_transform: Callable[[Sequence[Event]], Sequence[Event]] | None,
    attach_sink: bool,
    digest_only: bool,
) -> Records:
    import argparse

    _raw, (ingest, day_meta) = _real_bundle()
    events = slice_real_events(rth_replay(), end_index=end_index, fraction=fraction)
    if quote_transform is not None:
        events = list(quote_transform(events))
    log = InMemoryEventLog()
    log.append_batch(events)
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
    with _seams(engine_factory, rail_wrapper, attach_sink) as recorder:

        def factory(config: PlatformConfig, event_log: InMemoryEventLog, **kwargs: object):
            orchestrator, resolved = build_platform(config, event_log=event_log, **kwargs)  # type: ignore[arg-type]
            recorder.attach_global(orchestrator._bus)
            return orchestrator, resolved

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
        recorder.finalize(len(events))
        result = _records_from_live(recorder, digest_only=digest_only)
    return result


@functools.lru_cache(maxsize=None)
def _cached_real(
    end_index: int | None,
    fraction: float | None,
    factory_key: str,
    rail_key: str,
    transform_key: str,
    attach_sink: bool,
    clock_tag: str,
    digest_only: bool,
    resolution_key: str,
) -> Records:
    del clock_tag, resolution_key
    return _execute_real(
        end_index,
        fraction,
        _FACTORIES.get(factory_key),
        _RAILS.get(rail_key) if rail_key else None,
        _TRANSFORMS.get(transform_key) if transform_key else None,
        attach_sink,
        digest_only,
    )


def run_real(
    *,
    end_index: int | None = None,
    fraction: float | None = None,
    engine_factory: Callable[..., object] | None = None,
    rail_wrapper: Callable[..., object] | None = None,
    quote_transform: Callable[[Sequence[Event]], Sequence[Event]] | None = None,
    attach_sink: bool = True,
    digest_only: bool = False,
) -> Records:
    return _cached_real(
        end_index,
        fraction,
        _factory_key(engine_factory),
        _rail_key(rail_wrapper),
        _transform_key(quote_transform),
        attach_sink,
        _clock_tag(),
        digest_only,
        _resolution_key(),
    )


def format_line(row: Record) -> str:
    return f"{row.attributed_quote_sequence}\t{row.type_name}\t{row.canonical}"


def _dump_widened(path: str, rows: Sequence[Widened]) -> None:
    with open(path, "wb") as handle:
        handle.write(len(rows).to_bytes(4, "little"))
        for row in rows:
            name = row.type_name.encode()
            if row.cursor is None:
                cursor = -1
            elif row.cursor == "EOT":
                cursor = -2
            else:
                cursor = row.cursor
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
            if cursor == -1:
                loaded: int | str | None = None
            elif cursor == -2:
                loaded = "EOT"
            else:
                loaded = cursor
            rows.append(Widened(loaded, type_name, digest))
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


def _records_path(args: Sequence[str]) -> str | None:
    """Parent-supplied record file. An argument wins over FEELIES_RECORDS_OUT."""
    if len(args) == 3 and args[1] in {"syn_m1", "real_m1"}:
        return args[2]
    path = os.environ.get("FEELIES_RECORDS_OUT", "").strip()
    return path or None


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    if len(args) == 4 and args[1] == "prefix":
        rows = run_real(end_index=int(args[2]), digest_only=True).widened
        _dump_widened(args[3], rows)
        return 0
    out = _records_path(args)
    if (out is None and len(args) != 2) or (out is not None and len(args) not in {2, 3}):
        raise SystemExit(
            "usage: python -m tests.position_engine.scenarios <syn_m1|real_m1|prefix> [records_out]"
        )
    lines = [format_line(row) for row in _scenario(args[1])]
    if out is not None:
        text = "\n".join(lines)
        if lines:
            text += "\n"
        Path(out).write_text(text, encoding="utf-8", newline="\n")
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
