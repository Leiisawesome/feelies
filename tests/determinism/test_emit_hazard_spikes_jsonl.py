"""Unit tests for ``scripts/run_backtest.py::_emit_hazard_spikes_jsonl``.

Verifies the canonical JSON shape emitted under
``--emit-hazard-spikes-jsonl`` (Phase-3.1 Level-5 hazard parity stream,
docs/three_layer_architecture.md §20.11.2):

* prefix ``HAZARD_JSONL`` on every line,
* keys sorted (stable across Python versions),
* every Phase-3.1 hazard provenance field present
  (sequence, symbol, engine_name, departing_state,
  departing_posterior_prev/now, incoming_state, hazard_score,
  timestamp_ns, correlation_id), and
* arrival order preserved.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from feelies.core.events import RegimeHazardSpike


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "_runner_emit_hazard_spikes_test",
        Path("scripts/run_backtest.py").resolve(),
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_runner_emit_hazard_spikes_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


def _spike(seq: int, *, incoming: str | None = "state_calm") -> RegimeHazardSpike:
    return RegimeHazardSpike(
        timestamp_ns=10_000 * seq,
        correlation_id=f"haz-{seq}",
        sequence=seq,
        symbol="AAPL",
        engine_name="primary",
        departing_state="state_active",
        departing_posterior_prev=0.92,
        departing_posterior_now=0.31,
        incoming_state=incoming,
        hazard_score=0.69,
    )


def _make_recorder(runner, spikes: list[RegimeHazardSpike]):
    rec = runner.BusRecorder()
    for s in spikes:
        rec(s)
    return rec


# ── Shape and prefix ────────────────────────────────────────────────────


def test_emit_hazard_spikes_jsonl_prefix_and_count(runner, capsys) -> None:
    runner._emit_hazard_spikes_jsonl(_make_recorder(runner, [_spike(1), _spike(2)]))
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 2
    assert all(line.startswith("HAZARD_JSONL ") for line in out)


def test_emit_hazard_spikes_jsonl_row_shape(runner, capsys) -> None:
    runner._emit_hazard_spikes_jsonl(_make_recorder(runner, [_spike(7)]))
    line = capsys.readouterr().out.splitlines()[0]
    payload = json.loads(line[len("HAZARD_JSONL "):])
    assert payload == {
        "correlation_id": "haz-7",
        "departing_posterior_now": 0.31,
        "departing_posterior_prev": 0.92,
        "departing_state": "state_active",
        "engine_name": "primary",
        "hazard_score": 0.69,
        "incoming_state": "state_calm",
        "sequence": 7,
        "symbol": "AAPL",
        "timestamp_ns": 70_000,
    }


def test_emit_hazard_spikes_jsonl_handles_none_incoming(runner, capsys) -> None:
    runner._emit_hazard_spikes_jsonl(
        _make_recorder(runner, [_spike(3, incoming=None)])
    )
    line = capsys.readouterr().out.splitlines()[0]
    payload = json.loads(line[len("HAZARD_JSONL "):])
    assert payload["incoming_state"] is None


def test_emit_hazard_spikes_jsonl_keys_sorted(runner, capsys) -> None:
    runner._emit_hazard_spikes_jsonl(_make_recorder(runner, [_spike(3)]))
    raw = capsys.readouterr().out.splitlines()[0][len("HAZARD_JSONL "):]
    payload = json.loads(raw)
    assert raw == json.dumps(payload, sort_keys=True)


def test_emit_hazard_spikes_jsonl_preserves_arrival_order(runner, capsys) -> None:
    runner._emit_hazard_spikes_jsonl(
        _make_recorder(runner, [_spike(1), _spike(2), _spike(3)])
    )
    seqs = [
        json.loads(line[len("HAZARD_JSONL "):])["sequence"]
        for line in capsys.readouterr().out.splitlines()
    ]
    assert seqs == [1, 2, 3]


def test_emit_hazard_spikes_jsonl_empty(runner, capsys) -> None:
    runner._emit_hazard_spikes_jsonl(_make_recorder(runner, []))
    assert capsys.readouterr().out == ""


# ── Composability ──────────────────────────────────────────────────────


def test_emit_phase2_jsonl_dispatches_to_hazard_emitter(runner, capsys) -> None:
    """The Phase-3.1 flag must compose with the prior emitter wrapper."""
    import argparse
    args = argparse.Namespace(
        emit_sensor_readings_jsonl=False,
        emit_horizon_ticks_jsonl=False,
        emit_snapshots_jsonl=False,
        emit_signals_jsonl=False,
        emit_hazard_spikes_jsonl=True,
    )
    runner._emit_phase2_jsonl(args, _make_recorder(runner, [_spike(5)]))
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    assert out[0].startswith("HAZARD_JSONL ")


def test_emit_phase2_jsonl_skips_hazards_when_flag_off(runner, capsys) -> None:
    import argparse
    args = argparse.Namespace(
        emit_sensor_readings_jsonl=False,
        emit_horizon_ticks_jsonl=False,
        emit_snapshots_jsonl=False,
        emit_signals_jsonl=False,
        emit_hazard_spikes_jsonl=False,
    )
    runner._emit_phase2_jsonl(args, _make_recorder(runner, [_spike(5)]))
    assert capsys.readouterr().out == ""


# ── CLI parsing ────────────────────────────────────────────────────────


def test_cli_parses_emit_hazard_spikes_jsonl_flag(runner) -> None:
    """`--emit-hazard-spikes-jsonl` must be a recognized argparse flag."""
    args = runner.parse_args(
        ["--date", "2024-01-15", "--emit-hazard-spikes-jsonl"]
    )
    assert args.emit_hazard_spikes_jsonl is True


def test_cli_emit_hazard_spikes_jsonl_default_false(runner) -> None:
    args = runner.parse_args(["--date", "2024-01-15"])
    assert args.emit_hazard_spikes_jsonl is False
