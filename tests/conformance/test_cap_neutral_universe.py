"""Cap-neutral joint versus solo economics (F-P23a2-16).

Equity and ``capital_allocation_pct`` stay as configured. Platform and
alpha position, gross, and drawdown are lifted. PDT is unwired. The
buying-power multiplier is left alone. A missing disk-cache day fails
the test; this module never fetches.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from feelies.bootstrap import build_platform
from feelies.core.alpha_risk_budget import AlphaRiskBudget
from feelies.core.events import RiskAction, RiskVerdict
from feelies.core.platform_config import PlatformConfig
from feelies.core.trade_journal import TradeRecord
from feelies.harness import compute_economic_trade_hash, prepare_backtest_event_log
from feelies.harness.backtest_runner import (
    _attach_day_source_provenance,
    _enforce_ingest_event_mix,
    _run_backtest_phases_2_7,
)
from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache
from feelies.storage.disk_event_cache import DiskEventCache

pytestmark = pytest.mark.universe_check

_ROOT = Path(__file__).resolve().parents[2]
_DATE = "2026-03-26"
_PRIOR = "2026-03-25"
_SYMBOLS = ("APP", "CROX", "DIOD", "ENSG", "MLI", "OLN", "PCTY", "RMBS")
_POSITION = 1_000_000
_GROSS = 10_000.0
_DRAWDOWN = 10_000.0


def _require_disk_cache(symbols: tuple[str, ...]) -> None:
    cache = DiskEventCache(Path.home() / ".feelies" / "cache")
    bad = [
        f"{symbol}/{day}: {reason}"
        for symbol in symbols
        for day in (_PRIOR, _DATE)
        if (reason := cache.unusable_reason(symbol, day)) is not None
    ]
    if bad:
        pytest.fail("disk cache unusable; refusing to fetch\n" + "\n".join(bad))


def _economic_hash(records: list[TradeRecord]) -> str:
    """Order-id-excluded trade hash, including a single symbol's rows."""
    rows = list(records)
    return compute_economic_trade_hash(
        SimpleNamespace(trade_journal=SimpleNamespace(query=lambda: rows))
    )


def _timed(records: list[TradeRecord]) -> list[tuple[Any, ...]]:
    return [
        (
            record.symbol,
            record.strategy_id,
            record.side.name,
            record.filled_quantity,
            str(record.fill_price),
            str(record.realized_pnl),
            str(record.fees),
            str(record.cost_bps),
            record.fill_timestamp_ns,
        )
        for record in records
    ]


def _replay(symbols: tuple[str, ...]) -> tuple[list[TradeRecord], list[str]]:
    try:
        event_log, ingest_result, day_meta = load_event_log_from_disk_cache(
            list(symbols),
            _DATE,
            _DATE,
        )
    except CacheReplayError as exc:
        pytest.fail(f"disk cache replay refused; not fetching: {exc}")
    config = PlatformConfig.from_yaml(_ROOT / "configs" / "bt_app.yaml")
    config = replace(
        config,
        symbols=frozenset(symbols),
        risk_max_position_per_symbol=_POSITION,
        risk_max_gross_exposure_pct=_GROSS,
        risk_max_drawdown_pct=_DRAWDOWN,
    )
    syms = sorted(config.symbols)
    prep = prepare_backtest_event_log(config, event_log)
    mix = _enforce_ingest_event_mix(
        config,
        prep.event_log,
        source_label="cap-neutral disk cache",
        n_quotes=prep.n_quotes,
        n_trades=prep.n_trades,
    )
    if mix != 0:
        pytest.fail(f"ingest mix check returned {mix}")
    config = _attach_day_source_provenance(config, syms, day_meta)
    rejects: list[str] = []

    def factory(*args: Any, **kwargs: Any) -> Any:
        orchestrator, resolved = build_platform(*args, **kwargs)
        registry = orchestrator.alpha_registry
        assert registry is not None
        for alpha_id in registry.alpha_ids():
            module = registry.get(alpha_id)
            budget = module.manifest.risk_budget
            module._manifest = replace(
                module.manifest,
                risk_budget=AlphaRiskBudget(
                    max_position_per_symbol=_POSITION,
                    max_gross_exposure_pct=_GROSS,
                    max_drawdown_pct=_DRAWDOWN,
                    capital_allocation_pct=budget.capital_allocation_pct,
                ),
            )
        orchestrator._risk_engine._pdt_constraint = None

        def on_verdict(event: Any) -> None:
            if isinstance(event, RiskVerdict) and event.action in {
                RiskAction.REJECT,
                RiskAction.FORCE_FLATTEN,
            }:
                rejects.append(str(event.reason))

        orchestrator._bus.subscribe(RiskVerdict, on_verdict)
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
    outcome = _run_backtest_phases_2_7(
        args,
        event_log,
        ingest_result,
        day_meta,
        config,
        syms,
        ",".join(syms),
        _DATE,
        time.monotonic(),
        platform_factory=factory,
        prep=prep,
    )
    if outcome.exit_code not in (0, 2):
        pytest.fail(f"backtest exit {outcome.exit_code} for {syms}")
    journal = outcome.orchestrator.trade_journal
    assert journal is not None
    return list(journal.query()), rejects


def test_joint_economics_match_each_solo() -> None:
    """Each symbol's fills match its solo replay. Order ids may differ."""
    _require_disk_cache(_SYMBOLS)
    joint_records, joint_rejects = _replay(_SYMBOLS)
    assert joint_rejects == []
    assert any(record.symbol == "APP" for record in joint_records)
    for symbol in _SYMBOLS:
        solo_records, solo_rejects = _replay((symbol,))
        assert solo_rejects == []
        joint_symbol = [record for record in joint_records if record.symbol == symbol]
        assert _timed(joint_symbol) == _timed(solo_records)
        assert _economic_hash(joint_symbol) == _economic_hash(solo_records)
        assert all(record.symbol == symbol for record in solo_records)
