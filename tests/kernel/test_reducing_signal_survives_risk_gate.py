"""Ensure risk verdicts cannot strand exposure-reducing orders.

Reducing signals must still submit when shared exposure checks return
``REJECT`` or ``FORCE_FLATTEN``. Backtest mode isolates this contract because
it has no risk-lockdown transition to perform the reduction indirectly.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderRequest,
    RiskAction,
    RiskVerdict,
    Side,
    Signal,
    SignalDirection,
)
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import ZeroCostModel
from feelies.execution.moc_session import et_clock_to_ns
from feelies.execution.trading_session import TradingSessionBounds
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.position_store import PositionStore
from feelies.storage.memory_event_log import InMemoryEventLog

# Neither verdict may block a reduction in backtest mode.
_BLOCKING_ACTIONS = (RiskAction.REJECT, RiskAction.FORCE_FLATTEN)


class _NoOpMetricCollector:
    def record(self, _metric: Any) -> None:
        pass

    def flush(self) -> None:
        pass


class _StubMarketData:
    def events(self) -> Any:
        return iter([])


class _MinimalConfig:
    version = "test-reducing-signal-risk-gate"
    symbols = frozenset({"AAPL"})

    def validate(self) -> None:
        pass

    def snapshot(self) -> None:
        return None


class _FixedActionRiskEngine:
    """Returns a fixed action from both check methods (never ALLOW)."""

    def __init__(self, action: RiskAction) -> None:
        self._action = action

    def check_signal(self, signal: Signal, _positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=signal.timestamp_ns,
            correlation_id=signal.correlation_id,
            sequence=signal.sequence,
            symbol=signal.symbol,
            action=self._action,
            reason="reducing-signal-risk-gate-test",
        )

    def check_order(self, order: OrderRequest, _positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=self._action,
            reason="reducing-signal-risk-gate-test",
        )


class _FirstCheckOrderActionEngine:
    """ALLOWs check_signal; returns ``action`` on the *first* check_order
    call only (the reversal's exit leg), then ALLOWs the rest (the entry
    leg)."""

    def __init__(self, action: RiskAction) -> None:
        self._action = action
        self._check_order_calls = 0

    def check_signal(self, signal: Signal, _positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=signal.timestamp_ns,
            correlation_id=signal.correlation_id,
            sequence=signal.sequence,
            symbol=signal.symbol,
            action=RiskAction.ALLOW,
            reason="reducing-signal-risk-gate-test:signal",
        )

    def check_order(self, order: OrderRequest, _positions: PositionStore) -> RiskVerdict:
        self._check_order_calls += 1
        action = self._action if self._check_order_calls == 1 else RiskAction.ALLOW
        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=action,
            reason="reducing-signal-risk-gate-test:order",
        )


def _make_quote(
    *,
    ts: int = 1000,
    bid: str = "149.50",
    ask: str = "150.50",
    seq: int = 1,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"AAPL:{ts}:{seq}",
        sequence=seq,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=200,
        exchange_timestamp_ns=ts - 100,
    )


def _make_signal(
    quote: NBBOQuote,
    *,
    strategy_id: str = "test_signal_alpha",
    direction: SignalDirection = SignalDirection.LONG,
) -> Signal:
    return Signal(
        timestamp_ns=quote.timestamp_ns,
        correlation_id=quote.correlation_id,
        sequence=quote.sequence,
        symbol=quote.symbol,
        strategy_id=strategy_id,
        direction=direction,
        strength=0.8,
        edge_estimate_bps=5.0,
        layer="SIGNAL",
    )


def _build_orchestrator(
    clock: SimulatedClock,
    *,
    bus: EventBus,
    risk_engine: Any,
    position_store: MemoryPositionStore,
) -> Orchestrator:
    bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
    backend = ExecutionBackend(
        market_data=_StubMarketData(),
        order_router=bt_router,
        mode="BACKTEST",
    )
    return Orchestrator(
        clock=clock,
        bus=bus,
        backend=backend,
        risk_engine=risk_engine,
        position_store=position_store,
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
    )


def _boot_to_backtest(orch: Orchestrator) -> None:
    orch.boot(_MinimalConfig())
    assert orch.macro_state == MacroState.READY
    orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
    orch._micro.reset(trigger="session_start:test")


def _signal_from_bus(bus: EventBus, signal: Signal) -> None:
    """Republish ``signal`` (retimed) on every quote, mimicking
    ``HorizonSignalEngine``'s bus contract without the full snapshot
    pipeline."""

    def emit(quote: NBBOQuote) -> None:
        bus.publish(
            replace(
                signal,
                timestamp_ns=quote.timestamp_ns,
                correlation_id=quote.correlation_id,
                sequence=quote.sequence,
            )
        )

    bus.subscribe(NBBOQuote, emit)  # type: ignore[arg-type]


def _capture_orders(bus: EventBus) -> list[OrderRequest]:
    captured: list[OrderRequest] = []
    bus.subscribe(OrderRequest, captured.append)  # type: ignore[arg-type]
    return captured


@pytest.mark.parametrize("action", _BLOCKING_ACTIONS)
class TestStopLossSurvivesRiskGate:
    def test_stop_loss_flattens_despite_blocking_verdict(self, action: RiskAction) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"), timestamp_ns=1)
        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=_FixedActionRiskEngine(action),
            position_store=positions,
        )
        orch._stop_loss_per_share = 1.0
        captured = _capture_orders(bus)
        _boot_to_backtest(orch)

        # Price drops 5/share against the long — well past the $1 stop.
        quote = _make_quote(bid="144.50", ask="145.50")
        orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
        orch._process_tick(quote)

        assert positions.get("AAPL").quantity == 0, (
            f"stop-loss did not flatten the position under a {action.name} "
            "verdict from the shared exposure/drawdown gate"
        )
        assert any(o.side == Side.SELL and o.quantity == 100 for o in captured)


@pytest.mark.parametrize("action", _BLOCKING_ACTIONS)
class TestSessionFlattenSurvivesRiskGate:
    def test_session_flatten_closes_despite_blocking_verdict(self, action: RiskAction) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 50, Decimal("100.00"), timestamp_ns=1)
        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=_FixedActionRiskEngine(action),
            position_store=positions,
        )
        captured = _capture_orders(bus)
        _boot_to_backtest(orch)
        anchor = date(2026, 3, 26)
        orch._trading_session_bounds = TradingSessionBounds(
            session_date=anchor,
            rth_open_ns=et_clock_to_ns(anchor, "09:30"),
            rth_close_ns=et_clock_to_ns(anchor, "16:00"),
        )
        orch._session_flatten_enabled = True
        orch._session_flatten_seconds_before_close = 0

        # Past the 16:00 close.
        ns = et_clock_to_ns(anchor, "16:01")
        quote = _make_quote(ts=ns + 100, bid="99.99", ask="100.01")
        orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
        orch._process_tick(quote)

        assert positions.get("AAPL").quantity == 0, (
            f"session flatten did not close the position under a {action.name} "
            "verdict from the shared exposure/drawdown gate"
        )
        assert any(o.side == Side.SELL and o.quantity == 50 for o in captured)


@pytest.mark.parametrize("action", _BLOCKING_ACTIONS)
class TestAlphaFlatExitSurvivesRiskGate:
    def test_alpha_flat_exit_closes_despite_blocking_verdict(self, action: RiskAction) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 75, Decimal("150.00"), timestamp_ns=1)
        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=_FixedActionRiskEngine(action),
            position_store=positions,
        )
        captured = _capture_orders(bus)
        quote = _make_quote()
        flat_signal = _make_signal(quote, direction=SignalDirection.FLAT)
        _signal_from_bus(bus, flat_signal)
        _boot_to_backtest(orch)

        orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
        orch._process_tick(quote)

        assert positions.get("AAPL").quantity == 0, (
            f"alpha FLAT exit did not close the position under a {action.name} "
            "verdict from the shared exposure/drawdown gate"
        )
        assert any(o.side == Side.SELL and o.quantity == 75 for o in captured)


@pytest.mark.parametrize("action", _BLOCKING_ACTIONS)
class TestReversalExitLegSurvivesRiskGate:
    def test_reversal_exit_leg_closes_despite_blocking_verdict(self, action: RiskAction) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", -100, Decimal("150.00"), timestamp_ns=1)
        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=_FirstCheckOrderActionEngine(action),
            position_store=positions,
        )
        captured = _capture_orders(bus)
        quote = _make_quote()
        long_signal = _make_signal(quote, direction=SignalDirection.LONG)
        _signal_from_bus(bus, long_signal)
        _boot_to_backtest(orch)

        orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
        orch._process_tick(quote)

        # The short must be covered (quantity >= 0) regardless of whether
        # the entry leg also fires — the exit leg alone must never be the
        # thing a blocking verdict is allowed to strand.
        assert positions.get("AAPL").quantity >= 0, (
            f"reversal exit leg did not cover the short under a {action.name} "
            "verdict from the shared exposure/drawdown gate"
        )
        assert any(o.side == Side.BUY and o.quantity == 100 for o in captured)
