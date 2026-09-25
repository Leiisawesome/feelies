"""Member 1: reproducibility. Red from stage A until B (D-18)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from functools import partial
from unittest.mock import patch

import pytest

from feelies.core.events import PositionClosed, PositionSnapshot
from feelies.position.engine import PositionEngine
from tests.position_engine.scenarios import (
    T0,
    Records,
    format_line,
    nonvacuous,
    project_for_multiname,
    run_real,
    run_synthetic,
)
from tests.position_engine.tapes import make_tape

_MARK = pytest.mark.battery_member(member=1, green_from="B", red_reason="^NONVACUOUS: ")
_REAL = pytest.mark.battery_real


def _syn_tape():
    return make_tape(seed=11, n=36000, symbol="SYN", start_ns=T0, size=1000)


def _symbol(canonical: str) -> str | None:
    body = json.loads(canonical[canonical.index("{") :])
    symbol = body.get("symbol")
    return symbol if isinstance(symbol, str) else None


def _syn_projected(records: Records) -> list[str]:
    return [
        project_for_multiname(row.canonical) for row in records if _symbol(row.canonical) == "SYN"
    ]


def _clock():
    fixed = 946684800
    return patch.multiple(
        time,
        time=lambda: fixed,
        time_ns=lambda: fixed * 10**9,
        monotonic=lambda: 0.0,
        monotonic_ns=lambda: 0,
        perf_counter=lambda: 0.0,
        perf_counter_ns=lambda: 0,
    )


def _fresh(name: str) -> list[str]:
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    proc = subprocess.run(
        [sys.executable, "-m", "tests.position_engine.scenarios", name],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return [line for line in proc.stdout.splitlines() if line]


@_MARK
def test_m1_clock_syn() -> None:
    tape = _syn_tape()
    baseline = run_synthetic(tape, symbols=("SYN",))
    nonvacuous(baseline, PositionSnapshot, PositionClosed, scenario="m1_clock_syn")
    with _clock():
        records = run_synthetic(tape, symbols=("SYN",))
    assert records == baseline


@_MARK
@_REAL
def test_m1_clock_real() -> None:
    baseline = run_real()
    nonvacuous(baseline, PositionSnapshot, PositionClosed, scenario="m1_clock_real")
    with _clock():
        records = run_real()
    assert records == baseline


@_MARK
def test_m1_gates_syn() -> None:
    tape = _syn_tape()
    baseline = run_synthetic(tape, symbols=("SYN",))
    nonvacuous(baseline, PositionSnapshot, PositionClosed, scenario="m1_gates_syn")
    records = run_synthetic(
        tape,
        symbols=("SYN",),
        engine_factory=partial(PositionEngine, gate_order=("FAVORABLE", "ADVERSE")),
    )
    assert records == baseline


@_MARK
@_REAL
def test_m1_gates_real() -> None:
    baseline = run_real()
    nonvacuous(baseline, PositionSnapshot, PositionClosed, scenario="m1_gates_real")
    records = run_real(engine_factory=partial(PositionEngine, gate_order=("FAVORABLE", "ADVERSE")))
    assert records == baseline


@_MARK
def test_m1_fresh_syn() -> None:
    records = run_synthetic(_syn_tape(), symbols=("SYN",))
    nonvacuous(records, PositionSnapshot, PositionClosed, scenario="m1_fresh_syn")
    assert _fresh("syn_m1") == [format_line(row) for row in records]


@_MARK
@_REAL
def test_m1_fresh_real() -> None:
    records = run_real()
    nonvacuous(records, PositionSnapshot, PositionClosed, scenario="m1_fresh_real")
    assert _fresh("real_m1") == [format_line(row) for row in records]


@_MARK
def test_m1_sinks_syn() -> None:
    tape = _syn_tape()
    baseline = run_synthetic(tape, symbols=("SYN",))
    nonvacuous(baseline, PositionSnapshot, PositionClosed, scenario="m1_sinks_syn")
    records = run_synthetic(tape, symbols=("SYN",), attach_sink=False)
    assert records == baseline


@_MARK
@_REAL
def test_m1_sinks_real() -> None:
    baseline = run_real()
    nonvacuous(baseline, PositionSnapshot, PositionClosed, scenario="m1_sinks_real")
    records = run_real(attach_sink=False)
    assert records == baseline


@_MARK
def test_m1_multiname() -> None:
    syn = _syn_tape()
    alone = run_synthetic(syn, symbols=("SYN",))
    nonvacuous(alone, PositionSnapshot, PositionClosed, scenario="m1_multiname")
    zzz = make_tape(
        seed=12,
        n=36000,
        symbol="ZZZ",
        start_ns=T0 + 50_000_000,
        size=1000,
        start_sequence=1_000_001,
    )
    pair_tape = sorted([*syn, *zzz], key=lambda quote: quote.timestamp_ns)
    pair = run_synthetic(pair_tape, symbols=("SYN", "ZZZ"))
    if any(order.symbol == "ZZZ" for order in pair.order_requests):
        raise AssertionError("PRECONDITION: second name traded")
    assert _syn_projected(pair) == _syn_projected(alone)
