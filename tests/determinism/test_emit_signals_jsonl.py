"""Unit tests for ``scripts/run_backtest.py::_emit_signals_jsonl``.

Verifies the canonical JSON shape emitted under
``--emit-signals-jsonl`` (Phase-3 Level-2 SIGNAL parity stream,
design_docs/three_layer_architecture.md §11.2):

* prefix ``SIGNAL_JSONL`` on every line,
* keys sorted (stable across Python versions),
* every Phase-3 provenance field present (layer, horizon_seconds,
  regime_gate_state, consumed_features, trend_mechanism,
  expected_half_life_seconds), and
* arrival order preserved.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from feelies.core.events import Signal, SignalDirection, TrendMechanism


# Load ``scripts/run_backtest.py`` as a module without executing main()
# (the script's top-level ``sys.path.insert(0, .../src)`` happens at
# import time, which is exactly what we want).
def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "_runner_emit_signals_test",
        Path("scripts/run_backtest.py").resolve(),
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_runner_emit_signals_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


def _legacy_signal(seq: int) -> Signal:
    """Construct a Signal with bare-minimum fields.

    Workstream D.2 PR-2b-ii: the historical ``LEGACY_SIGNAL`` layer was
    retired together with the per-tick composite engines; the default
    ``layer`` is now ``"SIGNAL"``.  The function name is preserved so the
    parity-stream tests (``test_emit_signals_jsonl_preserves_arrival_order``
    et al.) continue to read naturally as a mix of "bare-defaults" and
    "fully-populated Phase-3" rows.
    """
    return Signal(
        timestamp_ns=1_000 * seq,
        correlation_id=f"corr-{seq}",
        sequence=seq,
        symbol="AAPL",
        strategy_id="legacy_alpha",
        direction=SignalDirection.LONG,
        strength=0.5,
        edge_estimate_bps=3.5,
    )


def _phase3_signal(seq: int) -> Signal:
    return Signal(
        timestamp_ns=2_000 * seq,
        correlation_id=f"corr-h-{seq}",
        sequence=seq,
        symbol="MSFT",
        strategy_id="pofi_benign_midcap_v1",
        direction=SignalDirection.SHORT,
        strength=-0.7,
        edge_estimate_bps=8.25,
        layer="SIGNAL",
        horizon_seconds=120,
        regime_gate_state="ON",
        consumed_features=("ofi_ewma", "spread_z_30d"),
        trend_mechanism=TrendMechanism.KYLE_INFO,
        expected_half_life_seconds=180,
    )


def _make_recorder(runner, signals: list[Signal]):
    rec = runner.BusRecorder()
    for s in signals:
        rec(s)
    return rec


# ── Shape and prefix ────────────────────────────────────────────────────


def test_emit_signals_jsonl_prefix_and_count(runner, capsys) -> None:
    runner._emit_signals_jsonl(_make_recorder(runner, [
        _legacy_signal(1), _phase3_signal(2),
    ]))
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 2
    assert all(line.startswith("SIGNAL_JSONL ") for line in out)


def test_emit_signals_jsonl_default_row_shape(runner, capsys) -> None:
    """Bare-defaults row shape post-D.2 PR-2b-ii.

    Defaults: ``layer="SIGNAL"`` (was ``"LEGACY_SIGNAL"`` pre-D.2),
    horizon=0, ``regime_gate_state="N/A"``, no consumed features and
    no trend mechanism.  Other Phase-3 provenance keys remain present
    in the canonical sorted-keys serialization.
    """
    runner._emit_signals_jsonl(_make_recorder(runner, [_legacy_signal(7)]))
    line = capsys.readouterr().out.splitlines()[0]
    payload = json.loads(line[len("SIGNAL_JSONL "):])
    assert payload == {
        "consumed_features": [],
        "direction": "LONG",
        "edge_estimate_bps": 3.5,
        "expected_half_life_seconds": 0,
        "horizon_seconds": 0,
        "layer": "SIGNAL",
        "regime_gate_state": "N/A",
        "sequence": 7,
        "strategy_id": "legacy_alpha",
        "strength": 0.5,
        "symbol": "AAPL",
        "trend_mechanism": None,
    }


def test_emit_signals_jsonl_phase3_row_shape(runner, capsys) -> None:
    runner._emit_signals_jsonl(_make_recorder(runner, [_phase3_signal(11)]))
    line = capsys.readouterr().out.splitlines()[0]
    payload = json.loads(line[len("SIGNAL_JSONL "):])
    assert payload["layer"] == "SIGNAL"
    assert payload["horizon_seconds"] == 120
    assert payload["regime_gate_state"] == "ON"
    assert payload["consumed_features"] == ["ofi_ewma", "spread_z_30d"]
    assert payload["trend_mechanism"] == "KYLE_INFO"
    assert payload["expected_half_life_seconds"] == 180
    assert payload["direction"] == "SHORT"


def test_emit_signals_jsonl_keys_sorted(runner, capsys) -> None:
    runner._emit_signals_jsonl(_make_recorder(runner, [_phase3_signal(3)]))
    line = capsys.readouterr().out.splitlines()[0]
    raw = line[len("SIGNAL_JSONL "):]
    payload = json.loads(raw)
    assert raw == json.dumps(payload, sort_keys=True)


def test_emit_signals_jsonl_preserves_arrival_order(runner, capsys) -> None:
    sigs = [_legacy_signal(1), _phase3_signal(2), _legacy_signal(3)]
    runner._emit_signals_jsonl(_make_recorder(runner, sigs))
    lines = capsys.readouterr().out.splitlines()
    seqs = [json.loads(line[len("SIGNAL_JSONL "):])["sequence"] for line in lines]
    assert seqs == [1, 2, 3]


def test_emit_signals_jsonl_empty(runner, capsys) -> None:
    runner._emit_signals_jsonl(_make_recorder(runner, []))
    assert capsys.readouterr().out == ""


# ── Composability ──────────────────────────────────────────────────────


def test_emit_phase2_jsonl_dispatches_to_signals_emitter(runner, capsys) -> None:
    """Verify the new flag is wired into the composable phase-2 wrapper."""
    import argparse
    args = argparse.Namespace(
        emit_sensor_readings_jsonl=False,
        emit_horizon_ticks_jsonl=False,
        emit_snapshots_jsonl=False,
        emit_signals_jsonl=True,
        emit_hazard_spikes_jsonl=False,
    )
    runner._emit_phase2_jsonl(args, _make_recorder(runner, [_phase3_signal(5)]))
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    assert out[0].startswith("SIGNAL_JSONL ")


def test_emit_phase2_jsonl_skips_signals_when_flag_off(runner, capsys) -> None:
    import argparse
    args = argparse.Namespace(
        emit_sensor_readings_jsonl=False,
        emit_horizon_ticks_jsonl=False,
        emit_snapshots_jsonl=False,
        emit_signals_jsonl=False,
        emit_hazard_spikes_jsonl=False,
    )
    runner._emit_phase2_jsonl(args, _make_recorder(runner, [_phase3_signal(5)]))
    assert capsys.readouterr().out == ""
