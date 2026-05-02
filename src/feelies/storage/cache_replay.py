"""Load merged event logs from :class:`DiskEventCache` without calling Massive.

Used by offline replay harnesses after a first run has populated::

    {cache_dir}/{SYMBOL}/{YYYY-MM-DD}.jsonl.gz
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, Sequence

from feelies.core.events import NBBOQuote, Trade
from feelies.core.identifiers import SequenceGenerator, make_correlation_id
from feelies.ingestion.massive_ingestor import IngestResult
from feelies.storage.disk_event_cache import DiskEventCache
from feelies.storage.memory_event_log import InMemoryEventLog

__all__ = ["CacheReplayError", "DiskCacheDayMeta", "load_event_log_from_disk_cache"]


class CacheReplayError(RuntimeError):
    """Missing, corrupt, or schema-incompatible disk cache for replay."""


@dataclass(frozen=True)
class DiskCacheDayMeta:
    """Provenance for one loaded cache file (mirrors scripts/run_backtest DaySource)."""

    symbol: str
    date: str
    source: Literal["cache"]
    event_count: int


def _iter_dates(start_date: str, end_date: str) -> list[str]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    dates: list[str] = []
    current = start
    while current <= end:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def _resequence(events: list[NBBOQuote | Trade]) -> list[NBBOQuote | Trade]:
    """Sort by exchange time and assign globally monotonic sequences."""
    events.sort(key=lambda e: e.exchange_timestamp_ns)
    seq = SequenceGenerator()
    result: list[NBBOQuote | Trade] = []
    for event in events:
        new_seq = seq.next()
        new_cid = make_correlation_id(
            event.symbol, event.exchange_timestamp_ns, new_seq,
        )
        result.append(replace(event, sequence=new_seq, correlation_id=new_cid))
    return result


def load_event_log_from_disk_cache(
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    *,
    cache_dir: Path | None = None,
) -> tuple[InMemoryEventLog, IngestResult, list[DiskCacheDayMeta]]:
    """Load and merge cached JSONL.gz days; fail fast if any day is absent.

    No network I/O.  Re-sequences identically to
    :func:`scripts.run_backtest.ingest_data` after cache hits.
    """
    resolved = cache_dir if cache_dir is not None else Path.home() / ".feelies" / "cache"
    cache = DiskEventCache(resolved)
    dates = _iter_dates(start_date, end_date)
    syms = [s.upper() for s in symbols]

    missing: list[str] = []
    for sym in syms:
        for day in dates:
            if not cache.exists(sym, day):
                missing.append(f"{sym}/{day} under {resolved}")

    if missing:
        raise CacheReplayError(
            "Disk cache miss — populate cache with a normal backtest download first "
            "or pass --cache-dir pointing at your cache root.\n  Missing:\n  "
            + "\n  ".join(missing)
        )

    all_events: list[NBBOQuote | Trade] = []
    day_meta: list[DiskCacheDayMeta] = []

    for sym in syms:
        for day in dates:
            loaded = cache.load(sym, day)
            if loaded is None:
                raise CacheReplayError(
                    f"Cache entry unreadable or checksum/schema mismatch: {sym}/{day}"
                )
            all_events.extend(loaded)
            day_meta.append(
                DiskCacheDayMeta(
                    symbol=sym, date=day, source="cache", event_count=len(loaded),
                )
            )

    resequenced = _resequence(all_events)
    event_log = InMemoryEventLog()
    event_log.append_batch(resequenced)

    ingest_result = IngestResult(
        events_ingested=len(resequenced),
        pages_processed=0,
        symbols_with_gaps=0,
        duplicates_filtered=0,
        symbols_completed=frozenset(syms),
    )

    return event_log, ingest_result, day_meta
