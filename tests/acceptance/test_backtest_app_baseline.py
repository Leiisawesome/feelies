"""Locked APP 2026-03-26 backtest regression baseline (Phase 0).

Requires a populated disk cache for ``APP/2026-03-26`` (run once with
``run_backtest.py`` and ``--cache-dir``).  Uses ``configs/backtest_app.yaml``
parameter overrides for ``sig_benign_midcap_v1``.

Re-baseline only when the trade path, config contract, or input dataset
changes intentionally — update constants and ``parity_hash`` in one commit.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest

from feelies.core.platform_config import PlatformConfig
from feelies.harness import (
    compute_combined_parity_hash,
    compute_config_hash,
    compute_parity_hash,
    prepare_backtest_event_log,
)
from feelies.kernel.orchestrator import Orchestrator
from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache

_BASELINE_SYMBOL = "APP"
_BASELINE_DATE = "2026-03-26"
_BASELINE_CONFIG = Path("configs/backtest_app.yaml")
# NOTE (G-1 / 2026-06-08): the position-manager decision layer is now driven
# by default with cost-aware TRIM enabled (PlatformConfig.position_manager_*).
# This intentionally changes BOTH config_hash (new snapshot keys) and the
# trade path (partial reduces). The constants below are the PRE-G-1 baseline
# and MUST be regenerated against the disk-cache dataset before this
# functional test passes again:
#   uv run python scripts/run_backtest.py --config configs/backtest_app.yaml \
#       --symbol APP --date 2026-03-26
# then update _BASELINE_PARITY_HASH / _BASELINE_NET_PNL / _BASELINE_FILL_COUNT
# from the report in one commit.
#
# NOTE (G-7 S1 / 2026-06-10): the sizing-tilt config keys (sizer_tilt_drive,
# sizer_edge_*, sizer_vol_*, sizer_inventory_*, sizer_tilt_*) were added to
# the PlatformConfig snapshot.  They are all default-off and the live trade
# path is byte-identical (the size shadow is measurement-only), so pnl_hash,
# Net P&L ($15.07), and the fill count (6) are UNCHANGED — but config_hash
# (a hash of the full snapshot) shifts, so the combined _BASELINE_PARITY_HASH
# below must be regenerated against the disk-cache dataset in the same merge:
#   uv run python scripts/run_backtest.py --config configs/backtest_app.yaml \
#       --symbol APP --date 2026-03-26
# and updated here (only the parity hash changes).
_BASELINE_PARITY_HASH = "f0da57e10c01d421db64a6b2ffe0d8e32583d382f3fb07cef27ba9ec7b32e936"
_BASELINE_NET_PNL = Decimal("15.07")
_BASELINE_FILL_COUNT = 6


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "_backtest_app_baseline_runner",
        Path("scripts/run_backtest.py").resolve(),
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_backtest_app_baseline_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


def _net_pnl_from_orchestrator(orchestrator: Orchestrator) -> Decimal:
    """Mirror ``generate_report`` net PnL at flat book (gross − journal fees)."""
    all_pos = orchestrator.position_store.all_positions()
    gross_pnl = sum(
        (p.realized_pnl + p.unrealized_pnl for p in all_pos.values()),
        Decimal("0"),
    )
    journal = orchestrator.trade_journal
    assert journal is not None
    fees = sum((r.fees for r in journal.query()), Decimal("0"))
    return gross_pnl - fees


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


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


@pytest.mark.functional
def test_app_20260326_backtest_baseline_from_disk_cache(runner) -> None:
    """Replay APP 2026-03-26 from disk cache; pin parity_hash and PnL."""
    if not _BASELINE_CONFIG.exists():
        pytest.fail(f"Missing baseline config: {_BASELINE_CONFIG}")

    try:
        event_log, ingest_result, day_meta = load_event_log_from_disk_cache(
            [_BASELINE_SYMBOL],
            _BASELINE_DATE,
            _BASELINE_DATE,
        )
    except CacheReplayError as exc:
        pytest.skip(
            "Disk cache miss for APP/2026-03-26 — populate with:\n"
            "  uv run python scripts/run_backtest.py "
            f"--config {_BASELINE_CONFIG} --symbol {_BASELINE_SYMBOL} "
            f"--date {_BASELINE_DATE}\n"
            f"  ({exc})"
        )

    config = PlatformConfig.from_yaml(_BASELINE_CONFIG)
    symbols = sorted(config.symbols)
    day_sources = [
        runner.DaySource(
            symbol=m.symbol,
            date=m.date,
            source=m.source,
            event_count=m.event_count,
            ingestion_health=m.ingestion_health,
        )
        for m in day_meta
    ]

    prep = prepare_backtest_event_log(config, event_log)
    rc = runner._enforce_ingest_event_mix(
        config,
        prep.event_log,
        source_label="loaded from disk cache (baseline test)",
        n_quotes=prep.n_quotes,
        n_trades=prep.n_trades,
    )
    assert rc == 0

    config = runner._attach_day_source_provenance(config, symbols, day_sources)

    outcome = runner._run_backtest_phases_2_7(
        _cache_args(),
        event_log,
        ingest_result,
        day_sources,
        config,
        symbols,
        _BASELINE_SYMBOL,
        _BASELINE_DATE,
        time.monotonic(),
        prep=prep,
    )

    assert outcome.exit_code == 0

    journal = outcome.orchestrator.trade_journal
    assert journal is not None
    records = list(journal.query())
    assert len(records) == _BASELINE_FILL_COUNT

    parity_hash = compute_combined_parity_hash(
        compute_parity_hash(outcome.orchestrator),
        compute_config_hash(outcome.config),
    )
    assert parity_hash == _BASELINE_PARITY_HASH
    assert _net_pnl_from_orchestrator(outcome.orchestrator) == _BASELINE_NET_PNL
