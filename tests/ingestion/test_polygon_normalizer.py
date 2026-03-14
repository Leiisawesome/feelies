"""Unit tests for PolygonNormalizer and PolygonLiveFeed validation."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, Trade
from feelies.ingestion.data_integrity import DataHealth
from feelies.ingestion.polygon_normalizer import PolygonNormalizer
from feelies.ingestion.polygon_ws import PolygonLiveFeed


class TestPolygonNormalizerWebSocket:
    """Tests for WebSocket message parsing (polygon_ws source)."""

    def test_parses_ws_quote(self, normalizer: PolygonNormalizer, clock: SimulatedClock) -> None:
        msg = {
            "ev": "Q",
            "sym": "AAPL",
            "bp": 150.0,
            "ap": 150.05,
            "bs": 100,
            "as": 200,
            "t": 1700000000000,
            "q": 1,
            "bx": 11,
            "ax": 12,
            "z": 3,
        }
        raw = json.dumps(msg).encode("utf-8")
        events = normalizer.on_message(raw, clock.now_ns(), "polygon_ws")
        assert len(events) == 1
        quote = events[0]
        assert isinstance(quote, NBBOQuote)
        assert quote.symbol == "AAPL"
        assert quote.bid == Decimal("150.0")
        assert quote.ask == Decimal("150.05")
        assert quote.bid_size == 100
        assert quote.ask_size == 200
        assert quote.exchange_timestamp_ns == 1_700_000_000_000_000_000
        assert quote.bid_exchange == 11
        assert quote.ask_exchange == 12
        assert quote.sequence_number == 1
        assert quote.tape == 3
        assert quote.correlation_id

    def test_parses_ws_trade(self, normalizer: PolygonNormalizer, clock: SimulatedClock) -> None:
        msg = {
            "ev": "T",
            "sym": "AAPL",
            "p": 150.02,
            "s": 100,
            "t": 1700000000001,
            "q": 2,
            "x": 4,
            "i": "trade123",
            "z": 3,
        }
        raw = json.dumps(msg).encode("utf-8")
        events = normalizer.on_message(raw, clock.now_ns(), "polygon_ws")
        assert len(events) == 1
        trade = events[0]
        assert isinstance(trade, Trade)
        assert trade.symbol == "AAPL"
        assert trade.price == Decimal("150.02")
        assert trade.size == 100
        assert trade.exchange == 4
        assert trade.trade_id == "trade123"
        assert trade.exchange_timestamp_ns == 1_700_000_000_001_000_000

    def test_ws_array_parses_multiple_messages(
        self, normalizer: PolygonNormalizer, clock: SimulatedClock
    ) -> None:
        msgs = [
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1},
            {"ev": "T", "sym": "AAPL", "p": 150.02, "s": 50, "t": 1001, "q": 2},
        ]
        raw = json.dumps(msgs).encode("utf-8")
        events = normalizer.on_message(raw, clock.now_ns(), "polygon_ws")
        assert len(events) == 2
        assert isinstance(events[0], NBBOQuote)
        assert isinstance(events[1], Trade)

    def test_dedup_filters_exact_duplicate(
        self, normalizer: PolygonNormalizer, clock: SimulatedClock
    ) -> None:
        msg = {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1}
        raw = json.dumps(msg).encode("utf-8")
        events1 = normalizer.on_message(raw, clock.now_ns(), "polygon_ws")
        events2 = normalizer.on_message(raw, clock.now_ns(), "polygon_ws")
        assert len(events1) == 1
        assert len(events2) == 0

    def test_unknown_source_returns_empty(self, normalizer: PolygonNormalizer, clock: SimulatedClock) -> None:
        raw = b'{"ev":"Q","sym":"AAPL","bp":150,"ap":150.05,"bs":10,"as":20,"t":1000,"q":1}'
        events = normalizer.on_message(raw, clock.now_ns(), "unknown_feed")
        assert events == []

    def test_invalid_json_returns_empty(self, normalizer: PolygonNormalizer, clock: SimulatedClock) -> None:
        events = normalizer.on_message(b"not json", clock.now_ns(), "polygon_ws")
        assert events == []


class TestPolygonNormalizerREST:
    """Tests for REST message parsing (polygon_rest source)."""

    def test_parses_rest_quote(self, normalizer: PolygonNormalizer, clock: SimulatedClock) -> None:
        rec = {
            "ticker": "MSFT",
            "bid_price": 400.0,
            "ask_price": 400.05,
            "bid_size": 50,
            "ask_size": 60,
            "bid_exchange": 11,
            "ask_exchange": 12,
            "sip_timestamp": 1_700_000_000_000_000_000,
            "sequence_number": 1,
            "tape": 3,
        }
        raw = json.dumps(rec).encode("utf-8")
        events = normalizer.on_message(raw, clock.now_ns(), "polygon_rest")
        assert len(events) == 1
        quote = events[0]
        assert isinstance(quote, NBBOQuote)
        assert quote.symbol == "MSFT"
        assert quote.bid == Decimal("400.0")
        assert quote.ask == Decimal("400.05")
        assert quote.exchange_timestamp_ns == 1_700_000_000_000_000_000

    def test_parses_rest_trade(self, normalizer: PolygonNormalizer, clock: SimulatedClock) -> None:
        rec = {
            "ticker": "MSFT",
            "price": 400.02,
            "size": 200,
            "sip_timestamp": 1_700_000_000_001_000_000,
            "sequence_number": 2,
            "exchange": 4,
            "id": "t123",
            "tape": 3,
        }
        raw = json.dumps(rec).encode("utf-8")
        events = normalizer.on_message(raw, clock.now_ns(), "polygon_rest")
        assert len(events) == 1
        trade = events[0]
        assert isinstance(trade, Trade)
        assert trade.symbol == "MSFT"
        assert trade.price == Decimal("400.02")
        assert trade.size == 200

    def test_rest_non_dict_returns_empty(self, normalizer: PolygonNormalizer, clock: SimulatedClock) -> None:
        raw = json.dumps([1, 2, 3]).encode("utf-8")
        events = normalizer.on_message(raw, clock.now_ns(), "polygon_rest")
        assert events == []


class TestPolygonNormalizerHealth:
    """Tests for DataHealth tracking."""

    def test_health_returns_healthy_for_unknown_symbol(
        self, normalizer: PolygonNormalizer
    ) -> None:
        assert normalizer.health("UNKNOWN") == DataHealth.HEALTHY

    def test_health_tracks_symbol_after_parse(
        self, normalizer: PolygonNormalizer, clock: SimulatedClock
    ) -> None:
        msg = {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1}
        raw = json.dumps(msg).encode("utf-8")
        normalizer.on_message(raw, clock.now_ns(), "polygon_ws")
        assert normalizer.health("AAPL") == DataHealth.HEALTHY

    def test_all_health_returns_tracked_symbols(
        self, normalizer: PolygonNormalizer, clock: SimulatedClock
    ) -> None:
        for sym in ("AAPL", "MSFT"):
            msg = {"ev": "Q", "sym": sym, "bp": 100.0, "ap": 100.05, "bs": 10, "as": 20, "t": 1000, "q": 1}
            normalizer.on_message(json.dumps(msg).encode("utf-8"), clock.now_ns(), "polygon_ws")
        health = normalizer.all_health()
        assert set(health.keys()) == {"AAPL", "MSFT"}
        assert all(h == DataHealth.HEALTHY for h in health.values())


class TestPolygonNormalizerDuplicateCounting:
    """Tests for duplicate counting."""

    def test_duplicates_filtered_starts_at_zero(
        self, normalizer: PolygonNormalizer
    ) -> None:
        assert normalizer.duplicates_filtered == 0

    def test_counts_exact_duplicates(
        self, normalizer: PolygonNormalizer, clock: SimulatedClock
    ) -> None:
        msg = {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1}
        raw = json.dumps(msg).encode("utf-8")
        normalizer.on_message(raw, clock.now_ns(), "polygon_ws")
        normalizer.on_message(raw, clock.now_ns(), "polygon_ws")
        normalizer.on_message(raw, clock.now_ns(), "polygon_ws")
        assert normalizer.duplicates_filtered == 2

    def test_non_duplicates_do_not_increment(
        self, normalizer: PolygonNormalizer, clock: SimulatedClock
    ) -> None:
        for q in (1, 2, 3):
            msg = {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000 + q, "q": q}
            normalizer.on_message(json.dumps(msg).encode("utf-8"), clock.now_ns(), "polygon_ws")
        assert normalizer.duplicates_filtered == 0


class TestPolygonNormalizerGapRecovery:
    """Tests for gap detection and automatic recovery."""

    def test_gap_triggers_gap_detected(
        self, normalizer: PolygonNormalizer, clock: SimulatedClock
    ) -> None:
        msgs = [
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1},
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1005, "q": 5},
        ]
        for msg in msgs:
            normalizer.on_message(json.dumps(msg).encode("utf-8"), clock.now_ns(), "polygon_ws")
        assert normalizer.health("AAPL") == DataHealth.GAP_DETECTED

    def test_continuity_after_gap_recovers_to_healthy(
        self, normalizer: PolygonNormalizer, clock: SimulatedClock
    ) -> None:
        msgs = [
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1},
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1005, "q": 5},
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1006, "q": 6},
        ]
        for msg in msgs:
            normalizer.on_message(json.dumps(msg).encode("utf-8"), clock.now_ns(), "polygon_ws")
        assert normalizer.health("AAPL") == DataHealth.HEALTHY


class TestPolygonLiveFeedValidation:
    """Tests for _validate_status_response (WebSocket auth/subscribe checks)."""

    def test_accepts_auth_success_array(self) -> None:
        raw = json.dumps([{"ev": "status", "status": "auth_success", "message": "authenticated"}])
        PolygonLiveFeed._validate_status_response(raw, "auth_success", "authentication")

    def test_accepts_subscribe_success(self) -> None:
        raw = json.dumps([{"ev": "status", "status": "success", "message": "subscribed to Q.AAPL"}])
        PolygonLiveFeed._validate_status_response(raw, "success", "subscription")

    def test_accepts_single_object(self) -> None:
        raw = json.dumps({"ev": "status", "status": "auth_success"})
        PolygonLiveFeed._validate_status_response(raw, "auth_success", "authentication")

    def test_rejects_auth_failure(self) -> None:
        raw = json.dumps([{"ev": "status", "status": "auth_failed", "message": "bad key"}])
        with pytest.raises(ConnectionError, match="authentication failed"):
            PolygonLiveFeed._validate_status_response(raw, "auth_success", "authentication")

    def test_rejects_invalid_json(self) -> None:
        with pytest.raises(ConnectionError, match="not valid JSON"):
            PolygonLiveFeed._validate_status_response(b"not json", "auth_success", "authentication")

    def test_rejects_empty_array(self) -> None:
        raw = json.dumps([])
        with pytest.raises(ConnectionError, match="authentication failed"):
            PolygonLiveFeed._validate_status_response(raw, "auth_success", "authentication")
