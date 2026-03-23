"""Unit tests for MassiveHistoricalIngestor."""

from __future__ import annotations

import importlib.util
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from feelies.core.clock import SimulatedClock
from feelies.ingestion.massive_ingestor import (
    InMemoryCheckpoint,
    MassiveHistoricalIngestor,
    _model_to_dict,
)
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.storage.memory_event_log import InMemoryEventLog


def _make_mock_quote(seq: int = 1, ts_ns: int = 1700000000000000000) -> Any:
    """Create a mock object resembling massive Quote model with __annotations__ on class."""

    class MockQuote:
        __annotations__ = {
            "ask_exchange": int,
            "ask_price": float,
            "ask_size": float,
            "bid_exchange": int,
            "bid_price": float,
            "bid_size": float,
            "conditions": list,
            "indicators": list,
            "participant_timestamp": int,
            "sequence_number": int,
            "sip_timestamp": int,
            "tape": int,
            "trf_timestamp": int,
        }

        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)

    return MockQuote(
        ask_exchange=12,
        ask_price=150.05,
        ask_size=100.0,
        bid_exchange=11,
        bid_price=150.0,
        bid_size=90.0,
        conditions=[1, 2],
        indicators=[],
        participant_timestamp=None,
        sequence_number=seq,
        sip_timestamp=ts_ns,
        tape=3,
        trf_timestamp=None,
    )


def _make_mock_trade(seq: int = 1, ts_ns: int = 1700000000001000000) -> Any:
    """Create a mock object resembling massive Trade model."""

    class MockTrade:
        __annotations__ = {
            "conditions": list,
            "correction": int,
            "exchange": int,
            "id": str,
            "participant_timestamp": int,
            "price": float,
            "sequence_number": int,
            "sip_timestamp": int,
            "size": float,
            "tape": int,
            "trf_id": int,
            "trf_timestamp": int,
        }

        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)

    return MockTrade(
        conditions=[0, 12],
        correction=0,
        exchange=11,
        id="trade123",
        participant_timestamp=None,
        price=150.02,
        sequence_number=seq,
        sip_timestamp=ts_ns,
        size=100.0,
        tape=3,
        trf_id=5,
        trf_timestamp=None,
    )


class TestModelToDict:
    """Tests for _model_to_dict helper."""

    def test_converts_mock_quote_to_dict(self) -> None:
        quote = _make_mock_quote()
        out = _model_to_dict(quote, "AAPL")
        assert out["ticker"] == "AAPL"
        assert out["bid_price"] == 150.0
        assert out["ask_price"] == 150.05
        assert out["sip_timestamp"] == 1700000000000000000
        assert out["sequence_number"] == 1

    def test_converts_mock_trade_to_dict(self) -> None:
        trade = _make_mock_trade()
        out = _model_to_dict(trade, "MSFT")
        assert out["ticker"] == "MSFT"
        assert out["price"] == 150.02
        assert out["size"] == 100.0
        assert out["sip_timestamp"] == 1700000000001000000

    def test_injects_ticker_if_missing(self) -> None:
        quote = _make_mock_quote()
        out = _model_to_dict(quote, "GOOG")
        assert out["ticker"] == "GOOG"

    def test_plain_dict_passthrough(self) -> None:
        d = {"ticker": "AAPL", "bid_price": 100.0, "sip_timestamp": 123}
        out = _model_to_dict(d, "AAPL")
        assert out == {"ticker": "AAPL", "bid_price": 100.0, "sip_timestamp": 123}


class TestMassiveHistoricalIngestor:
    """Tests for MassiveHistoricalIngestor with mocked REST client."""

    @pytest.mark.skipif(
        importlib.util.find_spec("massive") is not None,
        reason="massive installed; ImportError path only testable when package absent",
    )
    def test_ingest_raises_without_massive_package(self) -> None:
        """When massive is not installed, ingest raises ImportError."""
        ingestor = MassiveHistoricalIngestor(
            api_key="test-key",
            normalizer=MassiveNormalizer(SimulatedClock()),
            event_log=InMemoryEventLog(),
            clock=SimulatedClock(),
        )
        with pytest.raises(ImportError, match="massive"):
            ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-01")

    def test_ingest_with_mocked_rest_client(self) -> None:
        """Ingest uses REST client and persists normalized events."""
        clock = SimulatedClock(1700000000000000000)
        normalizer = MassiveNormalizer(clock)
        event_log = InMemoryEventLog()

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(return_value=iter([_make_mock_quote()]))
        mock_client.list_trades = MagicMock(return_value=iter([_make_mock_trade()]))

        ingestor = MassiveHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        with patch("massive.RESTClient", return_value=mock_client):
            result = ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-02")

        assert result.events_ingested >= 2  # at least 1 quote + 1 trade
        assert result.symbols_completed == frozenset({"AAPL"})
        assert len(event_log) >= 2


class TestParallelDownload:
    """Tests for ingest_symbol_parallel (parallel download, sequential normalize)."""

    def test_parallel_downloads_both_feeds(self) -> None:
        """ingest_symbol_parallel calls list_quotes and list_trades."""
        clock = SimulatedClock(1700000000000000000)
        normalizer = MassiveNormalizer(clock)
        event_log = InMemoryEventLog()

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(return_value=iter([_make_mock_quote()]))
        mock_client.list_trades = MagicMock(return_value=iter([_make_mock_trade()]))

        ingestor = MassiveHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ev_count, pg_count = ingestor.ingest_symbol_parallel(
            mock_client, "AAPL", "2024-01-01", "2024-01-02",
        )

        mock_client.list_quotes.assert_called_once()
        mock_client.list_trades.assert_called_once()
        assert ev_count >= 2
        assert pg_count >= 2
        assert len(event_log) >= 2

    def test_parallel_produces_chronological_order(self) -> None:
        """Events are merge-sorted by sip_timestamp across feeds."""
        clock = SimulatedClock(1700000000000000000)
        normalizer = MassiveNormalizer(clock)
        event_log = InMemoryEventLog()

        q1 = _make_mock_quote(seq=1, ts_ns=1700000000000000000)
        q2 = _make_mock_quote(seq=2, ts_ns=1700000000003000000)
        t1 = _make_mock_trade(seq=1, ts_ns=1700000000001000000)
        t2 = _make_mock_trade(seq=2, ts_ns=1700000000002000000)

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(return_value=iter([q1, q2]))
        mock_client.list_trades = MagicMock(return_value=iter([t1, t2]))

        ingestor = MassiveHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        ingestor.ingest_symbol_parallel(
            mock_client, "AAPL", "2024-01-01", "2024-01-02",
        )

        events = list(event_log.replay())
        timestamps = [e.exchange_timestamp_ns for e in events]
        assert timestamps == sorted(timestamps), "events must be in chronological order"

    def test_ingest_delegates_to_parallel(self) -> None:
        """ingest() routes through ingest_symbol_parallel."""
        clock = SimulatedClock(1700000000000000000)
        normalizer = MassiveNormalizer(clock)
        event_log = InMemoryEventLog()

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(return_value=iter([_make_mock_quote()]))
        mock_client.list_trades = MagicMock(return_value=iter([_make_mock_trade()]))

        ingestor = MassiveHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        with patch("massive.RESTClient", return_value=mock_client):
            result = ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-02")

        mock_client.list_quotes.assert_called_once()
        mock_client.list_trades.assert_called_once()
        assert result.events_ingested >= 2
        assert result.symbols_completed == frozenset({"AAPL"})


class TestDuplicateCountingInIngestor:
    """Tests that IngestResult.duplicates_filtered reflects normalizer counts."""

    def test_reports_duplicates_from_normalizer(self) -> None:
        clock = SimulatedClock(1700000000000000000)
        normalizer = MassiveNormalizer(clock)
        event_log = InMemoryEventLog()

        same_quote = _make_mock_quote(seq=1, ts_ns=1700000000000000000)

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(
            return_value=iter([same_quote, same_quote, same_quote]),
        )
        mock_client.list_trades = MagicMock(return_value=iter([]))

        ingestor = MassiveHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        with patch("massive.RESTClient", return_value=mock_client):
            result = ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-02")

        assert result.duplicates_filtered == 2
        assert result.events_ingested == 1
