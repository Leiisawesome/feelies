"""Unit tests for DiskEventCache — per-day JSONL.gz cache."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.storage.disk_event_cache import DiskEventCache


def _make_quote(seq: int = 1, ts: int = 1_000_000_000) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        exchange_timestamp_ns=ts,
        correlation_id=f"AAPL:{ts}:{seq}",
        sequence=seq,
        symbol="AAPL",
        bid=Decimal("150.00"),
        ask=Decimal("150.05"),
        bid_size=100,
        ask_size=200,
        bid_exchange=11,
        ask_exchange=12,
        conditions=(1, 2),
        indicators=(),
        sequence_number=seq,
        tape=3,
    )


def _make_trade(seq: int = 1, ts: int = 1_000_000_001) -> Trade:
    return Trade(
        timestamp_ns=ts,
        exchange_timestamp_ns=ts,
        correlation_id=f"AAPL:{ts}:{seq}",
        sequence=seq,
        symbol="AAPL",
        price=Decimal("150.02"),
        size=50,
        exchange=11,
        trade_id="t1",
        conditions=(0, 12),
        sequence_number=seq,
        tape=3,
    )


class TestDiskEventCacheRoundTrip:
    """save → exists → load produces identical events."""

    def test_save_and_load(self, tmp_path: Path) -> None:
        cache = DiskEventCache(tmp_path)
        events = [_make_quote(1), _make_trade(2, ts=2_000_000_000), _make_quote(3, ts=3_000_000_000)]

        cache.save("AAPL", "2026-03-13", events)

        assert cache.exists("AAPL", "2026-03-13")
        loaded = cache.load("AAPL", "2026-03-13")

        assert loaded is not None
        assert len(loaded) == 3

        for orig, restored in zip(events, loaded):
            assert type(orig) is type(restored)
            assert orig.symbol == restored.symbol
            assert orig.exchange_timestamp_ns == restored.exchange_timestamp_ns
            assert orig.sequence == restored.sequence
            assert orig.correlation_id == restored.correlation_id

        q_orig = events[0]
        q_loaded = loaded[0]
        assert isinstance(q_loaded, NBBOQuote)
        assert q_loaded.bid == q_orig.bid
        assert q_loaded.ask == q_orig.ask
        assert q_loaded.conditions == q_orig.conditions

        t_orig = events[1]
        t_loaded = loaded[1]
        assert isinstance(t_loaded, Trade)
        assert t_loaded.price == t_orig.price
        assert t_loaded.size == t_orig.size

    def test_decimal_precision_preserved(self, tmp_path: Path) -> None:
        cache = DiskEventCache(tmp_path)
        q = NBBOQuote(
            timestamp_ns=1, exchange_timestamp_ns=1,
            correlation_id="X:1:0", sequence=0,
            symbol="X", bid=Decimal("123.456789"), ask=Decimal("0.00000001"),
            bid_size=1, ask_size=1,
        )
        cache.save("X", "2026-01-01", [q])
        loaded = cache.load("X", "2026-01-01")
        assert loaded is not None
        assert loaded[0].bid == Decimal("123.456789")
        assert loaded[0].ask == Decimal("0.00000001")


class TestDiskEventCacheExists:

    def test_missing_returns_false(self, tmp_path: Path) -> None:
        cache = DiskEventCache(tmp_path)
        assert not cache.exists("AAPL", "2026-03-13")

    def test_exists_after_save(self, tmp_path: Path) -> None:
        cache = DiskEventCache(tmp_path)
        cache.save("AAPL", "2026-03-13", [_make_quote()])
        assert cache.exists("AAPL", "2026-03-13")


class TestDiskEventCacheFailSafe:
    """Corrupt or invalid caches return None (Inv-11)."""

    def test_corrupted_data_returns_none(self, tmp_path: Path) -> None:
        cache = DiskEventCache(tmp_path)
        cache.save("AAPL", "2026-03-13", [_make_quote()])

        data_path = tmp_path / "AAPL" / "2026-03-13.jsonl.gz"
        data_path.write_bytes(b"garbage data that is not gzip")

        result = cache.load("AAPL", "2026-03-13")
        assert result is None

    def test_missing_manifest_returns_none(self, tmp_path: Path) -> None:
        cache = DiskEventCache(tmp_path)
        cache.save("AAPL", "2026-03-13", [_make_quote()])

        manifest_path = tmp_path / "AAPL" / "2026-03-13.manifest.json"
        manifest_path.unlink()

        assert not cache.exists("AAPL", "2026-03-13")
        result = cache.load("AAPL", "2026-03-13")
        assert result is None

    def test_schema_mismatch_returns_none(self, tmp_path: Path) -> None:
        cache = DiskEventCache(tmp_path)
        cache.save("AAPL", "2026-03-13", [_make_quote()])

        manifest_path = tmp_path / "AAPL" / "2026-03-13.manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["event_schema_hash"] = "sha256:stale_hash"
        manifest_path.write_text(json.dumps(manifest))

        assert not cache.exists("AAPL", "2026-03-13")
        result = cache.load("AAPL", "2026-03-13")
        assert result is None

    def test_event_count_mismatch_returns_none(self, tmp_path: Path) -> None:
        cache = DiskEventCache(tmp_path)
        cache.save("AAPL", "2026-03-13", [_make_quote()])

        manifest_path = tmp_path / "AAPL" / "2026-03-13.manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["event_count"] = 999
        manifest_path.write_text(json.dumps(manifest))

        result = cache.load("AAPL", "2026-03-13")
        assert result is None


class TestDiskEventCacheManifest:
    """Manifest contains expected metadata."""

    def test_manifest_has_counts(self, tmp_path: Path) -> None:
        cache = DiskEventCache(tmp_path)
        events = [_make_quote(), _make_trade(), _make_quote(2, ts=2_000_000_000)]
        cache.save("AAPL", "2026-03-13", events)

        manifest_path = tmp_path / "AAPL" / "2026-03-13.manifest.json"
        manifest = json.loads(manifest_path.read_text())

        assert manifest["symbol"] == "AAPL"
        assert manifest["date"] == "2026-03-13"
        assert manifest["event_count"] == 3
        assert manifest["quotes_count"] == 2
        assert manifest["trades_count"] == 1
        assert manifest["checksum"].startswith("sha256:")
        assert manifest["event_schema_hash"].startswith("sha256:")
