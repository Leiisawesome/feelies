"""Dedicated tests for DefaultCostModel and ZeroCostModel.

Covers: actual half-spread vs floor, IB Tiered commission with min/max,
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
    """DefaultCostModel with IB Tiered defaults."""

    def test_actual_spread_used_no_floor(self) -> None:
        model = DefaultCostModel()
        # half_spread = $0.05, price = $100, qty = 100
        # actual spread cost = 0.05 * 100 = $5.00
        # floor spread cost  = 0 (min_spread_cost_bps = 0)
        result = model.compute("AAPL", Side.BUY, 100, Decimal("100"), Decimal("0.05"))
        assert result.spread_cost == Decimal("5.00")

    def test_custom_floor_used_when_larger_than_actual(self) -> None:
        config = DefaultCostModelConfig(min_spread_cost_bps=Decimal("0.5"))
        model = DefaultCostModel(config)
        # half_spread = $0.001, price = $200, qty = 100
        # actual spread cost = 0.001 * 100 = $0.10
        # floor spread cost  = 200*100 * 0.5/10000 = $1.00
        result = model.compute("AAPL", Side.BUY, 100, Decimal("200"), Decimal("0.001"))
        assert result.spread_cost == Decimal("1.00")

    def test_commission_per_share(self) -> None:
        model = DefaultCostModel()
        # 1000 shares * ($0.0035 + $0.003 taker fee) = $6.50 (above min $0.35)
        result = model.compute("AAPL", Side.BUY, 1000, Decimal("150"), Decimal("0.01"))
        assert result.commission == Decimal("6.50")

    def test_min_commission_floor(self) -> None:
        model = DefaultCostModel()
        # 10 shares * ($0.0035 + $0.003 taker fee) = $0.065 (below min $0.35)
        result = model.compute("AAPL", Side.BUY, 10, Decimal("150"), Decimal("0.01"))
        assert result.commission == Decimal("0.35")

    def test_max_commission_cap(self) -> None:
        model = DefaultCostModel()
        # 100 shares at $0.01 → notional = $1.00
        # raw commission = 100 * (0.0035 + 0.003) = $0.65, but max cap = 1.0% of $1.00 = $0.01
        result = model.compute("PENNY", Side.BUY, 100, Decimal("0.01"), Decimal("0"))
        assert result.commission == Decimal("0.01")

    def test_total_fees_is_sum(self) -> None:
        model = DefaultCostModel(DefaultCostModelConfig(
            passive_adverse_selection_bps=Decimal("0"),
            sell_regulatory_bps=Decimal("0"),
        ))
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
            taker_exchange_per_share=Decimal("0.002"),
            min_commission=Decimal("2.00"),
            max_commission_pct=Decimal("1.0"),
        )
        model = DefaultCostModel(config)
        result = model.compute("AAPL", Side.BUY, 100, Decimal("100"), Decimal("0.001"))
        # floor spread = 100*100 * 1.0/10000 = $1.00
        assert result.spread_cost == Decimal("1.00")
        # commission = max(100*(0.01+0.002), 2.00) = max(1.20, 2.00) = $2.00
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
        assert result.commission == Decimal("0.35")  # min commission still applies
        assert result.cost_bps == Decimal("0")  # notional is 0

    def test_zero_price(self) -> None:
        model = DefaultCostModel()
        result = model.compute("AAPL", Side.BUY, 100, Decimal("0"), Decimal("0"))
        assert result.spread_cost == Decimal("0.00")
        assert result.cost_bps == Decimal("0")

    def test_locked_market_zero_spread_no_floor(self) -> None:
        model = DefaultCostModel()
        # half_spread = 0, no floor (min_spread_cost_bps=0) → spread_cost = 0
        result = model.compute("AAPL", Side.BUY, 100, Decimal("100"), Decimal("0"))
        assert result.spread_cost == Decimal("0.00")

    def test_locked_market_with_custom_floor(self) -> None:
        config = DefaultCostModelConfig(min_spread_cost_bps=Decimal("0.5"))
        model = DefaultCostModel(config)
        # half_spread = 0, floor = 100*100 * 0.5/10000 = $0.50
        result = model.compute("AAPL", Side.BUY, 100, Decimal("100"), Decimal("0"))
        assert result.spread_cost == Decimal("0.50")


class TestStressCostMultiplier:
    """Inv 12: 1.5x cost stress test produces 1.5x output."""

    def test_1_5x_cost_multiplier(self) -> None:
        base_config = DefaultCostModelConfig()
        stress_config = DefaultCostModelConfig(
            min_spread_cost_bps=base_config.min_spread_cost_bps * Decimal("1.5"),
            commission_per_share=base_config.commission_per_share * Decimal("1.5"),
            taker_exchange_per_share=base_config.taker_exchange_per_share * Decimal("1.5"),
            maker_exchange_per_share=base_config.maker_exchange_per_share,  # rebate not stressed
            min_commission=base_config.min_commission * Decimal("1.5"),
            max_commission_pct=Decimal("100"),  # disable cap for this test
        )
        base_model = DefaultCostModel(
            DefaultCostModelConfig(max_commission_pct=Decimal("100"))
        )
        stress_model = DefaultCostModel(stress_config)

        hs = Decimal("0.005")
        # 10000 shares at $100, half_spread $0.005 (taker path)
        # spread cost = 0.005 * 10000 = $50 (actual > floor since floor=0)
        # base commission = 10000 * (0.0035 + 0.003) = $65.00
        # stress commission = 10000 * (0.00525 + 0.0045) = $97.50 = $65.00 * 1.5
        base = base_model.compute("AAPL", Side.BUY, 10000, Decimal("100"), hs)
        stress = stress_model.compute("AAPL", Side.BUY, 10000, Decimal("100"), hs)

        assert stress.commission == (base.commission * Decimal("1.5")).quantize(Decimal("0.01"))


class TestHTBBorrowFee:
    """2g: hard-to-borrow daily fee for short-side sells."""

    def test_htb_added_for_short_sell(self) -> None:
        """is_short=True + side=SELL + htb_borrow_annual_bps>0 → extra fee."""
        config = DefaultCostModelConfig(htb_borrow_annual_bps=Decimal("252"))
        model = DefaultCostModel(config)

        # notional = 100 * $100 = $10 000
        # daily htb = 10 000 * 252 / 252 / 10 000 = $1.00
        result = model.compute("AAPL", Side.SELL, 100, Decimal("100"), Decimal("0"), is_short=True)
        baseline = model.compute("AAPL", Side.SELL, 100, Decimal("100"), Decimal("0"), is_short=False)
        assert result.total_fees - baseline.total_fees == pytest.approx(Decimal("1.00"), abs=Decimal("0.01"))

    def test_htb_not_applied_to_long_sell(self) -> None:
        """is_short=False → no HTB fee even if config has htb_borrow_annual_bps set."""
        config = DefaultCostModelConfig(htb_borrow_annual_bps=Decimal("252"))
        model = DefaultCostModel(config)
        no_htb_config = DefaultCostModelConfig()
        baseline = DefaultCostModel(no_htb_config)

        result = model.compute("AAPL", Side.SELL, 100, Decimal("100"), Decimal("0"), is_short=False)
        base = baseline.compute("AAPL", Side.SELL, 100, Decimal("100"), Decimal("0"))
        assert result.total_fees == base.total_fees

    def test_htb_zero_when_disabled(self) -> None:
        """Default htb_borrow_annual_bps=0 → no HTB fee even for short sells."""
        model = DefaultCostModel()
        with_htb = model.compute("AAPL", Side.SELL, 100, Decimal("100"), Decimal("0"), is_short=True)
        without_htb = model.compute("AAPL", Side.SELL, 100, Decimal("100"), Decimal("0"), is_short=False)
        assert with_htb.total_fees == without_htb.total_fees

    def test_htb_not_applied_to_buys(self) -> None:
        """BUY orders never receive HTB fee, even if is_short flag is set."""
        config = DefaultCostModelConfig(htb_borrow_annual_bps=Decimal("252"))
        model = DefaultCostModel(config)

        buy_with_flag = model.compute("AAPL", Side.BUY, 100, Decimal("100"), Decimal("0"), is_short=True)
        buy_without = model.compute("AAPL", Side.BUY, 100, Decimal("100"), Decimal("0"))
        assert buy_with_flag.total_fees == buy_without.total_fees
