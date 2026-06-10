"""Unit tests for ``_emit_size_divergence_jsonl`` (G-7 measurement stream).

Verifies the ``SIZEDIV_JSONL`` stream emitted under
``--emit-size-divergence-jsonl``: prefix on every line, sorted keys,
``magnitude = tilted − base``, and record order preserved.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from feelies.risk.edge_weighted_sizer import SizeDivergence


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "_runner_emit_sizediv_test",
        Path("scripts/run_backtest.py").resolve(),
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_runner_emit_sizediv_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


def _div(seq: int, base: int, tilted: int, *, ts: int = 1_717_200_000_000_000_000) -> SizeDivergence:
    return SizeDivergence(
        symbol="AAPL",
        signal_sequence=seq,
        strategy_id="alpha_a",
        edge_bps=40.0,
        base_target_qty=base,
        tilted_target_qty=tilted,
        edge_factor=2.0,
        vol_factor=1.0,
        inventory_factor=1.0,
        combined_tilt=2.0,
        inventory_qty=0,
        timestamp_ns=ts,
    )


def test_prefix_and_order(runner, capsys) -> None:
    runner._emit_size_divergence_jsonl([_div(1, 100, 200), _div(2, 100, 50)])
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 2
    assert all(line.startswith("SIZEDIV_JSONL ") for line in out)
    seqs = [json.loads(ln[len("SIZEDIV_JSONL "):])["signal_sequence"] for ln in out]
    assert seqs == [1, 2]


def test_row_shape_and_magnitude(runner, capsys) -> None:
    runner._emit_size_divergence_jsonl([_div(7, 100, 200)])
    payload = json.loads(
        capsys.readouterr().out.splitlines()[0][len("SIZEDIV_JSONL "):]
    )
    assert payload == {
        "timestamp_ns": 1_717_200_000_000_000_000,
        "signal_sequence": 7,
        "symbol": "AAPL",
        "strategy_id": "alpha_a",
        "edge_bps": 40.0,
        "base_target_qty": 100,
        "tilted_target_qty": 200,
        "magnitude": 100,          # tilted − base
        "edge_factor": 2.0,
        "vol_factor": 1.0,
        "inventory_factor": 1.0,
        "combined_tilt": 2.0,
        "inventory_qty": 0,
    }


def test_downsize_magnitude_is_signed(runner, capsys) -> None:
    runner._emit_size_divergence_jsonl([_div(1, 100, 50)])
    payload = json.loads(
        capsys.readouterr().out.splitlines()[0][len("SIZEDIV_JSONL "):]
    )
    assert payload["magnitude"] == -50


def test_empty_emits_nothing(runner, capsys) -> None:
    runner._emit_size_divergence_jsonl([])
    assert capsys.readouterr().out == ""
