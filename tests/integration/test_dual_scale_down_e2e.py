"""Runtime confirmation for real gate sequencing under the gross cap.

This integration test drives the real backtest replay loop over a
single deterministic quote. A bus subscriber mimics the production
HorizonSignalEngine by publishing one standalone ``Signal`` in
response to that quote. The shipped ``BasicRiskEngine`` is configured
so the signal gate sees a near-cap snapshot and emits ``SCALE_DOWN``,
but the order gate's prospective-exposure check still rejects the
concrete order because the candidate leg would breach the hard cap.

What this test guarantees
-------------------------

* The backtest-mode runtime path reaches ``MacroState.READY`` after a
  full ``run_backtest()`` invocation.
* The real ``BasicRiskEngine`` emits ``SCALE_DOWN`` at the signal gate.
* The concrete-order gate then rejects because prospective gross
    exposure, not the pre-order snapshot, is the controlling input.
* The H2 "cap once, not twice" path remains covered separately by the
    stub-driven kernel regression that forces ``SCALE_DOWN`` at both gates.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, OrderRequest, RiskAction, RiskVerdict, Signal, SignalDirection
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import ZeroCostModel
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.storage.memory_event_log import InMemoryEventLog


pytestmark = pytest.mark.backtest_validation


class _NoOpMetricCollector:
    def record(self, _metric: object) -> None:
        pass

    def flush(self) -> None:
        pass


class _ReplayMarketData:
    def __init__(self, events: list[object]) -> None:
        self._events = list(events)

    def events(self):
        return iter(self._events)


class _MinimalConfig:
    version = "test-h2-runtime"
    symbols = frozenset({"AAPL"})

    def validate(self) -> None:
        pass

    def snapshot(self) -> None:
        return None


def _make_quote() -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=1_000_000_000,
        correlation_id="AAPL:1000000000:1",
        sequence=1,
        source_layer="INGESTION",
        symbol="AAPL",
        bid=Decimal("99.95"),
        ask=Decimal("100.05"),
        bid_size=1_000,
        ask_size=1_000,
        exchange_timestamp_ns=1_000_000_000,
    )


def _make_signal(quote: NBBOQuote) -> Signal:
    return Signal(
        timestamp_ns=quote.timestamp_ns,
        correlation_id=quote.correlation_id,
        sequence=quote.sequence,
        source_layer="SIGNAL",
        symbol=quote.symbol,
        strategy_id="runtime_scale_cap_alpha",
        direction=SignalDirection.LONG,
        strength=1.0,
        edge_estimate_bps=10.0,
        layer="SIGNAL",
    )


def test_signal_gate_scale_down_can_still_fail_order_gate_on_prospective_exposure() -> None:
    quote = _make_quote()
    clock = SimulatedClock(start_ns=quote.timestamp_ns)
    bus = EventBus()
    event_log = InMemoryEventLog()
    event_log.append_batch([quote])

    # Equity = 100k, gross cap = 10k, threshold = 80%.
    # Starting exposure = 90 shares × $100 = $9k on a different
    # symbol, so gate 1 scales down by exactly 0.5.  The resulting
    # 50-share AAPL order would still take prospective exposure to
    # $14k, so gate 2 rejects.
    positions = MemoryPositionStore()
    positions.update("MSFT", 90, Decimal("100.00"))

    risk_engine = BasicRiskEngine(RiskConfig(
        max_position_per_symbol=100_000,
        max_gross_exposure_pct=10.0,
        account_equity=Decimal("100000"),
        scale_down_threshold_pct=0.8,
    ))

    router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
    backend = ExecutionBackend(
        market_data=_ReplayMarketData([quote]),
        order_router=router,
        mode="BACKTEST",
    )
    orchestrator = Orchestrator(
        clock=clock,
        bus=bus,
        backend=backend,
        risk_engine=risk_engine,
        position_store=positions,
        event_log=event_log,
        metric_collector=_NoOpMetricCollector(),
    )

    captured_orders: list[OrderRequest] = []
    captured_risk: list[RiskVerdict] = []
    bus.subscribe(OrderRequest, captured_orders.append)  # type: ignore[arg-type]
    bus.subscribe(RiskVerdict, captured_risk.append)  # type: ignore[arg-type]
    bus.subscribe(NBBOQuote, router.on_quote)  # type: ignore[arg-type]

    def emit_signal(q: NBBOQuote) -> None:
        bus.publish(_make_signal(q))

    bus.subscribe(NBBOQuote, emit_signal)  # type: ignore[arg-type]

    orchestrator.boot(_MinimalConfig())
    orchestrator.run_backtest()

    scale_downs = [
        verdict for verdict in captured_risk
        if verdict.action == RiskAction.SCALE_DOWN
    ]
    rejects = [
        verdict for verdict in captured_risk
        if verdict.action == RiskAction.REJECT
    ]

    assert orchestrator.macro_state == MacroState.READY
    assert len(scale_downs) == 1, (
        f"expected one signal-gate SCALE_DOWN, got {captured_risk!r}"
    )
    assert scale_downs[0].scaling_factor == 0.5
    assert scale_downs[0].reason == "approaching exposure limit"
    assert len(rejects) == 1, (
        f"expected one order-gate REJECT, got {captured_risk!r}"
    )
    assert "gross exposure limit" in rejects[0].reason
    assert captured_orders == [], (
        "order-gate rejection should veto submission when the scaled "
        f"candidate still breaches the hard cap; got {captured_orders!r}"
    )
