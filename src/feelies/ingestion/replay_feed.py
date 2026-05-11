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


def _market_replay_sort_key(event: NBBOQuote | Trade) -> tuple[int, int, int, str]:
    """Deterministic tie-break when ``exchange_timestamp_ns`` ties (Inv-6).

    ``(timestamp, sequence, kind_rank, symbol)`` with quotes before trades
    at the same ``(timestamp, sequence)`` so merged L1 feeds replay
    identically across runs.
    """

    kind_rank = 0 if isinstance(event, NBBOQuote) else 1
    return (
        event.exchange_timestamp_ns,
        event.sequence,
        kind_rank,
        event.symbol,
    )


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
        ``(exchange_timestamp_ns, sequence, kind, symbol)`` order (see
        :func:`_market_replay_sort_key`).  Raises ``CausalityViolation``
        if the EventLog was not merge-sorted before replay (invariant 6).

        If a ``SimulatedClock`` was provided, sets its time to the
        event's ``exchange_timestamp_ns`` before yielding, so that
        downstream components see deterministic time progression.
        """
        last_key: tuple[int, int, int, str] | None = None
        for event in self._event_log.replay(
            self._start_sequence,
            self._end_sequence,
        ):
            if isinstance(event, (NBBOQuote, Trade)):
                key = _market_replay_sort_key(event)
                if last_key is not None and key < last_key:
                    raise CausalityViolation(
                        "ReplayFeed: market events out of deterministic order "
                        f"at sequence={event.sequence}: key={key!r} < "
                        f"previous {last_key!r}.  Sort the EventLog by "
                        "(exchange_timestamp_ns, sequence, event kind, symbol) "
                        "before replay (invariant 6)"
                    )
                last_key = key
                ts = event.exchange_timestamp_ns
                if isinstance(self._clock, SimulatedClock):
                    if ts > self._clock.now_ns():
                        self._clock.set_time(ts)
                yield event
