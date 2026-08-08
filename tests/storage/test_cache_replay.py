"""Tests for offline disk-cache replay loader."""

from __future__ import annotations

import json
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
    with pytest.raises(CacheReplayError, match="no data file"):
        load_event_log_from_disk_cache(
            ["ZZNONEXIST"],
            "2099-01-01",
            "2099-01-01",
            cache_dir=tmp_path,
        )


def test_schema_stale_day_is_not_reported_as_absent(tmp_path: Path) -> None:
    """A present-but-stale day must not be described as a missing one.

    Four real cache days (AAPL/2026-03-18, MSFT + NVDA/2026-04-08,
    TSLA/2024-12-20) hold 337 MB of readable events that every sweep reported as
    "Disk cache miss — populate cache with a normal backtest download first".
    Nothing was missing: their manifests predate two added ``NBBOQuote`` fields,
    so the schema hash no longer matches.  The message named the wrong cause and
    prescribed the wrong fix, which is worse than saying less.
    """
    cache = DiskEventCache(tmp_path)
    cache.save("AAPL", "2024-06-03", [_one_quote()], ingestion_health="HEALTHY")

    manifest_path = tmp_path / "AAPL" / "2024-06-03.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["event_schema_hash"] = "sha256:" + "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert not cache.exists("AAPL", "2024-06-03")
    reason = cache.unusable_reason("AAPL", "2024-06-03")
    assert reason is not None
    assert "event_schema_hash mismatch" in reason
    assert "data is present" in reason
    # Both hashes are named so an operator can see which schema it was written
    # under without opening the manifest.
    assert "0000000000" in reason

    with pytest.raises(CacheReplayError) as excinfo:
        load_event_log_from_disk_cache(["AAPL"], "2024-06-03", "2024-06-03", cache_dir=tmp_path)
    text = str(excinfo.value)
    assert "event_schema_hash mismatch" in text
    assert "no data file" not in text


def test_unreadable_manifest_is_distinguished_from_a_stale_one(tmp_path: Path) -> None:
    cache = DiskEventCache(tmp_path)
    cache.save("AAPL", "2024-06-03", [_one_quote()], ingestion_health="HEALTHY")
    (tmp_path / "AAPL" / "2024-06-03.manifest.json").write_text("{not json", encoding="utf-8")

    reason = cache.unusable_reason("AAPL", "2024-06-03")
    assert reason == "manifest missing or unreadable"


def test_usable_day_has_no_unusable_reason(tmp_path: Path) -> None:
    cache = DiskEventCache(tmp_path)
    cache.save("AAPL", "2024-06-03", [_one_quote()], ingestion_health="HEALTHY")
    assert cache.unusable_reason("AAPL", "2024-06-03") is None
    assert cache.exists("AAPL", "2024-06-03")


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
