"""Integration tests for parallel ingestion + disk cache pipeline.

Tests the full pipeline against the live Polygon API:
  parallel download → merge-sort → sequential normalize → disk cache → reload

Requires POLYGON_API_KEY.  Uses a small record limit to keep API calls fast.
Skips automatically when the key is absent or no recent data is found.
"""

from __future__ import annotations

import itertools
import os
import sys
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, Trade
from feelies.core.identifiers import SequenceGenerator, make_correlation_id
from feelies.ingestion.polygon_ingestor import (
    PolygonHistoricalIngestor,
    _download_quotes_raw,
    _download_trades_raw,
)
from feelies.ingestion.polygon_normalizer import PolygonNormalizer
from feelies.storage.disk_event_cache import DiskEventCache
from feelies.storage.memory_event_log import InMemoryEventLog

pytestmark = pytest.mark.functional

_RECORD_LIMIT = 200


def _require_api_key() -> str:
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        pytest.skip("Set POLYGON_API_KEY to run live Polygon integration tests.")
    return api_key


def _find_recent_trading_day(client: Any, symbol: str) -> str:
    """Walk backwards from today to find a date with both quotes and trades."""
    for days_back in range(1, 14):
        d = (datetime.now(UTC).date() - timedelta(days=days_back)).isoformat()
        start_ts = f"{d}T00:00:00Z"
        end_ts = f"{d}T23:59:59Z"

        has_quote = next(
            iter(client.list_quotes(symbol, timestamp_gte=start_ts, timestamp_lte=end_ts, limit=1)),
            None,
        )
        has_trade = next(
            iter(client.list_trades(symbol, timestamp_gte=start_ts, timestamp_lte=end_ts, limit=1)),
            None,
        )
        if has_quote is not None and has_trade is not None:
            return d

    pytest.skip(f"No recent trading day with data found for {symbol}")


class _LimitedClient:
    """Wraps a RESTClient to cap records per feed for fast tests."""

    __slots__ = ("_client", "_max")

    def __init__(self, client: Any, max_records: int) -> None:
        self._client = client
        self._max = max_records

    def list_quotes(self, *a: Any, **kw: Any) -> Iterator[Any]:
        kw["limit"] = min(int(kw.get("limit", self._max)), self._max)
        return itertools.islice(self._client.list_quotes(*a, **kw), self._max)

    def list_trades(self, *a: Any, **kw: Any) -> Iterator[Any]:
        kw["limit"] = min(int(kw.get("limit", self._max)), self._max)
        return itertools.islice(self._client.list_trades(*a, **kw), self._max)


def _resequence(events: list[NBBOQuote | Trade]) -> list[NBBOQuote | Trade]:
    seq = SequenceGenerator()
    result: list[NBBOQuote | Trade] = []
    for event in events:
        new_seq = seq.next()
        new_cid = make_correlation_id(event.symbol, event.exchange_timestamp_ns, new_seq)
        result.append(replace(event, sequence=new_seq, correlation_id=new_cid))
    return result


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def polygon_client() -> Any:
    polygon = pytest.importorskip("polygon")
    api_key = _require_api_key()
    return polygon.RESTClient(api_key=api_key)


@pytest.fixture(scope="module")
def trading_day(polygon_client: Any) -> str:
    return _find_recent_trading_day(polygon_client, "AAPL")


@pytest.fixture(scope="module")
def limited_client(polygon_client: Any) -> _LimitedClient:
    polygon = pytest.importorskip("polygon")
    api_key = _require_api_key()
    return _LimitedClient(polygon.RESTClient(api_key=api_key), _RECORD_LIMIT)


# ── Test 1: Raw download returns data ────────────────────────────────


class TestRawDownload:
    """Verify that _download_quotes_raw and _download_trades_raw work."""

    def test_downloads_quotes(self, limited_client: _LimitedClient, trading_day: str) -> None:
        raw_quotes, pages = _download_quotes_raw(limited_client, "AAPL", trading_day, trading_day)
        assert len(raw_quotes) > 0, "should download at least one quote"
        assert pages >= 1
        for d in raw_quotes:
            assert "sip_timestamp" in d, f"quote dict missing sip_timestamp: {list(d.keys())}"
            assert d.get("ticker") == "AAPL"

    def test_downloads_trades(self, limited_client: _LimitedClient, trading_day: str) -> None:
        raw_trades, pages = _download_trades_raw(limited_client, "AAPL", trading_day, trading_day)
        assert len(raw_trades) > 0, "should download at least one trade"
        assert pages >= 1
        for d in raw_trades:
            assert "sip_timestamp" in d, f"trade dict missing sip_timestamp: {list(d.keys())}"
            assert d.get("ticker") == "AAPL"


# ── Test 2: Parallel ingest produces chronological events ────────────


class TestParallelIngestChronological:
    """Parallel download + merge-sort + normalize produces time-ordered events."""

    def test_events_in_chronological_order(
        self, limited_client: _LimitedClient, trading_day: str,
    ) -> None:
        clock = SimulatedClock(start_ns=1_000_000_000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()

        ingestor = PolygonHistoricalIngestor(
            api_key="unused",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ev_count, pg_count = ingestor.ingest_symbol_parallel(
            limited_client, "AAPL", trading_day, trading_day,
        )

        assert ev_count > 0, "should ingest events"
        events = list(event_log.replay())
        assert len(events) == ev_count

        timestamps = [e.exchange_timestamp_ns for e in events]
        assert timestamps == sorted(timestamps), (
            "events must be in chronological order after merge-sort"
        )

    def test_contains_both_quotes_and_trades(
        self, limited_client: _LimitedClient, trading_day: str,
    ) -> None:
        clock = SimulatedClock(start_ns=1_000_000_000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()

        ingestor = PolygonHistoricalIngestor(
            api_key="unused",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ingestor.ingest_symbol_parallel(limited_client, "AAPL", trading_day, trading_day)
        events = list(event_log.replay())

        quotes = [e for e in events if isinstance(e, NBBOQuote)]
        trades = [e for e in events if isinstance(e, Trade)]
        assert len(quotes) > 0, "should have at least one quote"
        assert len(trades) > 0, "should have at least one trade"

    def test_sequences_are_monotonic(
        self, limited_client: _LimitedClient, trading_day: str,
    ) -> None:
        clock = SimulatedClock(start_ns=1_000_000_000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()

        ingestor = PolygonHistoricalIngestor(
            api_key="unused",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ingestor.ingest_symbol_parallel(limited_client, "AAPL", trading_day, trading_day)
        events = list(event_log.replay())

        sequences = [e.sequence for e in events]
        assert sequences == sorted(sequences), "sequences must be monotonically increasing"
        assert len(sequences) == len(set(sequences)), "sequences must be unique"

    def test_correlation_ids_are_unique(
        self, limited_client: _LimitedClient, trading_day: str,
    ) -> None:
        clock = SimulatedClock(start_ns=1_000_000_000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()

        ingestor = PolygonHistoricalIngestor(
            api_key="unused",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ingestor.ingest_symbol_parallel(limited_client, "AAPL", trading_day, trading_day)
        events = list(event_log.replay())

        cids = [e.correlation_id for e in events]
        assert len(cids) == len(set(cids)), "correlation IDs must be unique"


# ── Test 3: Disk cache round-trip preserves data ─────────────────────


class TestDiskCacheIntegration:
    """Cache save → load produces identical event data."""

    def test_cache_round_trip(
        self, limited_client: _LimitedClient, trading_day: str, tmp_path: Path,
    ) -> None:
        clock = SimulatedClock(start_ns=1_000_000_000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()

        ingestor = PolygonHistoricalIngestor(
            api_key="unused",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ingestor.ingest_symbol_parallel(limited_client, "AAPL", trading_day, trading_day)
        original_events: list[NBBOQuote | Trade] = list(event_log.replay())  # type: ignore[arg-type]
        assert len(original_events) > 0

        cache = DiskEventCache(tmp_path)
        cache.save("AAPL", trading_day, original_events)

        assert cache.exists("AAPL", trading_day)

        loaded_events = cache.load("AAPL", trading_day)
        assert loaded_events is not None
        assert len(loaded_events) == len(original_events)

        for orig, loaded in zip(original_events, loaded_events):
            assert type(orig) is type(loaded), (
                f"type mismatch at seq {orig.sequence}: {type(orig)} vs {type(loaded)}"
            )
            assert orig.symbol == loaded.symbol
            assert orig.exchange_timestamp_ns == loaded.exchange_timestamp_ns
            assert orig.sequence == loaded.sequence
            assert orig.correlation_id == loaded.correlation_id

            if isinstance(orig, NBBOQuote):
                assert isinstance(loaded, NBBOQuote)
                assert orig.bid == loaded.bid, f"bid mismatch: {orig.bid} vs {loaded.bid}"
                assert orig.ask == loaded.ask, f"ask mismatch: {orig.ask} vs {loaded.ask}"
                assert orig.bid_size == loaded.bid_size
                assert orig.ask_size == loaded.ask_size
                assert orig.conditions == loaded.conditions
            elif isinstance(orig, Trade):
                assert isinstance(loaded, Trade)
                assert orig.price == loaded.price, f"price mismatch: {orig.price} vs {loaded.price}"
                assert orig.size == loaded.size
                assert orig.conditions == loaded.conditions

    def test_cache_reuse_skips_api(
        self, limited_client: _LimitedClient, trading_day: str, tmp_path: Path,
    ) -> None:
        """Second load from cache doesn't need the API client at all."""
        clock = SimulatedClock(start_ns=1_000_000_000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()

        ingestor = PolygonHistoricalIngestor(
            api_key="unused",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ingestor.ingest_symbol_parallel(limited_client, "AAPL", trading_day, trading_day)
        events: list[NBBOQuote | Trade] = list(event_log.replay())  # type: ignore[arg-type]

        cache = DiskEventCache(tmp_path)
        cache.save("AAPL", trading_day, events)

        loaded_1 = cache.load("AAPL", trading_day)
        loaded_2 = cache.load("AAPL", trading_day)

        assert loaded_1 is not None
        assert loaded_2 is not None
        assert len(loaded_1) == len(loaded_2)

        for e1, e2 in zip(loaded_1, loaded_2):
            assert e1.correlation_id == e2.correlation_id
            assert e1.exchange_timestamp_ns == e2.exchange_timestamp_ns


# ── Test 4: Re-sequencing correctness ────────────────────────────────


class TestResequencing:
    """Re-sequencing assigns globally monotonic sequences."""

    def test_resequence_produces_contiguous_sequences(
        self, limited_client: _LimitedClient, trading_day: str, tmp_path: Path,
    ) -> None:
        clock = SimulatedClock(start_ns=1_000_000_000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()

        ingestor = PolygonHistoricalIngestor(
            api_key="unused",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ingestor.ingest_symbol_parallel(limited_client, "AAPL", trading_day, trading_day)
        day_events: list[NBBOQuote | Trade] = list(event_log.replay())  # type: ignore[arg-type]
        assert len(day_events) > 0

        resequenced = _resequence(day_events)

        sequences = [e.sequence for e in resequenced]
        assert sequences == list(range(len(resequenced))), (
            "resequenced events must have contiguous 0-based sequences"
        )

    def test_resequence_rebuilds_correlation_ids(
        self, limited_client: _LimitedClient, trading_day: str,
    ) -> None:
        clock = SimulatedClock(start_ns=1_000_000_000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()

        ingestor = PolygonHistoricalIngestor(
            api_key="unused",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ingestor.ingest_symbol_parallel(limited_client, "AAPL", trading_day, trading_day)
        day_events: list[NBBOQuote | Trade] = list(event_log.replay())  # type: ignore[arg-type]

        resequenced = _resequence(day_events)

        for event in resequenced:
            expected_cid = make_correlation_id(
                event.symbol, event.exchange_timestamp_ns, event.sequence,
            )
            assert event.correlation_id == expected_cid, (
                f"correlation_id mismatch: {event.correlation_id} != {expected_cid}"
            )

    def test_resequence_preserves_chronological_order(
        self, limited_client: _LimitedClient, trading_day: str,
    ) -> None:
        clock = SimulatedClock(start_ns=1_000_000_000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()

        ingestor = PolygonHistoricalIngestor(
            api_key="unused",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ingestor.ingest_symbol_parallel(limited_client, "AAPL", trading_day, trading_day)
        day_events: list[NBBOQuote | Trade] = list(event_log.replay())  # type: ignore[arg-type]

        resequenced = _resequence(day_events)

        timestamps = [e.exchange_timestamp_ns for e in resequenced]
        assert timestamps == sorted(timestamps), (
            "resequencing must not disturb chronological order"
        )


# ── Test 5: Multi-day cache + re-sequencing ──────────────────────────


class TestMultiDayCacheResequence:
    """Simulate multi-day scenario: two independent days cached then merged."""

    def test_two_days_resequenced_are_globally_monotonic(
        self, limited_client: _LimitedClient, trading_day: str, tmp_path: Path,
    ) -> None:
        cache = DiskEventCache(tmp_path)

        clock1 = SimulatedClock(start_ns=1_000_000_000)
        norm1 = PolygonNormalizer(clock1)
        log1 = InMemoryEventLog()
        ing1 = PolygonHistoricalIngestor(
            api_key="unused", normalizer=norm1, event_log=log1, clock=clock1,
        )
        ing1.ingest_symbol_parallel(limited_client, "AAPL", trading_day, trading_day)
        day1_events: list[NBBOQuote | Trade] = list(log1.replay())  # type: ignore[arg-type]
        cache.save("AAPL", trading_day, day1_events)

        day1_seqs = {e.sequence for e in day1_events}

        loaded_day1 = cache.load("AAPL", trading_day)
        assert loaded_day1 is not None

        # Simulate a second day by re-using the same data (content doesn't matter;
        # what matters is that sequences from two independent normalizers overlap).
        day2_events = day1_events  # same data, same 0-based sequences

        combined = list(loaded_day1) + list(day2_events)

        day1_loaded_seqs = {e.sequence for e in loaded_day1}
        day2_seqs = {e.sequence for e in day2_events}
        has_overlap = bool(day1_loaded_seqs & day2_seqs)
        assert has_overlap, (
            "pre-condition: two independent normalizer runs should produce overlapping sequences"
        )

        resequenced = _resequence(combined)
        final_seqs = [e.sequence for e in resequenced]
        assert final_seqs == list(range(len(resequenced))), (
            "after resequencing, sequences must be 0..N-1 contiguous"
        )
        assert len(set(final_seqs)) == len(final_seqs), "all sequences must be unique"


# ── Test 6: Event field fidelity through full pipeline ───────────────


class TestFieldFidelity:
    """Market data fields survive download → normalize → cache → reload."""

    def test_quote_fields_survive_pipeline(
        self, limited_client: _LimitedClient, trading_day: str, tmp_path: Path,
    ) -> None:
        clock = SimulatedClock(start_ns=1_000_000_000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()

        ingestor = PolygonHistoricalIngestor(
            api_key="unused",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ingestor.ingest_symbol_parallel(limited_client, "AAPL", trading_day, trading_day)
        events: list[NBBOQuote | Trade] = list(event_log.replay())  # type: ignore[arg-type]

        cache = DiskEventCache(tmp_path)
        cache.save("AAPL", trading_day, events)
        loaded = cache.load("AAPL", trading_day)
        assert loaded is not None

        quotes = [e for e in loaded if isinstance(e, NBBOQuote)]
        assert len(quotes) > 0

        q = quotes[0]
        assert isinstance(q.bid, Decimal), f"bid should be Decimal, got {type(q.bid)}"
        assert isinstance(q.ask, Decimal), f"ask should be Decimal, got {type(q.ask)}"
        assert q.bid >= 0
        assert q.ask >= 0
        assert q.ask >= q.bid, "ask must be >= bid"
        assert q.exchange_timestamp_ns > 0
        assert q.symbol == "AAPL"

        # Find a quote with positive bid/ask (skip auction/indicator quotes with bid=ask=0)
        normal_quotes = [qq for qq in quotes if qq.bid > 0 and qq.ask > 0]
        if normal_quotes:
            nq = normal_quotes[0]
            assert nq.bid_size > 0
            assert nq.ask_size > 0

    def test_trade_fields_survive_pipeline(
        self, limited_client: _LimitedClient, trading_day: str, tmp_path: Path,
    ) -> None:
        clock = SimulatedClock(start_ns=1_000_000_000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()

        ingestor = PolygonHistoricalIngestor(
            api_key="unused",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ingestor.ingest_symbol_parallel(limited_client, "AAPL", trading_day, trading_day)
        events: list[NBBOQuote | Trade] = list(event_log.replay())  # type: ignore[arg-type]

        cache = DiskEventCache(tmp_path)
        cache.save("AAPL", trading_day, events)
        loaded = cache.load("AAPL", trading_day)
        assert loaded is not None

        trades = [e for e in loaded if isinstance(e, Trade)]
        assert len(trades) > 0

        t = trades[0]
        assert isinstance(t.price, Decimal), f"price should be Decimal, got {type(t.price)}"
        assert t.price > 0
        assert t.size > 0
        assert t.exchange_timestamp_ns > 0
        assert t.symbol == "AAPL"
