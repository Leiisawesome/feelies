"""Harness self-tests. Ordinary tests; no battery marker."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from feelies.core.events import NBBOQuote, PositionSnapshot
from tests.position_engine.scenarios import (
    T0,
    canonical,
    format_line,
    nonvacuous,
    project_for_multiname,
    run_synthetic,
)
from tests.position_engine.tapes import make_tape


def _quote() -> NBBOQuote:
    return make_tape(seed=1, n=1, symbol="SYN", start_ns=T0, size=1000)[0]


def test_t1_canonical_is_deterministic_and_key_sorted() -> None:
    quote = _quote()
    first = canonical(quote)
    second = canonical(quote)
    assert first == second
    payload = json.loads(first[first.index("{") :])
    keys = list(payload)
    assert keys == sorted(keys)


def test_t2_project_drops_nested_sequence_and_cell_id() -> None:
    text = (
        'Demo{"cell_id":"c","keep":1,"nested":{"cell_id":"d","quote_sequence":3,"z":1},'
        '"sequence":9}'
    )
    projected = project_for_multiname(text)
    payload = json.loads(projected[projected.index("{") :])
    assert "cell_id" not in payload
    assert "sequence" not in payload
    nested = payload["nested"]
    assert "cell_id" not in nested
    assert "quote_sequence" not in nested
    assert nested["z"] == 1
    assert payload["keep"] == 1


def test_t3_mark_rail_attributed_to_its_quote() -> None:
    tape = make_tape(seed=11, n=50, symbol="SYN", start_ns=T0, size=1000)
    records = run_synthetic(tape, symbols=("SYN",))
    updates = [row for row in records if row.type_name == "MarkRailUpdate"]
    assert updates
    for row in updates:
        body = json.loads(row.canonical[row.canonical.index("{") :])
        assert row.attributed_quote_sequence == body["quote_sequence"]


def test_t4_nonvacuous_message_prefix() -> None:
    with pytest.raises(AssertionError, match="^NONVACUOUS: "):
        nonvacuous([], PositionSnapshot, scenario="t4")


def test_t5_syn_m1_entry_exits_zero() -> None:
    tape = make_tape(seed=11, n=36000, symbol="SYN", start_ns=T0, size=1000)
    records = run_synthetic(tape, symbols=("SYN",))
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    proc = subprocess.run(
        [sys.executable, "-m", "tests.position_engine.scenarios", "syn_m1"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line]
    assert lines == [format_line(row) for row in records]
    assert len(lines) == len(records)


def test_t6_nonvacuous_precedes_perturbation() -> None:
    reached = False

    def _member(baseline: list[object]) -> None:
        nonlocal reached
        nonvacuous(baseline, PositionSnapshot, scenario="t6")
        reached = True
        raise TypeError("perturbation")

    with pytest.raises(AssertionError, match="^NONVACUOUS: "):
        _member([])
    assert reached is False
