"""Tests for BudgetBasedSizer — position sizing with regime awareness."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.alpha.module import AlphaRiskBudget
from feelies.core.events import Signal, SignalDirection
from feelies.risk.position_sizer import BudgetBasedSizer
from feelies.services.regime_engine import HMM3StateFractional


def _make_signal(
    symbol: str = "AAPL",
    strength: float = 1.0,
) -> Signal:
    return Signal(
        timestamp_ns=1_000_000_000,
        correlation_id="corr-1",
        sequence=1,
        symbol=symbol,
        strategy_id="test_alpha",
        direction=SignalDirection.LONG,
        strength=strength,
        edge_estimate_bps=2.0,
    )


@pytest.fixture
def budget() -> AlphaRiskBudget:
    return AlphaRiskBudget(
        max_position_per_symbol=500,
        max_gross_exposure_pct=10.0,
        max_drawdown_pct=2.0,
        capital_allocation_pct=10.0,
    )


class TestBudgetAllocation:
    def test_basic_allocation(self, budget: AlphaRiskBudget) -> None:
        """equity=100k, alloc=10%, strength=1.0, price=$100 → 100 shares."""
        sizer = BudgetBasedSizer()
        qty = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        # 100000 * 10% = 10000 / 100 = 100
        assert qty == 100


class TestConvictionScaling:
    def test_half_strength_halves_quantity(self, budget: AlphaRiskBudget) -> None:
        sizer = BudgetBasedSizer()
        full = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        half = sizer.compute_target_quantity(
            _make_signal(strength=0.5),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        assert half == full // 2


class TestRegimeFactor:
    def test_vol_breakout_halves_size(self, budget: AlphaRiskBudget) -> None:
        regime = HMM3StateFractional()
        regime._posteriors["AAPL"] = [0.0, 0.0, 1.0]

        sizer = BudgetBasedSizer(regime_engine=regime)
        qty = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        # EV = 1.0*0.5 = 0.5, so 10000 * 0.5 / 100 = 50
        assert qty == 50

    def test_factor_clamped_at_one_when_config_supplies_amplifier(
        self, budget: AlphaRiskBudget
    ) -> None:
        """Audit P1 R-1: Inv-11 (regime state never amplifies exposure
        beyond 1.0) is enforced at the value level — an operator-
        supplied factor > 1.0 must NOT increase quantity above the
        un-scaled baseline."""
        regime = HMM3StateFractional()
        regime._posteriors["AAPL"] = [0.0, 1.0, 0.0]  # 100% "normal"
        # Misconfigured map: "normal" -> 2.0×.  EV would be 2.0; clamp
        # caps it at 1.0.
        sizer = BudgetBasedSizer(
            regime_engine=regime,
            regime_factors={"normal": 2.0, "vol_breakout": 0.5,
                            "compression_clustering": 0.75},
        )
        qty = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        # Without the clamp this would be 200; with the clamp it's 100.
        # 100000 * 10% (capital_allocation_pct) = 10000; 10000 * 1.0 / 100 = 100.
        assert qty == 100


class TestEdgeCases:
    def test_zero_price_returns_zero(self, budget: AlphaRiskBudget) -> None:
        sizer = BudgetBasedSizer()
        qty = sizer.compute_target_quantity(
            _make_signal(),
            budget,
            symbol_price=Decimal("0"),
            account_equity=Decimal("100000"),
        )
        assert qty == 0

    def test_zero_equity_returns_zero(self, budget: AlphaRiskBudget) -> None:
        sizer = BudgetBasedSizer()
        qty = sizer.compute_target_quantity(
            _make_signal(),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("0"),
        )
        assert qty == 0

    def test_cap_at_max_position(self) -> None:
        small_cap_budget = AlphaRiskBudget(
            max_position_per_symbol=10,
            max_gross_exposure_pct=100.0,
            max_drawdown_pct=50.0,
            capital_allocation_pct=100.0,
        )
        sizer = BudgetBasedSizer()
        qty = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            small_cap_budget,
            symbol_price=Decimal("1"),
            account_equity=Decimal("1000000"),
        )
        assert qty == 10

    def test_no_regime_engine_factor_is_one(self, budget: AlphaRiskBudget) -> None:
        sizer = BudgetBasedSizer(regime_engine=None)
        qty = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        # factor 1.0: 100000 * 10% = 10000 / 100 = 100
        assert qty == 100
