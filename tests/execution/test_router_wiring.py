"""Wiring safety tests: both routers require an explicit cost_model.

Audit F-H-12 (4th pass): the previous `cost_model = cost_model or ZeroCostModel()`
default in both routers silently zero-charged any caller that forgot to wire a
cost model.  These tests ensure the default is gone — callers must pass
``cost_model=...`` explicitly (a ``ZeroCostModel()`` instance still works when
the caller really wants zero-cost fills, but the silent fallback is removed).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.clock import SimulatedClock
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import DefaultCostModel, ZeroCostModel
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter

pytestmark = pytest.mark.backtest_validation


def test_backtest_router_requires_cost_model() -> None:
    clock = SimulatedClock(start_ns=0)
    with pytest.raises(TypeError):
        BacktestOrderRouter(clock)  # type: ignore[call-arg]


def test_passive_limit_router_requires_cost_model() -> None:
    clock = SimulatedClock(start_ns=0)
    with pytest.raises(TypeError):
        PassiveLimitOrderRouter(clock)  # type: ignore[call-arg]


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
