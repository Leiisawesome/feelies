"""Live-like execution-realism profile check (audit execution_fills_audit_2026-07-02, P1 #6).

``PlatformConfig`` code defaults leave several passive-fill and impact-realism
knobs off/zero for backward compatibility (``passive_through_fill_size_cap_enabled``,
``passive_require_trade_for_level_fill``, ``cost_within_l1_impact_factor`` /
``cost_permanent_impact_coefficient``); the reference ``platform.yaml`` opts them
all on, but nothing previously asserted that a config claiming to be cost-realistic
actually carries them forward. This is a config lint, not a loader-level gate —
call it explicitly against any config meant to represent a live-like backtest.
"""

from __future__ import annotations

from feelies.core.platform_config import PlatformConfig

_PASSIVE_EXECUTION_MODES = frozenset({"passive_limit", "minimum_cost"})


def live_like_realism_violations(config: PlatformConfig) -> list[str]:
    """Return violation messages for missing live-like passive/impact realism knobs.

    The passive-fill checks only apply when ``execution_mode`` actually posts
    passive limit orders (``passive_limit`` / ``minimum_cost``) — ``market`` mode
    has no passive-fill knobs to check. Returns an empty list when every
    applicable knob is enabled/non-zero.
    """
    violations: list[str] = []

    if config.execution_mode in _PASSIVE_EXECUTION_MODES:
        if not config.passive_through_fill_size_cap_enabled:
            violations.append(
                "passive_through_fill_size_cap_enabled is False — a through-fill "
                "assumes the full remaining order fills at once regardless of the "
                "crossing quote's displayed size."
            )
        if (
            not config.passive_require_trade_for_level_fill
            and config.passive_queue_position_shares <= 0
        ):
            violations.append(
                "passive_require_trade_for_level_fill is False and "
                "passive_queue_position_shares is 0 — a level (drain) fill can fire "
                "on quote-imbalance alone with zero observed trade volume at the level."
            )

    if config.cost_within_l1_impact_factor <= 0 and config.cost_permanent_impact_coefficient <= 0:
        violations.append(
            "cost_within_l1_impact_factor and cost_permanent_impact_coefficient are "
            "both 0 — orders at or below displayed L1 depth pay zero market impact."
        )

    return violations


def assert_live_like_execution_realism(config: PlatformConfig) -> None:
    """Raise ``ValueError`` if ``config`` is missing live-like execution-realism knobs.

    See :func:`live_like_realism_violations` for the individual checks.
    """
    violations = live_like_realism_violations(config)
    if violations:
        raise ValueError(
            "config is not live-like for execution realism:\n- " + "\n- ".join(violations)
        )


__all__ = [
    "assert_live_like_execution_realism",
    "live_like_realism_violations",
]
