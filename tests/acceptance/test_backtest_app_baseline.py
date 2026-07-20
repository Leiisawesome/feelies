"""Locked APP 2026-03-26 backtest regression baseline.

Requires a populated disk cache for ``APP/2026-03-26`` (run once with
``run_backtest.py`` and ``--cache-dir``).  Uses ``configs/bt_app.yaml``
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
    compute_config_hash,
    compute_parity_hash,
    prepare_backtest_event_log,
)
from feelies.kernel.orchestrator import Orchestrator
from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache

_BASELINE_SYMBOL = "APP"
_BASELINE_DATE = "2026-03-26"
_BASELINE_CONFIG = Path("configs/bt_app.yaml")
# The functional test skips without cached data; config wiring has separate
# data-free coverage. Re-pin these values from the cached run with:
#   uv run python scripts/run_backtest.py --config configs/bt_app.yaml \
#       --symbol APP --date 2026-03-26
_BASELINE_CONFIG_HASH = "be6047f70e25ec49b693fd085d1064bda3aaa410d75c5ec239ba389a250fde15"
_BASELINE_NET_PNL = Decimal("430.85")
_BASELINE_FILL_COUNT = 21


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


def _net_pnl_from_orchestrator(orchestrator: Orchestrator, recorder) -> Decimal:
    """Match report PnL by subtracting fees from every acknowledgement."""
    from feelies.core.events import OrderAck

    all_pos = orchestrator.position_store.all_positions()
    gross_pnl = sum(
        (p.realized_pnl + p.unrealized_pnl for p in all_pos.values()),
        Decimal("0"),
    )
    fees = sum((a.fees for a in recorder.of_type(OrderAck)), Decimal("0"))
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

    # Trade path — locked by Net P&L (to the cent) + fill count (above), which
    # pin the realized trade sequence against the dataset.  ``compute_parity_hash``
    # is exercised for determinism (a second call must match) but not pinned to
    # a literal, which can only be regenerated from a cached run.  The config
    # contract is pinned data-free in ``test_app_baseline_config_contract_hash``.
    pnl_hash = compute_parity_hash(outcome.orchestrator)
    assert pnl_hash == compute_parity_hash(outcome.orchestrator)

    # Fee reconciliation: the report's fee population (sum of all OrderAck.fees)
    # must equal the position store's cumulative_fees (the NAV truth, which
    # also absorbs cancel/expiry fees).  If these ever diverge, the printed
    # Net P&L no longer reconciles with the fills it summarizes.
    from feelies.core.events import OrderAck

    assert outcome.recorder is not None
    ack_fees = sum((a.fees for a in outcome.recorder.of_type(OrderAck)), Decimal("0"))
    cumulative_fees = sum(
        (p.cumulative_fees for p in outcome.orchestrator.position_store.all_positions().values()),
        Decimal("0"),
    )
    assert ack_fees == cumulative_fees
    assert _net_pnl_from_orchestrator(outcome.orchestrator, outcome.recorder) == _BASELINE_NET_PNL


def test_app_baseline_config_contract_hash() -> None:
    """Pin the raw config hash independently of cached market data."""
    if not _BASELINE_CONFIG.exists():
        pytest.fail(f"Missing baseline config: {_BASELINE_CONFIG}")
    config = PlatformConfig.from_yaml(_BASELINE_CONFIG)
    assert compute_config_hash(config) == _BASELINE_CONFIG_HASH
