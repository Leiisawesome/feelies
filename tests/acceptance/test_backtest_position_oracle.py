"""The position oracle (evaluation.md §1 row 3, D-254)."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import NoReturn

import pytest

from feelies.bootstrap import build_platform
from feelies.core.events import PositionClosed
from feelies.core.platform_config import PlatformConfig
from feelies.harness import (
    compute_config_hash,
    compute_economic_trade_hash,
    compute_parity_hash,
    prepare_backtest_event_log,
)
from feelies.harness.backtest_report import cache_data_version
from feelies.kernel.orchestrator import Orchestrator
from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache
from tests.acceptance.test_backtest_app_baseline import _BASELINE_DATA_VERSION

_ORACLE_SYMBOL = "APP"
_ORACLE_DATE = "2026-03-26"
_ORACLE_CONFIG = Path("configs/bt_position_arbitrary_not_calibrated.yaml")
POSITION_ORACLE_CLOSED_COUNT = 34
_CALIBRATION = ("2026-03-25", 50636)
POSITION_ORACLE_FILL_COUNT = None
POSITION_ORACLE_NET_PNL = None
POSITION_ORACLE_TRADE_PARITY_HASH = None
POSITION_ORACLE_ECONOMIC_TRADE_HASH = None
POSITION_ORACLE_CONFIG_HASH = None
POSITION_ORACLE_CLOSED_HASH = None


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "_backtest_position_oracle_runner",
        Path("scripts/run_backtest.py").resolve(),
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_backtest_position_oracle_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


def _calibration_view(orchestrator: Orchestrator) -> tuple[bool, str | None, int]:
    """(calibrated, NY date of the fit quotes, quote count)."""
    from feelies.storage.reference.corporate_actions import exchange_timestamp_to_ny_date

    engine = orchestrator._regime_engine
    calibrated = bool(getattr(engine, "calibrated", False)) if engine is not None else False
    quotes = tuple(orchestrator._regime_calibration_quotes or ())
    if not quotes:
        return calibrated, None, 0
    source = exchange_timestamp_to_ny_date(quotes[0].exchange_timestamp_ns).isoformat()
    return calibrated, source, len(quotes)


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
        f"Disk cache miss for {_ORACLE_SYMBOL}/{_ORACLE_DATE} — populate with:\n"
        "  uv run python scripts/run_backtest.py "
        f"--config {_ORACLE_CONFIG} --symbol {_ORACLE_SYMBOL} "
        f"--date {_ORACLE_DATE}\n"
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


def _closed_hash(closed: list[PositionClosed]) -> str:
    payload = json.dumps(
        [dataclasses.asdict(e) for e in closed],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@pytest.mark.functional
def test_app_20260326_position_oracle_from_disk_cache(runner) -> None:
    """Replay APP 2026-03-26 from disk cache; pin the position oracle."""
    if not _ORACLE_CONFIG.exists():
        pytest.fail(f"Missing baseline config: {_ORACLE_CONFIG}")

    try:
        event_log, ingest_result, day_meta = load_event_log_from_disk_cache(
            [_ORACLE_SYMBOL],
            _ORACLE_DATE,
            _ORACLE_DATE,
        )
    except CacheReplayError as exc:
        _missing_cache(exc)

    config = PlatformConfig.from_yaml(_ORACLE_CONFIG)
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

    closed: list[PositionClosed] = []

    def platform_factory(*args, **kwargs):
        result = build_platform(*args, **kwargs)
        result[0]._bus.subscribe(PositionClosed, closed.append)
        return result

    outcome = runner._run_backtest_phases_2_7(
        _cache_args(),
        event_log,
        ingest_result,
        day_sources,
        config,
        symbols,
        _ORACLE_SYMBOL,
        _ORACLE_DATE,
        time.monotonic(),
        platform_factory=platform_factory,
        prep=prep,
    )

    assert outcome.exit_code == 0

    journal = outcome.orchestrator.trade_journal
    assert journal is not None
    records = list(journal.query())
    fills = len(records)
    parity = compute_parity_hash(outcome.orchestrator)
    economic = compute_economic_trade_hash(outcome.orchestrator)
    assert outcome.recorder is not None
    net = _net_pnl_from_orchestrator(outcome.orchestrator, outcome.recorder)
    calibrated, source, n_cal = _calibration_view(outcome.orchestrator)
    digest = _closed_hash(closed)

    from feelies.core.events import OrderAck

    ack_fees = sum((a.fees for a in outcome.recorder.of_type(OrderAck)), Decimal("0"))
    cumulative_fees = sum(
        (p.cumulative_fees for p in outcome.orchestrator.position_store.all_positions().values()),
        Decimal("0"),
    )
    assert ack_fees == cumulative_fees
    assert outcome.orchestrator.regime_calibration_provenance == _CALIBRATION

    problems: list[str] = []
    if fills != POSITION_ORACLE_FILL_COUNT:
        problems.append(f"fills {fills} != {POSITION_ORACLE_FILL_COUNT}")
    if net != POSITION_ORACLE_NET_PNL:
        problems.append(f"net {net} != {POSITION_ORACLE_NET_PNL}")
    if parity != POSITION_ORACLE_TRADE_PARITY_HASH:
        problems.append(f"parity {parity} != {POSITION_ORACLE_TRADE_PARITY_HASH}")
    if economic != POSITION_ORACLE_ECONOMIC_TRADE_HASH:
        problems.append(f"economic {economic} != {POSITION_ORACLE_ECONOMIC_TRADE_HASH}")
    if len(closed) != POSITION_ORACLE_CLOSED_COUNT:
        problems.append(f"closed {len(closed)} != {POSITION_ORACLE_CLOSED_COUNT}")
    if digest != POSITION_ORACLE_CLOSED_HASH:
        problems.append(f"closed_hash {digest} != {POSITION_ORACLE_CLOSED_HASH}")
    if not (calibrated is True and source == _CALIBRATION[0] and n_cal == _CALIBRATION[1]):
        problems.append(f"calibrated={calibrated} source={source} n={n_cal}")
    assert not problems, (
        "; ".join(problems)
        + "\n"
        + f"fills={fills} net={net} parity={parity} economic={economic} "
        + f"closed_count={len(closed)} closed_hash={digest} "
        + f"calibrated={calibrated} source={source} n={n_cal}\n"
        + f"net beside -1321.15: {net}"
    )


def test_position_oracle_config_contract_hash() -> None:
    """Pin the raw config hash independently of cached market data."""
    if not _ORACLE_CONFIG.exists():
        pytest.fail(f"Missing baseline config: {_ORACLE_CONFIG}")
    config = PlatformConfig.from_yaml(_ORACLE_CONFIG)
    actual = compute_config_hash(config)
    assert actual == POSITION_ORACLE_CONFIG_HASH, actual
