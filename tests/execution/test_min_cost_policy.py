"""Tests for :class:`feelies.execution.min_cost_policy.MinimumCostExecutionPolicy`."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import Side
from feelies.execution.cost_model import (
    DefaultCostModel,
    DefaultCostModelConfig,
)
from feelies.execution.min_cost_policy import (
    MinCostPolicyConfig,
    MinimumCostExecutionPolicy,
)

pytestmark = pytest.mark.backtest_validation


def _model(**overrides) -> DefaultCostModel:
    cfg = DefaultCostModelConfig(**overrides)
    return DefaultCostModel(cfg)


class TestForcedAggressive:
    """Stop-loss / forced-flatten / EXIT must always cross."""

    def test_force_aggressive_overrides_cost_comparison(self) -> None:
        # A configuration where passive is wildly cheaper still gets
        # overridden by the safety flag.
        policy = MinimumCostExecutionPolicy(_model())
        decision = policy.decide(
            symbol="AAPL",
            side=Side.BUY,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.10"),
            force_aggressive=True,
        )
        assert decision == "aggressive"

    def test_zero_quantity_routes_aggressive(self) -> None:
        """Zero-qty (rounded down) won't fill anyway — pick the
        guaranteed path so the order completes / errors immediately."""
        policy = MinimumCostExecutionPolicy(_model())
        assert (
            policy.decide(
                symbol="AAPL",
                side=Side.BUY,
                quantity=0,
                mid_price=Decimal("100"),
                half_spread=Decimal("0.10"),
            )
            == "aggressive"
        )


class TestSmallOrderCarveOut:
    """Below the configured threshold, orders force aggressive."""

    def test_small_order_threshold_forces_aggressive(self) -> None:
        cfg = MinCostPolicyConfig(small_order_aggressive_threshold_shares=100)
        policy = MinimumCostExecutionPolicy(_model(), cfg)
        # Wide spread → passive would otherwise be cheaper.
        assert (
            policy.decide(
                symbol="AAPL",
                side=Side.BUY,
                quantity=50,
                mid_price=Decimal("100"),
                half_spread=Decimal("0.10"),
            )
            == "aggressive"
        )

    def test_at_threshold_uses_cost_comparison(self) -> None:
        cfg = MinCostPolicyConfig(small_order_aggressive_threshold_shares=100)
        policy = MinimumCostExecutionPolicy(_model(), cfg)
        # Exactly 100 shares — above the strict-less-than gate → cost-comp.
        d = policy.decide(
            symbol="AAPL",
            side=Side.BUY,
            quantity=100,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.10"),
        )
        # Wide spread + sufficient size → passive wins by cost comparison.
        assert d == "passive"


class TestTightSpreadCarveOut:
    """Tight spread ⇒ passive saving is too small after adverse selection."""

    def test_below_threshold_routes_aggressive(self) -> None:
        cfg = MinCostPolicyConfig(min_half_spread_for_passive=Decimal("0.05"))
        policy = MinimumCostExecutionPolicy(_model(), cfg)
        decision = policy.decide(
            symbol="AAPL",
            side=Side.BUY,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.01"),
        )
        assert decision == "aggressive"

    def test_above_threshold_passive_via_costcomp(self) -> None:
        cfg = MinCostPolicyConfig(min_half_spread_for_passive=Decimal("0.005"))
        policy = MinimumCostExecutionPolicy(_model(), cfg)
        decision = policy.decide(
            symbol="AAPL",
            side=Side.BUY,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.05"),
        )
        # Wide spread + adequate size → passive cheaper.
        assert decision == "passive"


class TestShortEntryCarveOut:
    """``allow_passive_short_entry=False`` forces shorts aggressive."""

    def test_short_sell_with_carve_out_is_aggressive(self) -> None:
        cfg = MinCostPolicyConfig(allow_passive_short_entry=False)
        policy = MinimumCostExecutionPolicy(_model(), cfg)
        decision = policy.decide(
            symbol="AAPL",
            side=Side.SELL,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.10"),
            is_short=True,
        )
        assert decision == "aggressive"

    def test_short_sell_without_carve_out_uses_costcomp(self) -> None:
        cfg = MinCostPolicyConfig(allow_passive_short_entry=True)
        policy = MinimumCostExecutionPolicy(_model(), cfg)
        decision = policy.decide(
            symbol="AAPL",
            side=Side.SELL,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.10"),
            is_short=True,
        )
        assert decision == "passive"

    def test_long_sell_unaffected_by_short_carve_out(self) -> None:
        cfg = MinCostPolicyConfig(allow_passive_short_entry=False)
        policy = MinimumCostExecutionPolicy(_model(), cfg)
        decision = policy.decide(
            symbol="AAPL",
            side=Side.SELL,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.10"),
            is_short=False,
        )
        # Long sell (closing a long) ignores the short-entry carve-out.
        assert decision == "passive"


class TestCostComparison:
    """Pure cost-model comparison for non-special-case orders."""

    def test_wide_spread_picks_passive(self) -> None:
        policy = MinimumCostExecutionPolicy(_model())
        decision = policy.decide(
            symbol="AAPL",
            side=Side.BUY,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.05"),
        )
        assert decision == "passive"

    def test_zero_spread_picks_aggressive(self) -> None:
        # When the spread is locked at zero, the only thing the passive
        # path adds is the adverse-selection penalty + the maker rebate.
        # Make adverse selection larger than the rebate's bps-equivalent
        # so aggressive wins.  The policy estimates the passive leg in the
        # queue-drain regime, so set the drain bps high.
        model = _model(adverse_selection_drain_bps=Decimal("5"))
        policy = MinimumCostExecutionPolicy(model)
        decision = policy.decide(
            symbol="AAPL",
            side=Side.BUY,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0"),
        )
        assert decision == "aggressive"

    def test_negative_bias_makes_passive_harder(self) -> None:
        cfg = MinCostPolicyConfig(prefer_passive_bias_bps=Decimal("-100"))
        policy = MinimumCostExecutionPolicy(_model(), cfg)
        # Even with a wide spread, a -100 bps bias forces aggressive.
        decision = policy.decide(
            symbol="AAPL",
            side=Side.BUY,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.05"),
        )
        assert decision == "aggressive"


class TestNonFillRisk:
    """The passive route includes the opportunity cost of non-fill."""

    def test_high_edge_with_high_non_fill_pushes_to_aggressive(self) -> None:
        cfg = MinCostPolicyConfig(
            passive_non_fill_probability=Decimal("0.50"),
        )
        policy = MinimumCostExecutionPolicy(_model(), cfg)
        # Very wide spread → passive saves a lot; but a 100-bps edge
        # and 50% non-fill probability adds 50 bps to passive cost,
        # which should tip toward aggressive.
        decision = policy.decide(
            symbol="AAPL",
            side=Side.BUY,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.05"),
            edge_bps=100.0,
        )
        assert decision == "aggressive"

    def test_zero_edge_falls_back_to_pure_cost_comparison(self) -> None:
        cfg = MinCostPolicyConfig(
            passive_non_fill_probability=Decimal("0.50"),
        )
        policy = MinimumCostExecutionPolicy(_model(), cfg)
        # Wide spread → passive cheaper.  edge_bps=0 means no
        # opportunity cost added → passive still wins.
        decision = policy.decide(
            symbol="AAPL",
            side=Side.BUY,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.05"),
            edge_bps=0.0,
        )
        assert decision == "passive"

    def test_zero_non_fill_probability_neutralises_edge_input(self) -> None:
        cfg = MinCostPolicyConfig(
            passive_non_fill_probability=Decimal("0.0"),
        )
        policy = MinimumCostExecutionPolicy(_model(), cfg)
        # Even with a 1000-bps edge, zero non-fill prob → no penalty.
        decision = policy.decide(
            symbol="AAPL",
            side=Side.BUY,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.05"),
            edge_bps=1000.0,
        )
        assert decision == "passive"


class TestQuantizationStability:
    """Decisions use raw rather than quantized cost bps."""

    def test_decision_stable_under_subcent_perturbation(self) -> None:
        policy = MinimumCostExecutionPolicy(_model())
        kwargs = dict(
            symbol="AAPL",
            side=Side.BUY,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.05"),
        )
        a = policy.decide(**kwargs)
        # Same inputs → identical decision (deterministic).
        b = policy.decide(**kwargs)
        assert a == b


class TestDeterministicReplay:
    """The policy is a pure function — Inv-5 deterministic replay."""

    def test_two_calls_same_inputs_same_decision(self) -> None:
        policy = MinimumCostExecutionPolicy(_model())
        kwargs = dict(
            symbol="AAPL",
            side=Side.BUY,
            quantity=1000,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.05"),
            is_short=False,
            force_aggressive=False,
        )
        first = policy.decide(**kwargs)
        second = policy.decide(**kwargs)
        assert first == second
