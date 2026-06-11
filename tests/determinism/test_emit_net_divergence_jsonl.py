"""Unit tests for ``_emit_net_divergence_jsonl`` (G-5 measurement stream).

Verifies the ``NETDIV_JSONL`` parity stream emitted under
``--emit-net-divergence-jsonl``: prefix on every line, sorted keys,
``magnitude = net − winner``, and record order preserved.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from feelies.execution.portfolio_netter import NetDivergence


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "_runner_emit_netdiv_test",
        Path("scripts/run_backtest.py").resolve(),
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_runner_emit_netdiv_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


def _div(
    seq: int, winner: int, net: int, n: int = 2, ts: int = 1_717_200_000_000_000_000
) -> NetDivergence:
    return NetDivergence(
        symbol="AAPL",
        signal_sequence=seq,
        winner_strategy_id="alpha_a",
        winner_target_qty=winner,
        net_target_qty=net,
        contributing_alphas=n,
        timestamp_ns=ts,
        detail="x",
    )


def test_prefix_and_order(runner, capsys) -> None:
    runner._emit_net_divergence_jsonl([_div(1, 100, 200), _div(2, 100, 0)])
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 2
    assert all(line.startswith("NETDIV_JSONL ") for line in out)
    seqs = [json.loads(ln[len("NETDIV_JSONL ") :])["signal_sequence"] for ln in out]
    assert seqs == [1, 2]  # record order preserved


def test_row_shape_and_magnitude(runner, capsys) -> None:
    runner._emit_net_divergence_jsonl([_div(7, 100, 200, n=3)])
    payload = json.loads(capsys.readouterr().out.splitlines()[0][len("NETDIV_JSONL ") :])
    assert payload == {
        "timestamp_ns": 1_717_200_000_000_000_000,
        "signal_sequence": 7,
        "symbol": "AAPL",
        "winner_strategy_id": "alpha_a",
        "winner_target_qty": 100,
        "net_target_qty": 200,
        "magnitude": 100,  # net − winner = 200 − 100
        "contributing_alphas": 3,
    }


def test_offset_magnitude_is_signed(runner, capsys) -> None:
    runner._emit_net_divergence_jsonl([_div(1, 100, 0)])  # opposing → net flat
    payload = json.loads(capsys.readouterr().out.splitlines()[0][len("NETDIV_JSONL ") :])
    assert payload["magnitude"] == -100  # 0 − 100


def test_empty_emits_nothing(runner, capsys) -> None:
    runner._emit_net_divergence_jsonl([])
    assert capsys.readouterr().out == ""
