"""Tests for AlphaBudgetRiskWrapper — per-alpha budget enforcement at order gate."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.alpha.module import AlphaManifest, AlphaRiskBudget
from feelies.alpha.registry import AlphaRegistry
from feelies.alpha.risk_wrapper import AlphaBudgetRiskWrapper
from feelies.core.events import (
    OrderRequest,
    OrderType,
    RiskAction,
    RiskVerdict,
    Side,
    Signal,
    SignalDirection,
)
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig

from tests.alpha.conftest import MockAlpha, _make_spread_feature


def _make_alpha(
    alpha_id: str = "test_alpha",
    max_position: int = 50,
    max_exposure_pct: float = 5.0,
    capital_pct: float = 10.0,
) -> MockAlpha:
    """Create a MockAlpha with custom risk budget."""

    class BudgetAlpha(MockAlpha):
        pass

    budget = AlphaRiskBudget(
        max_position_per_symbol=max_position,
        max_gross_exposure_pct=max_exposure_pct,
        max_drawdown_pct=5.0,
        capital_allocation_pct=capital_pct,
    )
    manifest = AlphaManifest(
        alpha_id=alpha_id,
        version="1.0",
        description="test",
        hypothesis="test",
        falsification_criteria=("test",),
        required_features=frozenset(),
        risk_budget=budget,
    )
    alpha = BudgetAlpha(alpha_id=alpha_id)
    alpha._manifest = manifest
    return alpha


def _make_order(
    symbol: str = "AAPL",
    side: Side = Side.BUY,
    quantity: int = 10,
    strategy_id: str = "test_alpha",
) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=1_000_000_000,
        correlation_id="corr-1",
        sequence=1,
        order_id="ord-1",
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        strategy_id=strategy_id,
    )


def _build_wrapper(
    alpha: MockAlpha,
    strategy_positions: StrategyPositionStore | None = None,
    platform_max_position: int = 1000,
    account_equity: Decimal = Decimal("100000"),
) -> AlphaBudgetRiskWrapper:
    registry = AlphaRegistry()
    registry.register(alpha)
    if strategy_positions is None:
        strategy_positions = StrategyPositionStore()
    platform_config = RiskConfig(
        max_position_per_symbol=platform_max_position,
        account_equity=account_equity,
    )
    inner = BasicRiskEngine(platform_config)
    return AlphaBudgetRiskWrapper(
        inner=inner,
        registry=registry,
        strategy_positions=strategy_positions,
        platform_config=platform_config,
        account_equity=account_equity,
    )


class TestCheckOrderPerAlphaPositionLimit:
    """check_order must enforce per-alpha position limits (Finding 2)."""

    def test_rejects_when_post_fill_exceeds_alpha_limit(self) -> None:
        alpha = _make_alpha(max_position=50)
        positions = StrategyPositionStore()
        positions.update("test_alpha", "AAPL", 45, Decimal("150"))

        wrapper = _build_wrapper(alpha, strategy_positions=positions)
        order = _make_order(quantity=10)
        agg = positions.as_aggregate()

        verdict = wrapper.check_order(order, agg)
        assert verdict.action == RiskAction.REJECT
        assert "per-alpha position limit at order gate" in verdict.reason

    def test_allows_when_within_alpha_limit(self) -> None:
        alpha = _make_alpha(
            max_position=50,
            max_exposure_pct=100.0,
            capital_pct=100.0,
        )
        positions = StrategyPositionStore()
        positions.update("test_alpha", "AAPL", 10, Decimal("150"))

        wrapper = _build_wrapper(alpha, strategy_positions=positions)
        order = _make_order(quantity=5)
        agg = positions.as_aggregate()

        verdict = wrapper.check_order(order, agg)
        assert verdict.action != RiskAction.REJECT

    def test_uses_min_of_alpha_and_platform_limit(self) -> None:
        alpha = _make_alpha(max_position=200)
        positions = StrategyPositionStore()
        positions.update("test_alpha", "AAPL", 95, Decimal("150"))

        wrapper = _build_wrapper(
            alpha, strategy_positions=positions,
            platform_max_position=100,
        )
        order = _make_order(quantity=10)
        agg = positions.as_aggregate()

        verdict = wrapper.check_order(order, agg)
        assert verdict.action == RiskAction.REJECT
        assert "per-alpha position limit at order gate" in verdict.reason


class TestCheckOrderPerAlphaExposureLimit:
    """check_order must enforce per-alpha exposure limits (Finding 2)."""

    def test_rejects_when_alpha_exposure_exceeds_budget(self) -> None:
        alpha = _make_alpha(
            max_exposure_pct=5.0,
            capital_pct=10.0,
        )
        positions = StrategyPositionStore()
        # equity=100k, capital_pct=10% -> alpha_equity=10k
        # max_exposure_pct=5% of 10k -> max_exposure=500
        # Fill 4 shares at $150 -> exposure = 600 > 500
        positions.update("test_alpha", "AAPL", 4, Decimal("150"))

        wrapper = _build_wrapper(alpha, strategy_positions=positions)
        order = _make_order(quantity=1)
        agg = positions.as_aggregate()

        verdict = wrapper.check_order(order, agg)
        assert verdict.action == RiskAction.REJECT
        assert "per-alpha exposure limit at order gate" in verdict.reason


class TestCheckOrderDelegatesToInner:
    """check_order still delegates to inner engine for aggregate checks."""

    def test_unknown_strategy_passes_through(self) -> None:
        alpha = _make_alpha()
        wrapper = _build_wrapper(alpha)
        order = _make_order(strategy_id="unknown_alpha")
        agg = StrategyPositionStore().as_aggregate()

        verdict = wrapper.check_order(order, agg)
        assert verdict.action in (RiskAction.ALLOW, RiskAction.SCALE_DOWN)

    def test_empty_strategy_id_passes_through(self) -> None:
        alpha = _make_alpha()
        wrapper = _build_wrapper(alpha)
        order = _make_order(strategy_id="")
        agg = StrategyPositionStore().as_aggregate()

        verdict = wrapper.check_order(order, agg)
        assert verdict.action in (RiskAction.ALLOW, RiskAction.SCALE_DOWN)
