"""Massive historical data ingestor (formerly Polygon.io) — batch ETL for
backtest datasets.

Downloads historical quotes and trades from the Massive REST API,
normalizes them in page-sized chunks via ``MassiveNormalizer``, and
persists via ``EventLog.append_batch()``.

This is NOT a ``MarketDataSource``.  It runs once (offline) to populate
an ``EventLog`` that is later replayed tick-by-tick through ``ReplayFeed``.

Uses the ``massive`` package ``RESTClient`` for paginated access to
``/v3/quotes/{ticker}`` and ``/v3/trades/{ticker}``.

Supports checkpoint-based resumability: if a ``BackfillCheckpoint`` store
is provided, completed (symbol, feed_type) pairs are skipped on retry,
making large backfills safe to interrupt and resume.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from feelies.core.clock import Clock
from feelies.core.events import NBBOQuote, Trade
from feelies.ingestion.data_integrity import DataHealth
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.storage.event_log import EventLog

if TYPE_CHECKING:
    from massive import RESTClient  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 5_000
_TYPE_RANK_QUOTE = 0
_TYPE_RANK_TRADE = 1


@dataclass(frozen=True)
class IngestResult:
    """Summary statistics from a historical ingestion run."""

    events_ingested: int
    pages_processed: int
    symbols_with_gaps: int
    duplicates_filtered: int
    symbols_completed: frozenset[str]


class BackfillCheckpoint(Protocol):
    """Tracks completed (symbol, feed_type) pairs for resumable backfill.

    Implementations may persist to disk, database, or remain in-memory.
    The key is ``(symbol, feed_type)`` where feed_type is ``"quotes"``
    or ``"trades"``.
    """

    def is_done(self, symbol: str, feed_type: str) -> bool:
        """Return True if this (symbol, feed_type) was already completed."""
        ...

    def mark_done(self, symbol: str, feed_type: str) -> None:
        """Record that this (symbol, feed_type) has been fully ingested."""
        ...


class InMemoryCheckpoint:
    """Volatile checkpoint — useful for single-run dedup within one call."""

    __slots__ = ("_done",)

    def __init__(self) -> None:
        self._done: set[tuple[str, str]] = set()

    def is_done(self, symbol: str, feed_type: str) -> bool:
        return (symbol, feed_type) in self._done

    def mark_done(self, symbol: str, feed_type: str) -> None:
        self._done.add((symbol, feed_type))


class MassiveHistoricalIngestor:
    """Batch ETL pipeline: Massive REST API -> normalize -> EventLog.

    Lifecycle:
      1. Construct with API key, normalizer, event_log, clock
      2. Call ``ingest(symbols, start_date, end_date)``
      3. Use ``ReplayFeed`` to replay the populated EventLog

    Each REST page is normalized as a chunk and persisted via
    ``EventLog.append_batch()``.  The normalizer tracks gap detection
    and dedup across pages.

    If a ``BackfillCheckpoint`` is provided, completed (symbol, feed_type)
    pairs are skipped on retry — making the ingest call idempotent and
    safe to resume after interruption.
    """

    __slots__ = ("_api_key", "_normalizer", "_event_log", "_clock", "_checkpoint")

    def __init__(
        self,
        api_key: str,
        normalizer: MassiveNormalizer,
        event_log: EventLog,
        clock: Clock,
        checkpoint: BackfillCheckpoint | None = None,
    ) -> None:
        self._api_key = api_key
        self._normalizer = normalizer
        self._event_log = event_log
        self._clock = clock
        self._checkpoint = checkpoint or InMemoryCheckpoint()

    def ingest(
        self,
        symbols: Sequence[str],
        start_date: str,
        end_date: str,
        *,
        on_page: Callable[[str, int, int, float], None] | None = None,
    ) -> IngestResult:
        """Download and persist historical quotes and trades.

        Args:
            symbols: Ticker symbols to ingest.
            start_date: Start date in ``YYYY-MM-DD`` format.
            end_date: End date in ``YYYY-MM-DD`` format.
            on_page: Optional callback invoked after each downloaded page.
                Signature: ``(feed_type, page_num, running_total, elapsed_secs)``.
                ``feed_type`` is ``"quotes"`` or ``"trades"``.

        Returns:
            Summary of the ingestion run.

        Completed (symbol, feed_type) pairs are recorded in the checkpoint
        store.  On retry, already-completed pairs are skipped.
        """
        try:
            from massive import RESTClient as _RESTClient  # pyright: ignore[reportMissingImports]
        except ImportError as exc:
            raise ImportError(
                "massive package is required for MassiveHistoricalIngestor. "
                "Install it with: pip install 'feelies[massive]'"
            ) from exc

        client: RESTClient = _RESTClient(api_key=self._api_key)

        total_events = 0
        total_pages = 0
        completed_symbols: set[str] = set()

        for symbol in symbols:
            logger.info(
                "massive_ingestor: ingesting %s from %s to %s",
                symbol, start_date, end_date,
            )

            ev_count, pg_count = self.ingest_symbol_parallel(
                client, symbol, start_date, end_date,
                on_page=on_page,
            )
            total_events += ev_count
            total_pages += pg_count

            completed_symbols.add(symbol)
            logger.info(
                "massive_ingestor: completed %s, cumulative events: %d",
                symbol, total_events,
            )

        health = self._normalizer.all_health()
        gaps = sum(
            1 for h in health.values()
            if h in (DataHealth.GAP_DETECTED, DataHealth.CORRUPTED)
        )

        return IngestResult(
            events_ingested=total_events,
            pages_processed=total_pages,
            symbols_with_gaps=gaps,
            duplicates_filtered=self._normalizer.duplicates_filtered,
            symbols_completed=frozenset(completed_symbols),
        )

    # ── Parallel download + merge-sort ─────────────────────────────

    def ingest_symbol_parallel(
        self,
        client: RESTClient,
        symbol: str,
        start_date: str,
        end_date: str,
        *,
        on_page: Callable[[str, int, int, float], None] | None = None,
    ) -> tuple[int, int]:
        """Download quotes + trades in parallel, merge-sort, normalize sequentially.

        Returns (events_ingested, pages_processed).
        """
        _lock: threading.Lock = threading.Lock()
        _t0: float = time.monotonic()

        def _q_on_page(page_num: int, total: int) -> None:
            if on_page is not None:
                with _lock:
                    on_page("quotes", page_num, total, time.monotonic() - _t0)

        def _t_on_page(page_num: int, total: int) -> None:
            if on_page is not None:
                with _lock:
                    on_page("trades", page_num, total, time.monotonic() - _t0)

        with ThreadPoolExecutor(max_workers=2) as pool:
            quotes_future = pool.submit(
                _download_quotes_raw, client, symbol, start_date, end_date, _q_on_page,
            )
            trades_future = pool.submit(
                _download_trades_raw, client, symbol, start_date, end_date, _t_on_page,
            )
            raw_quotes, q_pages = quotes_future.result()
            raw_trades, t_pages = trades_future.result()

        total_pages = q_pages + t_pages
        logger.info(
            "massive_ingestor: downloaded %d raw quotes + %d raw trades for %s (%d pages)",
            len(raw_quotes), len(raw_trades), symbol, total_pages,
        )

        for d in raw_quotes:
            d["__type_rank__"] = _TYPE_RANK_QUOTE
        for d in raw_trades:
            d["__type_rank__"] = _TYPE_RANK_TRADE

        merged = raw_quotes + raw_trades
        merged.sort(key=lambda d: (
            d.get("sip_timestamp", 0),
            d.get("sequence_number", 0),
            d.get("__type_rank__", 0),
        ))

        all_events: list[NBBOQuote | Trade] = []
        received_ns = self._clock.now_ns()

        for rec_dict in merged:
            rec_dict.pop("__type_rank__", None)
            raw = json.dumps(rec_dict).encode("utf-8")
            events = self._normalizer.on_message(raw, received_ns, "massive_rest")
            all_events.extend(events)

        if all_events:
            self._event_log.append_batch(all_events)

        return len(all_events), total_pages


def _download_quotes_raw(
    client: RESTClient,
    symbol: str,
    start_date: str,
    end_date: str,
    _on_page: Callable[[int, int], None] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Paginate through list_quotes(), collecting raw dicts. Pure download."""
    raw_dicts: list[dict[str, Any]] = []
    pages = 0

    try:
        quotes_iter = client.list_quotes(
            symbol,
            timestamp_gte=f"{start_date}T00:00:00Z",
            timestamp_lte=f"{end_date}T23:59:59Z",
            order="asc",
            sort="timestamp",
            limit=50000,
        )
    except Exception:
        logger.exception(
            "massive_ingestor: failed to start quotes iteration for %s", symbol,
        )
        return [], 0

    buf: list[Any] = []
    for obj in quotes_iter:
        buf.append(obj)
        if len(buf) >= _CHUNK_SIZE:
            for record in buf:
                d = _model_to_dict(record, symbol)
                if d:
                    raw_dicts.append(d)
            pages += 1
            if _on_page is not None:
                _on_page(pages, len(raw_dicts))
            buf = []

    if buf:
        for record in buf:
            d = _model_to_dict(record, symbol)
            if d:
                raw_dicts.append(d)
        pages += 1
        if _on_page is not None:
            _on_page(pages, len(raw_dicts))

    return raw_dicts, pages


def _download_trades_raw(
    client: RESTClient,
    symbol: str,
    start_date: str,
    end_date: str,
    _on_page: Callable[[int, int], None] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Paginate through list_trades(), collecting raw dicts. Pure download."""
    raw_dicts: list[dict[str, Any]] = []
    pages = 0

    try:
        trades_iter = client.list_trades(
            symbol,
            timestamp_gte=f"{start_date}T00:00:00Z",
            timestamp_lte=f"{end_date}T23:59:59Z",
            order="asc",
            sort="timestamp",
            limit=50000,
        )
    except Exception:
        logger.exception(
            "massive_ingestor: failed to start trades iteration for %s", symbol,
        )
        return [], 0

    buf: list[Any] = []
    for obj in trades_iter:
        buf.append(obj)
        if len(buf) >= _CHUNK_SIZE:
            for record in buf:
                d = _model_to_dict(record, symbol)
                if d:
                    raw_dicts.append(d)
            pages += 1
            if _on_page is not None:
                _on_page(pages, len(raw_dicts))
            buf = []

    if buf:
        for record in buf:
            d = _model_to_dict(record, symbol)
            if d:
                raw_dicts.append(d)
        pages += 1
        if _on_page is not None:
            _on_page(pages, len(raw_dicts))

    return raw_dicts, pages


def _model_to_dict(record: Any, symbol: str) -> dict[str, Any]:
    """Convert a massive model object to a dict.

    The massive ``@modelclass`` decorator stores only explicitly-set
    fields in ``__dict__``; class-level ``None`` defaults are invisible.
    We iterate through ``__annotations__`` on the model class to capture
    all declared fields, including those left at their default ``None``.
    """
    cls = type(record)
    annotations = getattr(cls, "__annotations__", None)

    if annotations:
        rec_dict = {
            k: getattr(record, k, None)
            for k in annotations
            if not k.startswith("_")
        }
    elif isinstance(record, dict):
        rec_dict = dict(record)
    elif hasattr(record, "__dict__"):
        rec_dict = dict(record.__dict__)
    else:
        return {}

    # Prune None values so the normalizer's .get() defaults work correctly
    rec_dict = {k: v for k, v in rec_dict.items() if v is not None}

    if "ticker" not in rec_dict:
        rec_dict["ticker"] = symbol

    return rec_dict
