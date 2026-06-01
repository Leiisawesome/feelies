"""Regression tests for bootstrap execution-backend factory wiring."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.bootstrap import _create_backend
from feelies.core.clock import SimulatedClock
from feelies.core.platform_config import OperatingMode
from feelies.storage.memory_event_log import InMemoryEventLog


@pytest.mark.parametrize("execution_mode", ["passive_limit", "minimum_cost"])
def test_create_backend_passive_paths_forward_market_impact_factor(
    execution_mode: str,
) -> None:
    """``cost_market_impact_factor`` must reach PassiveLimitOrderRouter (not default)."""
    clock = SimulatedClock()
    log = InMemoryEventLog()
    bundle = _create_backend(
        OperatingMode.BACKTEST,
        log,
        clock,
        execution_mode=execution_mode,
        market_impact_factor=0.33,
    )
    router = bundle.backtest_router
    assert router is not None
    assert router._market_impact_factor == Decimal("0.33")
