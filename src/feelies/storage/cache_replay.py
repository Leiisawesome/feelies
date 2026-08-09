"""Load merged event logs from :class:`DiskEventCache` without calling Massive.

Used by offline replay harnesses after a first run has populated::

    {cache_dir}/{SYMBOL}/{YYYY-MM-DD}.jsonl.gz
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, Sequence

from feelies.core.events import NBBOQuote, Trade
from feelies.ingestion.massive_ingestor import IngestResult
from feelies.storage.disk_event_cache import DiskEventCache
from feelies.storage.event_resequence import resequence_event_list
from feelies.storage.memory_event_log import InMemoryEventLog

__all__ = [
    "CacheReplayError",
    "IngestDayMeta",
    "iter_calendar_dates",
    "iter_trading_dates",
    "load_event_log_from_disk_cache",
]


class CacheReplayError(RuntimeError):
    """Missing, corrupt, or schema-incompatible disk cache for replay."""


@dataclass(frozen=True)
class IngestDayMeta:
    """Provenance for a single (symbol, date) ingestion or cache load."""

    symbol: str
    date: str
    source: Literal["cache", "api"] | str
    event_count: int
    ingestion_health: str | None = None


def iter_calendar_dates(start_date: str, end_date: str) -> list[str]:
    """Return YYYY-MM-DD strings for each calendar date in ``[start, end]``."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    dates: list[str] = []
    current = start
    while current <= end:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def iter_trading_dates(start_date: str, end_date: str) -> list[str]:
    """Weekday dates in ``[start, end]`` — the sessions a market range means.

    ``iter_calendar_dates`` is deliberately literal and its contract is pinned, so
    this is a separate filter rather than a change to it.  Every consumer of
    *market data* wants sessions: a Saturday has no tape, and demanding one from
    the cache is what produced the zero-event weekend placeholders that then read
    as ``CORRUPTED`` and failed any multi-day range spanning a weekend.

    Holidays are not covered, exactly as in ``tests/paper/conftest.require_rth_window``:
    the platform's holiday calendar arrives through configuration, and pulling it
    in here would make an offline cache loader depend on it.  A market holiday
    still needs a cache entry or an explicit range that skips it.
    """
    return [
        d for d in iter_calendar_dates(start_date, end_date) if date.fromisoformat(d).weekday() < 5
    ]


def load_event_log_from_disk_cache(
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    *,
    cache_dir: Path | None = None,
    require_healthy_ingestion_manifests: bool = False,
) -> tuple[InMemoryEventLog, IngestResult, list[IngestDayMeta]]:
    """Load and merge cached JSONL.gz days; fail fast if any day is absent.

    No network I/O.  Re-sequences identically to
    :func:`scripts.run_backtest.ingest_data` after cache hits.

    When ``require_healthy_ingestion_manifests`` is True, every manifest must
    carry ``ingestion_health == \"HEALTHY\"`` (fail-closed for stale cache
    written before ingestion-health tagging or degraded normalizer runs).
    """
    resolved = cache_dir if cache_dir is not None else Path.home() / ".feelies" / "cache"
    cache = DiskEventCache(resolved)
    dates = iter_trading_dates(start_date, end_date)
    if not dates:
        raise CacheReplayError(
            f"No trading days in {start_date}..{end_date} — the range is entirely "
            "weekend. Widen it or pick a session date."
        )
    syms = [s.upper() for s in symbols]

    # Report *why* each day is unusable, not just that it is.  "Disk cache miss"
    # over a schema-hash mismatch reads as "the data is not there" and sends the
    # operator to re-download a file that is present and readable, which is a
    # different problem with a different fix.
    unusable: list[str] = []
    for sym in syms:
        for day in dates:
            reason = cache.unusable_reason(sym, day)
            if reason is not None:
                unusable.append(f"{sym}/{day}: {reason}")

    if unusable:
        raise CacheReplayError(
            "Disk cache unusable — populate cache with a normal backtest download "
            "first or pass --cache-dir pointing at your cache root.\n"
            f"  Cache root: {resolved}\n  " + "\n  ".join(unusable)
        )

    all_events: list[NBBOQuote | Trade] = []
    day_meta: list[IngestDayMeta] = []

    for sym in syms:
        for day in dates:
            loaded = cache.load(sym, day)
            if loaded is None:
                raise CacheReplayError(
                    f"Cache entry unreadable or checksum/schema mismatch: {sym}/{day}"
                )
            manifest = cache.read_manifest(sym, day)
            ing_health = manifest.get("ingestion_health") if manifest else None
            if require_healthy_ingestion_manifests:
                if ing_health != "HEALTHY":
                    raise CacheReplayError(
                        f"{sym}/{day}: disk cache manifest ingestion_health="
                        f"{ing_health!r} (require HEALTHY — re-ingest this day)"
                    )
            all_events.extend(loaded)
            day_meta.append(
                IngestDayMeta(
                    symbol=sym,
                    date=day,
                    source="cache",
                    event_count=len(loaded),
                    ingestion_health=(str(ing_health) if ing_health is not None else None),
                )
            )

    resequenced = resequence_event_list(all_events)
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
