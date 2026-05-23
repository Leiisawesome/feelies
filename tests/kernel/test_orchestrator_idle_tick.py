"""Tests for the orchestrator's :class:`IdleTick` branch.

The IdleTick path is the paper/live trading hook that lets the
orchestrator drain broker-pushed fills (from :class:`IBOrderRouter`)
even when the WebSocket feed is between market events.  Asserts:

* the branch fires once per ``IdleTick``,
* the micro state machine stays at ``WAITING_FOR_MARKET_EVENT``
  (no spurious state walk),
* the ``IdleTick`` itself is never published to the bus and never
  appended to the event log (Inv-A: legacy bit-identical path
  preserved for BACKTEST).
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    Event,
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
from feelies.kernel.micro import MicroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.storage.memory_event_log import InMemoryEventLog


class _NoOpMetricCollector:
    def record(self, metric):  # noqa: D401, ANN001
        pass

    def flush(self) -> None:
        pass


class _IterableMarketData:
    """Market-data stub that yields a fixed sequence of events / IdleTicks."""

    def __init__(self, events) -> None:
        self._events = tuple(events)

    def events(self) -> Iterator:
        return iter(self._events)


class _QueuedRouter(BacktestOrderRouter):
    """Backtest router with an extra hook to inject async fill acks."""

    def push_async_ack(self, ack: OrderAck) -> None:
        self._pending_acks.append(ack)


def _make_quote(ts: int = 1000) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"AAPL:{ts}:1",
        sequence=1,
        symbol="AAPL",
        bid=Decimal("149.50"),
        ask=Decimal("150.50"),
        bid_size=100,
        ask_size=200,
        exchange_timestamp_ns=ts - 100,
    )


def _track_submitted_order(orch: Orchestrator) -> OrderRequest:
    order = OrderRequest(
        timestamp_ns=orch._clock.now_ns(),
        correlation_id="paper-order",
        sequence=1,
        order_id="ord-paper",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
        strategy_id="alpha_x",
    )
    orch._track_order(order.order_id, order.side, order)
    orch._transition_order(
        order.order_id, OrderState.SUBMITTED, "submitted",
    )
    orch._apply_ack_to_order(OrderAck(
        timestamp_ns=orch._clock.now_ns(),
        correlation_id="paper-order",
        sequence=1,
        order_id=order.order_id,
        symbol="AAPL",
        status=OrderAckStatus.ACKNOWLEDGED,
    ))
    return order


def _build_orch(
    clock: SimulatedClock,
    market_data: _IterableMarketData,
    *,
    router: _QueuedRouter | None = None,
    bus: EventBus | None = None,
    event_log: InMemoryEventLog | None = None,
) -> Orchestrator:
    bus = bus if bus is not None else EventBus()
    event_log = event_log if event_log is not None else InMemoryEventLog()
    router = router or _QueuedRouter(clock=clock)
    backend = ExecutionBackend(
        market_data=market_data,
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
        bus=bus,
        backend=backend,
        risk_engine=_AllowAll(),
        position_store=MemoryPositionStore(),
        event_log=event_log,
        metric_collector=_NoOpMetricCollector(),
    )


def _boot_to_paper(orch: Orchestrator) -> None:
    class _Cfg:
        version = "test-0.1"
        symbols = frozenset({"AAPL"})

        def validate(self) -> None:
            pass

        def snapshot(self):
            return None

    orch.boot(_Cfg())
    orch._macro.transition(
        MacroState.PAPER_TRADING_MODE, trigger="CMD_PAPER",
    )
    orch._micro.reset(trigger="session_start:paper")


def test_idle_tick_drains_async_fills_and_keeps_micro_waiting() -> None:
    clock = SimulatedClock(start_ns=1_000_000)
    router = _QueuedRouter(clock=clock)
    quote = _make_quote()
    router.on_quote(quote)
    market_data = _IterableMarketData([quote, IdleTick(timestamp_ns=2_000_000), IdleTick(timestamp_ns=3_000_000)])
    bus = EventBus()
    published_acks: list[OrderAck] = []
    bus.subscribe(OrderAck, published_acks.append)

    orch = _build_orch(clock, market_data, router=router, bus=bus)
    _boot_to_paper(orch)

    order = _track_submitted_order(orch)

    # Two async fills appear after the quote but before the idle ticks
    # would naturally arrive in production (the queue is filled by
    # poll_fills() in the live IB scenario; here we push them
    # directly).
    router.push_async_ack(OrderAck(
        timestamp_ns=2_100_000,
        correlation_id=order.correlation_id,
        sequence=99,
        order_id=order.order_id,
        symbol=order.symbol,
        status=OrderAckStatus.FILLED,
        filled_quantity=10,
        fill_price=Decimal("150.25"),
    ))

    orch._run_pipeline()

    assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT
    assert any(
        a.order_id == "ord-paper" and a.status == OrderAckStatus.FILLED
        for a in published_acks
    )


def test_idle_tick_not_published_or_logged() -> None:
    clock = SimulatedClock(start_ns=1_000_000)
    bus = EventBus()
    seen_events: list[Event] = []
    bus.subscribe(Event, seen_events.append)
    event_log = InMemoryEventLog()
    market_data = _IterableMarketData([
        IdleTick(timestamp_ns=1_500_000),
        IdleTick(timestamp_ns=2_500_000),
    ])
    orch = _build_orch(clock, market_data, bus=bus, event_log=event_log)
    _boot_to_paper(orch)
    orch._run_pipeline()

    assert all(not isinstance(e, IdleTick) for e in seen_events)
    for evt in event_log.replay():
        assert not isinstance(evt, IdleTick)


def test_idle_tick_no_op_when_router_empty() -> None:
    clock = SimulatedClock(start_ns=1_000_000)
    bus = EventBus()
    published_acks: list[OrderAck] = []
    bus.subscribe(OrderAck, published_acks.append)
    market_data = _IterableMarketData([IdleTick(timestamp_ns=1)])
    orch = _build_orch(clock, market_data, bus=bus)
    _boot_to_paper(orch)
    orch._run_pipeline()

    assert published_acks == []
    assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT


def test_idle_tick_after_macro_halt_breaks_loop() -> None:
    clock = SimulatedClock(start_ns=1_000_000)
    halted = {"yes": False}

    class _SignalingMarketData:
        def events(self):
            yield IdleTick(timestamp_ns=1)
            halted["yes"] = True
            yield IdleTick(timestamp_ns=2)
            yield IdleTick(timestamp_ns=3)

    orch = _build_orch(clock, _SignalingMarketData())
    _boot_to_paper(orch)

    # Halt the orchestrator after the first IdleTick is observed.
    # The pipeline check happens at the top of each iteration; the
    # second IdleTick must NOT be processed.
    drain_calls: list[str] = []
    original = orch._drain_async_fills

    def spy(correlation_id: str) -> None:
        drain_calls.append(correlation_id)
        if halted["yes"]:
            orch.halt()
        original(correlation_id)

    orch._drain_async_fills = spy  # type: ignore[method-assign]
    orch._run_pipeline()
    # First IdleTick triggers spy (no halt yet); after that the iterator
    # flips `halted["yes"]` then yields a second IdleTick that spy
    # observes (calling halt() before delegating).  The next iteration
    # of _run_pipeline sees macro state ≠ TRADING_MODES and breaks
    # before consuming the third IdleTick, so exactly 2 drains.
    assert len(drain_calls) == 2
