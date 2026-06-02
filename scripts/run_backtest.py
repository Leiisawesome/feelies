#!/usr/bin/env python3
"""Backtest runner CLI — thin wrapper over :mod:`feelies.harness.backtest_runner`.

Usage:
    python scripts/run_backtest.py --symbol AAPL --date 2024-01-15
    uv run feelies backtest --symbol AAPL --date 2024-01-15

Implementation lives under ``src/feelies/harness/``; this script remains for
backward-compatible ``importlib`` loading in tests and operator runbooks.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from feelies.harness.backtest_jsonl import (  # noqa: E402
    _emit_cross_sectional_jsonl,
    _emit_fills_jsonl,
    _emit_hazard_exits_jsonl,
    _emit_hazard_spikes_jsonl,
    _emit_horizon_ticks_jsonl,
    _emit_phase2_jsonl,
    _emit_sensor_readings_jsonl,
    _emit_signals_jsonl,
    _emit_snapshots_jsonl,
    _emit_sized_intents_jsonl,
)
from feelies.harness.backtest_prep import prepare_backtest_event_log  # noqa: E402
from feelies.harness.backtest_report import (  # noqa: E402
    compute_combined_parity_hash,
    compute_config_hash,
    compute_parity_hash,
    dedupe_republished_signal_events as _dedupe_republished_signal_events,
)
from feelies.harness.backtest_runner import (  # noqa: E402
    BacktestRunOutcome,
    BusRecorder,
    DaySource,
    _attach_day_source_provenance,
    _enforce_ingest_event_mix,
    _run_backtest_phases_2_7,
    main,
    main_cache_replay,
    parse_args,
    parse_cache_replay_args,
)

__all__ = [
    "BacktestRunOutcome",
    "BusRecorder",
    "DaySource",
    "_attach_day_source_provenance",
    "_dedupe_republished_signal_events",
    "_emit_cross_sectional_jsonl",
    "_emit_fills_jsonl",
    "_emit_hazard_exits_jsonl",
    "_emit_hazard_spikes_jsonl",
    "_emit_horizon_ticks_jsonl",
    "_emit_phase2_jsonl",
    "_emit_sensor_readings_jsonl",
    "_emit_signals_jsonl",
    "_emit_snapshots_jsonl",
    "_emit_sized_intents_jsonl",
    "_enforce_ingest_event_mix",
    "_run_backtest_phases_2_7",
    "compute_combined_parity_hash",
    "compute_config_hash",
    "compute_parity_hash",
    "main",
    "main_cache_replay",
    "parse_args",
    "parse_cache_replay_args",
    "prepare_backtest_event_log",
]

if __name__ == "__main__":
    sys.exit(main())
