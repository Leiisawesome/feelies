"""Shutdown drain ordering — fill preserved when IB still connected."""

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
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.storage.memory_trade_journal import InMemoryTradeJournal


class _NoOpMetricCollector:
    def record(self, metric) -> None:  # noqa: ANN001
        pass

    def flush(self) -> None:
        pass


class _DelayedAckRouter(BacktestOrderRouter):
    """Router that holds acks until explicitly released."""

    def __init__(self, clock: SimulatedClock) -> None:
        super().__init__(clock=clock)
        self._held: list[OrderAck] = []
        self._connected = True

    def poll_acks(self) -> list[OrderAck]:
        if not self._connected:
            return []
        out = list(self._held)
        self._held.clear()
        return out + super().poll_acks()

    def hold_ack(self, ack: OrderAck) -> None:
        self._held.append(ack)

    def disconnect(self) -> None:
        self._connected = False
        self._held.clear()


class _SingleQuoteFeed:
    def __init__(self, quote: NBBOQuote) -> None:
        self._quote = quote

    def events(self) -> Iterator[NBBOQuote]:
        yield self._quote


def _build_orchestrator(
    clock: SimulatedClock,
    router: _DelayedAckRouter,
    journal: InMemoryTradeJournal,
) -> Orchestrator:
    quote = NBBOQuote(
        timestamp_ns=1_000_000,
        correlation_id="SPY:1:1",
        sequence=1,
        symbol="SPY",
        bid=Decimal("500.00"),
        ask=Decimal("500.02"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=999_000,
    )
    backend = ExecutionBackend(
        market_data=_SingleQuoteFeed(quote),
        order_router=router,
        mode="PAPER",
    )
    return Orchestrator(
        clock=clock,
        bus=EventBus(),
        backend=backend,
        risk_engine=_AllowAllRisk(),
        position_store=MemoryPositionStore(),
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
        trade_journal=journal,
    )


class _AllowAllRisk:
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


def _boot_paper(orch: Orchestrator) -> None:
    class _Cfg:
        version = "test"
        symbols = frozenset({"SPY"})

        def validate(self) -> None:
            pass

        def snapshot(self):
            return None

    orch.boot(_Cfg())
    orch._macro.transition(MacroState.PAPER_TRADING_MODE, trigger="CMD_PAPER")


def _submit_and_acknowledge(orch: Orchestrator, router: _DelayedAckRouter) -> str:
    order = OrderRequest(
        timestamp_ns=1_000_000,
        correlation_id="paper-order",
        sequence=1,
        order_id="ord-shutdown",
        symbol="SPY",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=1,
        strategy_id="paper_smoke_v1",
    )
    orch._track_order(order.order_id, order.side, order)
    orch._transition_order(order.order_id, OrderState.SUBMITTED, "submitted")
    orch._apply_ack_to_order(
        OrderAck(
            timestamp_ns=1_000_100,
            correlation_id=order.correlation_id,
            sequence=1,
            order_id=order.order_id,
            symbol="SPY",
            status=OrderAckStatus.ACKNOWLEDGED,
        )
    )
    router.hold_ack(
        OrderAck(
            timestamp_ns=1_500_000,
            correlation_id=order.correlation_id,
            sequence=2,
            order_id=order.order_id,
            symbol="SPY",
            status=OrderAckStatus.FILLED,
            filled_quantity=1,
            fill_price=Decimal("500.01"),
        )
    )
    return order.order_id


def test_shutdown_drain_records_fill_while_router_connected() -> None:
    clock = SimulatedClock(start_ns=1_000_000)
    router = _DelayedAckRouter(clock)
    journal = InMemoryTradeJournal()
    orch = _build_orchestrator(clock, router, journal)
    _boot_paper(orch)
    _submit_and_acknowledge(orch, router)

    orch.shutdown()

    assert len(journal) == 1
    rec = next(iter(journal.query()))
    assert rec.order_id == "ord-shutdown"
    assert rec.filled_quantity == 1


def test_shutdown_drops_fill_when_router_disconnected_first() -> None:
    clock = SimulatedClock(start_ns=1_000_000)
    router = _DelayedAckRouter(clock)
    journal = InMemoryTradeJournal()
    orch = _build_orchestrator(clock, router, journal)
    _boot_paper(orch)
    _submit_and_acknowledge(orch, router)

    router.disconnect()
    orch.shutdown()

    assert len(journal) == 0
