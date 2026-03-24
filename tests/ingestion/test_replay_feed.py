"""Unit tests for ReplayFeed — generic MarketDataSource adapter over EventLog."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from decimal import Decimal

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.errors import CausalityViolation
from feelies.core.events import Event, NBBOQuote, Trade
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


class _UnsortedEventLog:
    """EventLog without causality enforcement, for testing ReplayFeed's guard."""

    def __init__(self, events: list[Event]) -> None:
        self._events = events

    def append(self, event: Event) -> None:
        self._events.append(event)

    def append_batch(self, events: Sequence[Event]) -> None:
        self._events.extend(events)

    def replay(
        self, start_sequence: int = 0, end_sequence: int | None = None,
    ) -> Iterator[Event]:
        yield from self._events

    def last_sequence(self) -> int:
        return self._events[-1].sequence if self._events else -1


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
        log.append(_make_quote(0, exchange_ts_ns=100))
        log.append(_make_trade(1, exchange_ts_ns=200))
        log.append(_make_quote(2, exchange_ts_ns=300))

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

    def test_advances_simulated_clock(self) -> None:
        """SimulatedClock advances to each event's exchange_timestamp_ns."""
        log = InMemoryEventLog()
        log.append(_make_quote(0, exchange_ts_ns=100))
        log.append(_make_trade(1, exchange_ts_ns=200))
        log.append(_make_quote(2, exchange_ts_ns=300))

        clock = SimulatedClock(start_ns=0)
        feed = ReplayFeed(log, clock=clock)
        events = list(feed.events())

        assert len(events) == 3
        assert clock.now_ns() == 300

    def test_empty_log_yields_nothing(self) -> None:
        """Empty EventLog yields no events."""
        log = InMemoryEventLog()
        feed = ReplayFeed(log, clock=None)
        assert list(feed.events()) == []


class TestReplayFeedCausalityEnforcement:
    """ReplayFeed raises CausalityViolation on out-of-order timestamps (invariant 6)."""

    def test_raises_on_backward_exchange_timestamp(self) -> None:
        """Defense-in-depth: catches unsorted EventLog implementations."""
        log = _UnsortedEventLog([
            _make_quote(0, exchange_ts_ns=100),
            _make_trade(1, symbol="MSFT", exchange_ts_ns=50),
            _make_quote(2, exchange_ts_ns=200),
        ])
        feed = ReplayFeed(log, clock=None)

        with pytest.raises(CausalityViolation, match="exchange_timestamp_ns=50"):
            list(feed.events())

    def test_accepts_equal_timestamps(self) -> None:
        log = _UnsortedEventLog([
            _make_quote(0, exchange_ts_ns=100),
            _make_trade(1, symbol="MSFT", exchange_ts_ns=100),
        ])
        feed = ReplayFeed(log, clock=None)
        assert len(list(feed.events())) == 2

    def test_inmemory_log_also_rejects_at_insert_time(self) -> None:
        """Primary guard: InMemoryEventLog catches backward timestamps on append."""
        log = InMemoryEventLog()
        log.append(_make_quote(0, exchange_ts_ns=100))

        with pytest.raises(CausalityViolation):
            log.append(_make_trade(1, exchange_ts_ns=50))
