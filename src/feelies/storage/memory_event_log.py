"""In-memory event log — implements EventLog protocol for testing and development.

Stores events in a plain ``list[Event]``.  Supports both per-tick
``append()`` and chunk-based ``append_batch()`` for efficient ingestion.
Thread-safe via ``threading.Lock``.

No persistence — all events are lost on process exit.  Use for unit tests,
integration tests, and development workflows where a persistent store is
unnecessary.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence

from feelies.core.events import Event


class InMemoryEventLog:
    """Volatile, list-backed event store implementing ``EventLog``."""

    __slots__ = ("_events", "_lock")

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._lock = threading.Lock()

    def append(self, event: Event) -> None:
        with self._lock:
            self._events.append(event)

    def append_batch(self, events: Sequence[Event]) -> None:
        with self._lock:
            self._events.extend(events)

    def replay(
        self,
        start_sequence: int = 0,
        end_sequence: int | None = None,
    ) -> Iterator[Event]:
        with self._lock:
            snapshot = list(self._events)

        for event in snapshot:
            if event.sequence < start_sequence:
                continue
            if end_sequence is not None and event.sequence > end_sequence:
                continue
            yield event

    def last_sequence(self) -> int:
        with self._lock:
            if not self._events:
                return -1
            return self._events[-1].sequence

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)
