"""Unit tests for FeatureSnapshotMeta and FeatureSnapshotStore."""

from __future__ import annotations

import pytest

from feelies.storage.feature_snapshot import FeatureSnapshotMeta, FeatureSnapshotStore


class TestFeatureSnapshotMeta:
    """Tests for FeatureSnapshotMeta dataclass."""

    def test_creates_with_required_fields(self) -> None:
        meta = FeatureSnapshotMeta(
            symbol="AAPL",
            feature_version="1.0",
            event_count=100,
            last_sequence=50,
            last_timestamp_ns=1_700_000_000_000_000_000,
            checksum="abc123",
        )
        assert meta.symbol == "AAPL"
        assert meta.feature_version == "1.0"
        assert meta.event_count == 100
        assert meta.last_sequence == 50
        assert meta.checksum == "abc123"

    def test_is_frozen(self) -> None:
        meta = FeatureSnapshotMeta(
            symbol="AAPL",
            feature_version="1.0",
            event_count=0,
            last_sequence=0,
            last_timestamp_ns=0,
            checksum="x",
        )
        with pytest.raises(AttributeError):
            meta.symbol = "MSFT"


class TestFeatureSnapshotStoreProtocol:
    """Tests that verify FeatureSnapshotStore protocol contract."""

    def test_in_memory_impl_satisfies_protocol(self) -> None:
        """Minimal in-memory impl for protocol structural check."""
        snapshots: dict[tuple[str, str], tuple[FeatureSnapshotMeta, bytes]] = {}

        class InMemoryFeatureSnapshotStore:
            def save(self, meta: FeatureSnapshotMeta, state: bytes) -> None:
                snapshots[(meta.symbol, meta.feature_version)] = (meta, state)

            def load(
                self, symbol: str, feature_version: str
            ) -> tuple[FeatureSnapshotMeta, bytes] | None:
                return snapshots.get((symbol, feature_version))

            def list_snapshots(self, symbol: str) -> list[FeatureSnapshotMeta]:
                return [m for (s, _), (m, _) in snapshots.items() if s == symbol]

        store: FeatureSnapshotStore = InMemoryFeatureSnapshotStore()

        meta = FeatureSnapshotMeta(
            symbol="AAPL",
            feature_version="1.0",
            event_count=10,
            last_sequence=5,
            last_timestamp_ns=1_000_000_000,
            checksum="deadbeef",
        )
        state = b"feature_state_blob"

        store.save(meta, state)
        result = store.load("AAPL", "1.0")
        assert result is not None
        loaded_meta, loaded_state = result
        assert loaded_meta.symbol == "AAPL"
        assert loaded_state == state

        assert store.load("MSFT", "1.0") is None
        assert len(store.list_snapshots("AAPL")) == 1
