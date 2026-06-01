"""Unit tests for shared backtest CLI helpers."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from feelies.core.inv12_stress import apply_inv12_stress
from feelies.core.platform_config import PlatformConfig
from feelies.harness.backtest_cli import (
    ConfigNotFoundError,
    apply_backtest_cli_overrides,
    load_platform_config,
    resolve_backtest_symbols,
)
from feelies.storage.cache_replay import IngestDayMeta, iter_calendar_dates


def test_iter_calendar_dates_single_day() -> None:
    assert iter_calendar_dates("2026-03-26", "2026-03-26") == ["2026-03-26"]


def test_iter_calendar_dates_inclusive_range() -> None:
    assert iter_calendar_dates("2026-03-26", "2026-03-28") == [
        "2026-03-26",
        "2026-03-27",
        "2026-03-28",
    ]


def test_load_platform_config_missing_raises(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(ConfigNotFoundError) as exc_info:
        load_platform_config(missing)
    assert exc_info.value.path == missing


def test_apply_backtest_cli_overrides_inv12_and_symbols() -> None:
    base = PlatformConfig(symbols=frozenset({"AAPL"}))
    out = apply_backtest_cli_overrides(
        base,
        inv12_stress=True,
        symbols=["app", "msft"],
    )
    expected = apply_inv12_stress(
        replace(base, symbols=frozenset({"APP", "MSFT"})),
    )
    assert out == expected


def test_resolve_backtest_symbols_sorted() -> None:
    cfg = PlatformConfig(symbols=frozenset({"ZZ", "AA"}))
    assert resolve_backtest_symbols(cfg) == ["AA", "ZZ"]


def test_ingest_day_meta_api_source() -> None:
    row = IngestDayMeta(
        symbol="APP",
        date="2026-03-26",
        source="api",
        event_count=100,
        ingestion_health="HEALTHY",
    )
    assert row.source == "api"
