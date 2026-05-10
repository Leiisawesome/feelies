"""Tests for offline disk-cache replay loader."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from feelies.core.events import NBBOQuote
from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache
from feelies.storage.disk_event_cache import DiskEventCache


def _one_quote(symbol: str = "AAPL") -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=1_700_000_000_000_000_000,
        correlation_id="q1",
        sequence=0,
        source_layer="INGESTION",
        symbol=symbol,
        bid=Decimal("150"),
        ask=Decimal("150.10"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=1_700_000_000_000_000_000,
    )


def test_load_cache_replay_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(CacheReplayError, match="Disk cache miss"):
        load_event_log_from_disk_cache(
            ["ZZNONEXIST"],
            "2099-01-01",
            "2099-01-01",
            cache_dir=tmp_path,
        )


def test_load_cache_replay_require_healthy_rejects_degraded(
    tmp_path: Path,
) -> None:
    cache = DiskEventCache(tmp_path)
    cache.save(
        "AAPL",
        "2024-06-03",
        [_one_quote()],
        ingestion_health="DEGRADED",
    )
    with pytest.raises(CacheReplayError, match="ingestion_health"):
        load_event_log_from_disk_cache(
            ["AAPL"],
            "2024-06-03",
            "2024-06-03",
            cache_dir=tmp_path,
            require_healthy_ingestion_manifests=True,
        )


def test_load_cache_replay_day_meta_carries_ingestion_health(
    tmp_path: Path,
) -> None:
    cache = DiskEventCache(tmp_path)
    cache.save(
        "AAPL",
        "2024-06-03",
        [_one_quote()],
        ingestion_health="HEALTHY",
    )
    _log, _ingest, meta = load_event_log_from_disk_cache(
        ["AAPL"],
        "2024-06-03",
        "2024-06-03",
        cache_dir=tmp_path,
    )
    assert len(meta) == 1
    assert meta[0].ingestion_health == "HEALTHY"
