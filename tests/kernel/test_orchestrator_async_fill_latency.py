"""IdleTick + delayed async fill latency (Tier 1 — no network)."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.order_state import OrderState
from feelies.ingestion.idle_tick import IdleTick
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.storage.memory_event_log import InMemoryEventLog


class _NoOpMetricCollector:
    def record(self, metric) -> None:  # noqa: ANN001
        pass

    def flush(self) -> None:
        pass


class _DelayedRouter(BacktestOrderRouter):
    def __init__(self, clock: SimulatedClock) -> None:
        super().__init__(clock=clock)
        self._pending: list[OrderAck] = []

    def submit(self, request: OrderRequest) -> None:
        super().submit(request)
        self._pending.append(
            OrderAck(
                timestamp_ns=self._clock.now_ns() + 500_000_000,
                correlation_id=request.correlation_id,
                sequence=request.sequence + 100,
                order_id=request.order_id,
                symbol=request.symbol,
                status=OrderAckStatus.FILLED,
                filled_quantity=request.quantity,
                fill_price=Decimal("100.00"),
            )
        )

    def poll_acks(self) -> list[OrderAck]:
        out = list(self._pending)
        self._pending.clear()
        return out + super().poll_acks()


class _FeedWithIdleTicks:
    def __init__(self, events) -> None:
        self._events = tuple(events)

    def events(self) -> Iterator:
        return iter(self._events)


def _build_orchestrator(clock: SimulatedClock, router: _DelayedRouter) -> Orchestrator:
    quote = NBBOQuote(
        timestamp_ns=1_000_000,
        correlation_id="AAPL:1:1",
        sequence=1,
        symbol="AAPL",
        bid=Decimal("99.00"),
        ask=Decimal("101.00"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=999_000,
    )
    events = [
        quote,
        IdleTick(timestamp_ns=1_200_000),
        IdleTick(timestamp_ns=1_400_000),
    ]
    backend = ExecutionBackend(
        market_data=_FeedWithIdleTicks(events),
        order_router=router,
        mode="PAPER",
    )

    class _AllowAll:
        def check_signal(self, signal, positions):  # noqa: ANN001
            from feelies.core.events import RiskAction, RiskVerdict

            return RiskVerdict(
                timestamp_ns=signal.timestamp_ns,
                correlation_id=signal.correlation_id,
                sequence=signal.sequence,
                symbol=signal.symbol,
                action=RiskAction.ALLOW,
                reason="t",
            )

        def check_order(self, order, positions):  # noqa: ANN001
            from feelies.core.events import RiskAction, RiskVerdict

            return RiskVerdict(
                timestamp_ns=order.timestamp_ns,
                correlation_id=order.correlation_id,
                sequence=order.sequence,
                symbol=order.symbol,
                action=RiskAction.ALLOW,
                reason="t",
            )

    return Orchestrator(
        clock=clock,
        bus=EventBus(),
        backend=backend,
        risk_engine=_AllowAll(),
        position_store=MemoryPositionStore(),
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
    )


def test_delayed_fill_reaches_position_store_via_idle_tick() -> None:
    clock = SimulatedClock(start_ns=1_000_000)
    router = _DelayedRouter(clock)
    orch = _build_orchestrator(clock, router)

    class _Cfg:
        version = "test"
        symbols = frozenset({"AAPL"})

        def validate(self) -> None:
            pass

        def snapshot(self):
            return None

    orch.boot(_Cfg())
    orch._macro.transition(MacroState.PAPER_TRADING_MODE, trigger="CMD_PAPER")

    order = OrderRequest(
        timestamp_ns=1_000_000,
        correlation_id="async-fill",
        sequence=1,
        order_id="ord-async",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        strategy_id="alpha_x",
    )
    orch._track_order(order.order_id, order.side, order)
    orch._transition_order(order.order_id, OrderState.SUBMITTED, "submitted")
    router.submit(order)

    orch._run_pipeline()

    pos = orch._positions.get("AAPL")
    assert pos is not None
    assert pos.quantity == 10
