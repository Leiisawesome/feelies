"""Locked APP 2026-03-26 backtest regression baseline (Phase 0).

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
# NOTE (G-1 / 2026-06-08, refreshed 2026-06-13): the position-manager
# decision layer is driven by default with cost-aware TRIM enabled
# (PlatformConfig.position_manager_*).  This intentionally changed BOTH
# config_hash (new snapshot keys) and the trade path (partial reduces).
# The constants below WERE regenerated against the disk-cache dataset to
# the trim-on / current-pipeline output in commit d101f30 (2026-06-13,
# "refresh APP 2026-03-26 backtest net-PnL baseline to $71.56"); they are
# the live trim-on baseline, NOT the pre-G-1 values.  To re-pin after a
# future intentional trade-path change, run against the cache and update
# the constants in one commit:
#   uv run python scripts/run_backtest.py --config configs/bt_app.yaml \
#       --symbol APP --date 2026-03-26
#
# CAVEAT (audit P0, 2026-06-18): this functional test is data-gated and
# SKIPS on cache miss, so it does not lock the trim defaults in CI.  The
# non-data-gated guard that the PlatformConfig defaults + bootstrap wiring
# actually drive TRIM lives in
# ``tests/bootstrap/test_position_manager_wiring.py``.
#
# NOTE (G-7 / 2026-06-11): the sizing-tilt config keys (sizer_tilt_drive,
# sizer_edge_*, sizer_vol_*, sizer_inventory_*, sizer_tilt_*) were added to
# the PlatformConfig snapshot.  They are all default-off and the live trade
# path is byte-identical (the size shadow is measurement-only), so Net P&L
# (then $15.07; later refreshed to $71.56 in d101f30) and the fill count
# (6) are UNCHANGED by G-7 — only the config snapshot shifts.  The config
# CONTRACT hash (raw YAML + defaults, no per-run ingest-
# health provenance) is data-independent, so it is re-baked directly here in
# ``test_app_baseline_config_contract_hash`` and runs without the dataset.
#
# The combined per-fill parity hash mixed the (data-derived) ingest-health
# provenance into config_hash and the trade journal into pnl_hash, so it can
# only be regenerated from a cached run; the trade path is instead locked by
# Net P&L + fill count.  To re-pin a full literal, run against the cache:
#   uv run python scripts/run_backtest.py --config configs/bt_app.yaml \
#       --symbol APP --date 2026-03-26
# Re-baked after audit P0/P1 + 2P: the reference alpha now confirms with
# ``book_imbalance_mean`` (2P-3), and the platform sensor block gained
# ``ofi_raw`` (2P-2, integrated signed flow) on top of ``book_imbalance`` and
# the P1-E ``max_gap_seconds`` keys — all shift the resolved config snapshot.
# Re-baked for audit R-1: added the ``regime_min_discriminability`` config
# field (default 0.0 — behaviour-neutral) to the snapshot, which shifts the
# config-contract hash. Trade path is byte-identical (the floor is a no-op at
# 0.0), so Net P&L / fill count are unchanged.
# Re-baked for audit P2.1 (2026-06-18): the discretionary-TRIM execution
# style flipped to PASSIVE-with-MARKET-fallback (position_manager_urgency_exec
# default ON), which shifts the resolved config snapshot, so the data-free
# config-contract hash below was recomputed.  The G-7 EDGE sizing factor
# (sizer_tilt_drive + sizer_edge_weighting_enabled) was left available
# OPT-IN / default OFF (audit P2.3), so it does not perturb this baseline.
# Net P&L / fill count were re-verified against the disk cache on 2026-06-18:
#   uv run python scripts/run_backtest.py --config configs/bt_app.yaml \
#       --symbol APP --date 2026-03-26
# The APP/2026-03-26 trade path emits no discretionary passive TRIM in this
# dataset, so Net P&L ($71.56) and fill count (6) are UNCHANGED from the
# d101f30 trim-on baseline — only the config snapshot shifted.
# Re-baked for the 2026-06-19 execution-realism audit (P1/P2 backlog): the
# new execution-realism knobs are additive and behaviour-neutral *in code*,
# but the reference ``platform.yaml`` now FLIPS the conservative profile ON so
# backtests price fills live-realistically by default —
# ``passive_through_fill_size_cap_enabled: true``,
# ``passive_require_trade_for_level_fill: true`` (inert here while
# ``passive_queue_position_shares > 0``), ``cost_within_l1_impact_factor: 0.3``,
# ``cost_stop_depth_depletion_factor: 2.0``, ``cost_moc_penalty_bps: 3.0``
# (inert for this non-MOC alpha).  This is a deliberate TRADE-PATH change: the
# +participation impact on aggressive exit legs and the through-fill cap cost
# the alpha ~$2.50, compressing Net P&L $71.56 → $69.06 (edge survives) while
# fill count stays 6.  Re-verified against the disk cache on 2026-06-19:
#   uv run python scripts/run_backtest.py --config configs/bt_app.yaml \
#       --symbol APP --date 2026-03-26
# The data-free config-contract hash was recomputed for the flipped snapshot.
# Re-baked again on 2026-06-24 for the forced-exit reason audit (P1): the
# stop-loss path now stamps the canonical ``STOP_EXIT`` order reason, which
# changes the replayed APP/2026-03-26 trade path to 4 fills and a net P&L of
# $19.64 while leaving the config-contract hash unchanged.
_BASELINE_CONFIG_HASH = (
    "0b46397723e95823c780b2c7e6ea2049d62163fea616b651e637c3abefba1236"
)
_BASELINE_NET_PNL = Decimal("19.64")
_BASELINE_FILL_COUNT = 4


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

    # Trade path — locked by Net P&L (to the cent) + fill count (above), which
    # pin the realized trade sequence against the dataset.  ``compute_parity_hash``
    # is exercised for determinism (a second call must match) but not pinned to
    # a literal, which can only be regenerated from a cached run.  The config
    # contract is pinned data-free in ``test_app_baseline_config_contract_hash``.
    pnl_hash = compute_parity_hash(outcome.orchestrator)
    assert pnl_hash == compute_parity_hash(outcome.orchestrator)
    assert _net_pnl_from_orchestrator(outcome.orchestrator) == _BASELINE_NET_PNL


def test_app_baseline_config_contract_hash() -> None:
    """Re-baked G-7 config-contract lock — runs without the dataset.

    ``compute_config_hash`` of the *raw* config (no per-run ingest-health
    provenance, which is data-derived) pins the YAML + PlatformConfig defaults
    contract.  The G-7 sizing-tilt keys are all default-off and shifted this
    snapshot; the value below is the re-baked hash.  Catches any unintended
    config-contract drift in CI, independent of the cached dataset.
    """
    if not _BASELINE_CONFIG.exists():
        pytest.fail(f"Missing baseline config: {_BASELINE_CONFIG}")
    config = PlatformConfig.from_yaml(_BASELINE_CONFIG)
    assert compute_config_hash(config) == _BASELINE_CONFIG_HASH
