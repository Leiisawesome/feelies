"""R3 — forced-exit fill stream is independent of NBBOQuote registration order.

StopExitController subscribes NBBOQuote and can publish an OrderRequest on
the same publish. Quotes are driven through Orchestrator._process_tick so the
nested submit sees the in-flight tick quote. Both simulated routers priced
submit() from ``_last_quotes``, which on_quote writes first. Router-first
therefore filled the stop at this quote; stop-first filled at the previous
quote. The streams must agree: a forced exit prices against the quote that
triggered it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, OrderAck, OrderAckStatus, OrderRequest
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.risk.stop_exit import (
    STOP_EXIT_REASON_STOP,
    StopExitController,
    StopExitPolicy,
)
from feelies.storage.memory_event_log import InMemoryEventLog

_SYMBOL = "AAPL"
_ENTRY = Decimal("100.00")
_QTY = 10
# Seed quote: mid equals entry, so the stop does not fire. Bid is the
# stale price a stop-first submit would cross a long against.
_SEED_BID = Decimal("99.50")
_SEED_ASK = Decimal("100.50")
# Trigger quote: mid is $9.50 through the $1 stop. Bid is the price a
# router-first submit would cross a long against.
_TRIGGER_BID = Decimal("90.00")
_TRIGGER_ASK = Decimal("91.00")


class _NoOpMetricCollector:
    def record(self, _metric: Any) -> None:
        pass

    def flush(self) -> None:
        pass


class _StubMarketData:
    def events(self):  # type: ignore[no-untyped-def]
        return iter([])


class _MinimalConfig:
    version = "test-r3-registration-order"
    symbols = frozenset({_SYMBOL})

    def validate(self) -> None:
        pass

    def snapshot(self) -> None:
        return None


def _quote(*, timestamp_ns: int, bid: Decimal, ask: Decimal, sequence: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=timestamp_ns,
        correlation_id=f"{_SYMBOL}:{timestamp_ns}:{sequence}",
        sequence=sequence,
        symbol=_SYMBOL,
        bid=bid,
        ask=ask,
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=timestamp_ns,
    )


def _nbbo_handler_names(bus: EventBus) -> list[str]:
    names: list[str] = []
    for handler in bus._handlers.get(NBBOQuote, ()):
        owner = getattr(handler, "__self__", None)
        if isinstance(owner, StopExitController):
            names.append("stop_exit")
        elif isinstance(owner, (BacktestOrderRouter, PassiveLimitOrderRouter)):
            names.append("router")
        else:
            names.append(type(owner).__name__ if owner is not None else repr(handler))
    return names


@dataclass(frozen=True)
class _Run:
    handler_order: tuple[str, ...]
    stop_reasons: tuple[str, ...]
    fills: tuple[tuple[str, str, str], ...]


def _fill_tuple(ack: OrderAck) -> tuple[str, str, str]:
    price = "" if ack.fill_price is None else str(ack.fill_price)
    return (ack.status.name, price, ack.reason)


def _run(router_cls: type[Any], *, stop_first: bool) -> _Run:
    clock = SimulatedClock(start_ns=1_000_000)
    bus = EventBus()
    positions = MemoryPositionStore()
    positions.update(_SYMBOL, _QTY, _ENTRY)
    router = router_cls(clock=clock)
    stop = StopExitController(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        position_store=positions,
        policy=StopExitPolicy(stop_loss_per_share=1.0),
    )
    orch = Orchestrator(
        clock=clock,
        bus=bus,
        backend=ExecutionBackend(
            market_data=_StubMarketData(),
            order_router=router,
            mode="BACKTEST",
        ),
        risk_engine=BasicRiskEngine(
            RiskConfig(
                account_equity=Decimal("1000000"),
                max_position_per_symbol=10_000,
                max_gross_exposure_pct=200.0,
            )
        ),
        position_store=positions,
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
        account_equity=Decimal("1000000"),
    )
    orch.boot(_MinimalConfig())
    orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
    orch._micro.reset(trigger="session_start:test")

    if stop_first:
        stop.attach()
        bus.subscribe(NBBOQuote, router.on_quote)
    else:
        bus.subscribe(NBBOQuote, router.on_quote)
        stop.attach()

    submitted: list[OrderRequest] = []
    fills: list[OrderAck] = []

    def _on_order(event: Any) -> None:
        if isinstance(event, OrderRequest):
            submitted.append(event)

    def _on_ack(event: Any) -> None:
        if isinstance(event, OrderAck):
            fills.append(event)

    bus.subscribe(OrderRequest, _on_order)
    bus.subscribe(OrderAck, _on_ack)

    orch._process_tick(
        _quote(timestamp_ns=1_000_000, bid=_SEED_BID, ask=_SEED_ASK, sequence=1)
    )
    orch._process_tick(
        _quote(timestamp_ns=2_000_000, bid=_TRIGGER_BID, ask=_TRIGGER_ASK, sequence=2)
    )
    return _Run(
        handler_order=tuple(_nbbo_handler_names(bus)),
        stop_reasons=tuple(o.reason for o in submitted if o.reason == STOP_EXIT_REASON_STOP),
        fills=tuple(_fill_tuple(a) for a in fills),
    )


def test_r3_forced_exit_fill_stream_independent_of_registration_order() -> None:
    routers = (
        ("BacktestOrderRouter", BacktestOrderRouter),
        ("PassiveLimitOrderRouter", PassiveLimitOrderRouter),
    )
    runs: dict[tuple[str, str], _Run] = {}
    for name, cls in routers:
        runs[(name, "router_first")] = _run(cls, stop_first=False)
        runs[(name, "stop_first")] = _run(cls, stop_first=True)

    for name, _cls in routers:
        router_first = runs[(name, "router_first")]
        stop_first = runs[(name, "stop_first")]
        assert router_first.handler_order == ("router", "stop_exit"), (
            f"{name} router_first handlers={router_first.handler_order!r}"
        )
        assert stop_first.handler_order == ("stop_exit", "router"), (
            f"{name} stop_first handlers={stop_first.handler_order!r}"
        )
        assert router_first.stop_reasons == (STOP_EXIT_REASON_STOP,), (
            f"{name} router_first did not submit a stop-exit: {router_first.stop_reasons!r}"
        )
        assert stop_first.stop_reasons == (STOP_EXIT_REASON_STOP,), (
            f"{name} stop_first did not submit a stop-exit: {stop_first.stop_reasons!r}"
        )
        assert any(row[0] == OrderAckStatus.FILLED.name or row[0] == OrderAckStatus.REJECTED.name
                   for row in router_first.fills), (
            f"{name} router_first produced no terminal acks: {router_first.fills!r}"
        )
        assert any(row[0] == OrderAckStatus.FILLED.name or row[0] == OrderAckStatus.REJECTED.name
                   for row in stop_first.fills), (
            f"{name} stop_first produced no terminal acks: {stop_first.fills!r}"
        )

    dump = "\n".join(
        f"  {name} {order}: handlers={run.handler_order} "
        f"stop={run.stop_reasons} fills={run.fills}"
        for (name, order), run in runs.items()
    )
    disagreements = []
    for name, _cls in routers:
        a = runs[(name, "router_first")].fills
        b = runs[(name, "stop_first")].fills
        if a != b:
            disagreements.append(f"{name}: router_first={a} stop_first={b}")
    assert not disagreements, (
        "forced-exit fill streams depend on NBBOQuote registration order\n"
        + "\n".join(disagreements)
        + "\nall four streams:\n"
        + dump
    )
