"""In-memory feature snapshot store for backtesting and testing.

Implements the ``FeatureSnapshotStore`` protocol with a dictionary store.
Not durable — snapshots are lost on process exit.
"""

from __future__ import annotations

import hashlib

from feelies.storage.feature_snapshot import FeatureSnapshotMeta


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
        """Compare checksums allowing either full or prefix form."""
        min_len = min(len(stored), len(computed))
        return stored[:min_len] == computed[:min_len]

    def list_snapshots(self, symbol: str) -> list[FeatureSnapshotMeta]:
        result: list[FeatureSnapshotMeta] = []
        for (sym, _), entries in self._snapshots.items():
            if sym == symbol:
                result.extend(meta for meta, _ in entries)
        result.sort(key=lambda m: m.last_timestamp_ns, reverse=True)
        return result
