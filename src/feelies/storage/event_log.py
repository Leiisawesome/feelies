"""Event log — persistent, append-only record of all events.

Enables deterministic replay (invariant 5) and full provenance (invariant 13).
Every decision is traceable to an event in this log.
"""

from __future__ import annotations

from typing import Iterator, Protocol

from feelies.core.events import Event


class EventLog(Protocol):
    """Append-only event store for replay and audit."""

    def append(self, event: Event) -> None:
        """Persist an event.  Must be durable before returning."""
        ...

    def replay(
        self,
        start_sequence: int = 0,
        end_sequence: int | None = None,
    ) -> Iterator[Event]:
        """Replay events in sequence order for deterministic replay."""
        ...

    def last_sequence(self) -> int:
        """Sequence number of the most recent persisted event."""
        ...
