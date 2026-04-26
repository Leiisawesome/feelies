"""Tests for the Orchestrator tick-processing pipeline.

Workstream D.2 PR-2b-iv migrated this file off the legacy
``feature_engine`` / ``signal_engine`` ctor stubs.  Tests that used to
inject ``_StubSignalEngine(signal=signal)`` now publish ``Signal``
events on the platform bus through ``_publish_signal_on_quote``;
``_on_bus_signal`` buffers them and the M4 ``SIGNAL_EVALUATE`` drain
walks the existing risk → order → fill pipeline.

Tests for behaviours that no longer exist were dropped:

* ``TestOrchestratorTickFailure`` (legacy signal-engine error → DEGRADED)
  — the bus subscriber cannot raise; the analogous failure mode is now
  exercised via a raising ``RiskEngine``.
* ``TestMultiAlphaB4Gate`` (``_build_net_order`` direct calls) — the
  helper was orphaned together with ``MultiAlphaEvaluator`` (PR-2b-ii)
  and deleted by PR-2b-iv.  The B4 gate still fires through
  ``_check_b4_gate`` on the per-tick walk and is covered by
  ``TestEdgeCostGate``.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    MetricEvent,
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
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.position_store import PositionStore
from feelies.storage.memory_event_log import InMemoryEventLog


# ── Stubs ────────────────────────────────────────────────────────────


class _NoOpMetricCollector:
    def record(self, metric: MetricEvent) -> None:
        pass

    def flush(self) -> None:
        pass


class _StubMarketData:
    """Empty market data source — yields no events."""

    def __init__(self, events=None):
        self._events = events or []

    def events(self):
        return iter(self._events)


class _StubRiskEngine:
    """Risk engine that returns a fixed action for both check methods."""

    def __init__(self, action: RiskAction = RiskAction.ALLOW) -> None:
        self._action = action

    def check_signal(self, signal: Signal, positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=signal.timestamp_ns,
            correlation_id=signal.correlation_id,
            sequence=signal.sequence,
            symbol=signal.symbol,
            action=self._action,
            reason="test",
        )

    def check_order(self, order: OrderRequest, positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=self._action,
            reason="test",
        )


class _RaisingRiskEngine:
    """Risk engine that always raises to test orchestrator error handling.

    Replaces the pre-PR-2b-iv ``_RaisingSignalEngine`` (which exercised
    the now-deleted legacy ``signal_engine`` ctor stub).  The bus-driven
    ``_on_bus_signal`` subscriber cannot raise, but the per-tick risk
    check inside ``_process_tick_inner`` still runs ``check_signal`` —
    making the risk engine the surviving choke-point for "tick raises →
    DEGRADED" coverage (Inv-11: fail-safe degradation rather than
    silent corruption).
    """

    def check_signal(self, signal: Signal, positions: PositionStore) -> RiskVerdict:
        raise RuntimeError("risk engine failure")

    def check_order(self, order: OrderRequest, positions: PositionStore) -> RiskVerdict:
        raise RuntimeError("risk engine failure")


class _ScaleDownToZeroRiskEngine:
    """Risk engine: ALLOW at signal, SCALE_DOWN with near-zero factor at order.

    Used to verify that scale-down to zero suppresses the order
    rather than forcing a min-lot of 1 (Finding 3).
    """

    def check_signal(self, signal: Signal, positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=signal.timestamp_ns,
            correlation_id=signal.correlation_id,
            sequence=signal.sequence,
            symbol=signal.symbol,
            action=RiskAction.ALLOW,
            reason="test",
        )

    def check_order(self, order: OrderRequest, positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=RiskAction.SCALE_DOWN,
            reason="scale to zero test",
            scaling_factor=0.001,
        )


class _MinimalConfig:
    """Minimal Configuration implementation for testing."""

    version = "test-0.1"
    symbols = frozenset({"AAPL"})

    def validate(self) -> None:
        pass

    def snapshot(self):
        return None


class _FailingConfig:
    """Configuration that raises on validate()."""

    version = "test-fail"
    symbols = frozenset({"AAPL"})

    def validate(self) -> None:
        from feelies.core.errors import ConfigurationError
        raise ConfigurationError("bad config")

    def snapshot(self):
        return None


# ── Helpers ──────────────────────────────────────────────────────────


def _make_quote(
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
    quote: NBBOQuote, direction: SignalDirection = SignalDirection.LONG,
) -> Signal:
    return Signal(
        timestamp_ns=quote.timestamp_ns,
        correlation_id=quote.correlation_id,
        sequence=quote.sequence,
        symbol=quote.symbol,
        strategy_id="test_strat",
        direction=direction,
        strength=0.8,
        edge_estimate_bps=5.0,
    )


def _publish_signal_on_quote(bus: EventBus, signal: Signal) -> None:
    """Republish ``signal`` on every ``NBBOQuote`` (mimics HorizonSignalEngine).

    Production: ``HorizonSignalEngine`` subscribes to
    ``HorizonFeatureSnapshot`` and publishes ``Signal`` events as a
    side-effect.  Tests don't bring up the full snapshot pipeline; we
    publish a Signal directly in response to each ``NBBOQuote``, which
    arrives at M1's ``bus.publish(quote)`` and is buffered by
    :py:meth:`Orchestrator._on_bus_signal` before M4 drains.
    """
    def emit(quote: NBBOQuote) -> None:
        bus.publish(replace(
            signal,
            timestamp_ns=quote.timestamp_ns,
            correlation_id=quote.correlation_id,
            sequence=quote.sequence,
        ))
    bus.subscribe(NBBOQuote, emit)  # type: ignore[arg-type]


def _build_orchestrator(
    clock: SimulatedClock,
    *,
    bus: EventBus | None = None,
    risk_engine: Any = None,
    market_data: Any = None,
    position_store: Any = None,
) -> Orchestrator:
    bus = bus if bus is not None else EventBus()
    event_log = InMemoryEventLog()
    pos_store = position_store or MemoryPositionStore()
    bt_router = BacktestOrderRouter(clock=clock)
    backend = ExecutionBackend(
        market_data=market_data or _StubMarketData(),
        order_router=bt_router,
        mode="BACKTEST",
    )
    return Orchestrator(
        clock=clock,
        bus=bus,
        backend=backend,
        risk_engine=risk_engine or _StubRiskEngine(),
        position_store=pos_store,
        event_log=event_log,
        metric_collector=_NoOpMetricCollector(),
    )


def _boot_to_ready(orch: Orchestrator) -> None:
    """Boot orchestrator: INIT → DATA_SYNC → READY."""
    config = _MinimalConfig()
    orch.boot(config)
    assert orch.macro_state == MacroState.READY


def _boot_to_backtest(orch: Orchestrator) -> None:
    """Transition macro SM: INIT → DATA_SYNC → READY → BACKTEST_MODE."""
    _boot_to_ready(orch)
    orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
    orch._micro.reset(trigger="session_start:test")


# ── Tests: Boot lifecycle ─────────────────────────────────────────────


class TestOrchestratorBoot:
    def test_initial_macro_state_is_init(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        assert orch.macro_state == MacroState.INIT

    def test_boot_transitions_to_ready(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        orch.boot(_MinimalConfig())
        assert orch.macro_state == MacroState.READY

    def test_boot_with_config_error_goes_to_shutdown(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        orch.boot(_FailingConfig())
        assert orch.macro_state == MacroState.SHUTDOWN

    def test_boot_micro_starts_in_waiting(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        orch.boot(_MinimalConfig())
        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT


# ── Tests: run_backtest ──────────────────────────────────────────────


class TestOrchestratorRunBacktest:
    def test_run_backtest_returns_to_ready(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        _boot_to_ready(orch)
        orch.run_backtest()
        assert orch.macro_state == MacroState.READY

    def test_run_backtest_with_quotes_processes_ticks(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        quote = _make_quote()
        market_data = _StubMarketData(events=[quote])

        bus = EventBus()
        captured_quotes: list[NBBOQuote] = []
        bus.subscribe(NBBOQuote, captured_quotes.append)

        orch = _build_orchestrator(clock, bus=bus, market_data=market_data)
        _boot_to_ready(orch)
        orch.run_backtest()

        assert len(captured_quotes) == 1, (
            "the single fixture quote must reach the bus exactly once "
            "(M1 publish in _process_tick_inner)"
        )
        assert orch.macro_state == MacroState.READY


# ── Tests: Full tick pipeline ─────────────────────────────────────────


class TestOrchestratorFullPipeline:
    def test_full_tick_m0_to_m10(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        quote = _make_quote()
        signal = _make_signal(quote)

        bus = EventBus()
        bt_router = BacktestOrderRouter(clock=clock)
        bt_router.on_quote(quote)

        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(action=RiskAction.ALLOW),
            position_store=MemoryPositionStore(),
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
        )
        _publish_signal_on_quote(bus, signal)

        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT
        assert orch.macro_state == MacroState.BACKTEST_MODE

    def test_position_updated_after_fill(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        quote = _make_quote()
        signal = _make_signal(quote)

        bus = EventBus()
        position_store = MemoryPositionStore()
        bt_router = BacktestOrderRouter(clock=clock)
        bt_router.on_quote(quote)

        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(action=RiskAction.ALLOW),
            position_store=position_store,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
        )
        _publish_signal_on_quote(bus, signal)

        _boot_to_backtest(orch)
        orch._process_tick(quote)

        pos = position_store.get("AAPL")
        assert pos.quantity != 0


# ── Tests: No signal path ────────────────────────────────────────────


class TestOrchestratorNoSignal:
    def test_no_signal_ends_at_m0(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        _boot_to_backtest(orch)

        quote = _make_quote()
        orch._process_tick(quote)

        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT
        assert orch.macro_state == MacroState.BACKTEST_MODE

    def test_no_signal_leaves_position_unchanged(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        position_store = MemoryPositionStore()
        orch = _build_orchestrator(clock, position_store=position_store)
        _boot_to_backtest(orch)

        orch._process_tick(_make_quote())
        pos = position_store.get("AAPL")
        assert pos.quantity == 0


# ── Tests: Flat signal exit ──────────────────────────────────────────


class TestOrchestratorFlatSignalExit:
    def test_flat_signal_with_position_generates_exit(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        quote = _make_quote()
        flat_signal = _make_signal(quote, direction=SignalDirection.FLAT)

        position_store = MemoryPositionStore()
        position_store.update("AAPL", 100, Decimal("150.00"))

        bus = EventBus()
        bt_router = BacktestOrderRouter(clock=clock)
        bt_router.on_quote(quote)

        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(action=RiskAction.ALLOW),
            position_store=position_store,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
        )
        _publish_signal_on_quote(bus, flat_signal)

        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT
        pos = position_store.get("AAPL")
        assert pos.quantity == 0


# ── Tests: Tick failure → DEGRADED ────────────────────────────────────


class TestOrchestratorTickFailure:
    """A raising RiskEngine (the surviving M5 choke-point post PR-2b-iv)
    must degrade the macro state, mirroring the pre-PR-2b-iv test that
    used a raising signal-engine stub.
    """

    def _build(self) -> Orchestrator:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        signal = _make_signal(_make_quote())
        orch = _build_orchestrator(clock, bus=bus, risk_engine=_RaisingRiskEngine())
        _publish_signal_on_quote(bus, signal)
        _boot_to_backtest(orch)
        return orch

    def test_risk_engine_error_degrades_macro(self) -> None:
        orch = self._build()
        orch._process_tick(_make_quote())
        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT
        assert orch.macro_state == MacroState.DEGRADED

    def test_micro_resets_to_waiting_on_failure(self) -> None:
        orch = self._build()
        orch._process_tick(_make_quote())
        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT


# ── Tests: Risk rejection ────────────────────────────────────────────


class TestOrchestratorRiskReject:
    def test_risk_reject_ends_at_m0_no_order(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        signal = _make_signal(quote)

        position_store = MemoryPositionStore()

        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=_StubRiskEngine(action=RiskAction.REJECT),
            position_store=position_store,
        )
        _publish_signal_on_quote(bus, signal)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT
        assert orch.macro_state == MacroState.BACKTEST_MODE
        assert position_store.get("AAPL").quantity == 0


# ── Tests: Shutdown ──────────────────────────────────────────────────


class TestOrchestratorShutdown:
    def test_shutdown_from_ready(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        _boot_to_ready(orch)
        orch.shutdown()
        assert orch.macro_state == MacroState.SHUTDOWN

    def test_shutdown_from_degraded(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        signal = _make_signal(_make_quote())
        orch = _build_orchestrator(clock, bus=bus, risk_engine=_RaisingRiskEngine())
        _publish_signal_on_quote(bus, signal)
        _boot_to_backtest(orch)
        orch._process_tick(_make_quote())
        assert orch.macro_state == MacroState.DEGRADED

        orch.shutdown()
        assert orch.macro_state == MacroState.SHUTDOWN


# ── Tests: Recovery from degraded ────────────────────────────────────


class TestOrchestratorRecovery:
    def test_recover_from_degraded_to_ready(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        signal = _make_signal(_make_quote())
        orch = _build_orchestrator(clock, bus=bus, risk_engine=_RaisingRiskEngine())
        _publish_signal_on_quote(bus, signal)
        _boot_to_backtest(orch)
        orch._process_tick(_make_quote())
        assert orch.macro_state == MacroState.DEGRADED

        result = orch.recover_from_degraded()
        assert result is True
        assert orch.macro_state == MacroState.READY


# ── Tests: Halt from trading mode ────────────────────────────────────


class TestOrchestratorHalt:
    def test_halt_from_backtest(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        _boot_to_backtest(orch)
        assert orch.macro_state == MacroState.BACKTEST_MODE

        orch.halt()
        assert orch.macro_state == MacroState.READY

    def test_halt_noop_when_not_trading(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        _boot_to_ready(orch)
        orch.halt()
        assert orch.macro_state == MacroState.READY


# ── Tests: Multiple ticks ────────────────────────────────────────────


class TestOrchestratorMultipleTicks:
    def test_two_consecutive_no_signal_ticks(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        _boot_to_backtest(orch)

        orch._process_tick(_make_quote(ts=1000, seq=1))
        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT

        orch._process_tick(_make_quote(ts=2000, seq=2))
        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT
        assert orch.macro_state == MacroState.BACKTEST_MODE


# ── Tests: Scale-down to zero suppression (Finding 3) ────────────────


class TestScaleDownToZeroSuppression:
    """When SCALE_DOWN yields quantity 0, the order must be suppressed.

    Before the fix, max(1, round(...)) forced a min-lot of 1 share,
    violating Inv-11 (fail-safe: safety controls only tighten).
    """

    def test_m6_scale_down_to_zero_suppresses_order(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        signal = _make_signal(quote)

        position_store = MemoryPositionStore()
        bt_router = BacktestOrderRouter(clock=clock)
        bt_router.on_quote(quote)

        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_ScaleDownToZeroRiskEngine(),
            position_store=position_store,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
        )
        _publish_signal_on_quote(bus, signal)

        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT
        assert orch.macro_state == MacroState.BACKTEST_MODE
        assert position_store.get("AAPL").quantity == 0


# ── B4: edge-cost gate ────────────────────────────────────────────────


def _make_signal_with_edge(quote: NBBOQuote, edge_bps: float) -> Signal:
    """Signal with explicit edge_estimate_bps for B4 gate testing."""
    return Signal(
        timestamp_ns=quote.timestamp_ns,
        correlation_id=quote.correlation_id,
        sequence=quote.sequence,
        symbol=quote.symbol,
        strategy_id="test_strat",
        direction=SignalDirection.LONG,
        strength=0.8,
        edge_estimate_bps=edge_bps,
    )


class TestEdgeCostGate:
    """B4: orders suppressed when edge < ratio × round-trip cost."""

    def _build_gated_orchestrator(
        self,
        clock: SimulatedClock,
        signal: Signal,
        edge_cost_ratio: float = 2.0,
    ) -> Orchestrator:
        from feelies.execution.cost_model import (
            DefaultCostModel,
            DefaultCostModelConfig,
        )
        bus = EventBus()
        event_log = InMemoryEventLog()
        pos_store = MemoryPositionStore()
        bt_router = BacktestOrderRouter(clock=clock)
        backend = ExecutionBackend(
            market_data=_StubMarketData(),
            order_router=bt_router,
            mode="BACKTEST",
        )
        cost_model = DefaultCostModel(DefaultCostModelConfig())
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=backend,
            risk_engine=_StubRiskEngine(),
            position_store=pos_store,
            event_log=event_log,
            metric_collector=_NoOpMetricCollector(),
            cost_model=cost_model,
        )
        _publish_signal_on_quote(bus, signal)
        orch._signal_min_edge_cost_ratio = edge_cost_ratio
        _boot_to_backtest(orch)
        return orch

    def test_order_suppressed_when_edge_below_threshold(self) -> None:
        """Edge ≈ 0 bps with ratio 2.0 → order should be gated out."""
        clock = SimulatedClock(start_ns=1000)
        quote = _make_quote(bid="99.00", ask="101.00")  # wide spread → high cost bps
        signal = _make_signal_with_edge(quote, edge_bps=0.0)

        orch = self._build_gated_orchestrator(clock, signal, edge_cost_ratio=2.0)
        orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
        orch._process_tick(quote)

        pos = orch._positions.get("AAPL")
        assert pos.quantity == 0

    def test_order_passes_when_edge_above_threshold(self) -> None:
        """Edge >> round-trip cost → order not suppressed."""
        clock = SimulatedClock(start_ns=1000)
        quote = _make_quote(bid="99.80", ask="100.20")  # tight spread
        signal = _make_signal_with_edge(quote, edge_bps=10_000.0)

        orch = self._build_gated_orchestrator(clock, signal, edge_cost_ratio=2.0)
        orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
        orch._process_tick(quote)

        pos = orch._positions.get("AAPL")
        assert pos.quantity != 0  # order was placed and filled

    def test_gate_disabled_when_ratio_is_zero(self) -> None:
        """ratio=0.0 disables the gate — even zero-edge signals produce orders."""
        clock = SimulatedClock(start_ns=1000)
        quote = _make_quote(bid="99.00", ask="101.00")
        signal = _make_signal_with_edge(quote, edge_bps=0.0)

        orch = self._build_gated_orchestrator(clock, signal, edge_cost_ratio=0.0)
        orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
        orch._process_tick(quote)

        pos = orch._positions.get("AAPL")
        assert pos.quantity != 0  # gate disabled, order allowed


# ── F1: Resting-order guard placed AFTER signal/risk evaluation ───────────


class TestRestingOrderGuardAfterRisk:
    """F1: Signal + risk always run even with a pending limit order resting.

    Only order *submission* is suppressed by the guard; EXIT intent bypasses it.
    """

    def _build_passive_orch(
        self,
        clock: SimulatedClock,
        signal: Signal,
        position_store: MemoryPositionStore | None = None,
    ) -> tuple[Orchestrator, EventBus]:
        bus = EventBus()
        pos_store = position_store or MemoryPositionStore()
        bt_router = BacktestOrderRouter(clock=clock)
        backend = ExecutionBackend(
            market_data=_StubMarketData(),
            order_router=bt_router,
            mode="BACKTEST",
        )
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=backend,
            risk_engine=_StubRiskEngine(action=RiskAction.ALLOW),
            position_store=pos_store,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
        )
        _publish_signal_on_quote(bus, signal)
        orch._use_passive_entries = True
        return orch, bus

    def _seed_pending_order(
        self,
        orch: Orchestrator,
        order_id: str,
        clock: SimulatedClock,
    ) -> None:
        """Inject a non-terminal AAPL limit order into the orchestrator's tracker."""
        from feelies.core.events import OrderType, Side

        fake_order = OrderRequest(
            timestamp_ns=clock.now_ns(),
            correlation_id="fake-cid",
            sequence=999,
            order_id=order_id,
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=50,
            limit_price=Decimal("149.50"),
            strategy_id="test_strat",
        )
        from feelies.core.events import Side as _Side
        orch._track_order(fake_order.order_id, _Side.BUY, fake_order)

    def test_risk_verdict_published_despite_resting_entry_order(self) -> None:
        """RiskVerdict appears on the bus even when the resting-order guard fires."""
        clock = SimulatedClock(start_ns=1000)
        quote = _make_quote()
        signal = _make_signal(quote, direction=SignalDirection.LONG)
        orch, bus = self._build_passive_orch(clock, signal)
        _boot_to_backtest(orch)
        self._seed_pending_order(orch, "fake-order-001", clock)

        verdicts: list[RiskVerdict] = []
        new_orders: list[OrderRequest] = []
        bus.subscribe(RiskVerdict, verdicts.append)
        bus.subscribe(OrderRequest, new_orders.append)

        orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
        orch._process_tick(quote)

        # Signal evaluation ran → signal-level risk verdict was published.
        assert len(verdicts) >= 1
        assert verdicts[0].action == RiskAction.ALLOW
        # Guard suppressed ALL new order submission.
        assert not new_orders

    def test_exit_bypasses_resting_order_guard(self) -> None:
        """EXIT intent ignores the resting-order guard and closes the position."""
        clock = SimulatedClock(start_ns=1000)
        quote = _make_quote()
        flat_signal = _make_signal(quote, direction=SignalDirection.FLAT)

        position_store = MemoryPositionStore()
        position_store.update("AAPL", 50, Decimal("150.00"))
        orch, _ = self._build_passive_orch(clock, flat_signal, position_store)
        _boot_to_backtest(orch)
        self._seed_pending_order(orch, "fake-order-002", clock)

        orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
        orch._process_tick(quote)

        # EXIT bypasses guard → position is fully closed.
        assert position_store.get("AAPL").quantity == 0


# ── F2: EXIT bypasses min_order_shares gate ──────────────────────────────


class TestExitBypassesMinOrderShares:
    """F2: EXIT intent is never gated by the min_order_shares threshold."""

    def test_exit_below_min_shares_still_executes(self) -> None:
        """50-share EXIT proceeds even when min_order_shares is set to 1000."""
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        flat_signal = _make_signal(quote, direction=SignalDirection.FLAT)

        position_store = MemoryPositionStore()
        position_store.update("AAPL", 50, Decimal("150.00"))

        bt_router = BacktestOrderRouter(clock=clock)
        bt_router.on_quote(quote)
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(action=RiskAction.ALLOW),
            position_store=position_store,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
        )
        _publish_signal_on_quote(bus, flat_signal)
        _boot_to_backtest(orch)
        orch._min_order_shares = 1000  # threshold far above exit qty of 50

        orch._process_tick(quote)

        assert position_store.get("AAPL").quantity == 0


# ── F3: EXIT bypasses B4 edge-cost gate ──────────────────────────────────


class TestExitBypassesEdgeCostGate:
    """F3: EXIT with zero edge_estimate_bps still executes when B4 is active."""

    def test_exit_with_zero_edge_closes_position(self) -> None:
        """FLAT signal with edge=0 closes a long position despite B4 ratio=2."""
        from feelies.execution.cost_model import (
            DefaultCostModel,
            DefaultCostModelConfig,
        )

        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        # Wide spread → any ENTRY with low edge would be gated out.
        quote = _make_quote(bid="99.00", ask="101.00")
        flat_signal = Signal(
            timestamp_ns=quote.timestamp_ns,
            correlation_id=quote.correlation_id,
            sequence=quote.sequence,
            symbol=quote.symbol,
            strategy_id="test_strat",
            direction=SignalDirection.FLAT,
            strength=0.8,
            edge_estimate_bps=0.0,  # zero edge — would gate an ENTRY
        )

        position_store = MemoryPositionStore()
        position_store.update("AAPL", 50, Decimal("150.00"))

        bt_router = BacktestOrderRouter(clock=clock)
        bt_router.on_quote(quote)
        cost_model = DefaultCostModel(DefaultCostModelConfig())
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(action=RiskAction.ALLOW),
            position_store=position_store,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
            cost_model=cost_model,
        )
        _publish_signal_on_quote(bus, flat_signal)
        orch._signal_min_edge_cost_ratio = 2.0
        _boot_to_backtest(orch)

        orch._process_tick(quote)

        # EXIT must bypass B4 gate → position fully closed.
        assert position_store.get("AAPL").quantity == 0
