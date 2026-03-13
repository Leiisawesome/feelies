"""Event log — persistent, append-only record of all events.

Enables deterministic replay (invariant 5) and full provenance (invariant 13).
Every decision is traceable to an event in this log.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Iterator, Protocol

from feelies.core.events import Event


class EventLog(Protocol):
    """Append-only event store for replay and audit.

    Supports both per-tick append (used by the orchestrator during
    pipeline execution) and batch append (used by historical
    ingestors for chunk-aware persistence).
    """

    def append(self, event: Event) -> None:
        """Persist a single event.  Must be durable before returning."""
        ...

    def append_batch(self, events: Sequence[Event]) -> None:
        """Persist a chunk of events atomically.

        Implementations choose the persistence strategy: in-memory
        ``list.extend()``, file-based batch flush, Parquet row-group
        writes, etc.  All events in the batch must be durable before
        returning.
        """
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
