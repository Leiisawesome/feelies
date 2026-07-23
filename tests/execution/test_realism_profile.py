"""Tests for live-like execution-realism profile checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.core.platform_config import PlatformConfig
from feelies.execution.realism_profile import (
    assert_live_like_execution_realism,
    live_like_realism_violations,
)


def _minimal_config(**overrides: object) -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset({"AAPL"}),
        alpha_specs=[Path("dummy.alpha.yaml")],
        **overrides,  # type: ignore[arg-type]
    )


def test_platform_yaml_reference_profile_is_live_like() -> None:
    """The shipped reference profile must never silently regress on these knobs."""
    cfg = PlatformConfig.from_yaml(Path("platform.yaml"))
    assert live_like_realism_violations(cfg) == []
    assert_live_like_execution_realism(cfg)  # must not raise


def test_market_mode_default_flags_only_impact_factor() -> None:
    """Default ``execution_mode="market"`` has no passive knobs to check."""
    cfg = _minimal_config()
    violations = live_like_realism_violations(cfg)
    assert len(violations) == 1
    assert "impact" in violations[0]


def test_passive_mode_code_defaults_flag_all_three_knobs() -> None:
    """Code defaults (all off/zero) fail every check once passive_limit is selected."""
    cfg = _minimal_config(execution_mode="passive_limit")
    violations = live_like_realism_violations(cfg)
    assert len(violations) == 3


def test_queue_position_shares_carve_out_for_level_fill_check() -> None:
    """A non-zero queue-depth threshold satisfies the level-fill check even
    when ``passive_require_trade_for_level_fill`` is off — the queue-depth
    regime already requires observed trade volume to drain."""
    cfg = _minimal_config(
        execution_mode="passive_limit",
        passive_through_fill_size_cap_enabled=True,
        passive_require_trade_for_level_fill=False,
        passive_queue_position_shares=200,
        cost_within_l1_impact_factor=0.3,
    )
    assert live_like_realism_violations(cfg) == []


def test_assert_raises_with_actionable_message() -> None:
    cfg = _minimal_config(execution_mode="passive_limit")
    with pytest.raises(ValueError, match="through_fill_size_cap_enabled"):
        assert_live_like_execution_realism(cfg)


def test_fully_live_like_passive_config_has_no_violations() -> None:
    cfg = _minimal_config(
        execution_mode="passive_limit",
        passive_through_fill_size_cap_enabled=True,
        passive_require_trade_for_level_fill=True,
        cost_within_l1_impact_factor=0.3,
    )
    assert live_like_realism_violations(cfg) == []
    assert_live_like_execution_realism(cfg)
