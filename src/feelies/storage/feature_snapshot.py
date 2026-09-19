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

from feelies.core.feature_snapshot import FeatureSnapshotMeta as FeatureSnapshotMeta
from feelies.core.feature_snapshot import FeatureSnapshotStore as FeatureSnapshotStore
