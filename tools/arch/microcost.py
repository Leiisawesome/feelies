#!/usr/bin/env python3
"""Phase 4 (Axis E) unit costs for the primitives the findings rest on.

Standard library only.  Writes ``tools/arch/evidence/microcost.json``.

Every per-event finding in ``hotpath.json`` is a count: "this construct runs N
times per quote".  A count is only actionable next to a unit cost, and a unit
cost quoted from memory is not evidence -- CPython's numbers move between
versions (3.10 gained a fast path for ``frozen=False`` dataclasses; 3.12 changed
``__slots__`` layout), so they are measured here, on this host, at this version,
in the same process shape as the replay.

Each row is timed with ``timeit`` at a repeat count high enough that the timer
granularity is irrelevant, and the *minimum* of several rounds is reported --
the minimum is the estimate least contaminated by scheduler preemption.

Usage:

    uv run python tools/arch/microcost.py
"""

from __future__ import annotations

import json
import platform
import sys
import timeit
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "tools" / "arch" / "evidence"

_SETUP = """
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any
import time


@dataclass(frozen=True, slots=True)
class FrozenRec:
    machine_name: str
    from_state: str
    to_state: str
    trigger: str
    timestamp_ns: int
    correlation_id: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class MutableRec:
    machine_name: str
    from_state: str
    to_state: str
    trigger: str
    timestamp_ns: int
    correlation_id: str = ""
    metadata: dict = field(default_factory=dict)


class ManualRec:
    __slots__ = (
        "machine_name", "from_state", "to_state", "trigger",
        "timestamp_ns", "correlation_id", "metadata",
    )

    def __init__(self, machine_name, from_state, to_state, trigger,
                 timestamp_ns, correlation_id="", metadata=None):
        self.machine_name = machine_name
        self.from_state = from_state
        self.to_state = to_state
        self.trigger = trigger
        self.timestamp_ns = timestamp_ns
        self.correlation_id = correlation_id
        self.metadata = metadata


# NBBOQuote's real shape: 19 fields, frozen, kw_only, slots.
@dataclass(frozen=True, kw_only=True, slots=True)
class Quote19:
    timestamp_ns: int
    correlation_id: str
    sequence: int
    source_layer: str = "UNKNOWN"
    symbol: str = ""
    bid: Decimal = Decimal(0)
    ask: Decimal = Decimal(0)
    bid_size: int = 0
    ask_size: int = 0
    bid_exchange: int = 0
    ask_exchange: int = 0
    exchange_timestamp_ns: int = 0
    conditions: tuple = ()
    indicators: tuple = ()
    sequence_number: int = 0
    tape: int = 0
    participant_timestamp_ns: int | None = None
    trf_timestamp_ns: int | None = None
    received_ns: int | None = None


# The same event with the seven fields no src/ reader touches removed.
@dataclass(frozen=True, kw_only=True, slots=True)
class Quote12:
    timestamp_ns: int
    correlation_id: str
    sequence: int
    source_layer: str = "UNKNOWN"
    symbol: str = ""
    bid: Decimal = Decimal(0)
    ask: Decimal = Decimal(0)
    bid_size: int = 0
    ask_size: int = 0
    exchange_timestamp_ns: int = 0
    conditions: tuple = ()
    sequence_number: int = 0


ARGS = ("tick_pipeline", "M0", "M1", "tick_arrived", 1, "APP:1:2")
QKW = dict(
    timestamp_ns=1, correlation_id="APP:1:2", sequence=3, symbol="APP",
    bid=Decimal("10.01"), ask=Decimal("10.03"), bid_size=100, ask_size=200,
    exchange_timestamp_ns=1,
)
TRANSITIONS = {"M0": frozenset({"M1", "M2"}), "M1": frozenset({"M2"})}
STATE = "M0"
POSITIONS = {f"SYM{i}": object() for i in range(8)}
EMPTY_FS = frozenset()
TWO = Decimal("2")
BID = Decimal("10.01")
ASK = Decimal("10.03")


class Inner:
    def refresh_high_water_mark(self, positions):
        return None


INNER = Inner()
"""

# (id, expression, what the number is evidence for)
CASES: list[tuple[str, str, str]] = [
    (
        "frozen_slots_dataclass_7field",
        "FrozenRec(*ARGS)",
        "TransitionRecord construction (core/state_machine.py:27)",
    ),
    (
        "mutable_slots_dataclass_7field",
        "MutableRec(*ARGS)",
        "same record without frozen=True, to price the frozen penalty",
    ),
    (
        "hand_written_slots_7field",
        "ManualRec(*ARGS)",
        "floor for a 7-attribute object with an ordinary __init__",
    ),
    (
        "tuple_7field",
        "ARGS + (None,)",
        "floor for carrying the same seven values with no class at all",
    ),
    (
        "frozen_event_19_fields",
        "Quote19(**QKW)",
        "NBBOQuote-shaped construction (core/events.py:58)",
    ),
    (
        "frozen_event_12_fields",
        "Quote12(**QKW)",
        "same minus the 7 fields with no src/ reader",
    ),
    (
        "fstring_two_slots",
        "f'{STATE}:{1}'",
        "make_correlation_id (core/identifiers.py:15), metric key (monitoring/in_memory.py:74)",
    ),
    (
        "frozenset_empty",
        "frozenset()",
        "the .get default in can_transition (core/state_machine.py:159)",
    ),
    (
        "dict_get_with_frozenset_default",
        "TRANSITIONS.get(STATE, frozenset())",
        "can_transition as written",
    ),
    (
        "dict_get_with_hoisted_default",
        "TRANSITIONS.get(STATE, EMPTY_FS)",
        "can_transition with the default hoisted to a constant",
    ),
    (
        "empty_dict_literal",
        "{}",
        "_tick_timings per tick (kernel/orchestrator.py:1525)",
    ),
    (
        "decimal_from_str",
        "Decimal('2')",
        "the mid divisor (kernel/orchestrator.py:1606)",
    ),
    (
        "decimal_hoisted_div",
        "(BID + ASK) / TWO",
        "the same mid with the divisor hoisted",
    ),
    (
        "decimal_inline_div",
        "(BID + ASK) / Decimal('2')",
        "the mid as written",
    ),
    (
        "getattr_present_plus_callable",
        "callable(getattr(INNER, 'refresh_high_water_mark', None))",
        "the HWM hook probe (alpha/risk_wrapper.py:329, kernel/orchestrator.py:1616)",
    ),
    (
        "direct_method_call",
        "INNER.refresh_high_water_mark(None)",
        "the same call without the probe",
    ),
    (
        "dict_copy_8_entries",
        "dict(POSITIONS)",
        "all_positions defensive copy (portfolio/memory_position_store.py:160)",
    ),
    (
        "perf_counter_ns",
        "time.perf_counter_ns()",
        "the tick-path timers (kernel/orchestrator.py:1524 and 6 more)",
    ),
]


def _measure(expr: str, *, target_s: float = 0.35, rounds: int = 5) -> float:
    """Return the minimum observed ns/op over ``rounds``."""
    t = timeit.Timer(expr, setup=_SETUP)
    n, _ = t.autorange()
    n = max(n, int(n * target_s / max(t.timeit(n), 1e-9)))
    return min(t.timeit(n) for _ in range(rounds)) / n * 1e9


def main() -> int:
    rows: dict[str, dict[str, Any]] = {}
    print(f"{'case':38s} {'ns/op':>9}  evidence for")
    for case_id, expr, why in CASES:
        ns = _measure(expr)
        rows[case_id] = {"expr": expr, "ns_per_op": round(ns, 1), "evidence_for": why}
        print(f"{case_id:38s} {ns:9.1f}  {why}")

    derived = {
        "frozen_penalty_ns": round(
            rows["frozen_slots_dataclass_7field"]["ns_per_op"]
            - rows["mutable_slots_dataclass_7field"]["ns_per_op"],
            1,
        ),
        "dataclass_over_handwritten_ns": round(
            rows["frozen_slots_dataclass_7field"]["ns_per_op"]
            - rows["hand_written_slots_7field"]["ns_per_op"],
            1,
        ),
        "unread_event_fields_ns": round(
            rows["frozen_event_19_fields"]["ns_per_op"]
            - rows["frozen_event_12_fields"]["ns_per_op"],
            1,
        ),
        "frozenset_default_ns": round(
            rows["dict_get_with_frozenset_default"]["ns_per_op"]
            - rows["dict_get_with_hoisted_default"]["ns_per_op"],
            1,
        ),
        "decimal_inline_divisor_ns": round(
            rows["decimal_inline_div"]["ns_per_op"] - rows["decimal_hoisted_div"]["ns_per_op"],
            1,
        ),
        "getattr_probe_over_direct_call_ns": round(
            rows["getattr_present_plus_callable"]["ns_per_op"]
            - rows["direct_method_call"]["ns_per_op"],
            1,
        ),
    }
    print()
    for k, v in derived.items():
        print(f"  {k:38s} {v:9.1f} ns")

    payload = {
        "measurement": {
            "tool": "tools/arch/microcost.py",
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "processor": platform.processor(),
            "note": (
                "timeit minimum of 5 rounds, autoranged to >=0.35s per round. "
                "GC is left at its default (enabled) here, unlike the replay "
                "measurement, which runs under the harness's gc.disable()."
            ),
        },
        "cases": rows,
        "derived_deltas_ns": derived,
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    dest = EVIDENCE / "microcost.json"
    dest.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\n  wrote {dest.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
