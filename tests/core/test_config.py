"""Unit tests for configuration."""

from __future__ import annotations

import pytest

from feelies.core.config import ConfigSnapshot


class TestConfigSnapshot:
    """Tests for ConfigSnapshot."""

    def test_creates_with_required_fields(self) -> None:
        snap = ConfigSnapshot(
            version="v1",
            timestamp_ns=1_000_000_000,
            author="test",
            data={"symbols": ["AAPL"]},
            checksum="abc123",
        )
        assert snap.version == "v1"
        assert snap.timestamp_ns == 1_000_000_000
        assert snap.author == "test"
        assert snap.data == {"symbols": ["AAPL"]}
        assert snap.checksum == "abc123"

    def test_is_frozen(self) -> None:
        snap = ConfigSnapshot(
            version="v1",
            timestamp_ns=0,
            author="x",
            data={},
            checksum="",
        )
        with pytest.raises(AttributeError):
            snap.version = "v2"  # type: ignore[misc]
