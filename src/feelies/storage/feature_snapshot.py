"""Feature snapshot protocol — checkpoint and restore feature engine state.

Enables warm-start without replaying full event history, and supports
deterministic replay by restoring feature state to a known checkpoint
(invariant 5).

Feature engine state is opaque to the storage layer — the engine
serializes its own state into bytes, and the snapshot store persists
those bytes with integrity metadata.  This preserves layer separation
(invariant 8): the storage layer never inspects feature internals.

Tradeoff: opaque blob storage sacrifices queryability for layer
independence.  Feature state is only meaningful to the feature engine
that produced it, so the storage layer should not interpret it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, kw_only=True)
class FeatureSnapshotMeta:
    """Metadata for a feature engine state checkpoint.

    Tied to a specific feature version so that snapshots from
    incompatible feature definitions are never silently loaded
    (invariant 13: every feature traceable to a version).
    """

    symbol: str
    feature_version: str
    event_count: int
    last_sequence: int
    last_timestamp_ns: int
    checksum: str


class FeatureSnapshotStore(Protocol):
    """Persists and restores feature engine state checkpoints.

    Failure mode: degrade.  If snapshot save fails, the system
    continues without the checkpoint (next warm-start replays
    from an earlier point).  If snapshot load fails, the feature
    engine cold-starts.
    """

    def save(self, meta: FeatureSnapshotMeta, state: bytes) -> None:
        """Persist a feature engine snapshot.

        Must be durable before returning.  Implementations must
        verify checksum on write.
        """
        ...

    def load(
        self,
        symbol: str,
        feature_version: str,
    ) -> tuple[FeatureSnapshotMeta, bytes] | None:
        """Restore the most recent snapshot for a symbol and version.

        Returns ``None`` if no snapshot exists.  Implementations must
        verify checksum on read — corrupt snapshots are equivalent
        to missing snapshots (cold-start), never silently loaded.
        """
        ...

    def list_snapshots(self, symbol: str) -> list[FeatureSnapshotMeta]:
        """Available snapshots for a symbol, most recent first."""
        ...
