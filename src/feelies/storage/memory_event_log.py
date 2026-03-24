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

from feelies.core.errors import CausalityViolation
from feelies.core.events import Event


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
    """Volatile, list-backed event store implementing ``EventLog``."""

    __slots__ = ("_events", "_lock", "_last_exchange_ts")

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self._last_exchange_ts: int = 0

    def append(self, event: Event) -> None:
        with self._lock:
            self._enforce_causality(event)
            self._events.append(event)

    def append_batch(self, events: Sequence[Event]) -> None:
        with self._lock:
            prev_ts = self._last_exchange_ts
            for event in events:
                ts: int | None = getattr(event, "exchange_timestamp_ns", None)
                if ts is not None:
                    if ts < prev_ts:
                        raise CausalityViolation(
                            f"append_batch: exchange_timestamp_ns={ts} "
                            f"at sequence={event.sequence} < previous {prev_ts} "
                            f"— events must be sorted by exchange time before "
                            f"insertion (invariant 6)"
                        )
                    prev_ts = ts
            self._last_exchange_ts = prev_ts
            self._events.extend(events)

    def _enforce_causality(self, event: Event) -> None:
        ts: int | None = getattr(event, "exchange_timestamp_ns", None)
        if ts is not None:
            if ts < self._last_exchange_ts:
                raise CausalityViolation(
                    f"append: exchange_timestamp_ns={ts} "
                    f"at sequence={event.sequence} < previous "
                    f"{self._last_exchange_ts} — multi-symbol events must be "
                    f"sorted by exchange time before insertion (invariant 6)"
                )
            self._last_exchange_ts = ts

    def replay(
        self,
        start_sequence: int = 0,
        end_sequence: int | None = None,
    ) -> Iterator[Event]:
        with self._lock:
            start_idx = bisect.bisect_left(
                _SequenceKey(self._events), start_sequence,
            )
            if end_sequence is not None:
                end_idx = bisect.bisect_right(
                    _SequenceKey(self._events), end_sequence,
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
