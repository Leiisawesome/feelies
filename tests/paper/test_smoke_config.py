"""Tests for paper_smoke_v1 alpha load."""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.alpha.loader import AlphaLoader
from feelies.core.platform_config import PlatformConfig


_REPO = Path(__file__).resolve().parents[2]
_ALPHA = _REPO / "alphas" / "_paper_smoke_v1" / "paper_smoke_v1.alpha.yaml"
_CONFIG = _REPO / "configs" / "paper_smoke_rth.yaml"


def test_paper_smoke_alpha_loads() -> None:
    if not _ALPHA.is_file():
        pytest.skip("paper_smoke_v1 alpha not present")
    loader = AlphaLoader(enforce_trend_mechanism=False)
    loaded = loader.load(_ALPHA)
    assert loaded.manifest.alpha_id == "paper_smoke_v1"
    assert loaded.horizon_seconds == 30


def test_paper_smoke_config_parses() -> None:
    if not _CONFIG.is_file():
        pytest.skip("paper_smoke_rth config not present")
    config = PlatformConfig.from_yaml(_CONFIG)
    assert config.mode.name == "PAPER"
    assert "SPY" in config.symbols
    sensor_ids = {s.sensor_id for s in config.sensor_specs}
    assert sensor_ids == {"micro_price", "realized_vol_30s"}
