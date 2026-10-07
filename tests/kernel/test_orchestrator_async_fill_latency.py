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
from feelies.kernel.orchestrator import _transition_order
from feelies.execution.order_state import OrderState
from feelies.ingestion.idle_tick import IdleTick
from feelies.kernel.macro import MacroState
from feelies.composition.selection_policy import Top1SelectionPolicy
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

    def submit(
        self,
        request: OrderRequest,
        triggering_quote: NBBOQuote | None = None,
    ) -> None:
        super().submit(request, triggering_quote=triggering_quote)
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
        selection_policy=Top1SelectionPolicy(),
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
    _transition_order(orch, order.order_id, OrderState.SUBMITTED, "submitted")
    router.submit(order)

    orch._run_pipeline()

    pos = orch._positions.get("AAPL")
    assert pos is not None
    assert pos.quantity == 10


_LATENCY_T0 = 10_000_000_000
_LATENCY_NS = 50_000_000
_LATENCY_SYMBOL = "AAPL"


def _latency_session() -> tuple[object, object, object, list[str]]:
    from typing import Any

    from feelies.core.events import DeRiskRequirement
    from feelies.core.identifiers import SequenceGenerator
    from feelies.portfolio.position_store import PositionStore
    from feelies.risk.sized_intent_result import SizedIntentRiskResult
    from feelies.risk.stop_exit import StopExitController, StopExitPolicy

    class _StubRiskEngine:
        def check_signal(self, signal: Any, positions: PositionStore) -> Any:
            del signal, positions
            raise AssertionError("signal path is not this test")

        def check_order(self, order: OrderRequest, positions: PositionStore) -> Any:
            del positions
            from feelies.core.events import RiskAction, RiskVerdict

            return RiskVerdict(
                timestamp_ns=order.timestamp_ns,
                correlation_id=order.correlation_id,
                sequence=order.sequence,
                symbol=order.symbol,
                action=RiskAction.ALLOW,
                reason="fill-report-latency",
            )

        def check_sized_intent(
            self, intent: Any, positions: PositionStore
        ) -> SizedIntentRiskResult:
            del intent, positions
            return SizedIntentRiskResult(orders=())

    class _LatencyConfig:
        version = "fill-report-latency"
        symbols = frozenset({_LATENCY_SYMBOL})

        def validate(self) -> None:
            return None

        def snapshot(self) -> None:
            return None

    clock = SimulatedClock(start_ns=_LATENCY_T0)
    bus = EventBus()
    stops: list[str] = []
    bus.subscribe(DeRiskRequirement, lambda event: stops.append(event.reason))
    bus.subscribe(OrderRequest, lambda event: stops.append(f"order:{event.reason}"))
    router = BacktestOrderRouter(clock=clock, latency_ns=0, fill_report_latency_ms=50)
    orch = Orchestrator(
        selection_policy=Top1SelectionPolicy(),
        clock=clock,
        bus=bus,
        backend=ExecutionBackend(
            market_data=_FeedWithIdleTicks(()),
            order_router=router,
            mode="BACKTEST",
        ),
        risk_engine=_StubRiskEngine(),
        position_store=MemoryPositionStore(),
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
    )
    StopExitController(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        position_store=orch._positions,
        policy=StopExitPolicy(stop_loss_per_share=1.0),
        clock=clock,
    ).attach()
    orch.boot(_LatencyConfig())
    orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
    orch._micro.reset(trigger="session_start:fill-report-latency")
    return clock, orch, router, stops


def _latency_quote(ts: int, seq: int, bid: str, ask: str) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"{_LATENCY_SYMBOL}:{ts}:{seq}",
        sequence=seq,
        symbol=_LATENCY_SYMBOL,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=500,
        ask_size=500,
        exchange_timestamp_ns=ts,
    )


def _latency_submit(orch: Orchestrator, quote: NBBOQuote, side: Side, reason: str) -> None:
    from feelies.core.identifiers import derive_order_id
    from feelies.kernel.orchestrator import _submit_tracked_order

    order_id = derive_order_id(f"{reason}:{quote.timestamp_ns}")
    order = OrderRequest(
        timestamp_ns=quote.timestamp_ns,
        correlation_id=quote.correlation_id,
        sequence=orch._seq.next(),
        order_id=order_id,
        symbol=_LATENCY_SYMBOL,
        side=side,
        order_type=OrderType.MARKET,
        quantity=100,
        strategy_id="fill_report_latency",
        reason=reason,
    )
    orch._track_order(
        order_id,
        side,
        order,
        trading_intent="ENTRY" if side is Side.BUY else "EXIT",
    )
    _submit_tracked_order(orch, order)


def _latency_tick(
    clock: SimulatedClock,
    orch: Orchestrator,
    ts: int,
    seq: int,
    bid: str,
    ask: str,
) -> None:
    clock.set_time(ts)
    orch._process_tick(_latency_quote(ts, seq, bid, ask))


def stop_scenario(crash_bid: str) -> dict[str, object]:
    """Open 100, hold the closing fill, then print ``crash_bid``.

    The entry fills at 150.10. A one-dollar stop is through only below 149.10.
    """
    clock, orch, router, stops = _latency_session()
    q0 = _latency_quote(_LATENCY_T0, 1, "150.00", "150.10")
    clock.set_time(_LATENCY_T0)
    router.on_quote(q0)
    _latency_submit(orch, q0, Side.BUY, "PROBE_ENTRY")
    _latency_tick(clock, orch, _LATENCY_T0, 1, "150.00", "150.10")
    qty_born = orch._positions.get(_LATENCY_SYMBOL).quantity
    _latency_tick(clock, orch, _LATENCY_T0 + _LATENCY_NS, 2, "150.00", "150.10")
    qty_open = orch._positions.get(_LATENCY_SYMBOL).quantity
    sell_ts = _LATENCY_T0 + _LATENCY_NS + 10_000_000
    q_sell = _latency_quote(sell_ts, 3, "149.80", "149.90")
    clock.set_time(sell_ts)
    router.on_quote(q_sell)
    _latency_submit(orch, q_sell, Side.SELL, "PROBE_EXIT")
    _latency_tick(clock, orch, sell_ts, 3, "149.80", "149.90")
    qty_held = orch._positions.get(_LATENCY_SYMBOL).quantity
    before = len(stops)
    crash_ask = str(Decimal(crash_bid) + Decimal("0.10"))
    _latency_tick(clock, orch, sell_ts + _LATENCY_NS, 4, crash_bid, crash_ask)
    return {
        "qty_born": qty_born,
        "qty_open": qty_open,
        "qty_held": qty_held,
        "qty_after": orch._positions.get(_LATENCY_SYMBOL).quantity,
        "stops": stops[before:],
    }


def test_due_fill_visible_to_stop_at_l50() -> None:
    """The closing fill is applied before the stop reads a crashed book."""
    row = stop_scenario("140.00")
    assert row["qty_open"] == 100
    assert row["qty_held"] == 100
    assert row["stops"] == []
    assert row["qty_after"] == 0


def test_trade_tick_releases_due_report() -> None:
    """A trade releases a due fill before the trade body runs. The quote path is idle."""
    from feelies.core.events import Trade

    clock, orch, router, _stops = _latency_session()
    q0 = _latency_quote(_LATENCY_T0, 1, "150.00", "150.10")
    clock.set_time(_LATENCY_T0)
    router.on_quote(q0)
    _latency_submit(orch, q0, Side.BUY, "PROBE_ENTRY")
    _latency_tick(clock, orch, _LATENCY_T0, 1, "150.00", "150.10")
    assert orch._positions.get(_LATENCY_SYMBOL).quantity == 0
    release_ns = _LATENCY_T0 + _LATENCY_NS + 5_000_000
    clock.set_time(release_ns)
    orch._process_trade(
        Trade(
            timestamp_ns=release_ns,
            correlation_id=f"{_LATENCY_SYMBOL}:{release_ns}:trade",
            sequence=2,
            symbol=_LATENCY_SYMBOL,
            price=Decimal("150.05"),
            size=100,
            exchange_timestamp_ns=release_ns,
        )
    )
    assert orch._positions.get(_LATENCY_SYMBOL).quantity == 100
