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
from feelies.storage.event_resequence import event_merge_sort_key


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

        Validates that market events are strictly non-decreasing in
        :func:`~feelies.storage.event_resequence.event_merge_sort_key`
        order.  Raises ``CausalityViolation`` if the EventLog was not
        merge-sorted before replay (invariant 6).

        If a ``SimulatedClock`` was provided, sets its time to the
        event's ``exchange_timestamp_ns`` before yielding, so that
        downstream components see deterministic time progression.
        """
        last_key: tuple[int, str, int, int] | None = None
        for event in self._event_log.replay(
            self._start_sequence,
            self._end_sequence,
        ):
            if isinstance(event, (NBBOQuote, Trade)):
                key = event_merge_sort_key(event)
                if last_key is not None and key < last_key:
                    raise CausalityViolation(
                        "ReplayFeed: market events out of deterministic order "
                        f"at sequence={event.sequence}: key={key!r} < "
                        f"previous {last_key!r}.  Sort the EventLog with "
                        ":func:`~feelies.storage.event_resequence.resequence_event_list` "
                        "or equivalent merge key (invariant 6)"
                    )
                last_key = key
                ts = event.exchange_timestamp_ns
                if isinstance(self._clock, SimulatedClock):
                    if ts > self._clock.now_ns():
                        self._clock.set_time(ts)
                yield event
