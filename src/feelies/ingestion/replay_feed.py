"""Replay feed — generic MarketDataSource adapter over EventLog.

Reads from any ``EventLog.replay()`` and yields ``NBBOQuote`` / ``Trade``
events tick-by-tick.  Provider-agnostic — works with any EventLog that was
populated through any ingestor.

When a ``SimulatedClock`` is provided, advances the clock to each event's
``exchange_timestamp_ns`` before yielding, enabling deterministic backtest
replay with latency injection.
"""

from __future__ import annotations

from collections.abc import Iterator

from feelies.core.clock import Clock, SimulatedClock
from feelies.core.errors import CausalityViolation
from feelies.core.events import NBBOQuote, Trade
from feelies.storage.event_log import EventLog


class ReplayFeed:
    """Tick-by-tick market data source backed by a persisted EventLog.

    Implements the ``MarketDataSource`` protocol.  The orchestrator
    consumes this identically to a live feed — same ``events()``
    interface, same ``_process_tick()`` path (invariant 9).
    """

    __slots__ = ("_event_log", "_clock", "_start_sequence", "_end_sequence")

    def __init__(
        self,
        event_log: EventLog,
        clock: Clock | None = None,
        start_sequence: int = 0,
        end_sequence: int | None = None,
    ) -> None:
        self._event_log = event_log
        self._clock = clock
        self._start_sequence = start_sequence
        self._end_sequence = end_sequence

    def events(self) -> Iterator[NBBOQuote | Trade]:
        """Yield market events in exchange-timestamp order from the EventLog.

        Filters for ``NBBOQuote`` and ``Trade`` events only — other
        event types (signals, risk verdicts, state transitions) are
        skipped since they are not market data inputs.

        Validates that ``exchange_timestamp_ns`` is monotonically
        non-decreasing across yielded events.  Raises
        ``CausalityViolation`` if a backward timestamp is detected,
        indicating the EventLog was not properly sorted before replay
        (invariant 6).

        If a ``SimulatedClock`` was provided, sets its time to the
        event's ``exchange_timestamp_ns`` before yielding, so that
        downstream components see deterministic time progression.
        """
        last_exchange_ts: int = 0
        for event in self._event_log.replay(
            self._start_sequence,
            self._end_sequence,
        ):
            if isinstance(event, (NBBOQuote, Trade)):
                ts = event.exchange_timestamp_ns
                if ts < last_exchange_ts:
                    raise CausalityViolation(
                        f"ReplayFeed: exchange_timestamp_ns={ts} "
                        f"at sequence={event.sequence} < previous "
                        f"{last_exchange_ts} — EventLog not sorted by "
                        f"exchange time (invariant 6)"
                    )
                last_exchange_ts = ts
                if isinstance(self._clock, SimulatedClock):
                    if ts > self._clock.now_ns():
                        self._clock.set_time(ts)
                yield event
