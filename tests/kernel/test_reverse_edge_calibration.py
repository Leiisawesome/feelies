"""B5 (reversal combined-edge guard) consumes the same per-alpha realization
calibration factor as B4.

Position-mgmt audit (2026-07-02) P2: before this fix, B5 compared the raw
disclosed ``edge_estimate_bps`` while B4 compared a realization-calibrated
edge, so a reversal's entry leg could clear B5 on a disclosed edge the
platform already knows (via calibration) to be unreliable, then immediately
fail the very next B4 check on the same, now-calibrated, number.  Mirrors
``tests/kernel/test_orchestrator_edge_calibration.py`` (the B4 coverage).
``_edge_calibration_factors`` defaults to empty (factor 1.0 for every
alpha), so this is parity-preserving unless an operator explicitly
configures per-alpha calibration.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, RiskAction, RiskVerdict, Side, Signal, SignalDirection
from feelies.execution.cost_model import DefaultCostModel, DefaultCostModelConfig
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.position_store import PositionStore
from tests.kernel.test_orchestrator import _build_orchestrator


class _AllowRiskEngine:
    """ALLOWs everything — isolates the test to the B5 edge gate itself."""

    def check_signal(self, signal: Signal, _positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=signal.timestamp_ns,
            correlation_id=signal.correlation_id,
            sequence=signal.sequence,
            symbol=signal.symbol,
            action=RiskAction.ALLOW,
            reason="allow",
        )

    def check_order(self, order, _positions: PositionStore) -> RiskVerdict:  # type: ignore[no-untyped-def]
        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=RiskAction.ALLOW,
            reason="allow",
        )


def _quote() -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=1_000,
        correlation_id="AAPL:1000:1",
        sequence=1,
        symbol="AAPL",
        bid=Decimal("100.00"),
        ask=Decimal("100.10"),
        bid_size=1_000,
        ask_size=1_000,
        exchange_timestamp_ns=1_000,
    )


def _reverse_signal(edge_bps: float, strategy_id: str = "alpha_x") -> Signal:
    # SHORT 100 open below; a LONG signal triggers REVERSE_SHORT_TO_LONG.
    return Signal(
        timestamp_ns=1_000,
        correlation_id="AAPL:1000:1",
        sequence=1,
        symbol="AAPL",
        strategy_id=strategy_id,
        direction=SignalDirection.LONG,
        strength=1.0,
        edge_estimate_bps=edge_bps,
    )


def _run_reversal(orch, signal: Signal) -> None:  # type: ignore[no-untyped-def]
    from dataclasses import replace

    from feelies.kernel.macro import MacroState

    orch.boot(_MinimalConfig())
    orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
    orch._micro.reset(trigger="session_start:test")
    quote = _quote()

    def emit(q: NBBOQuote) -> None:
        orch._bus.publish(
            replace(signal, timestamp_ns=q.timestamp_ns, correlation_id=q.correlation_id)
        )

    orch._bus.subscribe(NBBOQuote, emit)  # type: ignore[arg-type]
    orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
    orch._process_tick(quote)


class _MinimalConfig:
    version = "test-reverse-edge-calibration"
    symbols = frozenset({"AAPL"})

    def validate(self) -> None:
        pass

    def snapshot(self) -> None:
        return None


def _build(edge_bps: float, *, factor: dict[str, float] | None = None) -> tuple[object, object]:
    clock = SimulatedClock(start_ns=1_000)
    positions = MemoryPositionStore()
    positions.update("AAPL", -100, Decimal("100.00"), timestamp_ns=1)
    orch = _build_orchestrator(
        clock,
        risk_engine=_AllowRiskEngine(),
        position_store=positions,
    )
    orch._cost_model = DefaultCostModel(DefaultCostModelConfig())
    orch._reversal_min_edge_cost_multiplier = 1.5
    orch._min_order_shares = 1
    if factor is not None:
        orch._edge_calibration_factors = factor
    _run_reversal(orch, _reverse_signal(edge_bps))
    return orch, positions


def test_baseline_edge_clears_b5_and_flips_to_long() -> None:
    # Large disclosed edge clears the combined exit+entry round-trip cost
    # at the default 1.5x multiplier -> both legs submit -> net long.
    _orch, positions = _build(edge_bps=100.0)
    assert positions.get("AAPL").quantity > 0, "entry leg should have flipped the book long"


def test_haircut_factor_suppresses_the_entry_leg() -> None:
    # Same disclosed edge, but a 0.1 realization factor shrinks the
    # *B5-evaluated* edge below the combined cost -> flatten-only reversal.
    _orch, positions = _build(edge_bps=100.0, factor={"alpha_x": 0.1})
    assert positions.get("AAPL").quantity == 0, (
        "a haircut edge must suppress the entry leg the same way it "
        "would suppress a standalone B4 entry"
    )


def test_factor_one_is_identical_to_no_factor() -> None:
    baseline_orch, baseline_positions = _build(edge_bps=100.0)
    factor_one_orch, factor_one_positions = _build(edge_bps=100.0, factor={"alpha_x": 1.0})
    assert factor_one_positions.get("AAPL").quantity == baseline_positions.get("AAPL").quantity
