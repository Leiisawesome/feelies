"""Unit tests for Inv-12 joint stress harness (BT-9)."""

from __future__ import annotations

from dataclasses import replace

from feelies.alpha.cost_arithmetic import MIN_MARGIN_RATIO
from feelies.core.inv12_stress import (
    INV12_COST_STRESS_MULTIPLIER,
    INV12_LATENCY_STRESS_MULTIPLIER,
    apply_inv12_stress,
    disclosure_margin_after_cost_stress,
    disclosure_survives_inv12_cost_stress,
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
        )
        stressed = apply_inv12_stress(base)
        assert stressed.cost_stress_multiplier == INV12_COST_STRESS_MULTIPLIER
        assert stressed.backtest_fill_latency_ns == 60_000_000
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


class TestDisclosureSurvival:
    def test_margin_after_stress_formula(self) -> None:
        assert disclosure_margin_after_cost_stress(3.0) == 2.0

    def test_survival_at_floor(self) -> None:
        # 2.25 / 1.5 = 1.5 exactly
        from feelies.alpha.cost_arithmetic import CostArithmetic

        cost = CostArithmetic(
            edge_estimate_bps=15.0,
            half_spread_bps=2.0,
            impact_bps=2.0,
            fee_bps=2.0,
            margin_ratio=2.25,
        )
        assert disclosure_survives_inv12_cost_stress(cost)

    def test_survival_below_floor(self) -> None:
        from feelies.alpha.cost_arithmetic import CostArithmetic

        cost = CostArithmetic(
            edge_estimate_bps=8.0,
            half_spread_bps=2.0,
            impact_bps=2.0,
            fee_bps=1.0,
            margin_ratio=1.6,
        )
        assert not disclosure_survives_inv12_cost_stress(cost)
        assert disclosure_margin_after_cost_stress(1.6) < MIN_MARGIN_RATIO
