"""Unit tests for PolygonHistoricalIngestor."""

from __future__ import annotations

import importlib.util
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from feelies.core.clock import SimulatedClock
from feelies.ingestion.polygon_ingestor import (
    InMemoryCheckpoint,
    PolygonHistoricalIngestor,
    _model_to_dict,
)
from feelies.ingestion.polygon_normalizer import PolygonNormalizer
from feelies.storage.memory_event_log import InMemoryEventLog


def _make_mock_quote(seq: int = 1, ts_ns: int = 1700000000000000000) -> Any:
    """Create a mock object resembling polygon Quote model with __annotations__ on class."""

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
    """Create a mock object resembling polygon Trade model."""

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


class TestPolygonHistoricalIngestor:
    """Tests for PolygonHistoricalIngestor with mocked REST client."""

    @pytest.mark.skipif(
        importlib.util.find_spec("polygon") is not None,
        reason="polygon installed; ImportError path only testable when package absent",
    )
    def test_ingest_raises_without_polygon_package(self) -> None:
        """When polygon is not installed, ingest raises ImportError."""
        ingestor = PolygonHistoricalIngestor(
            api_key="test-key",
            normalizer=PolygonNormalizer(SimulatedClock()),
            event_log=InMemoryEventLog(),
            clock=SimulatedClock(),
        )
        with pytest.raises(ImportError, match="polygon-api-client"):
            ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-01")

    def test_ingest_with_mocked_rest_client(self) -> None:
        """Ingest uses REST client and persists normalized events."""
        clock = SimulatedClock(1700000000000000000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(return_value=iter([_make_mock_quote()]))
        mock_client.list_trades = MagicMock(return_value=iter([_make_mock_trade()]))

        ingestor = PolygonHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        with patch("polygon.RESTClient", return_value=mock_client):
            result = ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-02")

        assert result.events_ingested >= 2  # at least 1 quote + 1 trade
        assert result.symbols_completed == frozenset({"AAPL"})
        assert len(event_log) >= 2


class TestCheckpointResumability:
    """Tests for checkpoint-based resumable backfill."""

    def test_checkpoint_skips_completed_feeds(self) -> None:
        """When checkpoint says quotes are done, only trades are ingested."""
        clock = SimulatedClock(1700000000000000000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()
        checkpoint = InMemoryCheckpoint()
        checkpoint.mark_done("AAPL", "quotes")

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(return_value=iter([]))
        mock_client.list_trades = MagicMock(return_value=iter([_make_mock_trade()]))

        ingestor = PolygonHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
            checkpoint=checkpoint,
        )

        with patch("polygon.RESTClient", return_value=mock_client):
            result = ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-02")

        mock_client.list_quotes.assert_not_called()
        mock_client.list_trades.assert_called_once()
        assert result.events_ingested >= 1
        assert result.symbols_completed == frozenset({"AAPL"})

    def test_checkpoint_marks_done_after_ingest(self) -> None:
        """After successful ingest, checkpoint records completion."""
        clock = SimulatedClock(1700000000000000000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()
        checkpoint = InMemoryCheckpoint()

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(return_value=iter([_make_mock_quote()]))
        mock_client.list_trades = MagicMock(return_value=iter([_make_mock_trade()]))

        ingestor = PolygonHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
            checkpoint=checkpoint,
        )

        with patch("polygon.RESTClient", return_value=mock_client):
            ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-02")

        assert checkpoint.is_done("AAPL", "quotes")
        assert checkpoint.is_done("AAPL", "trades")
        assert not checkpoint.is_done("MSFT", "quotes")

    def test_second_ingest_skips_all_completed(self) -> None:
        """A re-run with the same checkpoint skips everything."""
        clock = SimulatedClock(1700000000000000000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()
        checkpoint = InMemoryCheckpoint()

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(return_value=iter([_make_mock_quote()]))
        mock_client.list_trades = MagicMock(return_value=iter([_make_mock_trade()]))

        ingestor = PolygonHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
            checkpoint=checkpoint,
        )

        with patch("polygon.RESTClient", return_value=mock_client):
            ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-02")

        mock_client.reset_mock()
        mock_client.list_quotes = MagicMock(return_value=iter([]))
        mock_client.list_trades = MagicMock(return_value=iter([]))

        with patch("polygon.RESTClient", return_value=mock_client):
            result2 = ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-02")

        mock_client.list_quotes.assert_not_called()
        mock_client.list_trades.assert_not_called()
        assert result2.events_ingested == 0


class TestDuplicateCountingInIngestor:
    """Tests that IngestResult.duplicates_filtered reflects normalizer counts."""

    def test_reports_duplicates_from_normalizer(self) -> None:
        clock = SimulatedClock(1700000000000000000)
        normalizer = PolygonNormalizer(clock)
        event_log = InMemoryEventLog()

        same_quote = _make_mock_quote(seq=1, ts_ns=1700000000000000000)

        mock_client = MagicMock()
        mock_client.list_quotes = MagicMock(
            return_value=iter([same_quote, same_quote, same_quote]),
        )
        mock_client.list_trades = MagicMock(return_value=iter([]))

        ingestor = PolygonHistoricalIngestor(
            api_key="test",
            normalizer=normalizer,
            event_log=event_log,
            clock=clock,
        )

        with patch("polygon.RESTClient", return_value=mock_client):
            result = ingestor.ingest(["AAPL"], "2024-01-01", "2024-01-02")

        assert result.duplicates_filtered == 2
        assert result.events_ingested == 1
