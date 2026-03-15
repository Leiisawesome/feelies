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
        regime._posteriors["AAPL"] = [0.05, 0.05, 0.90]

        sizer = BudgetBasedSizer(regime_engine=regime)
        qty = sizer.compute_target_quantity(
            _make_signal(strength=1.0),
            budget,
            symbol_price=Decimal("100"),
            account_equity=Decimal("100000"),
        )
        # 10000 * 0.5 / 100 = 50
        assert qty == 50


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
