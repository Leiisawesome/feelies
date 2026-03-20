"""Functional Massive ingestion tests against live REST and WebSocket APIs.

These tests are intentionally opt-in and require a real Massive API key.
They also skip automatically when the market is not producing live stock
quote/trade traffic within the configured timeout window.
"""

from __future__ import annotations

import itertools
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest

from feelies.core.clock import SimulatedClock, WallClock
from feelies.core.events import NBBOQuote, Trade
from feelies.ingestion.massive_ingestor import MassiveHistoricalIngestor
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.ingestion.massive_ws import MassiveLiveFeed
from feelies.storage.memory_event_log import InMemoryEventLog

pytestmark = pytest.mark.functional

_DEFAULT_SYMBOL = "SPY"
_REST_LOOKBACK_DAYS = 14
_REST_RECORD_LIMIT = 25
_WS_TIMEOUT_S = 20


def _require_api_key() -> str:
    api_key = os.getenv("MASSIVE_API_KEY")
    if not api_key:
        pytest.skip("Set MASSIVE_API_KEY to run live Massive functional tests.")
    return api_key


def _symbol() -> str:
    return os.getenv("MASSIVE_FUNCTIONAL_SYMBOL", _DEFAULT_SYMBOL).upper()


def _rest_record_limit() -> int:
    value = os.getenv("MASSIVE_FUNCTIONAL_REST_RECORD_LIMIT")
    if value is None:
        return _REST_RECORD_LIMIT
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("MASSIVE_FUNCTIONAL_REST_RECORD_LIMIT must be positive.")
    return parsed


def _ws_timeout_s() -> int:
    value = os.getenv("MASSIVE_FUNCTIONAL_WS_TIMEOUT_S")
    if value is None:
        return _WS_TIMEOUT_S
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("MASSIVE_FUNCTIONAL_WS_TIMEOUT_S must be positive.")
    return parsed


def _session_bounds(session_date: date) -> tuple[str, str]:
    day = session_date.isoformat()
    return f"{day}T00:00:00Z", f"{day}T23:59:59Z"


def _first_or_none(items: Iterator[Any]) -> Any | None:
    return next(items, None)


def _find_recent_session_with_data(client: Any, symbol: str) -> str:
    for days_back in range(1, _REST_LOOKBACK_DAYS + 1):
        session_date = datetime.now(UTC).date() - timedelta(days=days_back)
        start_ts, end_ts = _session_bounds(session_date)

        quote = _first_or_none(
            iter(
                client.list_quotes(
                    symbol,
                    timestamp_gte=start_ts,
                    timestamp_lte=end_ts,
                    order="asc",
                    sort="timestamp",
                    limit=1,
                )
            )
        )
        trade = _first_or_none(
            iter(
                client.list_trades(
                    symbol,
                    timestamp_gte=start_ts,
                    timestamp_lte=end_ts,
                    order="asc",
                    sort="timestamp",
                    limit=1,
                )
            )
        )

        if quote is not None and trade is not None:
            return session_date.isoformat()

    pytest.skip(
        f"No recent Massive quote/trade data found for {symbol} in the last "
        f"{_REST_LOOKBACK_DAYS} calendar days."
    )


class _LimitedRESTClient:
    __slots__ = ("_client", "_max_records")

    def __init__(self, client: Any, max_records: int) -> None:
        self._client = client
        self._max_records = max_records

    def list_quotes(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        kwargs["limit"] = min(int(kwargs.get("limit", self._max_records)), self._max_records)
        return itertools.islice(self._client.list_quotes(*args, **kwargs), self._max_records)

    def list_trades(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        kwargs["limit"] = min(int(kwargs.get("limit", self._max_records)), self._max_records)
        return itertools.islice(self._client.list_trades(*args, **kwargs), self._max_records)


def _next_live_event(feed: MassiveLiveFeed, timeout_s: int) -> NBBOQuote | Trade:
    def _read_one() -> NBBOQuote | Trade:
        return next(feed.events())

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_read_one)
        try:
            return future.result(timeout=timeout_s)
        except TimeoutError:
            feed.stop()
            pytest.skip(
                f"No live Massive stock quote/trade arrived for {_symbol()} within "
                f"{timeout_s}s. The market may be closed or inactive."
            )


def test_rest_ingest_uses_live_massive_data() -> None:
    massive = pytest.importorskip("massive")

    api_key = _require_api_key()
    symbol = _symbol()
    record_limit = _rest_record_limit()

    discovery_client = massive.RESTClient(api_key=api_key)
    session_date = _find_recent_session_with_data(discovery_client, symbol)

    limited_client = _LimitedRESTClient(
        client=massive.RESTClient(api_key=api_key),
        max_records=record_limit,
    )
    clock = SimulatedClock(start_ns=1_700_000_000_000_000_000)
    normalizer = MassiveNormalizer(clock)
    event_log = InMemoryEventLog()
    ingestor = MassiveHistoricalIngestor(
        api_key=api_key,
        normalizer=normalizer,
        event_log=event_log,
        clock=clock,
    )

    with patch("massive.RESTClient", return_value=limited_client):
        result = ingestor.ingest([symbol], session_date, session_date)

    events = list(event_log.replay())

    assert result.events_ingested == len(events)
    assert result.events_ingested > 0
    assert result.pages_processed >= 2
    assert result.symbols_completed == frozenset({symbol})
    assert any(isinstance(event, NBBOQuote) for event in events)
    assert any(isinstance(event, Trade) for event in events)


def test_websocket_feed_emits_live_massive_event() -> None:
    pytest.importorskip("websockets")

    api_key = _require_api_key()
    symbol = _symbol()
    timeout_s = _ws_timeout_s()
    feed = MassiveLiveFeed(
        api_key=api_key,
        symbols=[symbol],
        normalizer=MassiveNormalizer(WallClock()),
        clock=WallClock(),
    )

    feed.start()
    try:
        event = _next_live_event(feed, timeout_s)
    finally:
        feed.stop()

    assert isinstance(event, (NBBOQuote, Trade))
    assert event.symbol == symbol
    assert event.correlation_id
    assert event.sequence > 0
    if isinstance(event, NBBOQuote):
        assert event.bid > 0
        assert event.ask > 0
        assert event.exchange_timestamp_ns > 0
    else:
        assert event.price > 0
        assert event.size > 0
        assert event.exchange_timestamp_ns > 0