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


class TestInMemoryFeatureSnapshotStore:
    """Tests for the concrete InMemoryFeatureSnapshotStore implementation."""

    def test_save_and_load_roundtrip(self) -> None:
        import hashlib
        from feelies.storage.memory_feature_snapshot import InMemoryFeatureSnapshotStore

        store = InMemoryFeatureSnapshotStore()
        state = b"feature_state_data"
        checksum = hashlib.sha256(state).hexdigest()
        meta = FeatureSnapshotMeta(
            symbol="AAPL", feature_version="1.0", event_count=100,
            last_sequence=99, last_timestamp_ns=1_000_000,
            checksum=checksum,
        )
        store.save(meta, state)

        result = store.load("AAPL", "1.0")
        assert result is not None
        loaded_meta, loaded_state = result
        assert loaded_meta == meta
        assert loaded_state == state

    def test_load_returns_none_for_missing_symbol(self) -> None:
        from feelies.storage.memory_feature_snapshot import InMemoryFeatureSnapshotStore

        store = InMemoryFeatureSnapshotStore()
        assert store.load("AAPL", "1.0") is None

    def test_load_returns_none_for_version_mismatch(self) -> None:
        import hashlib
        from feelies.storage.memory_feature_snapshot import InMemoryFeatureSnapshotStore

        store = InMemoryFeatureSnapshotStore()
        state = b"data"
        meta = FeatureSnapshotMeta(
            symbol="AAPL", feature_version="1.0", event_count=10,
            last_sequence=9, last_timestamp_ns=500,
            checksum=hashlib.sha256(state).hexdigest(),
        )
        store.save(meta, state)
        assert store.load("AAPL", "2.0") is None

    def test_load_returns_latest_when_multiple_saved(self) -> None:
        import hashlib
        from feelies.storage.memory_feature_snapshot import InMemoryFeatureSnapshotStore

        store = InMemoryFeatureSnapshotStore()

        state_v1 = b"state_v1"
        meta_v1 = FeatureSnapshotMeta(
            symbol="AAPL", feature_version="1.0", event_count=10,
            last_sequence=9, last_timestamp_ns=100,
            checksum=hashlib.sha256(state_v1).hexdigest(),
        )
        store.save(meta_v1, state_v1)

        state_v2 = b"state_v2"
        meta_v2 = FeatureSnapshotMeta(
            symbol="AAPL", feature_version="1.0", event_count=20,
            last_sequence=19, last_timestamp_ns=200,
            checksum=hashlib.sha256(state_v2).hexdigest(),
        )
        store.save(meta_v2, state_v2)

        result = store.load("AAPL", "1.0")
        assert result is not None
        loaded_meta, loaded_state = result
        assert loaded_meta.event_count == 20
        assert loaded_state == state_v2

    def test_checksum_mismatch_on_save_raises(self) -> None:
        from feelies.storage.memory_feature_snapshot import InMemoryFeatureSnapshotStore

        store = InMemoryFeatureSnapshotStore()
        meta = FeatureSnapshotMeta(
            symbol="AAPL", feature_version="1.0", event_count=10,
            last_sequence=9, last_timestamp_ns=100,
            checksum="wrong_checksum_value",
        )
        with pytest.raises(ValueError, match="Checksum mismatch"):
            store.save(meta, b"data")

    def test_checksum_mismatch_on_load_returns_none(self) -> None:
        import hashlib
        from feelies.storage.memory_feature_snapshot import InMemoryFeatureSnapshotStore

        store = InMemoryFeatureSnapshotStore()
        state = b"original_data"
        meta = FeatureSnapshotMeta(
            symbol="AAPL", feature_version="1.0", event_count=10,
            last_sequence=9, last_timestamp_ns=100,
            checksum=hashlib.sha256(state).hexdigest(),
        )
        store.save(meta, state)

        store._snapshots[("AAPL", "1.0")][-1] = (meta, b"corrupted_data")
        assert store.load("AAPL", "1.0") is None

    def test_list_snapshots_multiple_versions(self) -> None:
        import hashlib
        from feelies.storage.memory_feature_snapshot import InMemoryFeatureSnapshotStore

        store = InMemoryFeatureSnapshotStore()
        for version, ts in [("1.0", 100), ("1.1", 200)]:
            state = f"state_{version}".encode()
            meta = FeatureSnapshotMeta(
                symbol="AAPL", feature_version=version, event_count=10,
                last_sequence=9, last_timestamp_ns=ts,
                checksum=hashlib.sha256(state).hexdigest(),
            )
            store.save(meta, state)

        snapshots = store.list_snapshots("AAPL")
        assert len(snapshots) == 2
        assert snapshots[0].last_timestamp_ns >= snapshots[1].last_timestamp_ns

    def test_list_snapshots_empty(self) -> None:
        from feelies.storage.memory_feature_snapshot import InMemoryFeatureSnapshotStore

        store = InMemoryFeatureSnapshotStore()
        assert store.list_snapshots("AAPL") == []


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
