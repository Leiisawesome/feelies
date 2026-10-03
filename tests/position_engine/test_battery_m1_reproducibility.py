"""Member 1: reproducibility. Red from stage A until B (D-18)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from functools import partial
from pathlib import Path
from unittest.mock import patch

import pytest

from feelies.core.events import PositionClosed, PositionSnapshot
from tests.position_engine.scenarios import (
    T0,
    Records,
    engine_class,
    format_line,
    nonvacuous,
    require_entry_fills,
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


def _one_snapshot_per_rail(records: Records) -> None:
    """At most one PositionSnapshot per (cell_id, rail_sequence)."""
    seen: set[tuple[object, object]] = set()
    for row in records:
        if row.type_name != "PositionSnapshot":
            continue
        body = json.loads(row.canonical[row.canonical.index("{") :])
        key = (body.get("cell_id"), body.get("rail_sequence"))
        if key in seen:
            raise AssertionError(f"duplicate PositionSnapshot for {key}")
        seen.add(key)


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


def _fresh(name: str, expected: list[str]) -> None:
    """Compare the child's record file. Stdout is the runner log, not the records."""
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    handle = tempfile.NamedTemporaryFile(prefix="feelies-records-", suffix=".txt", delete=False)
    path = handle.name
    handle.close()
    env["FEELIES_RECORDS_OUT"] = path
    proc = subprocess.run(
        [sys.executable, "-m", "tests.position_engine.scenarios", name],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    try:
        if proc.returncode != 0:
            raise AssertionError(
                f"fresh child exited {proc.returncode}\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        got = [line for line in Path(path).read_text(encoding="utf-8").splitlines() if line]
        if got != expected:
            raise AssertionError(
                f"fresh records differ\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
    finally:
        Path(path).unlink(missing_ok=True)


@_MARK
def test_m1_clock_syn() -> None:
    tape = _syn_tape()
    baseline = run_synthetic(tape, symbols=("SYN",))
    require_entry_fills(baseline)
    nonvacuous(baseline, PositionSnapshot, PositionClosed, scenario="m1_clock_syn")
    _one_snapshot_per_rail(baseline)
    with _clock():
        records = run_synthetic(tape, symbols=("SYN",))
    assert records == baseline


@_MARK
@_REAL
def test_m1_clock_real() -> None:
    baseline = run_real()
    require_entry_fills(baseline)
    nonvacuous(baseline, PositionSnapshot, PositionClosed, scenario="m1_clock_real")
    _one_snapshot_per_rail(baseline)
    with _clock():
        records = run_real()
    assert records == baseline


@_MARK
def test_m1_gates_syn() -> None:
    tape = _syn_tape()
    baseline = run_synthetic(tape, symbols=("SYN",))
    require_entry_fills(baseline)
    nonvacuous(baseline, PositionSnapshot, PositionClosed, scenario="m1_gates_syn")
    _one_snapshot_per_rail(baseline)
    records = run_synthetic(
        tape,
        symbols=("SYN",),
        engine_factory=partial(engine_class(), gate_order=("FAVORABLE", "ADVERSE")),
    )
    assert records == baseline


@_MARK
@_REAL
def test_m1_gates_real() -> None:
    baseline = run_real()
    require_entry_fills(baseline)
    nonvacuous(baseline, PositionSnapshot, PositionClosed, scenario="m1_gates_real")
    _one_snapshot_per_rail(baseline)
    records = run_real(engine_factory=partial(engine_class(), gate_order=("FAVORABLE", "ADVERSE")))
    assert records == baseline


@_MARK
def test_m1_fresh_syn() -> None:
    records = run_synthetic(_syn_tape(), symbols=("SYN",))
    require_entry_fills(records)
    nonvacuous(records, PositionSnapshot, PositionClosed, scenario="m1_fresh_syn")
    _one_snapshot_per_rail(records)
    _fresh("syn_m1", [format_line(row) for row in records])


@_MARK
@_REAL
def test_m1_fresh_real() -> None:
    records = run_real()
    require_entry_fills(records)
    nonvacuous(records, PositionSnapshot, PositionClosed, scenario="m1_fresh_real")
    _one_snapshot_per_rail(records)
    _fresh("real_m1", [format_line(row) for row in records])


@_MARK
def test_m1_sinks_syn() -> None:
    tape = _syn_tape()
    baseline = run_synthetic(tape, symbols=("SYN",))
    require_entry_fills(baseline)
    nonvacuous(baseline, PositionSnapshot, PositionClosed, scenario="m1_sinks_syn")
    _one_snapshot_per_rail(baseline)
    records = run_synthetic(tape, symbols=("SYN",), attach_sink=False)
    assert records == baseline


@_MARK
@_REAL
def test_m1_sinks_real() -> None:
    baseline = run_real()
    require_entry_fills(baseline)
    nonvacuous(baseline, PositionSnapshot, PositionClosed, scenario="m1_sinks_real")
    _one_snapshot_per_rail(baseline)
    records = run_real(attach_sink=False)
    assert records == baseline


def _projected(records: Records, symbol: str) -> list[str]:
    return [
        project_for_multiname(row.canonical) for row in records if _symbol(row.canonical) == symbol
    ]


def _run_pair_tapped(tape: list[object]) -> tuple[Records, dict[str, int]]:
    """Run the pair once, counting orders priced and sized from their own quote."""
    import feelies.kernel.orchestrator as orch_mod
    from feelies.core.events import NBBOQuote
    from tests.position_engine.scenarios import _cached_synthetic

    built: list[tuple[str, str | None, str | None]] = []
    draft: dict[str, str | None] = {}
    orig_qty = orch_mod._compute_target_quantity
    orig_route = orch_mod._resolve_order_route

    def _qty(self: object, signal: object, quote: object) -> object:
        draft.clear()
        symbol = getattr(signal, "symbol", None)
        draft["signal_symbol"] = symbol if isinstance(symbol, str) else None
        size_sym = getattr(quote, "symbol", None) if quote is not None else None
        draft["size_sym"] = size_sym if isinstance(size_sym, str) else None
        return orig_qty(self, signal, quote)

    def _route(self: object, **kwargs: object) -> object:
        if draft.get("signal_symbol") == kwargs.get("symbol"):
            quote = kwargs.get("quote")
            limit_sym = getattr(quote, "symbol", None) if quote is not None else None
            symbol = kwargs.get("symbol")
            built.append(
                (
                    symbol if isinstance(symbol, str) else "",
                    draft.get("size_sym"),
                    limit_sym if isinstance(limit_sym, str) else None,
                )
            )
            draft.clear()
        return orig_route(self, **kwargs)

    quotes = [quote for quote in tape if isinstance(quote, NBBOQuote)]
    orch_mod._compute_target_quantity = _qty  # type: ignore[method-assign]
    orch_mod._resolve_order_route = _route  # type: ignore[method-assign]
    try:
        _cached_synthetic.cache_clear()
        records = run_synthetic(quotes, symbols=("SYN", "ZZZ"))
    finally:
        orch_mod._compute_target_quantity = orig_qty  # type: ignore[method-assign]
        orch_mod._resolve_order_route = orig_route  # type: ignore[method-assign]
    counts: dict[str, int] = {}
    for symbol, size_sym, limit_sym in built:
        if size_sym not in (None, symbol) or limit_sym not in (None, symbol):
            raise AssertionError(
                f"sized from another symbol: {symbol} size={size_sym} limit={limit_sym}"
            )
        if size_sym == symbol and limit_sym == symbol:
            counts[symbol] = counts.get(symbol, 0) + 1
    return records, counts


@_MARK
def test_m1_multiname() -> None:
    syn = _syn_tape()
    zzz = make_tape(
        seed=12,
        n=36000,
        symbol="ZZZ",
        start_ns=T0 + 50_000_000,
        size=1000,
        start_sequence=1_000_001,
    )
    pair_tape = sorted([*syn, *zzz], key=lambda quote: quote.timestamp_ns)
    from tests.position_engine.scenarios import _cached_synthetic

    pair, sized = _run_pair_tapped(pair_tape)
    require_entry_fills(pair)
    nonvacuous(pair, PositionSnapshot, PositionClosed, scenario="m1_multiname")
    _one_snapshot_per_rail(pair)
    traded = {order.symbol for order in pair.order_requests}
    assert traded == {"SYN", "ZZZ"}, sorted(traded)
    assert sized.get("SYN", 0) >= 1, sized
    assert sized.get("ZZZ", 0) >= 1, sized
    _cached_synthetic.cache_clear()
    again = run_synthetic(pair_tape, symbols=("SYN", "ZZZ"))
    assert _projected(again, "SYN") == _projected(pair, "SYN")
    assert _projected(again, "ZZZ") == _projected(pair, "ZZZ")
