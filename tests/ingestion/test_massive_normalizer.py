"""Unit tests for MassiveNormalizer and MassiveLiveFeed validation."""

from __future__ import annotations

import asyncio
import json
import queue
from decimal import Decimal
from typing import Any

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, Trade
from feelies.ingestion.data_integrity import DataHealth
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.ingestion.massive_ws import MassiveLiveFeed


class TestMassiveNormalizerWebSocket:
    """Tests for WebSocket message parsing (massive_ws source)."""

    def test_parses_ws_quote(self, normalizer: MassiveNormalizer, clock: SimulatedClock) -> None:
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
        events = normalizer.on_message(raw, clock.now_ns(), "massive_ws")
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

    def test_parses_ws_trade(self, normalizer: MassiveNormalizer, clock: SimulatedClock) -> None:
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
        events = normalizer.on_message(raw, clock.now_ns(), "massive_ws")
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
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        msgs = [
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1},
            {"ev": "T", "sym": "AAPL", "p": 150.02, "s": 50, "t": 1001, "q": 2},
        ]
        raw = json.dumps(msgs).encode("utf-8")
        events = normalizer.on_message(raw, clock.now_ns(), "massive_ws")
        assert len(events) == 2
        assert isinstance(events[0], NBBOQuote)
        assert isinstance(events[1], Trade)

    def test_dedup_filters_exact_duplicate(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        msg = {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1}
        raw = json.dumps(msg).encode("utf-8")
        events1 = normalizer.on_message(raw, clock.now_ns(), "massive_ws")
        events2 = normalizer.on_message(raw, clock.now_ns(), "massive_ws")
        assert len(events1) == 1
        assert len(events2) == 0

    def test_unknown_source_returns_empty(self, normalizer: MassiveNormalizer, clock: SimulatedClock) -> None:
        raw = b'{"ev":"Q","sym":"AAPL","bp":150,"ap":150.05,"bs":10,"as":20,"t":1000,"q":1}'
        events = normalizer.on_message(raw, clock.now_ns(), "unknown_feed")
        assert events == []

    def test_invalid_json_returns_empty(self, normalizer: MassiveNormalizer, clock: SimulatedClock) -> None:
        events = normalizer.on_message(b"not json", clock.now_ns(), "massive_ws")
        assert events == []


class TestMassiveNormalizerREST:
    """Tests for REST message parsing (massive_rest source)."""

    def test_parses_rest_quote(self, normalizer: MassiveNormalizer, clock: SimulatedClock) -> None:
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
        events = normalizer.on_message(raw, clock.now_ns(), "massive_rest")
        assert len(events) == 1
        quote = events[0]
        assert isinstance(quote, NBBOQuote)
        assert quote.symbol == "MSFT"
        assert quote.bid == Decimal("400.0")
        assert quote.ask == Decimal("400.05")
        assert quote.exchange_timestamp_ns == 1_700_000_000_000_000_000

    def test_parses_rest_trade(self, normalizer: MassiveNormalizer, clock: SimulatedClock) -> None:
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
        events = normalizer.on_message(raw, clock.now_ns(), "massive_rest")
        assert len(events) == 1
        trade = events[0]
        assert isinstance(trade, Trade)
        assert trade.symbol == "MSFT"
        assert trade.price == Decimal("400.02")
        assert trade.size == 200

    def test_rest_non_dict_returns_empty(self, normalizer: MassiveNormalizer, clock: SimulatedClock) -> None:
        raw = json.dumps([1, 2, 3]).encode("utf-8")
        events = normalizer.on_message(raw, clock.now_ns(), "massive_rest")
        assert events == []

    def test_rest_thinned_history_large_seq_jumps_stay_healthy(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        """REST rows omit intervening SIP ticks; sequence_number is not contiguous."""
        base_ts = 1_700_000_000_000_000_000
        for seq in (1, 5000, 5001):
            rec = {
                "ticker": "AAPL",
                "bid_price": 150.0,
                "ask_price": 150.05,
                "bid_size": 10,
                "ask_size": 20,
                "sip_timestamp": base_ts + seq,
                "sequence_number": seq,
            }
            normalizer.on_message(json.dumps(rec).encode("utf-8"), clock.now_ns(), "massive_rest")
        assert normalizer.health("AAPL") == DataHealth.HEALTHY


class TestMassiveNormalizerHealth:
    """Tests for DataHealth tracking."""

    def test_health_returns_healthy_for_unknown_symbol(
        self, normalizer: MassiveNormalizer
    ) -> None:
        assert normalizer.health("UNKNOWN") == DataHealth.HEALTHY

    def test_health_tracks_symbol_after_parse(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        msg = {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1}
        raw = json.dumps(msg).encode("utf-8")
        normalizer.on_message(raw, clock.now_ns(), "massive_ws")
        assert normalizer.health("AAPL") == DataHealth.HEALTHY

    def test_all_health_returns_tracked_symbols(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        for sym in ("AAPL", "MSFT"):
            msg = {"ev": "Q", "sym": sym, "bp": 100.0, "ap": 100.05, "bs": 10, "as": 20, "t": 1000, "q": 1}
            normalizer.on_message(json.dumps(msg).encode("utf-8"), clock.now_ns(), "massive_ws")
        health = normalizer.all_health()
        assert set(health.keys()) == {"AAPL", "MSFT"}
        assert all(h == DataHealth.HEALTHY for h in health.values())


class TestMassiveNormalizerDuplicateCounting:
    """Tests for duplicate counting."""

    def test_duplicates_filtered_starts_at_zero(
        self, normalizer: MassiveNormalizer
    ) -> None:
        assert normalizer.duplicates_filtered == 0

    def test_counts_exact_duplicates(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        msg = {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1}
        raw = json.dumps(msg).encode("utf-8")
        normalizer.on_message(raw, clock.now_ns(), "massive_ws")
        normalizer.on_message(raw, clock.now_ns(), "massive_ws")
        normalizer.on_message(raw, clock.now_ns(), "massive_ws")
        assert normalizer.duplicates_filtered == 2

    def test_non_duplicates_do_not_increment(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        for q in (1, 2, 3):
            msg = {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000 + q, "q": q}
            normalizer.on_message(json.dumps(msg).encode("utf-8"), clock.now_ns(), "massive_ws")
        assert normalizer.duplicates_filtered == 0

    def test_quote_and_trade_with_same_seq_ts_not_deduped(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        """Quote and trade feeds have independent sequence_number spaces.

        A quote and trade sharing (sequence_number, timestamp) must both
        survive — dedup is per (symbol, feed_type), not per symbol alone.
        """
        quote = {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 5}
        trade = {"ev": "T", "sym": "AAPL", "p": 150.02, "s": 100, "t": 1000, "q": 5}
        q_events = normalizer.on_message(json.dumps(quote).encode(), clock.now_ns(), "massive_ws")
        t_events = normalizer.on_message(json.dumps(trade).encode(), clock.now_ns(), "massive_ws")
        assert len(q_events) == 1
        assert len(t_events) == 1
        assert isinstance(q_events[0], NBBOQuote)
        assert isinstance(t_events[0], Trade)
        assert normalizer.duplicates_filtered == 0

    def test_rest_quote_and_trade_with_same_seq_ts_not_deduped(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        """Same cross-feed dedup safety for the REST path."""
        quote = {
            "ticker": "AAPL", "bid_price": 150.0, "ask_price": 150.05,
            "bid_size": 10, "ask_size": 20,
            "sip_timestamp": 1_700_000_000_000_000_000, "sequence_number": 42,
        }
        trade = {
            "ticker": "AAPL", "price": 150.02, "size": 100,
            "sip_timestamp": 1_700_000_000_000_000_000, "sequence_number": 42,
        }
        q_events = normalizer.on_message(json.dumps(quote).encode(), clock.now_ns(), "massive_rest")
        t_events = normalizer.on_message(json.dumps(trade).encode(), clock.now_ns(), "massive_rest")
        assert len(q_events) == 1
        assert len(t_events) == 1
        assert normalizer.duplicates_filtered == 0


class TestMassiveNormalizerSequenceCollision:
    """Vendor sequence reuse with different payloads must surface CORRUPTED."""

    def test_ws_quote_same_sequence_different_bid_corrupts(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        base = {
            "ev": "Q",
            "sym": "AAPL",
            "bp": 150.0,
            "ap": 150.05,
            "bs": 10,
            "as": 20,
            "t": 1000,
            "q": 5,
        }
        normalizer.on_message(json.dumps(base).encode("utf-8"), clock.now_ns(), "massive_ws")
        alt = {**base, "bp": 151.0}
        out = normalizer.on_message(json.dumps(alt).encode("utf-8"), clock.now_ns(), "massive_ws")
        assert out == []
        assert normalizer.health("AAPL") == DataHealth.CORRUPTED

    @pytest.mark.parametrize(
        ("field", "first_value", "second_value"),
        [
            ("correction", 0, 1),
            (
                "participant_timestamp",
                1_700_000_000_001_234_567,
                1_700_000_000_001_234_568,
            ),
            ("ft", 1_700_000_000_002_000_000, 1_700_000_000_002_000_001),
        ],
    )
    def test_ws_trade_same_sequence_different_optional_field_corrupts(
        self,
        normalizer: MassiveNormalizer,
        clock: SimulatedClock,
        field: str,
        first_value: int,
        second_value: int,
    ) -> None:
        base = {
            "ev": "T",
            "sym": "AAPL",
            "p": 150.02,
            "s": 100,
            "t": 1000,
            "q": 5,
        }
        first = {**base, field: first_value}
        normalizer.on_message(json.dumps(first).encode("utf-8"), clock.now_ns(), "massive_ws")

        alt = {**base, field: second_value}
        out = normalizer.on_message(json.dumps(alt).encode("utf-8"), clock.now_ns(), "massive_ws")

        assert out == []
        assert normalizer.health("AAPL") == DataHealth.CORRUPTED
        assert normalizer.duplicates_filtered == 0


class TestMassiveNormalizerNotifyFeedInterrupted:
    def test_disconnect_flags_gap_before_first_tick(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        normalizer.notify_feed_interrupted(["ZZZZ"])
        assert normalizer.health("ZZZZ") == DataHealth.GAP_DETECTED


class TestMassiveNormalizerGapRecovery:
    """Tests for gap detection and automatic recovery."""

    def test_gap_triggers_gap_detected(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        msgs = [
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1},
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1005, "q": 5},
        ]
        for msg in msgs:
            normalizer.on_message(json.dumps(msg).encode("utf-8"), clock.now_ns(), "massive_ws")
        assert normalizer.health("AAPL") == DataHealth.GAP_DETECTED

    def test_continuity_after_gap_recovers_to_healthy(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        msgs = [
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1},
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1005, "q": 5},
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1006, "q": 6},
        ]
        for msg in msgs:
            normalizer.on_message(json.dumps(msg).encode("utf-8"), clock.now_ns(), "massive_ws")
        assert normalizer.health("AAPL") == DataHealth.HEALTHY

    def test_interleaved_feeds_no_spurious_gap(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        """Interleaving quotes (seq 1,2,3) with trades (seq 100,101,102)
        must not fire gap detection — sequences are tracked per feed type.
        """
        msgs = [
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1},
            {"ev": "T", "sym": "AAPL", "p": 150.02, "s": 50, "t": 1001, "q": 100},
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1002, "q": 2},
            {"ev": "T", "sym": "AAPL", "p": 150.03, "s": 50, "t": 1003, "q": 101},
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1004, "q": 3},
            {"ev": "T", "sym": "AAPL", "p": 150.04, "s": 50, "t": 1005, "q": 102},
        ]
        for msg in msgs:
            normalizer.on_message(json.dumps(msg).encode("utf-8"), clock.now_ns(), "massive_ws")
        assert normalizer.health("AAPL") == DataHealth.HEALTHY

    def test_gap_in_one_feed_does_not_mask_other(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        """A gap in trades still fires even when quote sequences are contiguous."""
        msgs = [
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1},
            {"ev": "T", "sym": "AAPL", "p": 150.02, "s": 50, "t": 1001, "q": 1},
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1002, "q": 2},
            {"ev": "T", "sym": "AAPL", "p": 150.03, "s": 50, "t": 1003, "q": 10},
        ]
        for msg in msgs:
            normalizer.on_message(json.dumps(msg).encode("utf-8"), clock.now_ns(), "massive_ws")
        assert normalizer.health("AAPL") == DataHealth.GAP_DETECTED


class TestMassiveNormalizerCrossFeedHealth:
    """Quote vs trade sequence spaces must not false-clear each other's gaps."""

    def test_trade_continuity_does_not_clear_quote_gap(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        msgs = [
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1000, "q": 1},
            {"ev": "Q", "sym": "AAPL", "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20, "t": 1005, "q": 5},
            {"ev": "T", "sym": "AAPL", "p": 150.02, "s": 50, "t": 1001, "q": 100},
            {"ev": "T", "sym": "AAPL", "p": 150.03, "s": 50, "t": 1003, "q": 101},
        ]
        for msg in msgs:
            normalizer.on_message(json.dumps(msg).encode("utf-8"), clock.now_ns(), "massive_ws")
        assert normalizer.health("AAPL") == DataHealth.GAP_DETECTED


class TestMassiveNormalizerWsOptionalTimestamps:
    def test_ws_quote_optional_participant_trf_nanoseconds(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        msg = {
            "ev": "Q",
            "sym": "AAPL",
            "bp": 150.0,
            "ap": 150.05,
            "bs": 10,
            "as": 20,
            "t": 1700000000000,
            "q": 1,
            "participant_timestamp": 1_700_000_000_001_234_567,
            "trf_timestamp": 1_700_000_000_002_345_678,
        }
        raw = json.dumps(msg).encode("utf-8")
        ev = normalizer.on_message(raw, clock.now_ns(), "massive_ws")[0]
        assert isinstance(ev, NBBOQuote)
        assert ev.participant_timestamp_ns == 1_700_000_000_001_234_567
        assert ev.trf_timestamp_ns == 1_700_000_000_002_345_678


class TestMassiveNormalizerRestTradeTrf:
    def test_rest_trade_populates_trf_timestamp_ns(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock
    ) -> None:
        rec = {
            "ticker": "AAPL",
            "price": 150.02,
            "size": 100,
            "sip_timestamp": 1_700_000_000_000_000_000,
            "sequence_number": 3,
            "trf_timestamp": 1_700_000_000_000_000_099,
        }
        events = normalizer.on_message(
            json.dumps(rec).encode("utf-8"),
            clock.now_ns(),
            "massive_rest",
        )
        assert len(events) == 1
        tr = events[0]
        assert isinstance(tr, Trade)
        assert tr.trf_timestamp_ns == 1_700_000_000_000_000_099


class TestMassiveNormalizerRestGapOptIn:
    def test_rest_gap_detection_when_enabled(
        self, clock: SimulatedClock,
    ) -> None:
        norm = MassiveNormalizer(
            clock, enable_rest_sequence_gap_detection=True,
        )
        for seq in (1, 5):
            rec = {
                "ticker": "AAPL",
                "bid_price": 150.0,
                "ask_price": 150.05,
                "bid_size": 10,
                "ask_size": 20,
                "sip_timestamp": 1_700_000_000_000_000_000 + seq,
                "sequence_number": seq,
            }
            norm.on_message(
                json.dumps(rec).encode("utf-8"),
                clock.now_ns(),
                "massive_rest",
            )
        assert norm.health("AAPL") == DataHealth.GAP_DETECTED


class TestMassiveLiveFeedValidation:
    """Tests for _validate_status_response (WebSocket auth/subscribe checks)."""

    def test_accepts_auth_success_array(self) -> None:
        raw = json.dumps([{"ev": "status", "status": "auth_success", "message": "authenticated"}])
        MassiveLiveFeed._validate_status_response(raw, "auth_success", "authentication")

    def test_accepts_subscribe_success(self) -> None:
        raw = json.dumps([{"ev": "status", "status": "success", "message": "subscribed to Q.AAPL"}])
        MassiveLiveFeed._validate_status_response(raw, "success", "subscription")

    def test_accepts_single_object(self) -> None:
        raw = json.dumps({"ev": "status", "status": "auth_success"})
        MassiveLiveFeed._validate_status_response(raw, "auth_success", "authentication")

    def test_rejects_auth_failure(self) -> None:
        raw = json.dumps([{"ev": "status", "status": "auth_failed", "message": "bad key"}])
        with pytest.raises(ConnectionError, match="authentication failed"):
            MassiveLiveFeed._validate_status_response(raw, "auth_success", "authentication")

    def test_rejects_invalid_json(self) -> None:
        with pytest.raises(ConnectionError, match="not valid JSON"):
            MassiveLiveFeed._validate_status_response(b"not json", "auth_success", "authentication")

    def test_rejects_empty_array(self) -> None:
        raw = json.dumps([])
        with pytest.raises(ConnectionError, match="authentication failed"):
            MassiveLiveFeed._validate_status_response(raw, "auth_success", "authentication")


class _AsyncMessages:
    def __init__(self, messages: list[str | bytes]) -> None:
        self._messages = iter(messages)

    def __aiter__(self) -> _AsyncMessages:
        return self

    async def __anext__(self) -> str | bytes:
        try:
            return next(self._messages)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _AlwaysFullQueue:
    def __init__(self) -> None:
        self.put_nowait_called = False
        self.put_called = False

    def put_nowait(self, _item: object) -> None:
        self.put_nowait_called = True
        raise queue.Full

    def put(self, _item: object) -> None:
        self.put_called = True
        raise AssertionError("blocking queue.put must not be used")


class _FullSentinelQueue:
    def __init__(self) -> None:
        self.items: list[object] = [object()]
        self.put_nowait_calls = 0
        self.put_called = False

    def put_nowait(self, item: object) -> None:
        self.put_nowait_calls += 1
        if self.items:
            raise queue.Full
        self.items.append(item)

    def get_nowait(self) -> object:
        try:
            return self.items.pop(0)
        except IndexError as exc:
            raise queue.Empty from exc

    def put(self, _item: object) -> None:
        self.put_called = True
        raise AssertionError("blocking queue.put must not be used")


class TestMassiveLiveFeedBackpressure:
    def test_consume_drops_when_queue_full_without_blocking(
        self,
        normalizer: MassiveNormalizer,
        clock: SimulatedClock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        feed = MassiveLiveFeed("key", ["AAPL"], normalizer, clock)
        full_queue = _AlwaysFullQueue()
        feed._queue = full_queue  # type: ignore[assignment]
        raw = json.dumps(
            {
                "ev": "Q",
                "sym": "AAPL",
                "bp": 150.0,
                "ap": 150.05,
                "bs": 10,
                "as": 20,
                "t": 1000,
                "q": 1,
            }
        ).encode("utf-8")

        caplog.set_level("WARNING", logger="feelies.ingestion.massive_ws")
        asyncio.run(feed._consume(_AsyncMessages([raw])))

        assert full_queue.put_nowait_called
        assert not full_queue.put_called
        assert "queue full, dropping event for AAPL" in caplog.text

    def test_stop_on_full_queue_logs_and_does_not_block(
        self,
        normalizer: MassiveNormalizer,
        clock: SimulatedClock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # When the queue is full at stop() time we attempt put_nowait once,
        # get queue.Full, log a warning, and do NOT fall back to blocking put.
        # events() will exit within 1 s via the _stop_event timeout path.
        feed = MassiveLiveFeed("key", ["AAPL"], normalizer, clock)
        full_queue = _AlwaysFullQueue()
        feed._queue = full_queue  # type: ignore[assignment]

        caplog.set_level("WARNING", logger="feelies.ingestion.massive_ws")
        feed.stop()

        assert full_queue.put_nowait_called
        assert not full_queue.put_called
        assert "queue full, sentinel not enqueued" in caplog.text


class TestHaltStatusDetection:
    """BT-5: normalizer surfaces DataHealth.HALTED from trade condition codes."""

    @staticmethod
    def _halt_normalizer(clock: SimulatedClock) -> MassiveNormalizer:
        return MassiveNormalizer(
            clock=clock,
            halt_on_codes=frozenset({5}),
            halt_off_codes=frozenset({6}),
        )

    @staticmethod
    def _ws_trade(symbol: str, seq: int, conditions: list[int]) -> bytes:
        return json.dumps({
            "ev": "T",
            "sym": symbol,
            "p": 150.0,
            "s": 100,
            "t": 1700000000000 + seq,
            "q": seq,
            "c": conditions,
            "z": 3,
        }).encode("utf-8")

    def test_default_normalizer_ignores_halt_codes(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock,
    ) -> None:
        normalizer.on_message(self._ws_trade("AAPL", 1, [5]), clock.now_ns(), "massive_ws")
        assert normalizer.health("AAPL") == DataHealth.HEALTHY

    def test_halt_on_transitions_to_halted(self, clock: SimulatedClock) -> None:
        norm = self._halt_normalizer(clock)
        norm.on_message(self._ws_trade("AAPL", 1, [5]), clock.now_ns(), "massive_ws")
        assert norm.health("AAPL") == DataHealth.HALTED

    def test_resume_returns_to_healthy(self, clock: SimulatedClock) -> None:
        norm = self._halt_normalizer(clock)
        norm.on_message(self._ws_trade("AAPL", 1, [5]), clock.now_ns(), "massive_ws")
        assert norm.health("AAPL") == DataHealth.HALTED
        norm.on_message(self._ws_trade("AAPL", 2, [6]), clock.now_ns(), "massive_ws")
        assert norm.health("AAPL") == DataHealth.HEALTHY

    def test_ordinary_trade_does_not_clear_halt(self, clock: SimulatedClock) -> None:
        norm = self._halt_normalizer(clock)
        norm.on_message(self._ws_trade("AAPL", 1, [5]), clock.now_ns(), "massive_ws")
        # A trade without the resume code keeps the symbol halted.
        norm.on_message(self._ws_trade("AAPL", 2, [9]), clock.now_ns(), "massive_ws")
        assert norm.health("AAPL") == DataHealth.HALTED


class TestMassiveNormalizerPriceValidation:
    """Decimal hardening (M3): NaN / Infinity / non-positive / InvalidOperation."""

    @staticmethod
    def _ws_quote(bp: object, ap: object = 150.05) -> bytes:
        return json.dumps({
            "ev": "Q", "sym": "AAPL",
            "bp": bp, "ap": ap, "bs": 10, "as": 20,
            "t": 1700000000000, "q": 1,
        }).encode("utf-8")

    def test_nan_bid_is_rejected(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock,
    ) -> None:
        events = normalizer.on_message(self._ws_quote("NaN"), clock.now_ns(), "massive_ws")
        assert events == []
        # CORRUPTED is reached because parse_error gates _mark_corrupted.
        assert normalizer.health("AAPL") == DataHealth.CORRUPTED

    def test_infinity_ask_is_rejected(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock,
    ) -> None:
        events = normalizer.on_message(
            self._ws_quote(150.0, "Infinity"), clock.now_ns(), "massive_ws",
        )
        assert events == []
        assert normalizer.health("AAPL") == DataHealth.CORRUPTED

    def test_negative_price_is_rejected(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock,
    ) -> None:
        events = normalizer.on_message(self._ws_quote(-1.5), clock.now_ns(), "massive_ws")
        assert events == []
        assert normalizer.health("AAPL") == DataHealth.CORRUPTED

    def test_zero_quote_price_is_accepted(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock,
    ) -> None:
        # Auction snapshots and indicator quotes legitimately carry bid=0 /
        # ask=0 on the wire; the normalizer must surface them rather than
        # marking the symbol CORRUPTED.
        events = normalizer.on_message(
            self._ws_quote(0, 0), clock.now_ns(), "massive_ws",
        )
        assert len(events) == 1
        quote = events[0]
        assert isinstance(quote, NBBOQuote)
        assert quote.bid == Decimal("0")
        assert quote.ask == Decimal("0")
        assert normalizer.health("AAPL") == DataHealth.HEALTHY

    def test_zero_trade_price_is_rejected(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock,
    ) -> None:
        # Trade prints at zero remain invalid: equities never trade at zero
        # and downstream cost / sizing math assumes ``price > 0``.
        raw = json.dumps({
            "ev": "T", "sym": "AAPL",
            "p": 0, "s": 10, "x": 11,
            "t": 1700000000000, "q": 1,
        }).encode("utf-8")
        events = normalizer.on_message(raw, clock.now_ns(), "massive_ws")
        assert events == []
        assert normalizer.health("AAPL") == DataHealth.CORRUPTED

    def test_malformed_decimal_does_not_crash_thread(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock,
    ) -> None:
        # "1.2.3" raises decimal.InvalidOperation, which the pre-fix catch
        # tuple (KeyError, ValueError, TypeError) did NOT include.
        events = normalizer.on_message(
            self._ws_quote("1.2.3"), clock.now_ns(), "massive_ws",
        )
        assert events == []
        assert normalizer.health("AAPL") == DataHealth.CORRUPTED


class TestMassiveNormalizerSequenceContiguity:
    """M4: failed event construction must not burn an internal sequence."""

    @staticmethod
    def _ws_quote(symbol: str, bp: object, seq: int = 1) -> bytes:
        return json.dumps({
            "ev": "Q", "sym": symbol,
            "bp": bp, "ap": 150.05, "bs": 10, "as": 20,
            "t": 1700000000000 + seq, "q": seq,
        }).encode("utf-8")

    def test_bad_payload_does_not_advance_internal_sequence(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock,
    ) -> None:
        # First a healthy event so we observe what the next sequence would be.
        events = normalizer.on_message(
            self._ws_quote("AAPL", 150.0, seq=1), clock.now_ns(), "massive_ws",
        )
        assert len(events) == 1
        first_seq = events[0].sequence

        # Bad event between (NaN price) — must NOT consume a sequence number.
        normalizer.on_message(
            self._ws_quote("MSFT", "NaN", seq=1), clock.now_ns(), "massive_ws",
        )

        # Healthy event after the failure: its sequence must be exactly
        # first_seq + 1 (no hole left by the failed event).
        events = normalizer.on_message(
            self._ws_quote("GOOG", 100.0, seq=1), clock.now_ns(), "massive_ws",
        )
        assert len(events) == 1
        assert events[0].sequence == first_seq + 1


class TestMassiveNormalizerCallbackBinding:
    """M5: on_health_transition is idempotent and replaces, not appends."""

    @staticmethod
    def _gap_msgs(symbol: str) -> tuple[bytes, bytes]:
        a = json.dumps({
            "ev": "Q", "sym": symbol,
            "bp": 100.0, "ap": 100.05, "bs": 10, "as": 20,
            "t": 1700000000000, "q": 1,
        }).encode("utf-8")
        b = json.dumps({
            "ev": "Q", "sym": symbol,
            "bp": 100.0, "ap": 100.05, "bs": 10, "as": 20,
            "t": 1700000000005, "q": 5,  # gap from seq=1 → seq=5
        }).encode("utf-8")
        return a, b

    def test_callback_fires_for_symbols_seen_before_registration(
        self, clock: SimulatedClock,
    ) -> None:
        norm = MassiveNormalizer(clock=clock)
        seen: list[str] = []

        # First message creates the SM under the default (no-op) callback.
        a, b = self._gap_msgs("AAPL")
        norm.on_message(a, clock.now_ns(), "massive_ws")

        # Bind the callback AFTER the SM exists.  The dispatcher pattern
        # makes this transparent — the next transition reaches our sink.
        norm.on_health_transition(lambda rec: seen.append(rec.trigger))
        norm.on_message(b, clock.now_ns(), "massive_ws")

        assert any("seq_gap" in s for s in seen)

    def test_rebind_replaces_prior_callback(self, clock: SimulatedClock) -> None:
        a_calls: list[str] = []
        b_calls: list[str] = []
        norm = MassiveNormalizer(
            clock=clock,
            transition_callback=lambda rec: a_calls.append(rec.trigger),
        )

        # SM for AAPL gets created by the first quote.
        a, b = self._gap_msgs("AAPL")
        norm.on_message(a, clock.now_ns(), "massive_ws")

        # Rebind to a new callback.  The old one must NOT fire any more.
        norm.on_health_transition(lambda rec: b_calls.append(rec.trigger))
        norm.on_message(b, clock.now_ns(), "massive_ws")

        assert a_calls == []
        assert any("seq_gap" in s for s in b_calls)

    def test_rebind_is_idempotent(self, clock: SimulatedClock) -> None:
        seen: list[str] = []
        cb = lambda rec: seen.append(rec.trigger)  # noqa: E731

        norm = MassiveNormalizer(clock=clock)
        norm.on_health_transition(cb)
        norm.on_health_transition(cb)  # second call must be a no-op
        norm.on_health_transition(cb)  # and a third for good measure

        a, b = self._gap_msgs("AAPL")
        norm.on_message(a, clock.now_ns(), "massive_ws")
        norm.on_message(b, clock.now_ns(), "massive_ws")

        # Even with three identical binds, the callback fires exactly once
        # per transition.  Pre-fix code would have fired three times because
        # ``sm.on_transition`` appends rather than replacing.
        gap_events = [s for s in seen if "seq_gap" in s]
        assert len(gap_events) == 1


class TestMassiveNormalizerDefensiveHardening:
    """Regression tests for the MINOR defensive hardening pass."""

    @staticmethod
    def _ws_quote(symbol: str = "AAPL", t_ms: int = 1700000000) -> bytes:
        return json.dumps({
            "ev": "Q", "sym": symbol,
            "bp": 150.0, "ap": 150.05, "bs": 10, "as": 20,
            "t": t_ms, "q": 1,
        }).encode("utf-8")

    def test_oversized_frame_is_dropped_with_counter(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock,
    ) -> None:
        # Synthesize a 17 MB payload — over the 16 MB default cap.
        big = b"X" * (17 * 1024 * 1024)
        events = normalizer.on_message(big, clock.now_ns(), "massive_ws")
        assert events == []
        assert normalizer.oversized_frames == 1

    def test_recursion_error_is_caught(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock,
    ) -> None:
        # JSON-decoder doesn't raise RecursionError for moderately nested
        # arrays; we patch json.loads to confirm the catch path is wired.
        from unittest.mock import patch
        with patch(
            "feelies.ingestion.massive_normalizer.json.loads",
            side_effect=RecursionError("pathological nesting"),
        ):
            events = normalizer.on_message(
                self._ws_quote(), clock.now_ns(), "massive_ws",
            )
        assert events == []
        # Health is HEALTHY because the parser caught it without marking
        # any symbol corrupted (we don't know which symbol the bad frame
        # was for).
        assert normalizer.health("AAPL") == DataHealth.HEALTHY

    def test_non_dict_element_increments_counter(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock,
    ) -> None:
        # WS messages are JSON arrays; sometimes a stray string lands.
        raw = json.dumps(["garbage", {"ev": "Q", "sym": "AAPL",
                                       "bp": 150.0, "ap": 150.05,
                                       "bs": 10, "as": 20,
                                       "t": 1700000000, "q": 1}]).encode("utf-8")
        events = normalizer.on_message(raw, clock.now_ns(), "massive_ws")
        assert len(events) == 1
        assert normalizer.unparseable_elements == 1

    def test_health_docstring_is_clear_about_unseen_symbols(
        self, normalizer: MassiveNormalizer,
    ) -> None:
        # Documented behavior: health() returns HEALTHY for never-seen.
        assert normalizer.health("ZZZZ_NEVER_SEEN") == DataHealth.HEALTHY
        # all_health() does NOT include unregistered unseen symbols, so
        # callers can distinguish.
        assert "ZZZZ_NEVER_SEEN" not in normalizer.all_health()

    def test_register_symbols_distinguishes_subscribed_from_observed(
        self, normalizer: MassiveNormalizer,
    ) -> None:
        normalizer.register_symbols({"AAPL", "MSFT"})
        all_h = normalizer.all_health()
        assert set(all_h.keys()) == {"AAPL", "MSFT"}
        assert all(h == DataHealth.HEALTHY for h in all_h.values())


class TestMassiveNormalizerAmbiguousRest:
    """r3-INGEST-03: ambiguous REST records warn (once)."""

    def test_record_with_both_quote_and_trade_fields_warns_once(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        ambiguous = json.dumps({
            "ticker": "AAPL",
            "sip_timestamp": 1700000000000000000,
            "sequence_number": 1,
            "bid_price": 150.0, "ask_price": 150.05,
            "bid_size": 10, "ask_size": 20,
            "price": 150.02, "size": 50,  # also has trade fields
        }).encode("utf-8")

        with caplog.at_level("WARNING", "feelies.ingestion.massive_normalizer"):
            normalizer.on_message(ambiguous, clock.now_ns(), "massive_rest")
            normalizer.on_message(ambiguous, clock.now_ns(), "massive_rest")
            normalizer.on_message(ambiguous, clock.now_ns(), "massive_rest")

        ambiguous_warnings = [
            r for r in caplog.records
            if "ambiguous REST record" in r.getMessage()
        ]
        # Warning suppressed after first occurrence per normalizer.
        assert len(ambiguous_warnings) == 1


class TestMassiveLiveFeedSymbolDedup:
    """r3-INGEST-10: duplicated symbol input is deduped at construction."""

    def test_repeated_symbols_collapse(self, clock: SimulatedClock) -> None:
        norm = MassiveNormalizer(clock=clock)
        feed = MassiveLiveFeed(
            api_key="unused",
            symbols=["AAPL", "AAPL", "MSFT", "AAPL"],
            normalizer=norm,
            clock=clock,
        )
        assert feed._symbols == ["AAPL", "MSFT"]
        # Counter starts at zero.
        assert feed.events_dropped == 0


class TestExchangeTimestampRangeGate:
    """r3-INGEST-02: bound wire timestamps to a plausible window around
    the wall clock — but only when the clock IS a wall clock.
    """

    def test_simulated_clock_skips_the_check(self) -> None:
        # SimulatedClock(start_ns=1e9) is below the wall-clock heuristic
        # threshold (~2e17), so any wire timestamp is accepted.
        clock = SimulatedClock(start_ns=1_000_000_000)
        norm = MassiveNormalizer(clock=clock)
        # ts = 1700000000 ms → 1.7e18 ns (Nov 2023).  Without the gate
        # carve-out this would look like "the future" relative to 1e9.
        raw = json.dumps({
            "ev": "Q", "sym": "AAPL",
            "bp": 100.0, "ap": 100.05, "bs": 10, "as": 20,
            "t": 1700000000, "q": 1,
        }).encode("utf-8")
        events = norm.on_message(raw, clock.now_ns(), "massive_ws")
        assert len(events) == 1

    def test_wall_clock_rejects_far_future_timestamp(self) -> None:
        # Pretend we're on a wall clock at Jan 2026.
        clock = SimulatedClock(start_ns=1_770_000_000_000_000_000)  # ~Feb 2026
        norm = MassiveNormalizer(clock=clock)
        # Event timestamp is 30+ days in the future → rejected.
        far_future_ms = 1_900_000_000_000  # ~mid-2030
        raw = json.dumps({
            "ev": "Q", "sym": "AAPL",
            "bp": 100.0, "ap": 100.05, "bs": 10, "as": 20,
            "t": far_future_ms, "q": 1,
        }).encode("utf-8")
        events = norm.on_message(raw, clock.now_ns(), "massive_ws")
        assert events == []
        # Per the M3/M4 parse-then-mutate ordering, the rejected event
        # still marks the symbol CORRUPTED via the catch path.
        assert norm.health("AAPL") == DataHealth.CORRUPTED


class TestRestQuoteFingerprintSymmetry:
    """A4-MINOR: REST quote fingerprint includes participant_timestamp
    and trf_timestamp, so a retransmission carrying corrected timestamps
    but the same sequence_number is treated as a payload mismatch
    (CORRUPTED) rather than a silent duplicate drop.
    """

    @staticmethod
    def _rest_quote(participant_ts: int | None = None) -> bytes:
        payload: dict[str, Any] = {
            "ticker": "AAPL",
            "sip_timestamp": 1700000000000000000,
            "sequence_number": 42,
            "bid_price": 150.0, "ask_price": 150.05,
            "bid_size": 10, "ask_size": 20,
            "conditions": [], "indicators": [], "tape": 3,
        }
        if participant_ts is not None:
            payload["participant_timestamp"] = participant_ts
        return json.dumps(payload).encode("utf-8")

    def test_same_seq_same_participant_ts_is_dedup(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock,
    ) -> None:
        raw = self._rest_quote(participant_ts=1700000000000000000)
        a = normalizer.on_message(raw, clock.now_ns(), "massive_rest")
        b = normalizer.on_message(raw, clock.now_ns(), "massive_rest")
        assert len(a) == 1
        assert len(b) == 0
        assert normalizer.duplicates_filtered == 1
        assert normalizer.health("AAPL") == DataHealth.HEALTHY

    def test_same_seq_different_participant_ts_is_corruption(
        self, normalizer: MassiveNormalizer, clock: SimulatedClock,
    ) -> None:
        a = normalizer.on_message(
            self._rest_quote(participant_ts=1700000000000000000),
            clock.now_ns(), "massive_rest",
        )
        b = normalizer.on_message(
            self._rest_quote(participant_ts=1700000000000000999),
            clock.now_ns(), "massive_rest",
        )
        assert len(a) == 1
        assert len(b) == 0
        # Fingerprint divergence → CORRUPTED (via _reject_sequence_reuse).
        assert normalizer.health("AAPL") == DataHealth.CORRUPTED
