"""Feature engine protocol — stateful computation from event streams.

Features at time T use only events with timestamp <= T (invariant 6).
Feature definitions are versioned (invariant 13).
Incremental by default — O(1) per tick, not O(history).

Uses Protocol (structural subtyping) rather than ABC so that
implementations need not inherit from this module.
"""

from __future__ import annotations

from typing import Protocol

from feelies.core.events import FeatureVector, NBBOQuote


class FeatureEngine(Protocol):
    """Computes features incrementally from market events.

    Implementations maintain per-symbol state.  The engine must be
    deterministic: same event sequence -> same feature values.
    """

    def update(self, quote: NBBOQuote) -> FeatureVector:
        """Process a quote and return the updated feature vector.

        Calling update() advances internal state exactly once per event.
        """
        ...

    def is_warm(self, symbol: str) -> bool:
        """Whether the engine has enough history for reliable features."""
        ...

    def reset(self, symbol: str) -> None:
        """Clear all state for a symbol — re-enters cold-start."""
        ...

    @property
    def version(self) -> str:
        """Feature definition version identifier.

        Snapshots are tied to this version — incompatible snapshots
        are rejected on restore (invariant 13).
        """
        ...

    def checkpoint(self, symbol: str) -> tuple[bytes, int]:
        """Serialize current state for a symbol to an opaque blob.

        Returns (state_bytes, event_count).  The caller pairs this
        with sequence/timestamp metadata for the snapshot store.
        """
        ...

    def restore(self, symbol: str, state: bytes) -> None:
        """Restore state from a previously serialized checkpoint.

        Must validate the blob; corrupt state raises ValueError,
        triggering cold-start fallback.
        """
        ...
