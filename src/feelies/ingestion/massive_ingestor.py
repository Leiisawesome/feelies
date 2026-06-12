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
from feelies.core.errors import DataIntegrityError
from feelies.core.events import NBBOQuote, Trade
from feelies.ingestion.data_integrity import DataHealth
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.storage.event_log import EventLog

if TYPE_CHECKING:
    from massive import RESTClient  # type: ignore[import-untyped]  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 5_000
_TYPE_RANK_QUOTE = 0
_TYPE_RANK_TRADE = 1


def _is_massive_rest_client_instance(client: object) -> bool:
    """Best-effort check for real Massive REST client instances.

    We only synthesize fresh per-thread clients for actual Massive
    REST clients (or thin wrappers around one).  Test doubles such as
    ``MagicMock`` and the limited wrapper fixtures used in ingestion
    tests should keep their configured methods and therefore fall back
    to the provided instance unless we can re-wrap a cloned inner
    Massive client safely.
    """
    return type(client).__module__.startswith("massive")


def _clone_parallel_clients(client: Any, api_key: str) -> tuple[Any, Any]:
    """Return per-thread clients when safe, else reuse the provided one.

    Real Massive REST clients get two fresh instances to avoid sharing
    the same urllib3 pool across the quote/trade threads.  For mocks,
    limited wrappers, and other test doubles, reusing the provided
    object is intentional: their configured methods, credentials, and
    record caps must stay attached to the instance the caller passed in.
    """

    if _is_massive_rest_client_instance(client):
        try:
            return type(client)(api_key=api_key), type(client)(api_key=api_key)
        except TypeError:
            pass

    return client, client


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

    __slots__ = (
        "_api_key",
        "_normalizer",
        "_event_log",
        "_clock",
        "_checkpoint",
        "_parallel_clients",
    )

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
        # Lazy cache of (source_client, client_q, client_t) used by all
        # ``ingest_symbol_parallel`` invocations sharing the same source
        # ``client``.  Avoids constructing 2N urllib3 pools for an N-symbol
        # backfill (audit B3-MINOR).  Keyed on the source ``client`` identity
        # so a reused ingestor or a later call with a different client (test
        # doubles, wrappers) rebuilds the pair instead of silently reusing
        # the stale one.
        self._parallel_clients: tuple[Any, Any, Any] | None = None

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

        # Multi-symbol ingest accumulates each symbol's full-session batches into
        # an order-tolerant scratch log: consecutive symbols carry overlapping
        # exchange-timestamp ranges, so appending them straight into the strict
        # destination log would raise ``CausalityViolation`` on the second symbol
        # before the global resequence below ever ran (audit ING-10).  Order is
        # imposed once, at the end, via ``resequence_event_list`` +
        # ``replace_events``.  Single-symbol ingest writes straight to the
        # destination and keeps the strict guard.
        multi_symbol = len(symbols) > 1
        from feelies.storage.memory_event_log import InMemoryEventLog

        accumulate_log: EventLog = (
            InMemoryEventLog(enforce_market_order=False) if multi_symbol else self._event_log
        )

        for symbol in symbols:
            q_done = self._checkpoint.is_done(symbol, "quotes")
            t_done = self._checkpoint.is_done(symbol, "trades")
            if q_done and t_done:
                logger.info("massive_ingestor: skipping %s (checkpoint complete)", symbol)
                completed_symbols.add(symbol)
                continue

            logger.info(
                "massive_ingestor: ingesting %s from %s to %s",
                symbol,
                start_date,
                end_date,
            )

            ev_count, pg_count = self.ingest_symbol_parallel(
                client,
                symbol,
                start_date,
                end_date,
                on_page=on_page,
                target_log=accumulate_log if multi_symbol else None,
            )
            total_events += ev_count
            total_pages += pg_count

            completed_symbols.add(symbol)
            logger.info(
                "massive_ingestor: completed %s, cumulative events: %d",
                symbol,
                total_events,
            )

        health = self._normalizer.all_health()
        gaps = sum(
            1 for h in health.values() if h in (DataHealth.GAP_DETECTED, DataHealth.CORRUPTED)
        )

        if multi_symbol:
            from feelies.storage.event_resequence import resequence_event_list

            merged_raw = [
                e for e in self._event_log.replay() if isinstance(e, (NBBOQuote, Trade))
            ]
            merged_raw.extend(
                e for e in accumulate_log.replay() if isinstance(e, (NBBOQuote, Trade))
            )
            sorted_events = resequence_event_list(merged_raw)
            self._event_log.replace_events(sorted_events)

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
        target_log: EventLog | None = None,
    ) -> tuple[int, int]:
        """Download quotes + trades in parallel, merge-sort, normalize sequentially.

        Returns (events_ingested, pages_processed).

        ``target_log`` overrides the destination for this symbol's batches
        (defaults to ``self._event_log``).  The multi-symbol :meth:`ingest`
        path passes an order-tolerant scratch log here so per-symbol batches
        (each a full session, whose timestamps overlap the previous symbol's)
        can accumulate without tripping the shared log's cross-symbol
        monotonicity guard; final order is imposed once by
        ``resequence_event_list`` + ``replace_events`` (audit ING-10).
        """
        dest = target_log if target_log is not None else self._event_log
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

        # Real Massive clients get distinct per-thread instances so their
        # urllib3 pools never collide.  Mocks and test wrappers fall back to
        # the configured client object unless we can safely clone and re-wrap
        # an inner Massive client.  Cached on ``self`` keyed by the source
        # ``client`` identity so a multi-symbol backfill reuses the same pair
        # across calls (audit B3-MINOR), while a reused ingestor or a later
        # call with a different client rebuilds the pair instead of silently
        # routing through the stale one.
        if self._parallel_clients is None or self._parallel_clients[0] is not client:
            client_q, client_t = _clone_parallel_clients(client, self._api_key)
            self._parallel_clients = (client, client_q, client_t)
        else:
            _, client_q, client_t = self._parallel_clients

        with ThreadPoolExecutor(max_workers=2) as pool:
            quotes_future = pool.submit(
                _download_raw,
                client_q,
                symbol,
                start_date,
                end_date,
                client_q.list_quotes,
                "quotes",
                _q_on_page,
            )
            trades_future = pool.submit(
                _download_raw,
                client_t,
                symbol,
                start_date,
                end_date,
                client_t.list_trades,
                "trades",
                _t_on_page,
            )
            # One REST stream can exceed 5m on liquid names / full session days;
            # ``TimeoutError`` has an empty ``str()``, so a too-tight bound looks
            # like an opaque ingestion failure in the backtest CLI.
            _DOWNLOAD_TIMEOUT_S = 900
            raw_quotes, q_pages, q_ok = quotes_future.result(timeout=_DOWNLOAD_TIMEOUT_S)
            raw_trades, t_pages, t_ok = trades_future.result(timeout=_DOWNLOAD_TIMEOUT_S)

        if not q_ok:
            raise DataIntegrityError(
                f"massive_ingestor: quotes REST pagination did not complete cleanly "
                f"for {symbol} ({start_date}–{end_date}) — refusing partial checkpoint "
                "and refusing to normalize",
            )
        if not t_ok:
            raise DataIntegrityError(
                f"massive_ingestor: trades REST pagination did not complete cleanly "
                f"for {symbol} ({start_date}–{end_date}) — refusing partial checkpoint "
                "and refusing to normalize",
            )

        total_pages = q_pages + t_pages
        logger.info(
            "massive_ingestor: downloaded %d raw quotes + %d raw trades for %s (%d pages)",
            len(raw_quotes),
            len(raw_trades),
            symbol,
            total_pages,
        )

        for d in raw_quotes:
            d["__type_rank__"] = _TYPE_RANK_QUOTE
        for d in raw_trades:
            d["__type_rank__"] = _TYPE_RANK_TRADE

        merged = raw_quotes + raw_trades
        del raw_quotes, raw_trades  # free the two intermediate copies before processing
        # Sort key MUST mirror the canonical ``event_merge_sort_key``
        # ``(exchange_timestamp_ns, symbol, type_rank, sequence)`` — within a
        # single-symbol ingest ``symbol`` is constant, so the alignment reduces
        # to ``(sip_timestamp, type_rank, sequence_number)``: quotes (rank 0)
        # sort before trades (rank 1) at equal timestamps, *then* by vendor
        # sequence.  Earlier code ordered ``sequence_number`` ahead of
        # ``type_rank``, which disagreed with the per-chunk stabilization in
        # ``InMemoryEventLog`` and could raise a spurious ``CausalityViolation``
        # when a run of same-ns quote/trade rows straddled a 5 000-row chunk
        # boundary (audit ING-02).
        merged.sort(
            key=lambda d: (
                d.get("sip_timestamp", 0),
                d.get("__type_rank__", 0),
                d.get("sequence_number", 0),
            )
        )

        total_events_local = 0
        chunk: list[NBBOQuote | Trade] = []

        for rec_dict in merged:
            rec_dict.pop("__type_rank__", None)
            raw = json.dumps(rec_dict).encode("utf-8")
            received_ns = self._clock.now_ns()
            events = self._normalizer.on_message(raw, received_ns, "massive_rest")
            chunk.extend(events)
            if len(chunk) >= _CHUNK_SIZE:
                dest.append_batch(chunk)
                total_events_local += len(chunk)
                chunk = []

        if chunk:
            dest.append_batch(chunk)
            total_events_local += len(chunk)

        self._checkpoint.mark_done(symbol, "quotes")
        self._checkpoint.mark_done(symbol, "trades")

        return total_events_local, total_pages


def _download_raw(
    client: RESTClient,
    symbol: str,
    start_date: str,
    end_date: str,
    list_fn: Callable[..., Any],
    data_label: str,
    _on_page: Callable[[int, int], None] | None = None,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Paginate through a client list method, collecting raw dicts.

    ``list_fn`` is either ``client.list_quotes`` or ``client.list_trades``.
    ``data_label`` is used only for log messages.

    Returns ``(records, pages, completed_ok)``.  ``completed_ok`` is False when
    iteration aborted via exception — callers must not checkpoint or treat
    the stream as complete (empty-but-successful downloads still yield True).
    """
    raw_dicts: list[dict[str, Any]] = []
    pages = 0

    try:
        records_iter = list_fn(
            symbol,
            timestamp_gte=f"{start_date}T00:00:00Z",
            timestamp_lte=f"{end_date}T23:59:59Z",
            order="asc",
            sort="timestamp",
            limit=50000,
        )
    except Exception:
        logger.exception(
            "massive_ingestor: failed to start %s iteration for %s",
            data_label,
            symbol,
        )
        return [], 0, False

    buf: list[Any] = []
    completed_ok = True
    try:
        for obj in records_iter:
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
    except Exception:
        completed_ok = False
        logger.exception(
            "massive_ingestor: mid-pagination error for %s/%s after %d pages;"
            " partial data (%d records) retained",
            symbol,
            data_label,
            pages,
            len(raw_dicts),
        )

    if buf:
        for record in buf:
            d = _model_to_dict(record, symbol)
            if d:
                raw_dicts.append(d)
        pages += 1
        if _on_page is not None:
            _on_page(pages, len(raw_dicts))

    return raw_dicts, pages, completed_ok


def _model_to_dict(record: Any, symbol: str) -> dict[str, Any]:
    """Convert a massive model object to a dict.

    The massive ``@modelclass`` decorator stores only explicitly-set
    fields in ``__dict__``; class-level ``None`` defaults are invisible.
    We iterate through ``__annotations__`` on the model class to capture
    all declared fields, including those left at their default ``None``.

    Defense-in-depth: when the upstream returns a ``ticker`` that does
    not match the requested ``symbol`` (Massive bug, proxy misconfig,
    cache poisoning), drop the record with a warning so the wrong-symbol
    data never pollutes the normalizer's state machines (audit
    r3-INGEST-05).  Empty / missing ``ticker`` is back-filled to the
    requested symbol — that is the documented contract.
    """
    cls = type(record)
    annotations = getattr(cls, "__annotations__", None)

    if annotations:
        rec_dict = {k: getattr(record, k, None) for k in annotations if not k.startswith("_")}
    elif isinstance(record, dict):
        rec_dict = dict(record)
    elif hasattr(record, "__dict__"):
        rec_dict = dict(record.__dict__)
    else:
        return {}

    # Prune None values so the normalizer's .get() defaults work correctly
    rec_dict = {k: v for k, v in rec_dict.items() if v is not None}

    returned = rec_dict.get("ticker")
    if returned is None or returned == "":
        rec_dict["ticker"] = symbol
    elif str(returned).upper() != symbol.upper():
        logger.warning(
            "massive_ingestor: REST record ticker %r does not match "
            "requested symbol %r — dropping record",
            returned,
            symbol,
        )
        return {}

    return rec_dict
