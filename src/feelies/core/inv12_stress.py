"""Inv-12 joint cost + latency stress harness (BT-9).

Invariant 12 requires every edge to survive **1.5× variable cost** and
**2× fill latency** relative to the operator's baseline backtest config.
This module is the single chokepoint for applying that joint stress to
:class:`~feelies.core.platform_config.PlatformConfig` before bootstrap
or ``run_backtest.py`` replay.

The harness is intentionally pure (``dataclasses.replace`` only) so
replay determinism (Inv-5) is preserved: same event log + stressed
parameters → bit-identical outputs.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from feelies.core.platform_config import PlatformConfig

# Locked Inv-12 stress factors (remediation plan BT-9).
INV12_COST_STRESS_MULTIPLIER: float = 1.5
INV12_LATENCY_STRESS_MULTIPLIER: int = 2


def stressed_fill_latency_ns(baseline_latency_ns: int) -> int:
    """Return ``baseline × 2`` when latency modeling is active, else 0."""
    if baseline_latency_ns <= 0:
        return 0
    return int(baseline_latency_ns * INV12_LATENCY_STRESS_MULTIPLIER)


def stressed_cost_multiplier(baseline_multiplier: float) -> float:
    """Scale the platform cost-stress knob by 1.5× (Inv-12 cost leg)."""
    return float(baseline_multiplier) * INV12_COST_STRESS_MULTIPLIER


def apply_inv12_stress(config: PlatformConfig) -> PlatformConfig:
    """Return a copy with joint 1.5× cost-stress and 2× fill +
    market-data latency (BT-17: both latency legs scale together)."""
    return replace(
        config,
        cost_stress_multiplier=stressed_cost_multiplier(
            config.cost_stress_multiplier,
        ),
        backtest_fill_latency_ns=stressed_fill_latency_ns(
            config.backtest_fill_latency_ns,
        ),
        market_data_latency_ns=stressed_fill_latency_ns(
            config.market_data_latency_ns,
        ),
    )
