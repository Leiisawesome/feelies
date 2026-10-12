"""Pins for the economic trade hash. The parity hash constants are untouched.

R-SYN is the production engine on the synthetic tape. R-FIX is the reference
engine on the APP cache. The eight-name pin needs that cache and is marked
functional so the check job, which restores APP only, does not run it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from feelies.bootstrap import build_platform
from feelies.harness.backtest_report import compute_economic_trade_hash

_ROOT = Path(__file__).resolve().parents[2]
_EIGHT = ("APP", "CROX", "DIOD", "ENSG", "MLI", "OLN", "PCTY", "RMBS")

ECONOMIC_TRADE_HASH_RFIX = "bb5f94cf0f29f29f1d7b6918d3fd9ea53b9a7ec764a5971f07293fd29f9cb648"
ECONOMIC_TRADE_HASH_RSYN = "3b795e551574d0f56e5c2319acaef921137396f80baba52868434bb07201060c"
ECONOMIC_TRADE_HASH_EIGHT = "aae3847abdb29b4524b7a285d13784058fbcce0f3c5cd0682f8877c6a3e84484"


def _capture(run: Any) -> Any:
    import tests.position_engine.scenarios as scenarios

    box: dict[str, Any] = {}
    saved = scenarios.build_platform

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        orchestrator, resolved = build_platform(*args, **kwargs)
        box["orch"] = orchestrator
        return orchestrator, resolved

    scenarios.build_platform = wrapped  # type: ignore[misc, assignment]
    try:
        run()
    finally:
        scenarios.build_platform = saved  # type: ignore[misc, assignment]
    return box["orch"]


def test_rsyn_economic_trade_hash() -> None:
    from tests.position_engine.scenarios import T0, run_synthetic
    from tests.position_engine.tapes import make_tape

    tape = make_tape(seed=11, n=36000, symbol="SYN", start_ns=T0, size=1000)
    orchestrator = _capture(lambda: run_synthetic(tape, symbols=("SYN",)))
    records = list(orchestrator.trade_journal.query())
    assert len(records) == 29
    assert compute_economic_trade_hash(orchestrator) == ECONOMIC_TRADE_HASH_RSYN


def test_rfix_economic_trade_hash() -> None:
    from tests.position_engine.scenarios import run_real

    keys = ("FEELIES_ENGINE", "FEELIES_RAIL")
    saved = {key: os.environ.get(key) for key in keys}
    os.environ["FEELIES_ENGINE"] = "tests.position_engine.reference.engine.PositionEngine"
    os.environ["FEELIES_RAIL"] = "tests.position_engine.reference.rail.ReferenceRail"
    try:
        orchestrator = _capture(run_real)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    records = list(orchestrator.trade_journal.query())
    assert len(records) == 98
    assert compute_economic_trade_hash(orchestrator) == ECONOMIC_TRADE_HASH_RFIX


def _eight_orchestrator() -> Any:
    import argparse
    import importlib.util
    import time
    from dataclasses import replace

    from feelies.core.platform_config import PlatformConfig
    from feelies.storage.cache_replay import load_event_log_from_disk_cache
    from feelies.storage.disk_event_cache import DiskEventCache

    cache = DiskEventCache(Path.home() / ".feelies" / "cache")
    bad = [
        f"{symbol}/{day}"
        for symbol in _EIGHT
        for day in ("2026-03-25", "2026-03-26")
        if cache.unusable_reason(symbol, day) is not None
    ]
    if bad:
        pytest.fail("cache unusable, refusing to fetch: " + ", ".join(bad))
    event_log, ingest_result, day_meta = load_event_log_from_disk_cache(
        list(_EIGHT), "2026-03-26", "2026-03-26"
    )
    spec = importlib.util.spec_from_file_location(
        "_economic_hash_runner", _ROOT / "scripts" / "run_backtest.py"
    )
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    config = replace(
        PlatformConfig.from_yaml(_ROOT / "configs" / "bt_app.yaml"),
        symbols=frozenset(_EIGHT),
    )
    syms = sorted(config.symbols)
    day_sources = [
        runner.DaySource(
            symbol=meta.symbol,
            date=meta.date,
            source=meta.source,
            event_count=meta.event_count,
            ingestion_health=meta.ingestion_health,
        )
        for meta in day_meta
    ]
    from feelies.harness import prepare_backtest_event_log

    prep = prepare_backtest_event_log(config, event_log)
    rc = runner._enforce_ingest_event_mix(
        config,
        prep.event_log,
        source_label="economic hash disk cache",
        n_quotes=prep.n_quotes,
        n_trades=prep.n_trades,
    )
    assert rc == 0
    config = runner._attach_day_source_provenance(config, syms, day_sources)
    box: dict[str, Any] = {}

    def factory(*args: Any, **kwargs: Any) -> Any:
        orchestrator, resolved = build_platform(*args, **kwargs)
        box["orch"] = orchestrator
        return orchestrator, resolved

    args = argparse.Namespace(
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
    outcome = runner._run_backtest_phases_2_7(
        args,
        event_log,
        ingest_result,
        day_sources,
        config,
        syms,
        ",".join(syms),
        "2026-03-26",
        time.monotonic(),
        platform_factory=factory,
        prep=prep,
    )
    assert outcome.exit_code == 0
    return box["orch"]


@pytest.mark.functional
def test_eight_name_economic_trade_hash() -> None:
    orchestrator = _eight_orchestrator()
    records = list(orchestrator.trade_journal.query())
    assert len(records) == 12
    assert compute_economic_trade_hash(orchestrator) == ECONOMIC_TRADE_HASH_EIGHT
