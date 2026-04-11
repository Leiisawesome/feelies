"""In-memory feature snapshot store for backtesting and testing.

Implements the ``FeatureSnapshotStore`` protocol with a dictionary store.
Not durable — snapshots are lost on process exit.
"""

from __future__ import annotations

import hashlib

from feelies.storage.feature_snapshot import FeatureSnapshotMeta

_CHECKSUM_MIN_LEN = 8  # minimum hex chars stored checksum must supply (32-bit coverage)


class InMemoryFeatureSnapshotStore:
    """In-memory FeatureSnapshotStore implementation."""

    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, str], list[tuple[FeatureSnapshotMeta, bytes]]] = {}

    def save(self, meta: FeatureSnapshotMeta, state: bytes) -> None:
        actual_full = hashlib.sha256(state).hexdigest()
        if meta.checksum and not self._checksums_match(meta.checksum, actual_full):
            raise ValueError(
                f"Checksum mismatch on save: expected {meta.checksum}, "
                f"got {actual_full}"
            )
        key = (meta.symbol, meta.feature_version)
        self._snapshots.setdefault(key, []).append((meta, bytes(state)))

    def load(
        self,
        symbol: str,
        feature_version: str,
    ) -> tuple[FeatureSnapshotMeta, bytes] | None:
        key = (symbol, feature_version)
        entries = self._snapshots.get(key)
        if not entries:
            return None
        meta, state = entries[-1]
        actual_full = hashlib.sha256(state).hexdigest()
        if meta.checksum and not self._checksums_match(meta.checksum, actual_full):
            return None
        return meta, state

    @staticmethod
    def _checksums_match(stored: str, computed: str) -> bool:
        """Compare checksums: stored must be at least _CHECKSUM_MIN_LEN hex chars.

        A stored value shorter than _CHECKSUM_MIN_LEN has too few collision-
        resistance bits to be meaningful and indicates a data/config bug.
        """
        if len(stored) < _CHECKSUM_MIN_LEN:
            raise ValueError(
                f"Stored checksum too short ({len(stored)} chars); "
                f"minimum is {_CHECKSUM_MIN_LEN} hex characters"
            )
        return computed.startswith(stored)

    def list_snapshots(self, symbol: str) -> list[FeatureSnapshotMeta]:
        result: list[FeatureSnapshotMeta] = []
        for (sym, _), entries in self._snapshots.items():
            if sym == symbol:
                result.extend(meta for meta, _ in entries)
        result.sort(key=lambda m: m.last_timestamp_ns, reverse=True)
        return result
