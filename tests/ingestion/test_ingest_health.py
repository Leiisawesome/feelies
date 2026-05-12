"""Tests for multi-day ingestion health aggregation."""

from __future__ import annotations

from dataclasses import dataclass

from feelies.ingestion.data_integrity import DataHealth
from feelies.ingestion.ingest_health import (
    merge_worst_health,
    parse_ingestion_health_label,
    terminal_symbol_health_rows,
)


@dataclass
class _Day:
    symbol: str
    date: str
    ingestion_health: str | None


def test_terminal_rows_worst_case_per_symbol() -> None:
    days = (
        _Day("AAPL", "2024-01-02", "HEALTHY"),
        _Day("AAPL", "2024-01-03", "GAP_DETECTED"),
        _Day("MSFT", "2024-01-02", "HEALTHY"),
    )
    rows = terminal_symbol_health_rows(("AAPL", "MSFT"), days)
    mp = dict(rows)
    assert mp["AAPL"] == DataHealth.GAP_DETECTED.name
    assert mp["MSFT"] == DataHealth.HEALTHY.name


def test_parse_unknown_label_maps_to_corrupted() -> None:
    assert parse_ingestion_health_label("NOT_A_REAL_STATE") == DataHealth.CORRUPTED


def test_merge_worst_health_ordering() -> None:
    assert (
        merge_worst_health(
            DataHealth.HEALTHY,
            DataHealth.CORRUPTED,
        )
        == DataHealth.CORRUPTED
    )
    assert (
        merge_worst_health(
            DataHealth.GAP_DETECTED,
            DataHealth.HEALTHY,
        )
        == DataHealth.GAP_DETECTED
    )
