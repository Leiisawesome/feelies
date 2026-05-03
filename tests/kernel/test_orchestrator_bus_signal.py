"""Tests for the PR-2b-iii bus-driven ``Signal`` subscriber.

The orchestrator's :meth:`Orchestrator._on_bus_signal` translates
``Signal(layer="SIGNAL")`` events published on the platform bus into the
existing per-tick risk → order → fill walk.

PR-2b-iv (this commit) deleted the legacy ``signal_engine`` /
``feature_engine`` ctor scaffolding, so the bus subscriber is now the
sole standalone-SIGNAL → Order path.

These tests assert the contract:

* A bus-published SIGNAL alpha's ``Signal`` triggers the order pipeline.
* Stop-loss exits computed inline by ``_check_stop_exit`` always
  override (Inv-11: position safety beats alpha conviction).
* Signals with ``layer != "SIGNAL"`` and synthetic ``__stop_exit__``
  signals are filtered out of the buffer.
* Signals from SIGNAL alphas referenced by any registered PORTFOLIO's
  ``depends_on_signals`` are skipped — they aggregate through
  ``CompositionEngine`` into ``SizedPositionIntent`` events and would
  otherwise double-trade (Inv-11).
* The buffer is cleared at the start of every tick so prior-tick
  Signals cannot leak into subsequent ticks.
* When more than one standalone SIGNAL alpha fires on the same tick,
  ``EdgeWeightedArbitrator`` (default; injectable via ``signal_arbitrator``)
  selects one candidate (FLAT privileged; else edge*strength; tie →
  arrival order).  A once-per-process WARNING recommends PORTFOLIO
  aggregation for richer multi-alpha policy.
* Standalone Signals buffered only from Trade-driven horizon ticks (between
  quote ticks) receive a trace row when the next quote tick clears the
  buffer, so ``--trace-signal-orders`` stays aligned with bus Signal counts.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    RiskAction,
    RiskVerdict,
    Signal,
    SignalDirection,
)
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.kernel.macro import MacroState
from feelies.kernel.micro import MicroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.kernel.signal_order_trace import SignalOrderTraceRow
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.position_store import PositionStore
from feelies.storage.memory_event_log import InMemoryEventLog


# ── Stubs (mirror tests/kernel/test_orchestrator.py shape) ───────────


class _NoOpMetricCollector:
    def record(self, _metric: Any) -> None:
        pass

    def flush(self) -> None:
        pass


class _StubMarketData:
    def __init__(self, events: list[Any] | None = None) -> None:
        self._events = events or []

    def events(self):
        return iter(self._events)


class _StubRiskEngine:
    def __init__(self, action: RiskAction = RiskAction.ALLOW) -> None:
        self._action = action

    def check_signal(self, signal: Signal, _positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=signal.timestamp_ns,
            correlation_id=signal.correlation_id,
            sequence=signal.sequence,
            symbol=signal.symbol,
            action=self._action,
            reason="bus-signal-test",
        )

    def check_order(self, order: OrderRequest, _positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=self._action,
            reason="bus-signal-test",
        )


class _MinimalConfig:
    version = "test-bus-signal"
    symbols = frozenset({"AAPL"})

    def validate(self) -> None:
        pass

    def snapshot(self) -> None:
        return None


class _StaticPortfolioModule:
    """Minimal stand-in for ``LoadedPortfolioLayerModule`` with only the
    surface the orchestrator's skip-rule actually inspects.
    """

    def __init__(self, *, depends_on_signals: tuple[str, ...]) -> None:
        self._depends = depends_on_signals

    @property
    def depends_on_signals(self) -> tuple[str, ...]:
        return self._depends


class _StaticAlphaRegistry:
    """Minimal stand-in for ``AlphaRegistry`` exposing ``portfolio_alphas``.

    Intentionally raises ``KeyError`` from :meth:`get` for any alpha_id —
    the orchestrator's ``_compute_target_quantity`` is documented to fall
    back to the IntentTranslator default in that case (no alpha-side risk
    budget to apply), which is exactly what these tests want: a default
    100-share target that exercises the order pipeline.
    """

    def __init__(self, *, portfolio_modules: tuple[_StaticPortfolioModule, ...] = ()) -> None:
        self._portfolio_modules = portfolio_modules

    def portfolio_alphas(self) -> tuple[_StaticPortfolioModule, ...]:
        return self._portfolio_modules

    def get(self, alpha_id: str) -> Any:
        raise KeyError(alpha_id)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_quote(
    *, ts: int = 1000, bid: str = "149.50", ask: str = "150.50", seq: int = 1,
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
    layer: str = "SIGNAL",
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
        layer=layer,
    )


def _build_orchestrator(
    clock: SimulatedClock,
    *,
    bus: EventBus | None = None,
    risk_engine: Any | None = None,
    alpha_registry: Any | None = None,
    position_store: MemoryPositionStore | None = None,
) -> Orchestrator:
    bus = bus if bus is not None else EventBus()
    pos = position_store or MemoryPositionStore()
    bt_router = BacktestOrderRouter(clock=clock)
    backend = ExecutionBackend(
        market_data=_StubMarketData(),
        order_router=bt_router,
        mode="BACKTEST",
    )
    return Orchestrator(
        clock=clock,
        bus=bus,
        backend=backend,
        risk_engine=risk_engine or _StubRiskEngine(),
        position_store=pos,
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
        alpha_registry=alpha_registry,
    )


def _boot_to_backtest(orch: Orchestrator) -> None:
    orch.boot(_MinimalConfig())
    assert orch.macro_state == MacroState.READY
    orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
    orch._micro.reset(trigger="session_start:test")


def _capture_orders(bus: EventBus) -> list[OrderRequest]:
    captured: list[OrderRequest] = []
    bus.subscribe(OrderRequest, captured.append)  # type: ignore[arg-type]
    return captured


def _signal_from_bus(bus: EventBus, signal: Signal) -> None:
    """Subscribe an emit-on-quote republisher mimicking HorizonSignalEngine.

    Production: ``HorizonSignalEngine`` subscribes to
    ``HorizonFeatureSnapshot`` and publishes ``Signal`` events as a
    side-effect.  Tests don't bring up the full snapshot pipeline; we
    publish a Signal directly in response to each ``NBBOQuote``, which
    arrives at M1's ``bus.publish(quote)`` and is buffered by the
    orchestrator's ``_on_bus_signal`` before M4 drains.
    """
    def emit(quote: NBBOQuote) -> None:
        bus.publish(replace(
            signal,
            timestamp_ns=quote.timestamp_ns,
            correlation_id=quote.correlation_id,
            sequence=quote.sequence,
        ))
    bus.subscribe(NBBOQuote, emit)  # type: ignore[arg-type]


# ── Tests ────────────────────────────────────────────────────────────


class TestBusDrivenSignalProducesOrder:
    """Bus-published Signal triggers the per-tick order pipeline.

    This is the core PR-2b-iii contract: production SIGNAL alphas publish
    on the bus, and the orchestrator translates that into an order.
    """

    def test_bus_signal_translates_to_order_request(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        signal = _make_signal(quote, strategy_id="test_standalone_alpha")

        orch = _build_orchestrator(clock, bus=bus)
        captured = _capture_orders(bus)
        _signal_from_bus(bus, signal)

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert len(captured) == 1, (
            f"expected exactly 1 OrderRequest from the bus-fed Signal, "
            f"got {len(captured)}"
        )
        assert captured[0].symbol == "AAPL"
        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT

    def test_bus_signal_with_no_signal_published_ends_at_log_and_metrics(
        self,
    ) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()

        orch = _build_orchestrator(clock, bus=bus)
        captured = _capture_orders(bus)

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert captured == []
        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT


class TestPortfolioConsumedSignalsSkipped:
    """SIGNAL alphas referenced by any registered PORTFOLIO's
    ``depends_on_signals`` must be skipped to avoid double-trading."""

    def test_signal_consumed_by_portfolio_is_skipped(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        signal = _make_signal(quote, strategy_id="alpha_consumed_by_pf")

        registry = _StaticAlphaRegistry(
            portfolio_modules=(
                _StaticPortfolioModule(
                    depends_on_signals=("alpha_consumed_by_pf", "other_alpha"),
                ),
            ),
        )
        orch = _build_orchestrator(
            clock, bus=bus, alpha_registry=registry,
        )
        captured = _capture_orders(bus)
        _signal_from_bus(bus, signal)

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert captured == [], (
            "PORTFOLIO-consumed Signal must NOT translate to an OrderRequest; "
            "the composition engine aggregates it into a "
            "SizedPositionIntent which the PR-2b-iv ``_on_bus_sized_intent`` "
            "subscriber translates separately."
        )

    def test_signal_not_consumed_by_portfolio_still_translates(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        signal = _make_signal(quote, strategy_id="standalone_alpha")

        registry = _StaticAlphaRegistry(
            portfolio_modules=(
                _StaticPortfolioModule(
                    depends_on_signals=("different_alpha",),
                ),
            ),
        )
        orch = _build_orchestrator(
            clock, bus=bus, alpha_registry=registry,
        )
        captured = _capture_orders(bus)
        _signal_from_bus(bus, signal)

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert len(captured) == 1, (
            "Standalone SIGNAL alpha (not referenced by any PORTFOLIO) "
            "must still translate to an OrderRequest."
        )


class TestBufferLifecycle:
    """The per-tick Signal buffer must be cleared at the start of every
    ``_process_tick_inner`` call to prevent leak-through."""

    def test_buffer_cleared_between_ticks(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote_1 = _make_quote(ts=1000, seq=1)
        quote_2 = _make_quote(ts=2000, seq=2)
        signal = _make_signal(quote_1, strategy_id="standalone_alpha")

        orch = _build_orchestrator(clock, bus=bus)
        captured = _capture_orders(bus)
        bus.publish(signal)
        assert orch._signal_buffer == [signal], (
            "the buffer must accept Signals published outside a tick "
            "(this normally happens at M1 within the tick, but the "
            "subscriber itself does not gate on tick-state)."
        )

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote_1)
        _boot_to_backtest(orch)
        orch._process_tick(quote_1)
        BacktestOrderRouter.on_quote(orch._backend.order_router, quote_2)
        orch._process_tick(quote_2)

        assert len(captured) == 0, (
            "the pre-tick stale Signal must be cleared at the start of "
            "tick 1's _process_tick_inner; tick 2 has no fresh Signal so "
            "no OrderRequest should fire on either tick."
        )


class TestFiltering:
    """``_on_bus_signal`` filters out Signals that should not enter the
    per-tick Signal → Order pipeline."""

    def test_non_signal_layer_is_filtered_out(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        orch = _build_orchestrator(clock, bus=bus)

        portfolio_signal = _make_signal(
            _make_quote(), strategy_id="pf_alpha", layer="PORTFOLIO",
        )
        bus.publish(portfolio_signal)

        assert orch._signal_buffer == [], (
            "PORTFOLIO-layer Signals (if any future code emits them) "
            "must not enter the per-tick legacy order pipeline.  PR-2b-iv "
            "will wire SizedPositionIntent → OrderRequest separately."
        )

    def test_stop_exit_signal_is_filtered_out(self) -> None:
        """``__stop_exit__`` Signals are computed inline by
        ``_check_stop_exit`` and must not be double-routed via the bus.
        """
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        orch = _build_orchestrator(clock, bus=bus)

        stop_exit_signal = _make_signal(
            _make_quote(), strategy_id="__stop_exit__",
        )
        bus.publish(stop_exit_signal)

        assert orch._signal_buffer == []


class TestMultipleStandaloneSignalsPerTick:
    """One micro-SM order walk per tick; multiple candidates → arbitrator."""

    def test_tie_break_favors_first_arrival_when_scores_equal(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="feelies.kernel.orchestrator")
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        signal_a = _make_signal(quote, strategy_id="alpha_first")
        signal_b = _make_signal(quote, strategy_id="alpha_second")

        orch = _build_orchestrator(clock, bus=bus)
        captured = _capture_orders(bus)

        def emit_two_signals(q: NBBOQuote) -> None:
            for s in (signal_a, signal_b):
                bus.publish(replace(
                    s,
                    timestamp_ns=q.timestamp_ns,
                    correlation_id=q.correlation_id,
                    sequence=q.sequence,
                ))
        bus.subscribe(NBBOQuote, emit_two_signals)  # type: ignore[arg-type]

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert len(captured) == 1, (
            "exactly one OrderRequest per tick (micro-SM constraint)"
        )
        assert captured[0].strategy_id == "alpha_first"
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("standalone SIGNAL alphas fired" in r.message for r in warnings), (
            "expected a once-per-process WARNING about multiple "
            "standalone Signals; got logs: "
            + str([r.message for r in warnings])
        )

    def test_arbitration_prefers_higher_composite_over_first_arrival(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="feelies.kernel.orchestrator")
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        weak_first = _make_signal(quote, strategy_id="weak_first")
        weak_first = replace(weak_first, strength=0.2, edge_estimate_bps=5.0)
        strong_second = _make_signal(quote, strategy_id="strong_second")
        strong_second = replace(strong_second, strength=1.0, edge_estimate_bps=50.0)

        orch = _build_orchestrator(clock, bus=bus)
        captured = _capture_orders(bus)

        def emit_two_signals(q: NBBOQuote) -> None:
            for s in (weak_first, strong_second):
                bus.publish(replace(
                    s,
                    timestamp_ns=q.timestamp_ns,
                    correlation_id=q.correlation_id,
                    sequence=q.sequence,
                ))
        bus.subscribe(NBBOQuote, emit_two_signals)  # type: ignore[arg-type]

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert len(captured) == 1
        assert captured[0].strategy_id == "strong_second"

    def test_warning_emitted_only_once_per_process(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="feelies.kernel.orchestrator")
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        signal_a = _make_signal(_make_quote(), strategy_id="alpha_first")
        signal_b = _make_signal(_make_quote(), strategy_id="alpha_second")

        orch = _build_orchestrator(clock, bus=bus)

        def emit_two_signals(q: NBBOQuote) -> None:
            for s in (signal_a, signal_b):
                bus.publish(replace(
                    s,
                    timestamp_ns=q.timestamp_ns,
                    correlation_id=q.correlation_id,
                    sequence=q.sequence,
                ))
        bus.subscribe(NBBOQuote, emit_two_signals)  # type: ignore[arg-type]

        _boot_to_backtest(orch)
        for i in range(3):
            q = _make_quote(ts=1000 + i * 1000, seq=i + 1)
            BacktestOrderRouter.on_quote(orch._backend.order_router, q)
            orch._process_tick(q)

        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "standalone SIGNAL alphas fired" in r.message
        ]
        assert len(warnings) == 1, (
            f"expected exactly 1 WARNING across 3 ticks (once-per-process "
            f"latch), got {len(warnings)}"
        )


def test_trace_sink_records_buffer_evicted_standalone_signals() -> None:
    """Signals left in ``_signal_buffer`` across quote ticks get one trace row.

    Mirrors Trade-driven ``HorizonTick`` paths: bus-visible Signals that were
    buffered but never drained by M4 must not disappear from
    ``signal_order_trace_sink`` when the next tick clears the buffer.
    """
    clock = SimulatedClock(start_ns=1000)
    bus = EventBus()
    sink: list[SignalOrderTraceRow] = []
    orch = _build_orchestrator(clock, bus=bus)
    orch._signal_order_trace_sink = sink
    _boot_to_backtest(orch)

    q1 = _make_quote(ts=1000, seq=1)
    orch._process_tick(q1)

    orphan = replace(
        _make_signal(q1, strategy_id="orphan_alpha"),
        sequence=91_000,
        timestamp_ns=q1.timestamp_ns + 500,
    )
    orch._signal_buffer.append(orphan)

    q2 = _make_quote(ts=2000, seq=2)
    orch._process_tick(q2)

    evicted = [
        r
        for r in sink
        if r.signal_sequence == 91_000
        and "signal_buffer_cleared_unprocessed_at_tick_boundary" in r.reasons
    ]
    assert len(evicted) == 1
    assert evicted[0].quote_sequence == q1.sequence
    assert evicted[0].outcome == "NO_ORDER"
