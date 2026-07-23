"""Unit tests for ``feelies.harness.backtest_runner``."""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

from feelies.harness.backtest_runner import _run_backtest_phases_2_7
from feelies.ingestion.massive_ingestor import IngestResult
from feelies.kernel.orchestrator import Orchestrator

_REPO = Path(__file__).resolve().parents[2]
_SMOKE = _REPO / "scripts" / "smoke_pipeline.py"


def _load_smoke():
    spec = importlib.util.spec_from_file_location("smoke_pipeline_runner_test", _SMOKE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["smoke_pipeline_runner_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_smoke_alphas(mod, tmp_path: Path) -> list[Path]:
    paths: list[Path] = []
    for name, yaml in (
        ("smoke_always_on_v1", mod._SMOKE_SIGNAL_YAML),
        ("smoke_portfolio_feeder_v1", mod._SMOKE_FEEDER_YAML),
        ("smoke_portfolio_v1", mod._SMOKE_PORTFOLIO_YAML),
    ):
        p = tmp_path / f"{name}.alpha.yaml"
        p.write_text(yaml, encoding="utf-8")
        paths.append(p)
    return paths


def _cache_args() -> argparse.Namespace:
    return argparse.Namespace(
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


def _build_phase_inputs(mod, tmp_path: Path):
    """Assemble the (config, event_log, symbols, ...) inputs
    ``_run_backtest_phases_2_7`` needs, reusing smoke_pipeline's synthetic
    alphas/events/sensors but routed through the *real* harness phase
    machinery (unlike ``smoke_pipeline._build``, which bypasses it)."""
    from feelies.core.platform_config import OperatingMode, PlatformConfig
    from feelies.storage.memory_event_log import InMemoryEventLog

    paths = _write_smoke_alphas(mod, tmp_path)
    config = PlatformConfig(
        symbols=frozenset(mod._SYMBOLS),
        mode=OperatingMode.BACKTEST,
        alpha_specs=paths,
        regime_engine="hmm_3state_fractional",
        sensor_specs=mod._SENSOR_SPECS,
        horizons_seconds=frozenset({30, 120, 300}),
        session_open_ns=mod.SESSION_OPEN_NS,
        account_equity=100_000.0,
        enforce_trend_mechanism=False,
        session_kind="EXT",  # avoid RTH-filtering synthetic timestamps
    )
    synth_events = mod._synth_events(seed=42)
    event_log = InMemoryEventLog()
    event_log.append_batch(synth_events)

    symbols = sorted(mod._SYMBOLS)
    ingest_result = IngestResult(
        events_ingested=len(synth_events),
        pages_processed=0,
        symbols_with_gaps=0,
        duplicates_filtered=0,
        symbols_completed=frozenset(symbols),
    )
    return config, event_log, symbols, ingest_result


def test_run_backtest_phases_prints_clean_message_and_exits_nonzero_on_integrity_failure(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """A pipeline integrity exception must produce a clear
    labeled error line (in addition to the traceback) and a controlled nonzero
    exit code, rather than only an uncaught traceback."""
    mod = _load_smoke()
    config, event_log, symbols, ingest_result = _build_phase_inputs(mod, tmp_path)

    def _raise(self: Orchestrator) -> None:
        raise RuntimeError("synthetic integrity failure for test")

    monkeypatch.setattr(Orchestrator, "run_backtest", _raise)

    outcome = _run_backtest_phases_2_7(
        _cache_args(),
        event_log,
        ingest_result,
        [],
        config,
        symbols,
        ", ".join(symbols),
        "test-date",
        time.monotonic(),
    )

    assert outcome.exit_code == 1
    captured = capsys.readouterr()
    assert "ERROR: Backtest integrity failure: RuntimeError" in captured.err
    assert "synthetic integrity failure for test" in captured.err
    # The full traceback must still be available for diagnosis.
    assert "Traceback (most recent call last)" in captured.err
    assert "RuntimeError: synthetic integrity failure for test" in captured.err


def test_run_backtest_phases_prints_partial_diagnostics_when_degraded_without_exception(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """A run that ends DEGRADED without raising
    ``generate_report`` is never reached on this path) must still surface
    basic triage counts, not just a one-line macro-state error."""
    from feelies.kernel.macro import MacroState

    mod = _load_smoke()
    config, event_log, symbols, ingest_result = _build_phase_inputs(mod, tmp_path)

    real_run_backtest = Orchestrator.run_backtest

    def _run_then_degrade(self: Orchestrator) -> None:
        # Run the real pipeline (so signals/orders/fills actually occur),
        # then simulate an integrity gap that leaves macro non-READY without
        # raising, which is a distinct failure shape.
        real_run_backtest(self)
        self._macro._state = MacroState.DEGRADED

    monkeypatch.setattr(Orchestrator, "run_backtest", _run_then_degrade)

    outcome = _run_backtest_phases_2_7(
        _cache_args(),
        event_log,
        ingest_result,
        [],
        config,
        symbols,
        ", ".join(symbols),
        "test-date",
        time.monotonic(),
    )

    assert outcome.exit_code == 1
    captured = capsys.readouterr()
    assert "ERROR: Backtest ended in macro state DEGRADED" in captured.err
    assert "PARTIAL/UNTRUSTED DIAGNOSTICS" in captured.err
    assert "Signals emitted" in captured.err
    assert "Orders submitted" in captured.err
    assert "Fills" in captured.err
    assert "Kill switch" in captured.err
