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
    stressed_fill_latency_ns,
)
from feelies.core.platform_config import PlatformConfig
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import DefaultCostModel, DefaultCostModelConfig, ZeroCostModel
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter


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
        assert stressed.backtest_fill_latency_ns == (cfg.backtest_fill_latency_ns * 2)


def test_stressed_cost_model_raises_variable_fees() -> None:
    baseline = DefaultCostModel(
        DefaultCostModelConfig(stress_multiplier=Decimal("1")),
    )
    stressed = DefaultCostModel(
        DefaultCostModelConfig(stress_multiplier=Decimal("1.5")),
    )
    base_bps = float(
        baseline.compute(
            "AAPL",
            Side.BUY,
            100,
            Decimal("150"),
            Decimal("0.05"),
        ).cost_bps,
    )
    stressed_bps = float(
        stressed.compute(
            "AAPL",
            Side.BUY,
            100,
            Decimal("150"),
            Decimal("0.05"),
        ).cost_bps,
    )
    assert stressed_bps > base_bps


def test_router_deferred_fill_uses_doubled_latency() -> None:
    """Deferred MARKET fills must honour 2× ``backtest_fill_latency_ns``.

    Discriminative construction: the intermediate quote sits at exactly
    the *baseline* deadline (``quote_ts + baseline_latency``).  Under
    baseline latency the router would fill there; under 2× latency the
    deadline is ``quote_ts + 2*baseline`` so the intermediate quote
    stays below the gate and only the final quote (at the stressed
    deadline) clears it.  A regression that stopped doubling latency in
    ``apply_inv12_stress`` / ``stressed_fill_latency_ns`` would fill at
    the intermediate quote and break the empty ``poll_acks()``
    assertion below.
    """
    cfg = PlatformConfig.from_yaml(Path("platform.yaml"))
    baseline_latency_ns = cfg.backtest_fill_latency_ns
    if baseline_latency_ns <= 0:
        pytest.skip("baseline backtest_fill_latency_ns is 0; latency leg inert")

    stressed_cfg = apply_inv12_stress(cfg)
    latency_ns = stressed_cfg.backtest_fill_latency_ns
    assert latency_ns == stressed_fill_latency_ns(baseline_latency_ns)
    assert latency_ns == baseline_latency_ns * INV12_LATENCY_STRESS_MULTIPLIER

    quote_ex_ts = 1_000
    intermediate_ex_ts = quote_ex_ts + baseline_latency_ns
    final_ex_ts = quote_ex_ts + latency_ns

    clock = SimulatedClock(start_ns=0)
    router = BacktestOrderRouter(clock, latency_ns=latency_ns)
    router.on_quote(
        NBBOQuote(
            timestamp_ns=quote_ex_ts,
            correlation_id="q",
            sequence=1,
            symbol="AAPL",
            bid=Decimal("100"),
            ask=Decimal("101"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=quote_ex_ts,
        ),
    )
    router.submit(
        OrderRequest(
            timestamp_ns=quote_ex_ts + 1,
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
            timestamp_ns=intermediate_ex_ts + 100,
            correlation_id="q2",
            sequence=2,
            symbol="AAPL",
            bid=Decimal("100"),
            ask=Decimal("101"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=intermediate_ex_ts,
        ),
    )
    assert router.poll_acks() == []
    router.on_quote(
        NBBOQuote(
            timestamp_ns=final_ex_ts + 100,
            correlation_id="q3",
            sequence=3,
            symbol="AAPL",
            bid=Decimal("100"),
            ask=Decimal("101"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=final_ex_ts,
        ),
    )
    acks = router.poll_acks()
    assert any(a.status == OrderAckStatus.FILLED for a in acks)


def test_passive_router_aggressive_fallback_uses_doubled_latency() -> None:
    """``PassiveLimitOrderRouter``'s MARKET/aggressive path must also honour
    2× ``backtest_fill_latency_ns`` under Inv-12 stress.

    ``platform.yaml`` runs ``execution_mode: passive_limit`` (not
    ``market``), so ``test_router_deferred_fill_uses_doubled_latency`` above
    — which only exercises ``BacktestOrderRouter`` — does not prove the
    latency-doubling contract for the router the reference profile actually
    uses (audit execution_fills_audit_2026-07-02, finding #7 / P1). Same
    discriminative construction: the intermediate quote sits at the
    *baseline* deadline and must not fill; only the final quote, at the
    stressed deadline, clears it.
    """
    cfg = PlatformConfig.from_yaml(Path("platform.yaml"))
    baseline_latency_ns = cfg.backtest_fill_latency_ns
    if baseline_latency_ns <= 0:
        pytest.skip("baseline backtest_fill_latency_ns is 0; latency leg inert")

    latency_ns = stressed_fill_latency_ns(baseline_latency_ns)
    assert latency_ns == baseline_latency_ns * INV12_LATENCY_STRESS_MULTIPLIER

    quote_ex_ts = 1_000
    intermediate_ex_ts = quote_ex_ts + baseline_latency_ns
    final_ex_ts = quote_ex_ts + latency_ns

    clock = SimulatedClock(start_ns=0)
    router = PassiveLimitOrderRouter(clock, latency_ns=latency_ns, cost_model=ZeroCostModel())
    router.on_quote(
        NBBOQuote(
            timestamp_ns=quote_ex_ts,
            correlation_id="q",
            sequence=1,
            symbol="AAPL",
            bid=Decimal("100"),
            ask=Decimal("101"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=quote_ex_ts,
        ),
    )
    router.submit(
        OrderRequest(
            timestamp_ns=quote_ex_ts + 1,
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
            timestamp_ns=intermediate_ex_ts + 100,
            correlation_id="q2",
            sequence=2,
            symbol="AAPL",
            bid=Decimal("100"),
            ask=Decimal("101"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=intermediate_ex_ts,
        ),
    )
    assert router.poll_acks() == []
    router.on_quote(
        NBBOQuote(
            timestamp_ns=final_ex_ts + 100,
            correlation_id="q3",
            sequence=3,
            symbol="AAPL",
            bid=Decimal("100"),
            ask=Decimal("101"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=final_ex_ts,
        ),
    )
    acks = router.poll_acks()
    assert any(a.status == OrderAckStatus.FILLED for a in acks)


def test_passive_router_resting_post_uses_doubled_latency() -> None:
    """A resting passive LIMIT order must not become fill-eligible until 2×
    ``backtest_fill_latency_ns`` has elapsed under Inv-12 stress.

    This is the order-entry latency gate added by the 2026-07-01 P0 fix
    (``passive_limit_router.py:540,589-593``) — distinct from the aggressive-
    fallback path covered above. Discriminative construction: the
    intermediate quote already satisfies the guaranteed "through fill"
    price condition (ask at/below the resting limit) at exactly the
    *baseline* deadline; under correct 2× stress it must still not fill,
    because the order is not yet live at the exchange. Only the final quote,
    at the stressed deadline, clears the gate and fills.
    """
    cfg = PlatformConfig.from_yaml(Path("platform.yaml"))
    baseline_latency_ns = cfg.backtest_fill_latency_ns
    if baseline_latency_ns <= 0:
        pytest.skip("baseline backtest_fill_latency_ns is 0; latency leg inert")

    latency_ns = stressed_fill_latency_ns(baseline_latency_ns)
    assert latency_ns == baseline_latency_ns * INV12_LATENCY_STRESS_MULTIPLIER

    quote_ex_ts = 1_000
    post_eligible_ns = quote_ex_ts + latency_ns  # pending.ack_timestamp_ns
    intermediate_ex_ts = quote_ex_ts + baseline_latency_ns
    final_ex_ts = post_eligible_ns

    clock = SimulatedClock(start_ns=0)
    router = PassiveLimitOrderRouter(clock, latency_ns=latency_ns, cost_model=ZeroCostModel())
    router.on_quote(
        NBBOQuote(
            timestamp_ns=quote_ex_ts,
            correlation_id="q",
            sequence=1,
            symbol="AAPL",
            bid=Decimal("100.00"),
            ask=Decimal("100.10"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=quote_ex_ts,
        ),
    )
    router.submit(
        OrderRequest(
            timestamp_ns=quote_ex_ts + 1,
            correlation_id="o",
            sequence=2,
            order_id="ord1",
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            limit_price=Decimal("100.00"),
        ),
    )
    acks = router.poll_acks()
    assert [a.status for a in acks] == [OrderAckStatus.ACKNOWLEDGED]

    # Intermediate quote: ask has dropped through our limit (a guaranteed
    # "through fill" if the order were live) but sim-time is only at the
    # *baseline* deadline — 2× stress must keep this un-filled.
    router.on_quote(
        NBBOQuote(
            timestamp_ns=intermediate_ex_ts + 100,
            correlation_id="q2",
            sequence=2,
            symbol="AAPL",
            bid=Decimal("98.90"),
            ask=Decimal("99.00"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=intermediate_ex_ts,
        ),
    )
    assert router.poll_acks() == []

    # Final quote at the stressed deadline: same through-fill condition,
    # now honoured.
    router.on_quote(
        NBBOQuote(
            timestamp_ns=final_ex_ts + 100,
            correlation_id="q3",
            sequence=3,
            symbol="AAPL",
            bid=Decimal("98.90"),
            ask=Decimal("99.00"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=final_ex_ts,
        ),
    )
    acks = router.poll_acks()
    assert any(a.status == OrderAckStatus.FILLED for a in acks)
