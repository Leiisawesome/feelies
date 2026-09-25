"""Member 2: no lookahead. Red from stage A until B (D-18)."""

from __future__ import annotations

import pytest

from feelies.core.events import PositionSnapshot
from tests.position_engine.scenarios import (
    T0,
    Record,
    nonvacuous,
    real_cutoff_sequence,
    run_real,
    run_synthetic,
)
from tests.position_engine.tapes import make_tape

_MARK = pytest.mark.battery_member(member=2, green_from="B", red_reason="^NONVACUOUS: ")
_REAL = pytest.mark.battery_real


def _upto(records: list[Record], seq_k: int) -> list[Record]:
    return [
        row
        for row in records
        if row.attributed_quote_sequence is not None and row.attributed_quote_sequence <= seq_k
    ]


@_MARK
def test_m2_syn() -> None:
    n = 36000
    tape = make_tape(seed=11, n=n, symbol="SYN", start_ns=T0, size=1000)
    full = run_synthetic(tape, symbols=("SYN",))
    nonvacuous(full, PositionSnapshot, scenario="m2_syn")
    for i in range(1, 21):
        k = round(n * i / 20) - 1
        truncated = run_synthetic(tape[: k + 1], symbols=("SYN",))
        seq_k = tape[k].sequence
        assert _upto(truncated, seq_k) == _upto(full, seq_k)


def _real(fraction: float) -> None:
    full = run_real()
    nonvacuous(full, PositionSnapshot, scenario=f"m2_real_{fraction}")
    truncated = run_real(fraction=fraction)
    seq_k = real_cutoff_sequence(fraction)
    assert _upto(truncated, seq_k) == _upto(full, seq_k)


@_MARK
@_REAL
def test_m2_real_025() -> None:
    _real(0.25)


@_MARK
@_REAL
def test_m2_real_050() -> None:
    _real(0.50)


@_MARK
@_REAL
def test_m2_real_075() -> None:
    _real(0.75)
