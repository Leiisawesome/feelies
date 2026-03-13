"""Unit tests for ReplayFeed — generic MarketDataSource adapter over EventLog."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, Trade
from feelies.ingestion.replay_feed import ReplayFeed
from feelies.storage.memory_event_log import InMemoryEventLog


def _make_quote(seq: int, symbol: str = "AAPL", exchange_ts_ns: int = 1_700_000_000_000_000_000) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=exchange_ts_ns,
        correlation_id=f"{symbol}:{exchange_ts_ns}:{seq}",
        sequence=seq,
        symbol=symbol,
        bid=Decimal("150.00"),
        ask=Decimal("150.05"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=exchange_ts_ns,
    )


def _make_trade(seq: int, symbol: str = "AAPL", exchange_ts_ns: int = 1_700_000_000_000_100_000) -> Trade:
    return Trade(
        timestamp_ns=exchange_ts_ns,
        correlation_id=f"{symbol}:{exchange_ts_ns}:{seq}",
        sequence=seq,
        symbol=symbol,
        price=Decimal("150.02"),
        size=100,
        exchange_timestamp_ns=exchange_ts_ns,
    )


class TestReplayFeed:
    """ReplayFeed yields NBBOQuote and Trade events from EventLog."""

    def test_filters_for_market_events_only(self) -> None:
        """Non-market events (e.g. MetricEvent) are skipped."""
        from feelies.core.events import MetricEvent, MetricType

        log = InMemoryEventLog()
        log.append(_make_quote(0))
        log.append(MetricEvent(
            timestamp_ns=0,
            correlation_id="",
            sequence=1,
            layer="test",
            name="foo",
            value=1.0,
            metric_type=MetricType.COUNTER,
        ))
        log.append(_make_trade(2))

        feed = ReplayFeed(log, clock=None)
        events = list(feed.events())
        assert len(events) == 2
        assert isinstance(events[0], NBBOQuote)
        assert isinstance(events[1], Trade)

    def test_replays_in_sequence_order(self) -> None:
        """Events yielded in sequence order."""
        log = InMemoryEventLog()
        log.append(_make_quote(0))
        log.append(_make_trade(1))
        log.append(_make_quote(2))

        feed = ReplayFeed(log, clock=None)
        events = list(feed.events())
        assert [e.sequence for e in events] == [0, 1, 2]

    def test_respects_sequence_range(self) -> None:
        """start_sequence and end_sequence limit replay."""
        log = InMemoryEventLog()
        log.append(_make_quote(0))
        log.append(_make_quote(1))
        log.append(_make_quote(2))
        log.append(_make_quote(3))

        feed = ReplayFeed(log, clock=None, start_sequence=1, end_sequence=2)
        events = list(feed.events())
        assert len(events) == 2
        assert events[0].sequence == 1
        assert events[1].sequence == 2

    def test_advances_simulated_clock_forward_only(self) -> None:
        """SimulatedClock only advances, never backward."""
        log = InMemoryEventLog()
        log.append(_make_quote(0, exchange_ts_ns=100))
        log.append(_make_trade(1, symbol="MSFT", exchange_ts_ns=50))  # earlier ts
        log.append(_make_quote(2, exchange_ts_ns=200))

        clock = SimulatedClock(start_ns=0)
        feed = ReplayFeed(log, clock=clock)
        events = list(feed.events())

        assert len(events) == 3
        # First event: 100
        assert clock.now_ns() == 200  # advanced to 200 at end
        # Clock should not have gone backward for event with ts=50

    def test_empty_log_yields_nothing(self) -> None:
        """Empty EventLog yields no events."""
        log = InMemoryEventLog()
        feed = ReplayFeed(log, clock=None)
        assert list(feed.events()) == []
