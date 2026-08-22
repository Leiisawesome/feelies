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
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import NoReturn

import pytest

from feelies.core.platform_config import PlatformConfig
from feelies.harness import (
    compute_config_hash,
    compute_parity_hash,
    prepare_backtest_event_log,
)
from feelies.harness.backtest_report import cache_data_version
from feelies.kernel.orchestrator import Orchestrator
from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache

_BASELINE_SYMBOL = "APP"
_BASELINE_DATE = "2026-03-26"
_BASELINE_CONFIG = Path("configs/bt_app.yaml")
# The functional test skips without cached data; config wiring has separate
# data-free coverage. Re-pin these values from the cached run with:
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
# Re-baked on 2026-06-29 against the current APP/2026-03-26 disk-cache output
# after the L1->L2 boundary-time/latch regression audit.  The current trade
# path pins 21 journal records and $430.85 net P&L.
#
# Re-baked 2026-07-02 (sensor_audit_2026-07-02 P1): platform.yaml's
# quote_replenish_asymmetry / quote_hazard_rate / quote_flicker_rate sensor
# specs gained an opt-in min_window_span_seconds param (set to 5s in
# production), shifting the resolved config hash. Config-contract change
# only — sig_benign_midcap_v1 (the alpha this baseline backtests) does not
# depend on any of those three sensors, so the trade path / P&L pins above
# are unaffected.
#
# Re-baked again 2026-07-02 (sensor_audit_2026-07-02 P2): platform.yaml's
# scheduled_flow_window sensor spec gained throttled_ms=1000 (verified safe:
# its update() reads no state at all). Config-contract change only —
# sig_benign_midcap_v1 does not depend on this sensor either.
#
# Re-baked again 2026-07-02 (sensor_review_2026-07-02 F1): platform.yaml's
# kyle_lambda_60s sensor bumped 2.0.0 → 2.1.0 (causal alignment +
# numerically-stable Welford covariance estimator; equal to the 2.0.0 slope
# in exact arithmetic, but without the sum-of-products denominator
# cancellation). Config-contract change only — sig_benign_midcap_v1 does not
# depend on kyle_lambda_60s, so the trade path / P&L pins above are unaffected.
#
# Re-baked 2026-07-25: the F1 value above was pinned on the sensor-audit branch
# *before* it merged main (dc347ec).  That merge brought in `prune_unused_sensors`
# (6436154), which `PlatformConfig._to_dict()` discloses, so the resolved
# snapshot gained one key and the pin went stale on the merge commit rather
# than on any later change.  The added key is the sole snapshot delta between
# the F1 tree and this one; every other field is identical.
#
# CAVEAT — unlike the three re-bakes above, this one is NOT provenance-only.
# `configs/bt_sig_benign_midcap.yaml` (which bt_app.yaml extends) has long set
# `prune_unused_sensors: true`, but the key was inert until 6436154 added the
# PlatformConfig field and the bootstrap helper; it now actually drops sensor
# specs no loaded SIGNAL alpha declares.  6436154 (2026-07-19) postdates the
# commit that pinned _BASELINE_NET_PNL / _BASELINE_FILL_COUNT (08c3da6,
# 2026-06-29), so those two pins have NOT been re-verified since pruning went
# live.  They are deliberately left untouched here: this environment has no
# APP/2026-03-26 disk cache, so the data-gated test skips and cannot confirm
# or refute them.  Re-verify against a cached run before trusting them:
#   uv run python scripts/run_backtest.py --config configs/bt_app.yaml \
#       --symbol APP --date 2026-03-26
#
# Re-pinned 2026-07-25 (net PnL only): 430.85 -> 363.34.  This is the re-verification
# the CAVEAT above asks for, run against a real APP/2026-03-26 disk cache — and it
# found a behavioural change, not pruning drift.
#
# Cause: fills never reached `StrategyPositionStore`, so
# `standalone_signal_actionable_for_strategy` (alpha/arbitration.py) evaluated
# `_signal_reduces_book(strategy_qty=0, ...)` — always False — and **silently
# suppressed every directional reducing exit from a standalone alpha**.  Populating
# the slice book on single-strategy fills un-blocks those exits, which is what that
# function documents ("directional exits likewise require matching strategy
# exposure").  The old 430.85 encodes the suppressed-exit bug: the alpha was holding
# positions it should have exited, which flattered PnL on this session.
#
# Gross realized 536.31 -> 468.80; fees unchanged at 105.46.  `_BASELINE_FILL_COUNT`
# and the parity hash are **unchanged** — same number of fills, same replay stream;
# only which exits were actionable moved.  Per-alpha budgets in
# `AlphaBudgetRiskWrapper` also became computable for the first time, but measured on
# this cell none bind, so they are not part of this delta.
# See docs/research/stage0_residual_2026-07-25.md §1.8.1.
# Re-baselined when ``edge_calibration_path`` became a real ``PlatformConfig``
# field.  The config snapshot gained one key (value ``None`` for this run), so the
# contract hash moves by construction — no configured value changed, and
# ``_BASELINE_NET_PNL`` / ``_BASELINE_FILL_COUNT`` are unaffected.  Before the
# field existed, bootstrap probed it with ``getattr`` and ``from_yaml`` rejected
# it as an unknown key, so the forensics -> B4-gate loop was unreachable from
# configuration and only the backtest CLI could supply factors (Inv-9).
# Re-baselined again when ``position_manager_drive`` was removed: the planner is
# now the only decision path, so the flag left the config surface and the
# snapshot lost a key.  No configured value changed and no trade-path behaviour
# moved — the flag's production default was already ``True``.
# Re-baselined 2026-08-12 -- ``platform_min_order_shares`` stopped inflating sized
# targets.  This is a deliberate behaviour change, not drift, and it moves every
# constant below.
#
# The floor used to raise any nonzero sized target up to itself
# (``_compute_target_quantity``).  platform.yaml set it to 50; at 50,000 equity
# and APP near $396 this alpha's declared ``capital_allocation_pct: 25.0`` asks
# for 15-31 shares depending on strength, so *every* target was raised to 50.
# The floor, not the risk budget, decided position size -- any allocation below
# ~39.6% produced an identical 50-share order -- and the book carried 2.4x the
# size the alpha had declared.  A control that autonomously *increases* exposure
# beyond a declared risk budget is a loosening, and Inv-11 reserves loosening for
# a human.  The floor is now a venue lot-size veto only (1 share, US equities)
# and never raises a target; economic viability is the B4 gate's job.
#
# Measured sweep on this exact cell, floor -> (shares, net):
#     1 or 10 -> (394, $103.93)   25 -> (512, $173.56)   50 -> (960, $363.34)
# Fill count is 20 at every floor: the clamp never gated *whether* the alpha
# traded, only how much.
#
# So the prior 363.34 was the alpha trading 960 shares against a budget that
# sanctioned 394.  103.93 is what ``capital_allocation_pct: 25.0`` actually buys
# on this session.  Gross 468.80 -> 149.05, fees 105.46 -> 45.12.  The trade
# journal loses one record (21 -> 20): the old run left one order submitted and
# unfilled, the new one does not.  ``config_hash`` moves because
# ``platform_min_order_shares`` is part of the config snapshot.  Note this
# constant pins the raw ``from_yaml`` snapshot; the operator report prints the
# post-CLI-override hash, which is a different value for the same run.
_BASELINE_CONFIG_HASH = "89d43554e749134925b9407c9e810a2fa2e7ce56a3efa26bf596818d0e3cd64c"
_BASELINE_TRADE_PARITY_HASH = "0601295a20b518ea4b6997cbd1aff145049570de044a0766a16b566a3ba17df3"
# Content-bound identifier for the input tape (per-day event counts + ingestion
# health). Distinct from the parity hashes: this pins what went *in*.
_BASELINE_DATA_VERSION = "cache:2364ef7fe41c27d9"
_BASELINE_NET_PNL = Decimal("103.93")
_BASELINE_FILL_COUNT = 20


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


def _missing_cache(exc: Exception) -> NoReturn:
    """Skip on a cache miss -- unless the caller demanded the oracle actually run.

    This test is the platform's parity oracle, and until 2026-08-12 it had three
    independent ways to report success without executing:

      * ``@pytest.mark.functional`` deselects it from CI
        (``-m "not functional and not paper_rth"``);
      * the same marker deselects it from the documented fast local run
        (``-m "not functional and not slow"``);
      * and a cache miss skipped, which pytest reports green.

    So "the suite is green" never implied the baseline was checked. Setting
    ``FEELIES_REQUIRE_BASELINE_CACHE=1`` converts the skip into a failure, which
    is what makes "I verified parity" a checkable claim rather than an assertion.
    Default stays a skip so a contributor without the cache is not blocked.
    """
    hint = (
        f"Disk cache miss for {_BASELINE_SYMBOL}/{_BASELINE_DATE} — populate with:\n"
        "  uv run python scripts/run_backtest.py "
        f"--config {_BASELINE_CONFIG} --symbol {_BASELINE_SYMBOL} "
        f"--date {_BASELINE_DATE}\n"
        f"  ({exc})"
    )
    if os.environ.get("FEELIES_REQUIRE_BASELINE_CACHE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        pytest.fail(
            "FEELIES_REQUIRE_BASELINE_CACHE is set, so the parity oracle must "
            f"run rather than skip.\n{hint}"
        )
    pytest.skip(hint)


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
        _missing_cache(exc)

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

    # Pin the *input tape* before pinning anything derived from it.
    #
    # The `parity oracle` CI job refetches this session from Massive when its
    # actions/cache entry misses. If the vendor ever returns a different event
    # count or ingestion health, every downstream assertion moves — and a bare
    # parity-hash failure reads as "the code regressed" when the truth is "the
    # data changed". Asserting the content-bound data_version first makes that
    # distinction the failure message rather than something to work out
    # afterwards, and it is exactly the case parity_manifest.py warns about:
    # a moved hash is either a real behaviour change or a fact about the inputs.
    #
    # If this fires, do NOT re-pin the parity constants. Establish which tape is
    # correct first.
    assert cache_data_version(day_sources) == _BASELINE_DATA_VERSION, (
        "APP/2026-03-26 input tape changed — event count or ingestion health "
        f"differs from the corpus the baseline was minted on.\n"
        f"  Expected: {_BASELINE_DATA_VERSION}\n"
        f"  Actual:   {cache_data_version(day_sources)}\n"
        "The parity constants below describe the expected tape; re-pinning them "
        "to match a different one would silently retire the baseline."
    )

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

    # Trade path — locked by its canonical sequence hash, Net P&L (to the cent),
    # and fill count (above). The config contract is pinned data-free in
    # ``test_app_baseline_config_contract_hash``.
    assert compute_parity_hash(outcome.orchestrator) == _BASELINE_TRADE_PARITY_HASH

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
