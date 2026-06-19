"""In-memory event log — implements EventLog protocol for testing and development.

Stores events in a plain ``list[Event]``.  Supports both per-tick
``append()`` and chunk-based ``append_batch()`` for efficient ingestion.
Thread-safe via ``threading.Lock``.

No persistence — all events are lost on process exit.  Use for unit tests,
integration tests, and development workflows where a persistent store is
unnecessary.
"""

from __future__ import annotations

import bisect
import threading
from collections.abc import Iterator, Sequence
from typing import cast

from feelies.core.errors import CausalityViolation
from feelies.core.events import Event, NBBOQuote, Trade
from feelies.storage.event_resequence import event_merge_sort_key


class _SequenceKey:
    """Adapter for bisect on a list of Events keyed by sequence."""

    __slots__ = ("_events",)

    def __init__(self, events: list[Event]) -> None:
        self._events = events

    def __len__(self) -> int:
        return len(self._events)

    def __getitem__(self, idx: int) -> int:
        return self._events[idx].sequence


class InMemoryEventLog:
    """Volatile, list-backed event store implementing ``EventLog``.

    ``enforce_market_order`` (default ``True``) governs whether the
    replay-grade monotonicity guard fires.  Replay / ingest / resequence
    logs keep it on — they are populated from a stream that was already
    merge-sorted, so any backward :func:`event_merge_sort_key` is a
    programming error and must raise (Inv-6).

    Live / paper logs constructed by the orchestrator (M1 ``append`` per
    inbound quote/trade) must set it ``False``: a live feed delivers events
    in *arrival* order, which is not necessarily exchange-timestamp
    monotonic across symbols (or across exchanges for a single symbol).
    Rejecting a benign out-of-order arrival would crash the live pipeline
    to DEGRADED (audit ING-01).  The log stays a faithful arrival-order
    audit record; ``ReplayFeed`` and ``resequence_event_list`` re-impose
    deterministic order at forensic-replay time, so determinism is
    preserved where it is contractual.
    """

    __slots__ = ("_events", "_lock", "_last_market_key", "_enforce_market_order_enabled")

    def __init__(self, *, enforce_market_order: bool = True) -> None:
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self._last_market_key: tuple[int, str, int, int] | None = None
        self._enforce_market_order_enabled = enforce_market_order

    def append(self, event: Event) -> None:
        with self._lock:
            self._enforce_market_order(event)
            self._events.append(event)

    @staticmethod
    def _stabilize_market_slice(events: list[Event]) -> None:
        """Sort ``NBBOQuote`` / ``Trade`` rows in-place at their indices (Inv-6)."""
        idxs = [i for i, e in enumerate(events) if isinstance(e, (NBBOQuote, Trade))]
        if not idxs:
            return
        market = cast(
            list[NBBOQuote | Trade],
            [events[i] for i in idxs],
        )
        market.sort(key=event_merge_sort_key)
        for i, e in zip(idxs, market):
            events[i] = e

    def append_batch(self, events: Sequence[Event]) -> None:
        with self._lock:
            ev = list(events)
            self._stabilize_market_slice(ev)
            for event in ev:
                self._enforce_market_order(event)
            self._events.extend(ev)

    def replace_events(self, events: Sequence[Event]) -> None:
        """Replace the entire log with *events* (ingestion merge-sort path).

        Caller should supply merge-sorted market rows; intra-batch
        ``NBBOQuote``/``Trade`` ordering is stabilized the same way as
        :meth:`append_batch` before the monotonicity check.
        """
        with self._lock:
            ev = list(events)
            self._stabilize_market_slice(ev)
            self._last_market_key = None
            for event in ev:
                self._enforce_market_order(event)
            self._events.clear()
            self._events.extend(ev)

    def _enforce_market_order(self, event: Event) -> None:
        if isinstance(event, (NBBOQuote, Trade)):
            key = event_merge_sort_key(event)
            if (
                self._enforce_market_order_enabled
                and self._last_market_key is not None
                and key < self._last_market_key
            ):
                raise CausalityViolation(
                    "InMemoryEventLog: market event out of merge-sort order "
                    f"at sequence={event.sequence}: key={key!r} < "
                    f"previous {self._last_market_key!r} — use "
                    ":func:`~feelies.storage.event_resequence.resequence_event_list` "
                    "before append (invariant 6)"
                )
            self._last_market_key = key

    def replay(
        self,
        start_sequence: int = 0,
        end_sequence: int | None = None,
    ) -> Iterator[Event]:
        with self._lock:
            start_idx = bisect.bisect_left(
                _SequenceKey(self._events),
                start_sequence,
            )
            if end_sequence is not None:
                end_idx = bisect.bisect_right(
                    _SequenceKey(self._events),
                    end_sequence,
                )
                snapshot = self._events[start_idx:end_idx]
            else:
                snapshot = self._events[start_idx:]

        yield from snapshot

    def last_sequence(self) -> int:
        with self._lock:
            if not self._events:
                return -1
            return self._events[-1].sequence

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)
