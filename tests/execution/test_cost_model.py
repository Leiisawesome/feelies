"""Dedicated tests for DefaultCostModel and ZeroCostModel.

Covers: actual half-spread vs floor, commission with min floor,
edge cases (zero qty/price), and 1.5x stress-test multiplier (Inv 12).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import Side
from feelies.execution.cost_model import (
    CostBreakdown,
    DefaultCostModel,
    DefaultCostModelConfig,
    ZeroCostModel,
)


@pytest.fixture
def default_model() -> DefaultCostModel:
    return DefaultCostModel()


@pytest.fixture
def default_config() -> DefaultCostModelConfig:
    return DefaultCostModelConfig()


class TestDefaultCostModel:
    """DefaultCostModel with actual half-spread and commission."""

    def test_actual_spread_used_when_larger_than_floor(self) -> None:
        model = DefaultCostModel()
        # half_spread = $0.05, price = $100, qty = 100
        # actual spread cost = 0.05 * 100 = $5.00
        # floor spread cost  = 100*100 * 0.5/10000 = $0.50
        # actual wins
        result = model.compute("AAPL", Side.BUY, 100, Decimal("100"), Decimal("0.05"))
        assert result.spread_cost == Decimal("5.00")

    def test_floor_used_when_larger_than_actual(self) -> None:
        model = DefaultCostModel()
        # half_spread = $0.001, price = $200, qty = 100
        # actual spread cost = 0.001 * 100 = $0.10
        # floor spread cost  = 200*100 * 0.5/10000 = $1.00
        # floor wins
        result = model.compute("AAPL", Side.BUY, 100, Decimal("200"), Decimal("0.001"))
        assert result.spread_cost == Decimal("1.00")

    def test_commission_per_share(self) -> None:
        model = DefaultCostModel()
        # 1000 shares * $0.005 = $5.00 (above min $1.00)
        result = model.compute("AAPL", Side.BUY, 1000, Decimal("150"), Decimal("0.01"))
        assert result.commission == Decimal("5.00")

    def test_min_commission_floor(self) -> None:
        model = DefaultCostModel()
        # 10 shares * $0.005 = $0.05 (below min $1.00)
        result = model.compute("AAPL", Side.BUY, 10, Decimal("150"), Decimal("0.01"))
        assert result.commission == Decimal("1.00")

    def test_total_fees_is_sum(self) -> None:
        model = DefaultCostModel()
        result = model.compute("AAPL", Side.BUY, 1000, Decimal("100"), Decimal("0.005"))
        expected_total = result.spread_cost + result.commission
        assert result.total_fees == expected_total

    def test_cost_bps_computation(self) -> None:
        model = DefaultCostModel()
        result = model.compute("AAPL", Side.SELL, 100, Decimal("200"), Decimal("0.01"))
        notional = Decimal("200") * 100
        expected_bps = (result.total_fees / notional * Decimal("10000")).quantize(Decimal("0.01"))
        assert result.cost_bps == expected_bps

    def test_buy_and_sell_same_cost(self) -> None:
        model = DefaultCostModel()
        buy = model.compute("AAPL", Side.BUY, 100, Decimal("150"), Decimal("0.005"))
        sell = model.compute("AAPL", Side.SELL, 100, Decimal("150"), Decimal("0.005"))
        assert buy.total_fees == sell.total_fees

    def test_custom_config(self) -> None:
        config = DefaultCostModelConfig(
            min_spread_cost_bps=Decimal("1.0"),
            commission_per_share=Decimal("0.01"),
            min_commission=Decimal("2.00"),
        )
        model = DefaultCostModel(config)
        result = model.compute("AAPL", Side.BUY, 100, Decimal("100"), Decimal("0.001"))
        # floor spread = 100*100 * 1.0/10000 = $1.00
        assert result.spread_cost == Decimal("1.00")
        # commission = max(100*0.01, 2.00) = max(1.00, 2.00) = $2.00
        assert result.commission == Decimal("2.00")


class TestZeroCostModel:
    """ZeroCostModel always returns zero costs."""

    def test_all_zeros(self) -> None:
        model = ZeroCostModel()
        result = model.compute("AAPL", Side.BUY, 100, Decimal("150"), Decimal("0.01"))
        assert result.spread_cost == Decimal("0")
        assert result.commission == Decimal("0")
        assert result.total_fees == Decimal("0")
        assert result.cost_bps == Decimal("0")

    def test_ignores_half_spread(self) -> None:
        model = ZeroCostModel()
        result = model.compute("AAPL", Side.BUY, 100, Decimal("150"), Decimal("10.00"))
        assert result.total_fees == Decimal("0")


class TestEdgeCases:
    """Edge cases: zero quantity, zero price, locked market."""

    def test_zero_quantity(self) -> None:
        model = DefaultCostModel()
        result = model.compute("AAPL", Side.BUY, 0, Decimal("150"), Decimal("0.01"))
        assert result.spread_cost == Decimal("0.00")
        assert result.commission == Decimal("1.00")  # min commission still applies
        assert result.cost_bps == Decimal("0")  # notional is 0

    def test_zero_price(self) -> None:
        model = DefaultCostModel()
        result = model.compute("AAPL", Side.BUY, 100, Decimal("0"), Decimal("0"))
        assert result.spread_cost == Decimal("0.00")
        assert result.cost_bps == Decimal("0")

    def test_locked_market_zero_spread(self) -> None:
        model = DefaultCostModel()
        # half_spread = 0 (locked market), floor should kick in
        result = model.compute("AAPL", Side.BUY, 100, Decimal("100"), Decimal("0"))
        # floor = 100*100 * 0.5/10000 = $0.50
        assert result.spread_cost == Decimal("0.50")


class TestStressCostMultiplier:
    """Inv 12: 1.5x cost stress test produces 1.5x output."""

    def test_1_5x_cost_multiplier(self) -> None:
        base_config = DefaultCostModelConfig()
        stress_config = DefaultCostModelConfig(
            min_spread_cost_bps=base_config.min_spread_cost_bps * Decimal("1.5"),
            commission_per_share=base_config.commission_per_share * Decimal("1.5"),
            min_commission=base_config.min_commission * Decimal("1.5"),
        )
        base_model = DefaultCostModel(base_config)
        stress_model = DefaultCostModel(stress_config)

        hs = Decimal("0.005")
        # Use a large order so min_commission doesn't dominate, and
        # actual spread is below floor so floor is used
        base = base_model.compute("AAPL", Side.BUY, 10000, Decimal("100"), hs)
        stress = stress_model.compute("AAPL", Side.BUY, 10000, Decimal("100"), hs)

        # floor spread: both use floor since 0.005*10000=$50 < 100*10000*bps/10000
        # base floor = 1e6 * 0.5/10000 = $50, stress floor = 1e6 * 0.75/10000 = $75
        # commission: base = 10000*0.005=$50, stress = 10000*0.0075=$75
        assert stress.spread_cost == (base.spread_cost * Decimal("1.5")).quantize(Decimal("0.01"))
        assert stress.commission == (base.commission * Decimal("1.5")).quantize(Decimal("0.01"))
        assert stress.total_fees == (base.total_fees * Decimal("1.5")).quantize(Decimal("0.01"))
