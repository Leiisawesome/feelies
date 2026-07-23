"""Unit tests for the invariant-12 joint stress harness."""

from __future__ import annotations

from dataclasses import replace

from feelies.core.inv12_stress import (
    INV12_COST_STRESS_MULTIPLIER,
    apply_inv12_stress,
    stressed_cost_multiplier,
    stressed_fill_latency_ns,
)
from feelies.core.platform_config import PlatformConfig


class TestInv12StressTransforms:
    def test_stressed_latency_doubles_positive_baseline(self) -> None:
        assert stressed_fill_latency_ns(50_000_000) == 100_000_000

    def test_stressed_latency_zero_stays_zero(self) -> None:
        assert stressed_fill_latency_ns(0) == 0

    def test_stressed_cost_scales_baseline(self) -> None:
        assert stressed_cost_multiplier(1.0) == INV12_COST_STRESS_MULTIPLIER
        assert stressed_cost_multiplier(2.0) == 3.0

    def test_apply_inv12_stress_joint(self) -> None:
        base = PlatformConfig(
            cost_stress_multiplier=1.0,
            backtest_fill_latency_ns=30_000_000,
            market_data_latency_ns=10_000_000,
        )
        stressed = apply_inv12_stress(base)
        assert stressed.cost_stress_multiplier == INV12_COST_STRESS_MULTIPLIER
        assert stressed.backtest_fill_latency_ns == 60_000_000
        assert stressed.market_data_latency_ns == 20_000_000
        assert stressed is not base

    def test_apply_inv12_stress_preserves_other_fields(self) -> None:
        base = replace(
            PlatformConfig(),
            symbols=frozenset({"AAPL"}),
            signal_min_edge_cost_ratio=1.5,
        )
        stressed = apply_inv12_stress(base)
        assert stressed.symbols == frozenset({"AAPL"})
        assert stressed.signal_min_edge_cost_ratio == 1.5
