"""Tests for offline disk-cache replay loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache


def test_load_cache_replay_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(CacheReplayError, match="Disk cache miss"):
        load_event_log_from_disk_cache(
            ["ZZNONEXIST"],
            "2099-01-01",
            "2099-01-01",
            cache_dir=tmp_path,
        )
