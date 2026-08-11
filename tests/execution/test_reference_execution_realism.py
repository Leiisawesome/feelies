"""Pin live-like execution settings in the shipped reference profile."""

from __future__ import annotations

from pathlib import Path

from feelies.core.platform_config import PlatformConfig


def test_platform_yaml_reference_profile_is_live_like() -> None:
    """The shipped profile must keep passive fills and impact conservative."""
    cfg = PlatformConfig.from_yaml(Path("platform.yaml"))
    assert cfg.execution_mode in {"passive_limit", "minimum_cost"}
    assert cfg.passive_through_fill_size_cap_enabled
    assert cfg.passive_require_trade_for_level_fill or cfg.passive_queue_position_shares > 0
    assert cfg.cost_within_l1_impact_factor > 0 or cfg.cost_permanent_impact_coefficient > 0
