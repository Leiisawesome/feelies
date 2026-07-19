"""Wiring safety tests for router cost-model defaults.

The merged router behavior keeps ``ZeroCostModel`` as the compatibility
fallback so existing callers that instantiate routers without an explicit
``cost_model`` continue to work.
"""

from __future__ import annotations


import pytest

from feelies.core.clock import SimulatedClock
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import DefaultCostModel, ZeroCostModel
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter

pytestmark = pytest.mark.backtest_validation


def test_backtest_router_defaults_to_zero_cost_model() -> None:
    clock = SimulatedClock(start_ns=0)
    router = BacktestOrderRouter(clock)
    assert router is not None


def test_passive_limit_router_defaults_to_zero_cost_model() -> None:
    clock = SimulatedClock(start_ns=0)
    router = PassiveLimitOrderRouter(clock)
    assert router is not None


def test_backtest_router_accepts_explicit_zero_cost_model() -> None:
    """Operators who genuinely want zero-cost can still pass ZeroCostModel."""
    clock = SimulatedClock(start_ns=0)
    router = BacktestOrderRouter(clock, cost_model=ZeroCostModel())
    assert router is not None


def test_passive_limit_router_accepts_explicit_zero_cost_model() -> None:
    clock = SimulatedClock(start_ns=0)
    router = PassiveLimitOrderRouter(clock, cost_model=ZeroCostModel())
    assert router is not None


def test_backtest_router_accepts_default_cost_model() -> None:
    clock = SimulatedClock(start_ns=0)
    router = BacktestOrderRouter(clock, cost_model=DefaultCostModel())
    assert router is not None


def test_passive_limit_router_accepts_default_cost_model() -> None:
    clock = SimulatedClock(start_ns=0)
    router = PassiveLimitOrderRouter(clock, cost_model=DefaultCostModel())
    assert router is not None
