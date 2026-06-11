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
    SizedPositionIntent,
)
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import ZeroCostModel
from feelies.kernel.macro import MacroState
from feelies.kernel.micro import MicroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.kernel.signal_order_trace import SignalOrderTraceRow
from feelies.monitoring.in_memory import InMemoryKillSwitch
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.position_store import PositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.risk.escalation import RiskLevel
from feelies.risk.sized_intent_result import SizedIntentRiskResult
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

    def check_sized_intent(
        self,
        intent: SizedPositionIntent,
        _positions: PositionStore,
    ) -> SizedIntentRiskResult:
        del intent
        return SizedIntentRiskResult(orders=())


class _DualScaleDownRiskEngine:
    """Emit SCALE_DOWN at both gates to verify single-application."""

    def __init__(self, factor: float = 0.5) -> None:
        self._factor = factor

    def check_signal(self, signal: Signal, _positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=signal.timestamp_ns,
            correlation_id=signal.correlation_id,
            sequence=signal.sequence,
            symbol=signal.symbol,
            action=RiskAction.SCALE_DOWN,
            reason="dual-scale-down-test:signal",
            scaling_factor=self._factor,
        )

    def check_order(self, order: OrderRequest, _positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=RiskAction.SCALE_DOWN,
            reason="dual-scale-down-test:order",
            scaling_factor=self._factor,
        )

    def check_sized_intent(
        self,
        intent: SizedPositionIntent,
        _positions: PositionStore,
    ) -> SizedIntentRiskResult:
        del intent
        return SizedIntentRiskResult(orders=())


class _ForceFlattenOnFirstCheckOrderEngine:
    """First :meth:`check_order` in the tick returns FORCE_FLATTEN (reverse exit)."""

    def __init__(self) -> None:
        self._check_order_calls = 0

    def check_signal(self, signal: Signal, _positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=signal.timestamp_ns,
            correlation_id=signal.correlation_id,
            sequence=signal.sequence,
            symbol=signal.symbol,
            action=RiskAction.ALLOW,
            reason="force-flatten-first-order-test:signal",
        )

    def check_order(self, order: OrderRequest, _positions: PositionStore) -> RiskVerdict:
        self._check_order_calls += 1
        if self._check_order_calls == 1:
            return RiskVerdict(
                timestamp_ns=order.timestamp_ns,
                correlation_id=order.correlation_id,
                sequence=order.sequence,
                symbol=order.symbol,
                action=RiskAction.FORCE_FLATTEN,
                reason="test_reverse_exit_drawdown",
            )
        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=RiskAction.ALLOW,
            reason="force-flatten-first-order-test:pass",
        )

    def check_sized_intent(
        self,
        intent: SizedPositionIntent,
        _positions: PositionStore,
    ) -> SizedIntentRiskResult:
        del intent
        return SizedIntentRiskResult(orders=())


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

    def has_portfolio_alphas(self) -> bool:
        return bool(self._portfolio_modules)

    def get(self, alpha_id: str) -> Any:
        raise KeyError(alpha_id)


# ── Helpers ──────────────────────────────────────────────────────────


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
    kill_switch: Any | None = None,
) -> Orchestrator:
    bus = bus if bus is not None else EventBus()
    pos = position_store or MemoryPositionStore()
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
        risk_engine=risk_engine or _StubRiskEngine(),
        position_store=pos,
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
        alpha_registry=alpha_registry,
        kill_switch=kill_switch,
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
        bus.publish(
            replace(
                signal,
                timestamp_ns=quote.timestamp_ns,
                correlation_id=quote.correlation_id,
                sequence=quote.sequence,
            )
        )

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
            f"expected exactly 1 OrderRequest from the bus-fed Signal, got {len(captured)}"
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

    def test_scale_down_at_both_gates_applies_once_for_entry(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        signal = _make_signal(quote, strategy_id="double_scale_alpha")

        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=_DualScaleDownRiskEngine(0.5),
        )
        captured = _capture_orders(bus)
        _signal_from_bus(bus, signal)

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert len(captured) == 1
        assert captured[0].strategy_id == "double_scale_alpha"
        assert captured[0].quantity == 50, (
            f"expected 100-share default target scaled once by 0.5, got {captured[0].quantity}"
        )

    def test_scale_down_at_both_gates_applies_once_for_reverse_entry(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        signal = _make_signal(quote, strategy_id="double_scale_reverse")
        pos = MemoryPositionStore()
        pos.update("AAPL", -100, Decimal("150"))

        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=_DualScaleDownRiskEngine(0.5),
            position_store=pos,
        )
        captured = _capture_orders(bus)
        _signal_from_bus(bus, signal)

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert len(captured) == 2, (
            f"expected reverse path to submit exit + entry, got {captured!r}"
        )
        quantities = sorted(order.quantity for order in captured)
        assert quantities == [50, 100], (
            "expected 100-share short cover plus 50-share new long entry; "
            f"got quantities={quantities!r}"
        )

    def test_reverse_exit_force_flatten_triggers_global_escalation(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        signal = _make_signal(
            quote, strategy_id="reverse_ff_escalate", direction=SignalDirection.LONG
        )
        pos = MemoryPositionStore()
        pos.update("AAPL", -100, Decimal("150"))

        kill = InMemoryKillSwitch()
        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=_ForceFlattenOnFirstCheckOrderEngine(),
            position_store=pos,
            kill_switch=kill,
        )
        captured = _capture_orders(bus)
        _signal_from_bus(bus, signal)

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        orch.boot(_MinimalConfig())
        orch._macro.transition(MacroState.LIVE_TRADING_MODE, trigger="CMD_LIVE_DEPLOY")
        orch._micro.reset(trigger="session_start:test")
        orch._process_tick(quote)

        non_emergency = [o for o in captured if o.strategy_id != "emergency_flatten"]
        assert non_emergency == [], (
            "reverse exit and entry must not submit; only emergency_flatten orders OK"
        )
        assert orch.risk_level == RiskLevel.LOCKED
        assert orch.macro_state == MacroState.RISK_LOCKDOWN
        assert kill.is_active

    def test_reverse_entry_counts_prospective_exposure(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        signal = _make_signal(quote, strategy_id="reverse_exposure_cap")
        pos = MemoryPositionStore()
        pos.update("AAPL", -50, Decimal("150"))

        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=BasicRiskEngine(
                RiskConfig(
                    max_position_per_symbol=100_000,
                    max_gross_exposure_pct=10.0,
                    max_drawdown_pct=99.0,
                    account_equity=Decimal("100000"),
                )
            ),
            position_store=pos,
        )
        captured = _capture_orders(bus)
        _signal_from_bus(bus, signal)

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert len(captured) == 1, (
            "expected only the exit leg when the reverse entry would "
            f"breach the gross-exposure cap, got {captured!r}"
        )
        assert captured[0].quantity == 50

    def test_reverse_entry_post_exit_exposure_uses_live_mark(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        signal = _make_signal(quote, strategy_id="reverse_live_mark")
        pos = MemoryPositionStore()
        pos.update("AAPL", -50, Decimal("100"))

        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=BasicRiskEngine(
                RiskConfig(
                    max_position_per_symbol=100_000,
                    max_gross_exposure_pct=16.0,
                    max_drawdown_pct=99.0,
                    account_equity=Decimal("100000"),
                )
            ),
            position_store=pos,
        )
        captured = _capture_orders(bus)
        _signal_from_bus(bus, signal)

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert len(captured) == 2, (
            "expected the reverse entry to pass when the live-mark-based "
            f"post-exit exposure stays below the cap, got {captured!r}"
        )


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
            clock,
            bus=bus,
            alpha_registry=registry,
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
            clock,
            bus=bus,
            alpha_registry=registry,
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
            _make_quote(),
            strategy_id="pf_alpha",
            layer="PORTFOLIO",
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
            _make_quote(),
            strategy_id="__stop_exit__",
        )
        bus.publish(stop_exit_signal)

        assert orch._signal_buffer == []


class TestMultipleStandaloneSignalsPerTick:
    """One micro-SM order walk per tick; multiple candidates → arbitrator."""

    def test_tie_break_favors_first_arrival_when_scores_equal(
        self,
        caplog: pytest.LogCaptureFixture,
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
                bus.publish(
                    replace(
                        s,
                        timestamp_ns=q.timestamp_ns,
                        correlation_id=q.correlation_id,
                        sequence=q.sequence,
                    )
                )

        bus.subscribe(NBBOQuote, emit_two_signals)  # type: ignore[arg-type]

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert len(captured) == 1, "exactly one OrderRequest per tick (micro-SM constraint)"
        assert captured[0].strategy_id == "alpha_first"
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("standalone SIGNAL candidate(s)" in r.message for r in warnings), (
            "expected a once-per-process WARNING about multiple "
            "standalone Signals; got logs: " + str([r.message for r in warnings])
        )

    def test_arbitration_prefers_higher_composite_over_first_arrival(
        self,
        caplog: pytest.LogCaptureFixture,
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
                bus.publish(
                    replace(
                        s,
                        timestamp_ns=q.timestamp_ns,
                        correlation_id=q.correlation_id,
                        sequence=q.sequence,
                    )
                )

        bus.subscribe(NBBOQuote, emit_two_signals)  # type: ignore[arg-type]

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert len(captured) == 1
        assert captured[0].strategy_id == "strong_second"

    def test_warning_emitted_only_once_per_process(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="feelies.kernel.orchestrator")
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        signal_a = _make_signal(_make_quote(), strategy_id="alpha_first")
        signal_b = _make_signal(_make_quote(), strategy_id="alpha_second")

        orch = _build_orchestrator(clock, bus=bus)

        def emit_two_signals(q: NBBOQuote) -> None:
            for s in (signal_a, signal_b):
                bus.publish(
                    replace(
                        s,
                        timestamp_ns=q.timestamp_ns,
                        correlation_id=q.correlation_id,
                        sequence=q.sequence,
                    )
                )

        bus.subscribe(NBBOQuote, emit_two_signals)  # type: ignore[arg-type]

        _boot_to_backtest(orch)
        for i in range(3):
            q = _make_quote(ts=1000 + i * 1000, seq=i + 1)
            BacktestOrderRouter.on_quote(orch._backend.order_router, q)
            orch._process_tick(q)

        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "standalone SIGNAL candidate(s)" in r.message
        ]
        assert len(warnings) == 1, (
            f"expected exactly 1 WARNING across 3 ticks (once-per-process "
            f"latch), got {len(warnings)}"
        )

    def test_warning_reports_candidate_count_vs_unique_alpha_ids(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.WARNING, logger="feelies.kernel.orchestrator")
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        dup_a = _make_signal(quote, strategy_id="same_alpha")
        dup_b = replace(dup_a, strength=0.9, edge_estimate_bps=8.0)

        orch = _build_orchestrator(clock, bus=bus)

        def emit_two_signals(q: NBBOQuote) -> None:
            for s in (dup_a, dup_b):
                bus.publish(
                    replace(
                        s,
                        timestamp_ns=q.timestamp_ns,
                        correlation_id=q.correlation_id,
                        sequence=q.sequence,
                    )
                )

        bus.subscribe(NBBOQuote, emit_two_signals)  # type: ignore[arg-type]

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        warnings = [
            r.message
            for r in caplog.records
            if r.levelno == logging.WARNING and "standalone SIGNAL candidate(s)" in r.message
        ]
        assert len(warnings) == 1
        assert "2 standalone SIGNAL candidate(s) from 1 alpha id(s)" in warnings[0]
        assert "['same_alpha']" in warnings[0]


def test_trace_sink_records_buffer_evicted_standalone_signals() -> None:
    """Signals left in ``_signal_buffer`` across quote ticks get one trace row.

    Mirrors Trade-driven ``HorizonTick`` paths: bus-visible Signals that were
    buffered but never drained by M4 must not disappear from
    ``signal_order_trace_sink`` when the next tick clears the buffer.

    Signals with ``horizon_seconds == 0`` (non-horizon producers) are treated
    as stale on every inter-tick carry-over — this test exercises that branch.
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


# ── H1 regression tests ───────────────────────────────────────────────


def test_trade_path_fresh_signal_reaches_m4() -> None:
    """Trade-path Signal within its horizon window is NOT evicted — H1 fix.

    A Signal with ``horizon_seconds=30`` emitted by the trade path (between
    quote ticks) must survive the PR-2b-iii freshness partition and reach M4
    when the next quote tick arrives within the 30 s window, producing an
    order rather than a trace eviction row.
    """
    _BASE_NS = 1_000_000_000  # 1 s — large enough for realistic arithmetic
    clock = SimulatedClock(start_ns=_BASE_NS)
    bus = EventBus()
    sink: list[SignalOrderTraceRow] = []
    orch = _build_orchestrator(clock, bus=bus)
    orch._signal_order_trace_sink = sink
    captured = _capture_orders(bus)
    _boot_to_backtest(orch)

    q1 = _make_quote(ts=_BASE_NS, seq=1)
    BacktestOrderRouter.on_quote(orch._backend.order_router, q1)
    orch._process_tick(q1)

    # Simulate a Signal produced by the trade path between q1 and q2.
    trade_signal = replace(
        _make_signal(q1, strategy_id="trade_path_alpha"),
        sequence=99_001,
        timestamp_ns=_BASE_NS,
        horizon_seconds=30,
    )
    bus.publish(trade_signal)

    # q2 arrives 10 s later — well within the 30 s horizon.
    q2 = _make_quote(ts=_BASE_NS + 10_000_000_000, seq=2)
    BacktestOrderRouter.on_quote(orch._backend.order_router, q2)
    orch._process_tick(q2)

    evicted = [
        r
        for r in sink
        if r.signal_sequence == 99_001
        and "signal_buffer_cleared_unprocessed_at_tick_boundary" in r.reasons
    ]
    assert evicted == [], (
        "trade-path Signal within horizon window was evicted instead of "
        f"reaching M4; evicted={evicted!r}"
    )
    assert any(o.strategy_id == "trade_path_alpha" for o in captured), (
        "expected an OrderRequest from the carried-forward trade-path Signal "
        f"but none was produced; orders={captured!r}"
    )


def test_trade_path_fresh_signal_is_drained_only_once() -> None:
    """Carried trade-path Signal is consumed on the next quote only once.

    The H1 fix must preserve an inter-quote Signal until the first quote can
    run M4, but once that happens the same signal sequence must not be
    reconsidered on later quote ticks inside the same horizon window.
    """
    _BASE_NS = 1_000_000_000
    clock = SimulatedClock(start_ns=_BASE_NS)
    bus = EventBus()
    orch = _build_orchestrator(clock, bus=bus)
    captured = _capture_orders(bus)
    _boot_to_backtest(orch)

    q1 = _make_quote(ts=_BASE_NS, seq=1)
    BacktestOrderRouter.on_quote(orch._backend.order_router, q1)
    orch._process_tick(q1)

    trade_signal = replace(
        _make_signal(q1, strategy_id="trade_once_alpha"),
        sequence=99_010,
        timestamp_ns=_BASE_NS,
        horizon_seconds=30,
    )
    bus.publish(trade_signal)

    q2 = _make_quote(ts=_BASE_NS + 10_000_000_000, seq=2)
    BacktestOrderRouter.on_quote(orch._backend.order_router, q2)
    orch._process_tick(q2)

    q3 = _make_quote(ts=_BASE_NS + 20_000_000_000, seq=3)
    BacktestOrderRouter.on_quote(orch._backend.order_router, q3)
    orch._process_tick(q3)

    trade_orders = [o for o in captured if o.strategy_id == "trade_once_alpha"]
    assert len(trade_orders) == 1, (
        f"expected carried trade-path signal to be drained exactly once; orders={trade_orders!r}"
    )


def test_trade_path_expired_signal_is_evicted() -> None:
    """Trade-path Signal past its horizon window IS evicted — H1 fix.

    Complement of ``test_trade_path_fresh_signal_reaches_m4``: a Signal with
    ``horizon_seconds=30`` whose timestamp is more than 30 s before the
    incoming quote must still be discarded and traced, not forwarded to M4.
    """
    _BASE_NS = 1_000_000_000
    clock = SimulatedClock(start_ns=_BASE_NS)
    bus = EventBus()
    sink: list[SignalOrderTraceRow] = []
    orch = _build_orchestrator(clock, bus=bus)
    orch._signal_order_trace_sink = sink
    captured = _capture_orders(bus)
    _boot_to_backtest(orch)

    q1 = _make_quote(ts=_BASE_NS, seq=1)
    BacktestOrderRouter.on_quote(orch._backend.order_router, q1)
    orch._process_tick(q1)

    stale_signal = replace(
        _make_signal(q1, strategy_id="stale_alpha"),
        sequence=99_002,
        timestamp_ns=_BASE_NS,
        horizon_seconds=30,
    )
    bus.publish(stale_signal)

    # q2 arrives 31 s later — one second past the 30 s horizon.
    q2 = _make_quote(ts=_BASE_NS + 31_000_000_000, seq=2)
    BacktestOrderRouter.on_quote(orch._backend.order_router, q2)
    orch._process_tick(q2)

    evicted = [
        r
        for r in sink
        if r.signal_sequence == 99_002
        and "signal_buffer_cleared_unprocessed_at_tick_boundary" in r.reasons
    ]
    assert len(evicted) == 1, (
        f"expected expired Signal to be evicted with trace row, got {evicted!r}"
    )
    assert evicted[0].outcome == "NO_ORDER"
    assert not any(o.strategy_id == "stale_alpha" for o in captured), (
        "expired trade-path Signal must not produce an order"
    )
