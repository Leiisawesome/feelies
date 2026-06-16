"""B4 gate consumes the per-alpha realization calibration factor.

The gate multiplies the disclosed ``edge_estimate_bps`` by a per-alpha
factor in [0, 1] before the edge-vs-cost comparison (close-the-loop: gate on
realized-adjusted edge). Empty factors -> 1.0 -> identical behaviour.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, Side, Signal, SignalDirection
from feelies.execution.cost_model import DefaultCostModel, DefaultCostModelConfig
from tests.kernel.test_orchestrator import _build_orchestrator


def _quote(symbol: str = "AAPL") -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=1_000,
        correlation_id="q",
        sequence=1,
        symbol=symbol,
        bid=Decimal("100.00"),
        ask=Decimal("100.10"),
        bid_size=1_000,
        ask_size=1_000,
        exchange_timestamp_ns=1_000,
    )


def _signal(edge_bps: float, strategy_id: str = "alpha_x") -> Signal:
    return Signal(
        timestamp_ns=1_000,
        correlation_id="s",
        sequence=1,
        symbol="AAPL",
        strategy_id=strategy_id,
        direction=SignalDirection.LONG,
        strength=1.0,
        edge_estimate_bps=edge_bps,
    )


def _gate(orch, signal: Signal) -> bool:
    return orch._signal_passes_edge_cost_gate(
        signal,
        symbol="AAPL",
        entry_side=Side.BUY,
        quantity=100,
        quote=_quote(),
        is_taker_entry=True,
        is_short_entry=False,
        correlation_id="c",
        detail="test",
    )


def test_default_factors_empty_and_no_op() -> None:
    orch = _build_orchestrator(SimulatedClock(start_ns=0))
    assert orch._edge_calibration_factors == {}


def test_haircut_factor_flips_gate_from_pass_to_fail() -> None:
    clock = SimulatedClock(start_ns=0)
    cost_model = DefaultCostModel(DefaultCostModelConfig())
    orch = _build_orchestrator(clock)
    orch._cost_model = cost_model
    orch._signal_min_edge_cost_ratio = 1.0
    orch._signal_edge_cost_basis = "round_trip"

    # Find an edge that passes the gate at factor 1.0.
    sig = _signal(edge_bps=50.0)
    assert _gate(orch, sig) is True, "baseline edge should clear the gate"

    # Same edge, but a 0.1 realization factor shrinks it below cost.
    orch._edge_calibration_factors = {"alpha_x": 0.1}
    assert _gate(orch, sig) is False, "haircut edge must fail the gate"

    # An alpha without a factor is unaffected (defaults to 1.0).
    other = _signal(edge_bps=50.0, strategy_id="alpha_other")
    assert _gate(orch, other) is True


def test_factor_one_is_identical_to_no_factor() -> None:
    clock = SimulatedClock(start_ns=0)
    orch = _build_orchestrator(clock)
    orch._cost_model = DefaultCostModel(DefaultCostModelConfig())
    orch._signal_min_edge_cost_ratio = 1.0

    sig = _signal(edge_bps=50.0)
    baseline = _gate(orch, sig)
    orch._edge_calibration_factors = {"alpha_x": 1.0}
    assert _gate(orch, sig) == baseline
