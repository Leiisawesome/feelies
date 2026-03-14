"""Polygon.io historical data ingestor — batch ETL for backtest datasets.

Downloads historical quotes and trades from the Polygon.io REST API,
normalizes them in page-sized chunks via ``PolygonNormalizer``, and
persists via ``EventLog.append_batch()``.

This is NOT a ``MarketDataSource``.  It runs once (offline) to populate
an ``EventLog`` that is later replayed tick-by-tick through ``ReplayFeed``.

Uses the ``polygon-api-client`` (``polygon`` package) ``RESTClient`` for
paginated access to ``/v3/quotes/{ticker}`` and ``/v3/trades/{ticker}``.

Supports checkpoint-based resumability: if a ``BackfillCheckpoint`` store
is provided, completed (symbol, feed_type) pairs are skipped on retry,
making large backfills safe to interrupt and resume.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from feelies.core.clock import Clock
from feelies.core.events import NBBOQuote, Trade
from feelies.ingestion.data_integrity import DataHealth
from feelies.ingestion.polygon_normalizer import PolygonNormalizer
from feelies.storage.event_log import EventLog

if TYPE_CHECKING:
    from polygon import RESTClient  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 5_000


@dataclass(frozen=True)
class IngestResult:
    """Summary statistics from a historical ingestion run."""

    events_ingested: int
    pages_processed: int
    gaps_detected: int
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


class PolygonHistoricalIngestor:
    """Batch ETL pipeline: Polygon REST API -> normalize -> EventLog.

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
        normalizer: PolygonNormalizer,
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
    ) -> IngestResult:
        """Download and persist historical quotes and trades.

        Args:
            symbols: Ticker symbols to ingest.
            start_date: Start date in ``YYYY-MM-DD`` format.
            end_date: End date in ``YYYY-MM-DD`` format.

        Returns:
            Summary of the ingestion run.

        Completed (symbol, feed_type) pairs are recorded in the checkpoint
        store.  On retry, already-completed pairs are skipped.
        """
        try:
            from polygon import RESTClient as _RESTClient  # pyright: ignore[reportMissingImports]
        except ImportError as exc:
            raise ImportError(
                "polygon-api-client is required for PolygonHistoricalIngestor. "
                "Install it with: pip install 'feelies[polygon]'"
            ) from exc

        client: RESTClient = _RESTClient(api_key=self._api_key)

        total_events = 0
        total_pages = 0
        completed_symbols: set[str] = set()

        for symbol in symbols:
            logger.info(
                "polygon_ingestor: ingesting %s from %s to %s",
                symbol, start_date, end_date,
            )

            if self._checkpoint.is_done(symbol, "quotes"):
                logger.info("polygon_ingestor: skipping quotes for %s (checkpoint)", symbol)
            else:
                ev_count, pg_count = self._ingest_quotes(
                    client, symbol, start_date, end_date,
                )
                total_events += ev_count
                total_pages += pg_count
                self._checkpoint.mark_done(symbol, "quotes")

            if self._checkpoint.is_done(symbol, "trades"):
                logger.info("polygon_ingestor: skipping trades for %s (checkpoint)", symbol)
            else:
                ev_count, pg_count = self._ingest_trades(
                    client, symbol, start_date, end_date,
                )
                total_events += ev_count
                total_pages += pg_count
                self._checkpoint.mark_done(symbol, "trades")

            completed_symbols.add(symbol)
            logger.info(
                "polygon_ingestor: completed %s, cumulative events: %d",
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
            gaps_detected=gaps,
            duplicates_filtered=self._normalizer.duplicates_filtered,
            symbols_completed=frozenset(completed_symbols),
        )

    def _ingest_quotes(
        self,
        client: RESTClient,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> tuple[int, int]:
        """Ingest historical quotes for a single symbol.

        Returns (events_ingested, pages_processed).
        """
        total_events = 0
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
                "polygon_ingestor: failed to start quotes iteration for %s",
                symbol,
            )
            return 0, 0

        page_buffer: list[Any] = []
        for quote_obj in quotes_iter:
            page_buffer.append(quote_obj)
            if len(page_buffer) >= _CHUNK_SIZE:
                ingested = self._flush_chunk(page_buffer, symbol)
                total_events += ingested
                pages += 1
                page_buffer = []

        if page_buffer:
            ingested = self._flush_chunk(page_buffer, symbol)
            total_events += ingested
            pages += 1

        return total_events, pages

    def _ingest_trades(
        self,
        client: RESTClient,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> tuple[int, int]:
        """Ingest historical trades for a single symbol.

        Returns (events_ingested, pages_processed).
        """
        total_events = 0
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
                "polygon_ingestor: failed to start trades iteration for %s",
                symbol,
            )
            return 0, 0

        page_buffer: list[Any] = []
        for trade_obj in trades_iter:
            page_buffer.append(trade_obj)
            if len(page_buffer) >= _CHUNK_SIZE:
                ingested = self._flush_chunk(page_buffer, symbol)
                total_events += ingested
                pages += 1
                page_buffer = []

        if page_buffer:
            ingested = self._flush_chunk(page_buffer, symbol)
            total_events += ingested
            pages += 1

        return total_events, pages

    def _flush_chunk(
        self,
        records: list[Any],
        symbol: str,
    ) -> int:
        """Normalize a chunk of REST records and persist to EventLog.

        Returns the number of canonical events persisted.
        """
        all_events: list[NBBOQuote | Trade] = []
        received_ns = self._clock.now_ns()

        for record in records:
            rec_dict = _model_to_dict(record, symbol)
            if not rec_dict:
                continue

            raw = json.dumps(rec_dict).encode("utf-8")
            events = self._normalizer.on_message(raw, received_ns, "polygon_rest")
            all_events.extend(events)

        if all_events:
            self._event_log.append_batch(all_events)
        return len(all_events)


def _model_to_dict(record: Any, symbol: str) -> dict[str, Any]:
    """Convert a polygon-api-client model object to a dict.

    The polygon ``@modelclass`` decorator stores only explicitly-set
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
