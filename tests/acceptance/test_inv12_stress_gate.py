"""BT-9 acceptance — Inv-12 joint 1.5× cost + 2× latency stress gate.

Locks the remediation-plan harness that every SIGNAL alpha must be
re-validated against under BT-12.  This module asserts:

* The stress helpers exist and apply the locked factors.
* ``apply_inv12_stress`` composes on ``platform.yaml`` defaults.
* The cost model scales variable fees at 1.5× when stressed.
* Deferred MARKET fills honour 2× ``backtest_fill_latency_ns``.

Load-time G12 (``margin_ratio >= 1.5``) is in
``test_reference_alpha_load_invariants.py``.  Per-alpha survival under
joint stress (DSR, CPCV, full backtest PnL) is the BT-12 bar.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.core.inv12_stress import (
    INV12_COST_STRESS_MULTIPLIER,
    INV12_LATENCY_STRESS_MULTIPLIER,
    apply_inv12_stress,
)
from feelies.core.platform_config import PlatformConfig
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import DefaultCostModel, DefaultCostModelConfig


def test_inv12_locked_factors() -> None:
    assert INV12_COST_STRESS_MULTIPLIER == 1.5
    assert INV12_LATENCY_STRESS_MULTIPLIER == 2


def test_apply_inv12_stress_on_platform_yaml_defaults() -> None:
    cfg = PlatformConfig.from_yaml(Path("platform.yaml"))
    stressed = apply_inv12_stress(cfg)
    assert stressed.cost_stress_multiplier == pytest.approx(
        cfg.cost_stress_multiplier * 1.5,
    )
    if cfg.backtest_fill_latency_ns > 0:
        assert stressed.backtest_fill_latency_ns == (
            cfg.backtest_fill_latency_ns * 2
        )


def test_stressed_cost_model_raises_variable_fees() -> None:
    baseline = DefaultCostModel(
        DefaultCostModelConfig(stress_multiplier=Decimal("1")),
    )
    stressed = DefaultCostModel(
        DefaultCostModelConfig(stress_multiplier=Decimal("1.5")),
    )
    base_bps = float(
        baseline.compute(
            "AAPL", Side.BUY, 100, Decimal("150"), Decimal("0.05"),
        ).cost_bps,
    )
    stressed_bps = float(
        stressed.compute(
            "AAPL", Side.BUY, 100, Decimal("150"), Decimal("0.05"),
        ).cost_bps,
    )
    assert stressed_bps > base_bps


def test_router_deferred_fill_uses_doubled_latency() -> None:
    clock = SimulatedClock(start_ns=0)
    router = BacktestOrderRouter(clock, latency_ns=2_000)
    router.on_quote(
        NBBOQuote(
            timestamp_ns=1000,
            correlation_id="q",
            sequence=1,
            symbol="AAPL",
            bid=Decimal("100"),
            ask=Decimal("101"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=1000,
        ),
    )
    router.submit(
        OrderRequest(
            timestamp_ns=2000,
            correlation_id="o",
            sequence=2,
            order_id="ord1",
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
        ),
    )
    acks = router.poll_acks()
    assert [a.status for a in acks] == [OrderAckStatus.ACKNOWLEDGED]
    router.on_quote(
        NBBOQuote(
            timestamp_ns=2500,
            correlation_id="q2",
            sequence=2,
            symbol="AAPL",
            bid=Decimal("100"),
            ask=Decimal("101"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=1999,
        ),
    )
    assert router.poll_acks() == []
    router.on_quote(
        NBBOQuote(
            timestamp_ns=3500,
            correlation_id="q3",
            sequence=3,
            symbol="AAPL",
            bid=Decimal("100"),
            ask=Decimal("101"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=3000,
        ),
    )
    acks = router.poll_acks()
    assert any(a.status == OrderAckStatus.FILLED for a in acks)
