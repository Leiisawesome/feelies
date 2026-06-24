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

from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.errors import OrchestratorPipelineAbortError, SessionEntryBlockedError
from feelies.core.state_machine import TransitionRecord
from feelies.core.events import (
    Alert,
    Event,
    MetricEvent,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    PositionUpdate,
    RiskAction,
    RiskVerdict,
    Side,
    Signal,
    SignalDirection,
    StateTransition,
    SymbolHalted,
    Trade,
)
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import ZeroCostModel
from feelies.execution.intent import OrderIntent, TradingIntent
from feelies.execution.order_state import OrderState
from feelies.execution.regulatory.borrow_availability import BorrowTier
from feelies.kernel.macro import MacroState
from feelies.kernel.micro import MicroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.monitoring.in_memory import InMemoryKillSwitch
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.position_store import Position
from feelies.portfolio.position_store import PositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.risk.escalation import RiskLevel
from feelies.storage.memory_event_log import InMemoryEventLog


# ── Stubs ────────────────────────────────────────────────────────────


class _NoOpMetricCollector:
    def record(self, metric: MetricEvent) -> None:
        pass

    def flush(self) -> None:
        pass


class _CountingReplayLog:
    """Event log stub that exposes how far calibration iterated."""

    def __init__(self, events: Sequence[Event]) -> None:
        self._events = tuple(events)
        self.events_yielded = 0

    def append(self, event: Event) -> None:
        raise NotImplementedError

    def append_batch(self, events: Sequence[Event]) -> None:
        raise NotImplementedError

    def replace_events(self, _events: Sequence[Event]) -> None:
        raise NotImplementedError

    def replay(
        self,
        start_sequence: int = 0,
        end_sequence: int | None = None,
    ) -> Iterator[Event]:
        del start_sequence, end_sequence
        for event in self._events:
            self.events_yielded += 1
            yield event

    def last_sequence(self) -> int:
        return self._events[-1].sequence if self._events else -1


class _StubRegimeEngine:
    def __init__(self) -> None:
        self.calibrated = False
        self.calibration_count: int | None = None

    @property
    def state_names(self) -> Sequence[str]:
        return ("normal",)

    @property
    def n_states(self) -> int:
        return 1

    def calibrate(self, quotes: Sequence[NBBOQuote]) -> bool:
        self.calibrated = True
        self.calibration_count = len(quotes)
        return True

    def posterior(self, quote: NBBOQuote) -> list[float]:
        return [1.0]

    def current_state(self, symbol: str) -> list[float] | None:
        return None

    def reset(self, symbol: str) -> None:
        pass

    def checkpoint(self) -> bytes:
        return b"{}"

    def restore(self, data: bytes) -> None:
        pass


class _StubMarketData:
    """Empty market data source — yields no events."""

    def __init__(self, events=None):
        self._events = events or []

    def events(self):
        return iter(self._events)


class _SnapshotStrategyPositionStore:
    """Minimal strategy store whose get() returns detached Position copies."""

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {
            "alpha_a": Position(symbol="AAPL", quantity=100),
            "alpha_b": Position(symbol="AAPL", quantity=100),
            "alpha_c": Position(symbol="AAPL", quantity=100),
            "alpha_d": Position(symbol="AAPL", quantity=1),
        }
        self.debit_fee_calls: list[tuple[str, str, Decimal]] = []

    def strategy_ids(self) -> tuple[str, ...]:
        return ("alpha_a", "alpha_b", "alpha_c", "alpha_d")

    def get(self, strategy_id: str, symbol: str) -> Position:
        pos = self._positions.get(strategy_id)
        if pos is None or pos.symbol != symbol:
            return Position(symbol=symbol)
        return Position(
            symbol=pos.symbol,
            quantity=pos.quantity,
            avg_entry_price=pos.avg_entry_price,
            realized_pnl=pos.realized_pnl,
            unrealized_pnl=pos.unrealized_pnl,
            cumulative_fees=pos.cumulative_fees,
        )

    def update(
        self,
        strategy_id: str,
        symbol: str,
        quantity_delta: int,
        fill_price: Decimal,
        fees: Decimal = Decimal("0"),
        timestamp_ns: int | None = None,
    ) -> Position:
        pos = self._positions.setdefault(strategy_id, Position(symbol=symbol))
        pos.quantity += quantity_delta
        pos.avg_entry_price = fill_price
        pos.cumulative_fees += fees
        return pos

    def debit_fees(self, strategy_id: str, symbol: str, fees: Decimal) -> None:
        self.debit_fee_calls.append((strategy_id, symbol, fees))
        pos = self._positions.setdefault(strategy_id, Position(symbol=symbol))
        pos.cumulative_fees += fees


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


class _CountingHwmRiskEngine(_StubRiskEngine):
    def __init__(self) -> None:
        super().__init__(RiskAction.ALLOW)
        self.refresh_calls: list[PositionStore] = []

    def refresh_high_water_mark(self, positions: PositionStore) -> None:
        self.refresh_calls.append(positions)


class _NonCallableHwmRiskEngine(_StubRiskEngine):
    refresh_high_water_mark = object()


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
    quote: NBBOQuote,
    direction: SignalDirection = SignalDirection.LONG,
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
        bus.publish(
            replace(
                signal,
                timestamp_ns=quote.timestamp_ns,
                correlation_id=quote.correlation_id,
                sequence=quote.sequence,
            )
        )

    bus.subscribe(NBBOQuote, emit)  # type: ignore[arg-type]


class _OrderRouterNoCancel:
    """Minimal router stub without ``cancel_order`` (cancel hygiene tests)."""

    def poll_acks(self) -> list[OrderAck]:
        return []


def _build_orchestrator(
    clock: SimulatedClock,
    *,
    bus: EventBus | None = None,
    risk_engine: Any = None,
    market_data: Any = None,
    position_store: Any = None,
    strategy_positions: Any = None,
    kill_switch: Any = None,
    order_router: Any = None,
) -> Orchestrator:
    bus = bus if bus is not None else EventBus()
    event_log = InMemoryEventLog()
    pos_store = position_store or MemoryPositionStore()
    router = (
        order_router
        if order_router is not None
        else BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
    )
    backend = ExecutionBackend(
        market_data=market_data or _StubMarketData(),
        order_router=router,
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
        strategy_positions=strategy_positions,
        kill_switch=kill_switch,
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

    def test_regime_calibration_does_not_scan_suffix_for_total_count(
        self,
    ) -> None:
        clock = SimulatedClock(start_ns=1000)
        quotes = tuple(_make_quote(ts=1000 + i, seq=i + 1) for i in range(100))
        event_log = _CountingReplayLog(quotes)
        regime_engine = _StubRegimeEngine()
        bt_router = BacktestOrderRouter(clock=clock)
        backend = ExecutionBackend(
            market_data=_StubMarketData(),
            order_router=bt_router,
            mode="BACKTEST",
        )
        orch = Orchestrator(
            clock=clock,
            bus=EventBus(),
            backend=backend,
            risk_engine=_StubRiskEngine(),
            position_store=MemoryPositionStore(),
            event_log=event_log,
            metric_collector=_NoOpMetricCollector(),
            regime_engine=regime_engine,
        )
        orch._regime_calibration_max_quotes = 3

        orch._calibrate_regime_engine()

        assert regime_engine.calibration_count == 3
        assert event_log.events_yielded == 3

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
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
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

    def test_mark_only_tick_refreshes_risk_high_water_mark(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        rally_quote = _make_quote(ts=1000, bid="119.50", ask="120.50", seq=1)
        drawdown_quote = _make_quote(ts=2000, bid="99.50", ask="100.50", seq=2)
        position_store = MemoryPositionStore()
        position_store.update("AAPL", 100, Decimal("100"))
        risk_engine = BasicRiskEngine(
            RiskConfig(
                max_position_per_symbol=100_000,
                max_gross_exposure_pct=100.0,
                max_drawdown_pct=1.0,
                account_equity=Decimal("100000"),
            )
        )

        bus = EventBus()
        verdicts: list[RiskVerdict] = []
        bus.subscribe(RiskVerdict, verdicts.append)

        def emit_second_quote_signal(quote: NBBOQuote) -> None:
            if quote.sequence == drawdown_quote.sequence:
                bus.publish(_make_signal(quote, direction=SignalDirection.SHORT))

        bus.subscribe(NBBOQuote, emit_second_quote_signal)

        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=risk_engine,
            position_store=position_store,
        )
        _boot_to_backtest(orch)

        orch._process_tick(rally_quote)
        orch._process_tick(drawdown_quote)

        assert verdicts[-1].action == RiskAction.FORCE_FLATTEN
        assert "drawdown" in verdicts[-1].reason

    def test_mark_only_tick_refreshes_risk_high_water_mark_once(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        position_store = MemoryPositionStore()
        risk_engine = _CountingHwmRiskEngine()
        orch = _build_orchestrator(
            clock,
            risk_engine=risk_engine,
            position_store=position_store,
        )
        _boot_to_backtest(orch)

        orch._process_tick(_make_quote())

        assert risk_engine.refresh_calls == [position_store]

    def test_non_callable_hwm_hook_is_skipped(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(
            clock,
            risk_engine=_NonCallableHwmRiskEngine(),
        )
        _boot_to_backtest(orch)

        orch._process_tick(_make_quote())

        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT
        assert orch.macro_state == MacroState.BACKTEST_MODE

    def test_position_updated_after_fill(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        quote = _make_quote()
        signal = _make_signal(quote)

        bus = EventBus()
        position_store = MemoryPositionStore()
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
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

    def test_fill_records_opened_at_timestamp(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        quote = _make_quote()
        signal = _make_signal(quote)

        bus = EventBus()
        position_store = MemoryPositionStore()
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
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

        assert position_store.opened_at_ns("AAPL") == quote.timestamp_ns

    def test_filled_position_update_uses_ack_timestamp(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        position_store = MemoryPositionStore()
        updates: list[PositionUpdate] = []
        bus.subscribe(PositionUpdate, updates.append)

        orch = _build_orchestrator(clock, bus=bus, position_store=position_store)
        order = OrderRequest(
            timestamp_ns=clock.now_ns(),
            correlation_id="fill-cid",
            sequence=2,
            order_id="filled-order",
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            strategy_id="alpha_1",
        )
        orch._track_order(order.order_id, Side.BUY, order)

        orch._reconcile_fills(
            [
                OrderAck(
                    timestamp_ns=2000,
                    correlation_id="fill-cid",
                    sequence=2,
                    order_id=order.order_id,
                    symbol="AAPL",
                    status=OrderAckStatus.FILLED,
                    filled_quantity=10,
                    fill_price=Decimal("150.00"),
                    fees=Decimal("0.10"),
                ),
            ],
            correlation_id="tick-cid",
        )

        assert len(updates) == 1
        assert updates[0].timestamp_ns == 2000


class TestOrchestratorFillReconcileGuards:
    def test_reconcile_ignores_fill_fields_on_rejected_ack(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)
        position_store = MemoryPositionStore()
        orch = _build_orchestrator(clock, bus=bus, position_store=position_store)
        order = OrderRequest(
            timestamp_ns=clock.now_ns(),
            correlation_id="c1",
            sequence=1,
            order_id="ord-rej-fill",
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            strategy_id="a",
        )
        orch._track_order(order.order_id, order.side, order)
        orch._transition_order(
            order.order_id,
            OrderState.SUBMITTED,
            "submitted",
            correlation_id=order.correlation_id,
        )

        orch._reconcile_fills(
            [
                OrderAck(
                    timestamp_ns=1100,
                    correlation_id="c1",
                    sequence=1,
                    order_id=order.order_id,
                    symbol="AAPL",
                    status=OrderAckStatus.REJECTED,
                    filled_quantity=10,
                    fill_price=Decimal("150"),
                    reason="simulated",
                ),
            ],
            correlation_id="tick-cid",
        )

        assert position_store.get("AAPL").quantity == 0
        assert any(a.alert_name == "fill_payload_inconsistent_with_ack_status" for a in alerts)

    def test_reconcile_alerts_on_filled_missing_price(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)
        position_store = MemoryPositionStore()
        orch = _build_orchestrator(clock, bus=bus, position_store=position_store)
        order = OrderRequest(
            timestamp_ns=clock.now_ns(),
            correlation_id="c2",
            sequence=1,
            order_id="ord-bad-fill",
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            strategy_id="a",
        )
        orch._track_order(order.order_id, order.side, order)
        orch._transition_order(
            order.order_id,
            OrderState.SUBMITTED,
            "submitted",
            correlation_id=order.correlation_id,
        )

        orch._reconcile_fills(
            [
                OrderAck(
                    timestamp_ns=1200,
                    correlation_id="c2",
                    sequence=1,
                    order_id=order.order_id,
                    symbol="AAPL",
                    status=OrderAckStatus.FILLED,
                    filled_quantity=10,
                    fill_price=None,
                ),
            ],
            correlation_id="tick-cid",
        )

        assert position_store.get("AAPL").quantity == 0
        assert any(a.alert_name == "fill_ack_missing_price_or_quantity" for a in alerts)

    def test_duplicate_filled_ack_emits_warning_alert(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)
        orch = _build_orchestrator(clock, bus=bus)
        order = OrderRequest(
            timestamp_ns=clock.now_ns(),
            correlation_id="c3",
            sequence=1,
            order_id="ord-dup-fill",
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            strategy_id="a",
        )
        orch._track_order(order.order_id, order.side, order)
        orch._transition_order(
            order.order_id,
            OrderState.SUBMITTED,
            "submitted",
            correlation_id=order.correlation_id,
        )
        orch._apply_ack_to_order(
            OrderAck(
                timestamp_ns=1300,
                correlation_id="c3",
                sequence=1,
                order_id=order.order_id,
                symbol="AAPL",
                status=OrderAckStatus.ACKNOWLEDGED,
            )
        )
        orch._apply_ack_to_order(
            OrderAck(
                timestamp_ns=1310,
                correlation_id="c3",
                sequence=2,
                order_id=order.order_id,
                symbol="AAPL",
                status=OrderAckStatus.FILLED,
                filled_quantity=10,
                fill_price=Decimal("150"),
            )
        )
        orch._apply_ack_to_order(
            OrderAck(
                timestamp_ns=1320,
                correlation_id="c3",
                sequence=3,
                order_id=order.order_id,
                symbol="AAPL",
                status=OrderAckStatus.FILLED,
                filled_quantity=10,
                fill_price=Decimal("150"),
            )
        )

        assert any(a.alert_name == "duplicate_terminal_fill_ack" for a in alerts)

    def test_emergency_flatten_poll_failure_force_terminals_order(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)

        class _PollFailsRouter(BacktestOrderRouter):
            def poll_acks(self):  # type: ignore[override]
                raise RuntimeError("poll boom")

        quote = _make_quote()
        router = _PollFailsRouter(clock=clock)
        router.on_quote(quote)

        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(),
            position_store=MemoryPositionStore(),
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
        )
        _boot_to_backtest(orch)
        orch._positions.update("AAPL", 100, Decimal("150.00"))

        failures, residual = orch._emergency_flatten_all("esc-cid")

        assert "AAPL" in failures
        assert residual["AAPL"] == 100
        assert any(a.alert_name == "order_pipeline_exception" for a in alerts)
        assert not any(
            sm.state == OrderState.SUBMITTED for sm, _, _ in orch._active_orders.values()
        )

    def test_cancel_order_without_router_resolves_to_cancelled(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)
        orch = _build_orchestrator(
            clock,
            bus=bus,
            order_router=_OrderRouterNoCancel(),
        )
        order = OrderRequest(
            timestamp_ns=clock.now_ns(),
            correlation_id="cc",
            sequence=1,
            order_id="ord-cancel-local",
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            strategy_id="a",
        )
        orch._track_order(order.order_id, order.side, order)
        orch._transition_order(
            order.order_id,
            OrderState.SUBMITTED,
            "submitted",
            correlation_id=order.correlation_id,
        )
        orch._apply_ack_to_order(
            OrderAck(
                timestamp_ns=clock.now_ns(),
                correlation_id="cc",
                sequence=1,
                order_id=order.order_id,
                symbol="AAPL",
                status=OrderAckStatus.ACKNOWLEDGED,
            )
        )

        assert orch.cancel_order(order.order_id) is True
        assert order.order_id not in orch._active_orders
        assert any(a.alert_name == "cancel_order_router_unsupported" for a in alerts)

    def test_shutdown_resolves_cancel_requested(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)
        orch = _build_orchestrator(clock, bus=bus)
        order = OrderRequest(
            timestamp_ns=clock.now_ns(),
            correlation_id="sd",
            sequence=1,
            order_id="ord-shut-cr",
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
            strategy_id="a",
        )
        orch._track_order(order.order_id, order.side, order)
        orch._transition_order(
            order.order_id,
            OrderState.SUBMITTED,
            "submitted",
            correlation_id=order.correlation_id,
        )
        orch._apply_ack_to_order(
            OrderAck(
                timestamp_ns=clock.now_ns(),
                correlation_id="sd",
                sequence=1,
                order_id=order.order_id,
                symbol="AAPL",
                status=OrderAckStatus.ACKNOWLEDGED,
            )
        )
        sm = orch._active_orders[order.order_id][0]
        sm.transition(
            OrderState.CANCEL_REQUESTED,
            trigger="manual_test",
            correlation_id=order.correlation_id,
        )

        orch.shutdown()

        assert order.order_id not in orch._active_orders
        assert not any(a.alert_name == "pending_orders_at_shutdown" for a in alerts)


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
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
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


class TestStopExitSignalMetadata:
    def test_stop_exit_signal_uses_signal_sequence_family(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        published_signals: list[Signal] = []
        bus.subscribe(Signal, published_signals.append)

        position_store = MemoryPositionStore()
        position_store.update("AAPL", 100, Decimal("150.00"))

        orch = _build_orchestrator(clock, bus=bus, position_store=position_store)
        orch._stop_loss_per_share = 1.0
        _boot_to_backtest(orch)

        quote = _make_quote(ts=2000, bid="147.50", ask="148.50", seq=7)

        orch._process_tick(quote)

        stop_signals = [
            signal for signal in published_signals if signal.strategy_id == "__stop_exit__"
        ]
        assert len(stop_signals) == 1
        stop_signal = stop_signals[0]
        assert stop_signal.correlation_id == quote.correlation_id
        assert stop_signal.sequence == 0
        assert stop_signal.sequence != quote.sequence
        assert stop_signal.source_layer == "SIGNAL"
        assert stop_signal.layer == "SIGNAL"
        assert stop_signal.regime_gate_state == "N/A"


class TestForcedExitReasonClassification:
    """Audit P1 (2026-06-20): forced MARKET exits must carry the canonical
    ``OrderRequest.reason`` so the fill model classifies them for panic
    slippage / depth depletion (``STOP_EXIT_REASONS``).  A *scheduled*
    session flatten is an orderly unwind, not an adverse-move panic, and
    must NOT be surcharged.
    """

    @staticmethod
    def _exit_intent(strategy_id: str) -> OrderIntent:
        signal = Signal(
            timestamp_ns=2000,
            correlation_id="AAPL:2000:1",
            sequence=0,
            source_layer="SIGNAL",
            symbol="AAPL",
            strategy_id=strategy_id,
            direction=SignalDirection.FLAT,
            strength=0.0,
            edge_estimate_bps=0.0,
        )
        return OrderIntent(
            intent=TradingIntent.EXIT,
            symbol="AAPL",
            strategy_id=strategy_id,
            target_quantity=100,
            current_quantity=100,
            signal=signal,
        )

    def test_only_stop_exit_intent_is_tagged_as_panic(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        verdict = RiskVerdict(
            timestamp_ns=2000,
            correlation_id="AAPL:2000:1",
            sequence=1,
            symbol="AAPL",
            action=RiskAction.ALLOW,
            reason="ok",
        )

        stop_order = orch._build_order_from_intent(
            self._exit_intent("__stop_exit__"), verdict, "AAPL:2000:1"
        )
        session_order = orch._build_order_from_intent(
            self._exit_intent("__session_flat__"), verdict, "AAPL:2000:1"
        )
        alpha_order = orch._build_order_from_intent(
            self._exit_intent("test_strat"), verdict, "AAPL:2000:1"
        )

        assert stop_order is not None and stop_order.reason == "STOP_EXIT"
        # Scheduled session flatten and ordinary alpha exit are not panics.
        assert session_order is not None and session_order.reason == ""
        assert alpha_order is not None and alpha_order.reason == ""

    def test_stop_trigger_tags_order_and_journals_reason(self) -> None:
        from feelies.storage.memory_trade_journal import InMemoryTradeJournal

        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        orders: list[OrderRequest] = []
        bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]

        position_store = MemoryPositionStore()
        position_store.update("AAPL", 100, Decimal("150.00"))

        orch = _build_orchestrator(clock, bus=bus, position_store=position_store)
        journal = InMemoryTradeJournal()
        orch._trade_journal = journal
        orch._stop_loss_per_share = 1.0
        _boot_to_backtest(orch)

        quote = _make_quote(ts=2000, bid="147.50", ask="148.50", seq=7)
        orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
        orch._process_tick(quote)

        stop_orders = [o for o in orders if o.strategy_id == "__stop_exit__"]
        assert len(stop_orders) == 1
        assert stop_orders[0].reason == "STOP_EXIT"

        # Inv-13 provenance: the forced-exit reason reaches the journal.
        recorded = list(journal.query(strategy_id="__stop_exit__"))
        assert len(recorded) == 1
        assert recorded[0].metadata["order_reason"] == "STOP_EXIT"
        assert "order_source_layer" in recorded[0].metadata

    def test_emergency_flatten_tags_force_flatten_reason(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        orders: list[OrderRequest] = []
        bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]

        orch = _build_orchestrator(clock, bus=bus, position_store=MemoryPositionStore())
        _boot_to_backtest(orch)
        orch._positions.update("AAPL", 100, Decimal("150.00"))
        orch._backend.order_router.on_quote(_make_quote(ts=2000, seq=7))  # type: ignore[attr-defined]

        orch._emergency_flatten_all("esc-cid")

        flat_orders = [o for o in orders if o.strategy_id == "emergency_flatten"]
        assert len(flat_orders) == 1
        assert flat_orders[0].reason == "FORCE_FLATTEN"


class TestCancelFeeAccounting:
    def test_cancel_fee_without_fill_creates_fee_only_position_and_update(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        position_store = MemoryPositionStore()
        updates: list[PositionUpdate] = []
        bus.subscribe(PositionUpdate, updates.append)

        orch = _build_orchestrator(clock, bus=bus, position_store=position_store)

        orch._reconcile_fills(
            [
                OrderAck(
                    timestamp_ns=2000,
                    correlation_id="cancel-cid",
                    sequence=2,
                    order_id="never-filled",
                    symbol="AAPL",
                    status=OrderAckStatus.CANCELLED,
                    fees=Decimal("0.50"),
                    reason="client_cancel",
                ),
            ],
            correlation_id="tick-cid",
        )

        pos = position_store.all_positions()["AAPL"]
        assert pos.quantity == 0
        assert pos.cumulative_fees == Decimal("0.50")
        assert len(updates) == 1
        assert updates[0].symbol == "AAPL"
        assert updates[0].quantity == 0
        assert updates[0].cumulative_fees == Decimal("0.50")
        assert updates[0].timestamp_ns == 2000

    def test_cancel_fee_without_fill_updates_strategy_fees(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        position_store = MemoryPositionStore()
        strategy_positions = StrategyPositionStore()

        orch = _build_orchestrator(
            clock,
            bus=bus,
            position_store=position_store,
            strategy_positions=strategy_positions,
        )

        order = OrderRequest(
            timestamp_ns=clock.now_ns(),
            correlation_id="cancel-cid",
            sequence=2,
            order_id="never-filled-alpha",
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=50,
            limit_price=Decimal("149.50"),
            strategy_id="alpha_1",
        )
        orch._track_order(order.order_id, Side.BUY, order)

        orch._reconcile_fills(
            [
                OrderAck(
                    timestamp_ns=2000,
                    correlation_id="cancel-cid",
                    sequence=2,
                    order_id=order.order_id,
                    symbol="AAPL",
                    status=OrderAckStatus.CANCELLED,
                    fees=Decimal("0.50"),
                    reason="client_cancel",
                ),
            ],
            correlation_id="tick-cid",
        )

        strat_pos = strategy_positions.get("alpha_1", "AAPL")
        assert strat_pos.quantity == 0
        assert strat_pos.cumulative_fees == Decimal("0.50")
        assert strategy_positions.get_strategy_cumulative_fees("alpha_1") == Decimal("0.50")


class TestStrategyFillDistribution:
    def test_fee_remainder_uses_debit_fees_on_last_nonzero_allocation(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        strategy_positions = _SnapshotStrategyPositionStore()

        orch = _build_orchestrator(
            clock,
            strategy_positions=strategy_positions,
        )

        orch._distribute_fill_to_strategies(
            symbol="AAPL",
            signed_qty=3,
            fill_price=Decimal("150.00"),
            fees=Decimal("0.01"),
            timestamp_ns=2000,
        )

        assert strategy_positions.get("alpha_a", "AAPL").quantity == 101
        assert strategy_positions.get("alpha_b", "AAPL").quantity == 101
        assert strategy_positions.get("alpha_c", "AAPL").quantity == 101
        assert strategy_positions.get("alpha_d", "AAPL").quantity == 1

        assert strategy_positions.debit_fee_calls == [
            ("alpha_c", "AAPL", Decimal("0.01")),
        ]
        assert strategy_positions.get("alpha_c", "AAPL").cumulative_fees == Decimal("0.01")
        assert strategy_positions.get("alpha_d", "AAPL").cumulative_fees == Decimal("0")


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

    def test_halt_resets_micro_state_machine(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        _boot_to_backtest(orch)
        orch.halt()
        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT

    def test_halt_noop_when_not_trading(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        _boot_to_ready(orch)
        orch.halt()
        assert orch.macro_state == MacroState.READY


# ── Macro lifecycle remediation (global stack audit) ──────────────────


class TestOrchestratorMacroLifecycleRemediation:
    def test_shutdown_from_risk_lockdown_reaches_shutdown(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        _boot_to_ready(orch)
        orch._macro.transition(
            MacroState.LIVE_TRADING_MODE,
            trigger="CMD_LIVE_DEPLOY",
        )
        orch._macro.transition(
            MacroState.RISK_LOCKDOWN,
            trigger="RISK_BREACH",
        )
        orch.shutdown()
        assert orch.macro_state == MacroState.SHUTDOWN

    def test_unlock_from_lockdown_clears_kill_switch(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        kill = InMemoryKillSwitch()
        kill.activate("pre_unlock", activated_by="test")
        bus = EventBus()
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=BacktestOrderRouter(clock=clock),
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(),
            position_store=MemoryPositionStore(),
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
            kill_switch=kill,
        )
        _boot_to_ready(orch)
        re = orch._risk_escalation
        re.transition(RiskLevel.WARNING, trigger="t")
        re.transition(RiskLevel.BREACH_DETECTED, trigger="t")
        re.transition(RiskLevel.FORCED_FLATTEN, trigger="t")
        re.transition(RiskLevel.LOCKED, trigger="t")
        orch._macro.transition(
            MacroState.LIVE_TRADING_MODE,
            trigger="CMD_LIVE_DEPLOY",
        )
        orch._macro.transition(
            MacroState.RISK_LOCKDOWN,
            trigger="RISK_BREACH",
        )
        assert kill.is_active
        orch.unlock_from_lockdown(audit_token="tok-audit")
        assert not kill.is_active
        assert orch.macro_state == MacroState.READY
        assert orch.risk_level == RiskLevel.NORMAL

    def test_run_paper_empty_feed_returns_ready(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        _boot_to_ready(orch)
        orch.run_paper()
        assert orch.macro_state == MacroState.READY

    def test_run_live_empty_feed_returns_ready(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        _boot_to_ready(orch)
        orch.run_live()
        assert orch.macro_state == MacroState.READY

    def test_run_backtest_refuses_active_kill_switch(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        kill = InMemoryKillSwitch()
        kill.activate("test_halt", activated_by="test")
        orch = _build_orchestrator(clock, kill_switch=kill)
        _boot_to_ready(orch)
        with pytest.raises(SessionEntryBlockedError, match="kill switch"):
            orch.run_backtest()

    def test_run_backtest_refuses_non_normal_risk(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        _boot_to_ready(orch)
        orch._risk_escalation.transition(RiskLevel.WARNING, trigger="probe")
        with pytest.raises(SessionEntryBlockedError, match="risk escalation"):
            orch.run_backtest()

    def test_live_mode_force_flatten_reaches_macro_risk_lockdown(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        signal = _make_signal(quote)
        _publish_signal_on_quote(bus, signal)
        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=_StubRiskEngine(RiskAction.FORCE_FLATTEN),
        )
        _boot_to_ready(orch)
        orch._macro.transition(MacroState.LIVE_TRADING_MODE, trigger="CMD_LIVE_DEPLOY")
        orch._process_tick(quote)
        assert orch.macro_state == MacroState.RISK_LOCKDOWN
        assert orch.risk_level == RiskLevel.LOCKED

    def test_backtest_force_flatten_does_not_reach_macro_lockdown(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        signal = _make_signal(quote)
        _publish_signal_on_quote(bus, signal)
        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=_StubRiskEngine(RiskAction.FORCE_FLATTEN),
        )
        _boot_to_backtest(orch)
        orch._process_tick(quote)
        assert orch.macro_state == MacroState.BACKTEST_MODE
        assert orch.risk_level == RiskLevel.NORMAL

    def test_recover_from_degraded_refuses_when_kill_switch_active(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        signal = _make_signal(_make_quote())
        kill = InMemoryKillSwitch()
        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=_RaisingRiskEngine(),
            kill_switch=kill,
        )
        _publish_signal_on_quote(bus, signal)
        _boot_to_ready(orch)
        orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
        orch._micro.reset(trigger="session_start:test")
        orch._process_tick(_make_quote())
        assert orch.macro_state == MacroState.DEGRADED
        kill.activate("during_degraded", activated_by="test")
        assert orch.recover_from_degraded() is False
        assert orch.macro_state == MacroState.DEGRADED

    def test_shutdown_macro_transition_uses_correlation_id(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        st_events: list[StateTransition] = []
        bus.subscribe(StateTransition, st_events.append)
        orch = _build_orchestrator(clock, bus=bus)
        _boot_to_ready(orch)
        orch.shutdown()
        macro_shutdown = [
            e for e in st_events if e.machine_name == "global_stack" and e.to_state == "SHUTDOWN"
        ]
        assert macro_shutdown
        assert macro_shutdown[-1].correlation_id == "orchestrator_shutdown"

    def test_shutdown_warns_on_pending_orders(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)
        orch = _build_orchestrator(clock, bus=bus)
        _boot_to_ready(orch)
        order = OrderRequest(
            timestamp_ns=clock.now_ns(),
            correlation_id="pending-cid",
            sequence=1,
            order_id="pending-order-1",
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            limit_price=Decimal("150.00"),
            strategy_id="alpha_1",
        )
        orch._track_order(order.order_id, Side.BUY, order)
        orch.shutdown()
        pending_alerts = [a for a in alerts if a.alert_name == "pending_orders_at_shutdown"]
        assert len(pending_alerts) == 1
        assert "pending-order-1" in pending_alerts[0].context.get("order_ids", [])

    def test_run_paper_pipeline_abort_not_session_feed_complete(self) -> None:
        """If DEGRADED transition fails inside tick recovery, do not → READY.

        Regression: ``_pipeline_abort_requested`` broke the tick loop without
        raising, so ``SESSION_FEED_COMPLETE`` looked like normal exhaustion.
        """
        clock = SimulatedClock(start_ns=1000)
        quote = _make_quote()
        orch = _build_orchestrator(
            clock,
            market_data=_StubMarketData([quote]),
        )
        _boot_to_ready(orch)

        def veto_drift(record: TransitionRecord) -> None:
            if record.trigger.startswith("EXECUTION_DRIFT_DETECTED"):
                raise RuntimeError("macro transition subscriber boom")

        orch._macro.on_transition(veto_drift)

        def boom(_quote: NBBOQuote) -> None:
            raise RuntimeError("tick boom")

        orch._process_tick_inner = boom  # type: ignore[method-assign]

        with pytest.raises(OrchestratorPipelineAbortError):
            orch.run_paper()

        assert orch.macro_state == MacroState.DEGRADED


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
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
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
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
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


# ── G-1 Phase P1: position-manager shadow harness ─────────────────────


class _EmptyPlanManager:
    """Wrong-on-purpose manager: always plans nothing (divergence probe)."""

    def plan(self, *, desired, current, market=None, config=None):
        from feelies.execution.position_manager import PositionPlan

        return PositionPlan()


class TestPositionManagerShadow:
    """The legacy planner runs alongside the legacy path with zero
    divergence, drives nothing, and the harness genuinely detects a
    mismatch when one exists."""

    def _build(
        self,
        clock: SimulatedClock,
        *,
        manager,
        sink,
        position_store=None,
    ) -> tuple[Orchestrator, EventBus]:
        bus = EventBus()
        pos_store = position_store or MemoryPositionStore()
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(),
            position_store=pos_store,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
            position_manager=manager,
            position_manager_shadow_sink=sink,
        )
        return orch, bus

    def test_legacy_manager_zero_divergence_entry_reverse_exit(self) -> None:
        from feelies.execution.position_manager import (
            LegacyPositionManager,
            PlanDivergence,
        )

        clock = SimulatedClock(start_ns=1000)
        sink: list[PlanDivergence] = []
        pos_store = MemoryPositionStore()
        orch, bus = self._build(
            clock,
            manager=LegacyPositionManager(),
            sink=sink,
            position_store=pos_store,
        )

        long_sig = _make_signal(_make_quote(), SignalDirection.LONG)
        short_sig = _make_signal(_make_quote(), SignalDirection.SHORT)
        flat_sig = _make_signal(_make_quote(), SignalDirection.FLAT)

        def emit(quote: NBBOQuote) -> None:
            sig = {1: long_sig, 2: short_sig, 3: flat_sig}.get(quote.sequence)
            if sig is not None:
                bus.publish(
                    replace(
                        sig,
                        timestamp_ns=quote.timestamp_ns,
                        correlation_id=quote.correlation_id,
                        sequence=quote.sequence,
                    )
                )

        bus.subscribe(NBBOQuote, emit)  # type: ignore[arg-type]
        _boot_to_backtest(orch)

        for seq in (1, 2, 3):
            q = _make_quote(ts=1000 + seq, seq=seq)
            orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
            orch._process_tick(q)

        # Legacy path drove the book through entry → reverse → exit …
        assert pos_store.get("AAPL").quantity == 0
        # … and the shadow planner never disagreed.
        assert sink == [], f"unexpected divergence: {sink}"

    def test_shadow_harness_detects_real_divergence(self) -> None:
        # A manager that plans nothing must be caught diverging on an entry.
        from feelies.execution.position_manager import PlanDivergence

        clock = SimulatedClock(start_ns=1000)
        sink: list[PlanDivergence] = []
        orch, bus = self._build(clock, manager=_EmptyPlanManager(), sink=sink)
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.LONG),
        )
        _boot_to_backtest(orch)
        q = _make_quote()
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)

        assert len(sink) == 1
        assert sink[0].legacy_intent == "ENTRY_LONG"
        assert sink[0].planner_quantity == 0

    def test_shadow_is_noop_without_sink(self) -> None:
        # Manager wired but no sink → harness is inert, book still moves.
        from feelies.execution.position_manager import LegacyPositionManager

        clock = SimulatedClock(start_ns=1000)
        orch, bus = self._build(
            clock,
            manager=LegacyPositionManager(),
            sink=None,
        )
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.LONG),
        )
        _boot_to_backtest(orch)
        q = _make_quote()
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        assert orch._positions.get("AAPL").quantity > 0


class TestPositionManagerDrive:
    """The flip: driving the decision from the planner (drive=True) produces
    byte-identical orders to the legacy translator (drive=False)."""

    @staticmethod
    def _run_scenario(*, drive: bool) -> list[tuple]:
        from feelies.execution.position_manager import LegacyPositionManager

        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        orders: list[OrderRequest] = []
        bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(),
            position_store=MemoryPositionStore(),
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
            position_manager=LegacyPositionManager(),
            position_manager_drive=drive,
        )
        long_sig = _make_signal(_make_quote(), SignalDirection.LONG)
        short_sig = _make_signal(_make_quote(), SignalDirection.SHORT)
        flat_sig = _make_signal(_make_quote(), SignalDirection.FLAT)

        def emit(quote: NBBOQuote) -> None:
            sig = {1: long_sig, 2: short_sig, 3: flat_sig}.get(quote.sequence)
            if sig is not None:
                bus.publish(
                    replace(
                        sig,
                        timestamp_ns=quote.timestamp_ns,
                        correlation_id=quote.correlation_id,
                        sequence=quote.sequence,
                    )
                )

        bus.subscribe(NBBOQuote, emit)  # type: ignore[arg-type]
        _boot_to_backtest(orch)

        for seq in (1, 2, 3):
            q = _make_quote(ts=1000 + seq, seq=seq)
            orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
            orch._process_tick(q)

        return [
            (o.order_id, o.side.name, o.quantity, o.order_type.name, str(o.limit_price))
            for o in orders
        ]

    def test_drive_is_byte_identical_to_legacy(self) -> None:
        legacy_orders = self._run_scenario(drive=False)
        driven_orders = self._run_scenario(drive=True)
        assert driven_orders, "scenario must submit at least one order"
        assert driven_orders == legacy_orders


class TestPositionManagerTrim:
    """P3: a cost-aware TRIM partially reduces a same-direction position
    that legacy would hold — default-off (byte-identical when disabled)."""

    @staticmethod
    def _run(*, enable_trim: bool) -> tuple[int, list[tuple[str, int]]]:
        from feelies.execution.position_manager import TargetPositionManager

        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        orders: list[OrderRequest] = []
        bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]
        pos_store = MemoryPositionStore()
        pos_store.update("AAPL", 150, Decimal("100"))  # long 150
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(),
            position_store=pos_store,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
            position_manager=TargetPositionManager(trim_min_fraction=0.10),
            position_manager_drive=True,
            position_manager_enable_trim=enable_trim,
        )
        # LONG signal → default target 100 < current 150 → would trim 50.
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.LONG),
        )
        _boot_to_backtest(orch)
        q = _make_quote()
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        return (
            pos_store.get("AAPL").quantity,
            [(o.side.name, o.quantity) for o in orders],
        )

    def test_trim_enabled_reduces_toward_target(self) -> None:
        qty, orders = self._run(enable_trim=True)
        assert qty == 100  # 150 trimmed down to the target 100
        assert orders == [("SELL", 50)]  # one partial reduce

    def test_trim_disabled_holds_position(self) -> None:
        qty, orders = self._run(enable_trim=False)
        assert qty == 150  # legacy hold — no trim
        assert orders == []

    @staticmethod
    def _run_edge_gate(*, edge_bps: float) -> int:
        # P3b end-to-end: edge gate on, real cost model, tight spread.
        from feelies.execution.cost_model import (
            DefaultCostModel,
            DefaultCostModelConfig,
        )
        from feelies.execution.position_manager import TargetPositionManager

        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        pos_store = MemoryPositionStore()
        pos_store.update("AAPL", 150, Decimal("100"))
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(),
            position_store=pos_store,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
            cost_model=DefaultCostModel(DefaultCostModelConfig()),
            position_manager=TargetPositionManager(trim_min_fraction=0.10),
            position_manager_drive=True,
            position_manager_enable_trim=True,
            position_manager_trim_edge_gate_multiplier=1.0,
        )
        sig = _make_signal_with_edge(_make_quote(), edge_bps)
        sig = replace(sig, direction=SignalDirection.LONG)
        _publish_signal_on_quote(bus, sig)
        _boot_to_backtest(orch)
        q = _make_quote(bid="99.99", ask="100.01")
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        return pos_store.get("AAPL").quantity

    def test_edge_gate_holds_high_edge_position(self) -> None:
        assert self._run_edge_gate(edge_bps=10_000.0) == 150  # held

    def test_edge_gate_trims_low_edge_position(self) -> None:
        assert self._run_edge_gate(edge_bps=0.0) == 100  # trimmed 150→100

    @staticmethod
    def _run_urgency(*, urgency_exec: bool) -> list[tuple[str, str, int]]:
        from feelies.execution.position_manager import TargetPositionManager

        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        orders: list[OrderRequest] = []
        bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]
        pos_store = MemoryPositionStore()
        pos_store.update("AAPL", 150, Decimal("100"))
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(),
            position_store=pos_store,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
            position_manager=TargetPositionManager(trim_min_fraction=0.10),
            position_manager_drive=True,
            position_manager_enable_trim=True,
            position_manager_urgency_exec=urgency_exec,
        )
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.LONG),
        )
        _boot_to_backtest(orch)
        q = _make_quote()
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        return [(o.side.name, o.order_type.name, o.quantity) for o in orders]

    def test_urgency_exec_posts_passive_trim(self) -> None:
        # urgency on → the discretionary trim works as a passive LIMIT.
        assert self._run_urgency(urgency_exec=True) == [("SELL", "LIMIT", 50)]

    def test_trim_is_market_by_default(self) -> None:
        # urgency off (default) → trim crosses at MARKET (immediate reduce).
        assert self._run_urgency(urgency_exec=False) == [("SELL", "MARKET", 50)]


# ── G-6: session / end-of-day flatten ─────────────────────────────────


class TestSessionFlatten:
    """Flat-by-close: open positions are unwound (and entries blocked) once
    the quote crosses the session-flatten deadline, independent of alphas."""

    @staticmethod
    def _day_anchored_bounds(anchor: "date"):
        """RTH bounds booted anchored to a single ``anchor`` date.

        Mirrors the multi-day CLI range path:
        ``apply_backtest_session_dates_from_cli`` only rebinds single-day
        runs, so a date *range* leaves ``rth_session_date`` unset and the
        bounds fall back to one (often stale ``event_calendar_path``) date.
        """
        from feelies.execution.moc_session import et_clock_to_ns
        from feelies.execution.trading_session import TradingSessionBounds

        return TradingSessionBounds(
            session_date=anchor,
            rth_open_ns=et_clock_to_ns(anchor, "09:30"),
            rth_close_ns=et_clock_to_ns(anchor, "16:00"),
        )

    @staticmethod
    def _quote_at(d: "date", hhmm: str, seq: int = 1) -> NBBOQuote:
        from feelies.execution.moc_session import et_clock_to_ns

        # _make_quote sets exchange_timestamp_ns = ts - 100; offset by +100 so
        # the exchange timestamp lands exactly on the ET wall-clock instant.
        ns = et_clock_to_ns(d, hhmm)
        return _make_quote(ts=ns + 100, bid="99.99", ask="100.01", seq=seq)

    def _orch(
        self,
        *,
        enabled: bool = True,
        position: int = 50,
        anchor: "date | None" = None,
        flatten_buffer_s: int = 0,
    ) -> tuple[Orchestrator, EventBus, list[OrderRequest], MemoryPositionStore]:
        from datetime import date

        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        orders: list[OrderRequest] = []
        bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]
        pos_store = MemoryPositionStore()
        if position:
            pos_store.update("AAPL", position, Decimal("100"))
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(),
            position_store=pos_store,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
        )
        _boot_to_backtest(orch)
        orch._trading_session_bounds = self._day_anchored_bounds(
            anchor or date(2026, 3, 26),
        )
        orch._session_flatten_enabled = enabled
        orch._session_flatten_seconds_before_close = flatten_buffer_s
        return orch, bus, orders, pos_store

    def test_flattens_open_position_past_close(self) -> None:
        orch, _bus, orders, pos = self._orch()
        q = self._quote_at(date(2026, 3, 26), "16:01")  # past the 16:00 close
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        assert pos.get("AAPL").quantity == 0
        assert len(orders) == 1
        assert orders[0].side == Side.SELL and orders[0].quantity == 50
        assert orders[0].order_type.name == "MARKET"  # EOD close is aggressive

    def test_holds_before_close(self) -> None:
        orch, _bus, orders, pos = self._orch()
        q = self._quote_at(date(2026, 3, 26), "15:59")  # before the 16:00 close
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        assert pos.get("AAPL").quantity == 50
        assert orders == []

    def test_disabled_holds_position(self) -> None:
        orch, _bus, orders, pos = self._orch(enabled=False)
        q = self._quote_at(date(2026, 3, 26), "16:01")
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        assert pos.get("AAPL").quantity == 50
        assert orders == []

    def test_blocks_new_entry_in_window(self) -> None:
        orch, bus, orders, pos = self._orch(position=0)
        q = self._quote_at(date(2026, 3, 26), "16:01")
        _publish_signal_on_quote(bus, _make_signal(q, SignalDirection.LONG))
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        assert pos.get("AAPL").quantity == 0  # entry suppressed in the window
        assert orders == []

    # ── Per-day rebinding for multi-day backtest ranges ───────────────
    #
    # A CLI date *range* (``--date D1 --end-date D2``) leaves
    # ``rth_session_date`` unset (``apply_backtest_session_dates_from_cli``
    # only rebinds single-day runs), so ``_trading_session_bounds`` is booted
    # anchored to a single — often stale ``event_calendar_path`` — date.  The
    # session-flatten window must therefore resolve the close *per replayed
    # day* (``TradingSessionBounds.resolve_for_timestamp``); otherwise every
    # quote past the booted day's close reads as past-close and all entries
    # are blocked with ``session_flatten_window`` (0 orders for the range).

    def test_session_flatten_window_rebinds_per_replayed_day(self) -> None:
        day1, day2 = date(2026, 6, 1), date(2026, 6, 2)
        # Bounds booted anchored to DAY 1 (the stale-anchor range scenario).
        orch, _bus, _orders, _pos = self._orch(
            position=0,
            anchor=day1,
            flatten_buffer_s=300,
        )

        # Day-2 mid-session must NOT be in the flatten window — the regression:
        # the stale day-1 16:00 close made every day-2 quote read as past-close.
        assert not orch._in_session_flatten_window(self._quote_at(day2, "10:45"))
        # Day-2 within 5 min of its OWN 16:00 close still flattens.
        assert orch._in_session_flatten_window(self._quote_at(day2, "15:58"))
        # Day-1 behaviour is preserved (mid-session open, near-close flat).
        assert not orch._in_session_flatten_window(self._quote_at(day1, "10:45"))
        assert orch._in_session_flatten_window(self._quote_at(day1, "15:58"))

    def test_day2_intraday_entry_not_flatten_blocked(self) -> None:
        day1, day2 = date(2026, 6, 1), date(2026, 6, 2)
        orch, bus, orders, _pos = self._orch(
            position=0,
            anchor=day1,
            flatten_buffer_s=300,
        )

        q = self._quote_at(day2, "10:45")
        _publish_signal_on_quote(bus, _make_signal_with_edge(q, 10_000.0))
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        # The entry survives: a day-2 intraday LONG produces a BUY order even
        # though the bounds were booted anchored to day 1.
        assert len(orders) == 1
        assert orders[0].side == Side.BUY

    def test_day2_near_close_entry_still_flatten_blocked(self) -> None:
        day1, day2 = date(2026, 6, 1), date(2026, 6, 2)
        orch, bus, orders, _pos = self._orch(
            position=0,
            anchor=day1,
            flatten_buffer_s=300,
        )

        # Within 5 min of day-2's own close → entry is correctly suppressed.
        q = self._quote_at(day2, "15:58")
        _publish_signal_on_quote(bus, _make_signal_with_edge(q, 10_000.0))
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        assert orders == []


# ── P4b: working-exit MARKET fallback ─────────────────────────────────


class TestWorkingExitFallback:
    """A passive working reduction that terminates unfilled escalates its
    residual to a guaranteed MARKET order."""

    def _orch(self) -> tuple[Orchestrator, EventBus, list[OrderRequest]]:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        orders: list[OrderRequest] = []
        bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(),
            position_store=MemoryPositionStore(),
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
        )
        _boot_to_backtest(orch)
        return orch, bus, orders

    @staticmethod
    def _ack(order_id: str, status: OrderAckStatus, filled: int = 0):
        return OrderAck(
            timestamp_ns=2000,
            correlation_id="c",
            sequence=1,
            order_id=order_id,
            symbol="AAPL",
            status=status,
            filled_quantity=filled,
        )

    def test_cancelled_escalates_full_residual_to_market(self) -> None:
        orch, _bus, orders = self._orch()
        orch._working_exit_fallback["oid1"] = ("AAPL", Side.SELL, 50)
        orch._escalate_unfilled_working_exits(
            [self._ack("oid1", OrderAckStatus.CANCELLED)],
            "c",
        )
        assert len(orders) == 1
        assert orders[0].order_type.name == "MARKET"
        assert orders[0].side == Side.SELL and orders[0].quantity == 50
        assert "oid1" not in orch._working_exit_fallback  # tag cleared

    def test_partial_fill_escalates_only_residual(self) -> None:
        orch, _bus, orders = self._orch()
        orch._working_exit_fallback["oid2"] = ("AAPL", Side.SELL, 50)
        orch._order_filled_qty["oid2"] = 20
        orch._escalate_unfilled_working_exits(
            [self._ack("oid2", OrderAckStatus.EXPIRED, filled=20)],
            "c",
        )
        assert orders[0].quantity == 30  # 50 − 20 already filled

    def test_full_fill_no_fallback(self) -> None:
        orch, _bus, orders = self._orch()
        orch._working_exit_fallback["oid3"] = ("AAPL", Side.SELL, 50)
        orch._escalate_unfilled_working_exits(
            [self._ack("oid3", OrderAckStatus.FILLED, filled=50)],
            "c",
        )
        assert orders == []
        assert "oid3" not in orch._working_exit_fallback

    def test_noop_when_nothing_tagged(self) -> None:
        orch, _bus, orders = self._orch()
        orch._escalate_unfilled_working_exits(
            [self._ack("unknown", OrderAckStatus.CANCELLED)],
            "c",
        )
        assert orders == []

    def test_passive_trim_registers_a_fallback_tag(self) -> None:
        # End-to-end wiring: a driven urgency trim posts a LIMIT that is
        # tagged for fallback (the escalation itself is covered above).
        from feelies.execution.position_manager import TargetPositionManager

        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        orders: list[OrderRequest] = []
        bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]
        pos = MemoryPositionStore()
        pos.update("AAPL", 150, Decimal("100"))
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(),
            position_store=pos,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
            position_manager=TargetPositionManager(trim_min_fraction=0.10),
            position_manager_drive=True,
            position_manager_enable_trim=True,
            position_manager_urgency_exec=True,
        )
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.LONG),
        )
        _boot_to_backtest(orch)
        q = _make_quote()
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)

        limit_orders = [o for o in orders if o.order_type.name == "LIMIT"]
        assert len(limit_orders) == 1  # passive trim posted
        assert limit_orders[0].order_id in orch._working_exit_fallback


# ── G-5 N1: cross-alpha net shadow ────────────────────────────────────


class TestNetShadow:
    """The standing-target book is maintained from the live signal stream and
    the netter runs in shadow, recording where the budget-weighted net target
    disagrees with the winner-take-all decision (pure measurement)."""

    @staticmethod
    def _orch(sink):
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(),
            position_store=MemoryPositionStore(),
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
            net_shadow_sink=sink,
        )
        return orch, bus

    @staticmethod
    def _emit(bus: EventBus, specs: list[tuple[str, SignalDirection]]) -> None:
        def emit(quote: NBBOQuote) -> None:
            for i, (sid, direction) in enumerate(specs):
                bus.publish(
                    Signal(
                        timestamp_ns=quote.timestamp_ns,
                        correlation_id=quote.correlation_id,
                        sequence=quote.sequence * 100 + i,
                        symbol=quote.symbol,
                        strategy_id=sid,
                        direction=direction,
                        strength=0.8,
                        edge_estimate_bps=5.0,
                    )
                )

        bus.subscribe(NBBOQuote, emit)  # type: ignore[arg-type]

    def test_same_direction_alphas_diverge_by_stacking(self) -> None:
        from feelies.execution.portfolio_netter import NetDivergence

        sink: list[NetDivergence] = []
        orch, bus = self._orch(sink)
        self._emit(
            bus,
            [
                ("alpha_a", SignalDirection.LONG),
                ("alpha_b", SignalDirection.LONG),
            ],
        )
        _boot_to_backtest(orch)
        q = _make_quote()
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        assert len(sink) == 1
        d = sink[0]
        assert d.winner_target_qty == 100  # winner-take-all
        assert d.net_target_qty == 200  # net stacks both alphas
        assert d.contributing_alphas == 2

    def test_opposing_alphas_diverge_by_offset(self) -> None:
        from feelies.execution.portfolio_netter import NetDivergence

        sink: list[NetDivergence] = []
        orch, bus = self._orch(sink)
        self._emit(
            bus,
            [
                ("alpha_a", SignalDirection.LONG),
                ("alpha_b", SignalDirection.SHORT),
            ],
        )
        _boot_to_backtest(orch)
        q = _make_quote()
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        assert len(sink) == 1
        assert sink[0].net_target_qty == 0  # the two cancel
        assert abs(sink[0].winner_target_qty) == 100

    def test_single_alpha_no_divergence(self) -> None:
        from feelies.execution.portfolio_netter import NetDivergence

        sink: list[NetDivergence] = []
        orch, bus = self._orch(sink)
        self._emit(bus, [("alpha_a", SignalDirection.LONG)])
        _boot_to_backtest(orch)
        q = _make_quote()
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        assert sink == []  # net == winner

    def test_disabled_without_sink_is_noop(self) -> None:
        orch, bus = self._orch(None)
        self._emit(
            bus,
            [
                ("alpha_a", SignalDirection.LONG),
                ("alpha_b", SignalDirection.LONG),
            ],
        )
        _boot_to_backtest(orch)
        q = _make_quote()
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)  # must not raise; nothing recorded
        assert orch._positions.get("AAPL").quantity != 0  # legacy path drove


class TestSizeShadow:
    """G-7 S1: the size shadow records, per sized signal, how the
    edge/vol/inventory-tilted target would differ from the live single-factor
    base target (pure measurement; live size untouched)."""

    @staticmethod
    def _budget():
        from feelies.alpha.module import AlphaRiskBudget

        return AlphaRiskBudget(
            max_position_per_symbol=500,
            max_gross_exposure_pct=10.0,
            max_drawdown_pct=2.0,
            capital_allocation_pct=10.0,
        )

    def _orch_with_shadow(self, sink, *, enabled: bool):
        from types import SimpleNamespace

        from feelies.risk.edge_weighted_sizer import (
            EdgeWeightedSizer,
            SizerTiltConfig,
        )
        from feelies.risk.position_sizer import BudgetBasedSizer

        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        budget = self._budget()
        orch._alpha_registry = SimpleNamespace(  # type: ignore[attr-defined]
            get=lambda sid: SimpleNamespace(manifest=SimpleNamespace(risk_budget=budget))
        )
        cfg = SizerTiltConfig(edge_enabled=enabled, edge_ref_bps=20.0, edge_cap=2.0)
        orch._size_shadow_sizer = EdgeWeightedSizer(  # type: ignore[attr-defined]
            BudgetBasedSizer(), cfg
        )
        orch._size_shadow_sink = sink  # type: ignore[attr-defined]
        orch._account_equity = Decimal("150000")  # type: ignore[attr-defined]
        return orch

    @staticmethod
    def _signal(quote, edge_bps: float, strategy_id: str = "test_strat") -> Signal:
        return Signal(
            timestamp_ns=quote.timestamp_ns,
            correlation_id=quote.correlation_id,
            sequence=quote.sequence,
            symbol=quote.symbol,
            strategy_id=strategy_id,
            direction=SignalDirection.LONG,
            strength=1.0,
            edge_estimate_bps=edge_bps,
        )

    def test_high_edge_records_upsize(self) -> None:
        sink: list = []
        orch = self._orch_with_shadow(sink, enabled=True)
        q = _make_quote()  # mid 150 → base 150000*10%/150 = 100
        orch._record_size_shadow(self._signal(q, edge_bps=40.0), q)
        assert len(sink) == 1
        d = sink[0]
        assert d.base_target_qty == 100
        assert d.tilted_target_qty == 200  # edge 40/ref 20 → 2.0×
        assert d.edge_factor == 2.0
        assert d.timestamp_ns == q.exchange_timestamp_ns

    def test_edge_equal_ref_no_record(self) -> None:
        sink: list = []
        orch = self._orch_with_shadow(sink, enabled=True)
        q = _make_quote()
        orch._record_size_shadow(self._signal(q, edge_bps=20.0), q)
        assert sink == []  # factor 1.0 → tilted == base

    def test_disabled_factors_noop(self) -> None:
        sink: list = []
        orch = self._orch_with_shadow(sink, enabled=False)
        q = _make_quote()
        orch._record_size_shadow(self._signal(q, edge_bps=40.0), q)
        assert sink == []  # any_enabled False → no-op

    def test_no_sink_noop(self) -> None:
        orch = self._orch_with_shadow(None, enabled=True)
        q = _make_quote()
        orch._record_size_shadow(self._signal(q, edge_bps=40.0), q)  # no raise

    def test_synthetic_signal_skipped(self) -> None:
        sink: list = []
        orch = self._orch_with_shadow(sink, enabled=True)
        q = _make_quote()
        orch._record_size_shadow(self._signal(q, edge_bps=40.0, strategy_id="__stop_exit__"), q)
        assert sink == []


# ── G-5 N2: net-driven decision ───────────────────────────────────────


class TestNetDrive:
    """When portfolio netting is enabled, the SIGNAL-path decision is driven
    by the budget-weighted net target, not the single arbitrated winner."""

    @staticmethod
    def _run(*, netting: bool, specs) -> int:
        from feelies.execution.position_manager import LegacyPositionManager

        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        pos = MemoryPositionStore()
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(),
            position_store=pos,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
            position_manager=LegacyPositionManager(),
            position_manager_drive=True,
        )
        TestNetShadow._emit(bus, specs)
        _boot_to_backtest(orch)
        orch._enable_portfolio_netting = netting
        q = _make_quote()
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        return pos.get("AAPL").quantity

    def test_netting_on_drives_stacked_net_target(self) -> None:
        qty = self._run(
            netting=True,
            specs=[("alpha_a", SignalDirection.LONG), ("alpha_b", SignalDirection.LONG)],
        )
        assert qty == 200  # net stacks both alphas

    def test_netting_off_drives_winner_target(self) -> None:
        qty = self._run(
            netting=False,
            specs=[("alpha_a", SignalDirection.LONG), ("alpha_b", SignalDirection.LONG)],
        )
        assert qty == 100  # winner-take-all (byte-identical to pre-N2)

    def test_netting_opposing_offsets_to_flat(self) -> None:
        qty = self._run(
            netting=True,
            specs=[("alpha_a", SignalDirection.LONG), ("alpha_b", SignalDirection.SHORT)],
        )
        assert qty == 0  # the two desires cancel → no trade


# ── G-5 N3: PORTFOLIO → net shadow bridge ─────────────────────────────


class TestPortfolioNetBridge:
    """A PORTFOLIO SizedPositionIntent feeds the net shadow book (target_usd →
    shares via the mark) so the cross-alpha measurement spans both paths.
    Measurement-only: gated off while netting drives, or without a sink."""

    @staticmethod
    def _intent(target_usd: float, *, strategy_id: str = "port_a"):
        from feelies.core.events import SizedPositionIntent, TargetPosition

        return SizedPositionIntent(
            timestamp_ns=1000,
            correlation_id="c",
            sequence=1,
            strategy_id=strategy_id,
            target_positions={
                "AAPL": TargetPosition(
                    symbol="AAPL",
                    target_usd=target_usd,
                    urgency=0.7,
                ),
            },
        )

    def _orch(self):
        clock = SimulatedClock(start_ns=1000)
        orch = _build_orchestrator(clock)
        orch._positions.update_mark("AAPL", Decimal("100"))  # mark = $100
        return orch

    def test_portfolio_target_feeds_book_in_shadow(self) -> None:
        orch = self._orch()
        orch._net_shadow_sink = []  # measurement on
        orch._record_portfolio_net_shadow(self._intent(10_000.0))
        st = orch._desired_target_book.get("port_a", "AAPL")
        assert st is not None
        assert st.target_qty == 100  # $10k / $100 mark
        assert st.urgency == 0.7

    def test_short_portfolio_target(self) -> None:
        orch = self._orch()
        orch._net_shadow_sink = []
        orch._record_portfolio_net_shadow(self._intent(-5_000.0))
        st = orch._desired_target_book.get("port_a", "AAPL")
        assert st.target_qty == -50

    def test_no_sink_is_noop(self) -> None:
        orch = self._orch()  # sink is None
        orch._record_portfolio_net_shadow(self._intent(10_000.0))
        assert orch._desired_target_book.get("port_a", "AAPL") is None

    def test_gated_off_while_netting_drives(self) -> None:
        # Avoid double-counting the PORTFOLIO self-drive: no feed when driving.
        orch = self._orch()
        orch._net_shadow_sink = []
        orch._enable_portfolio_netting = True
        orch._record_portfolio_net_shadow(self._intent(10_000.0))
        assert orch._desired_target_book.get("port_a", "AAPL") is None

    def test_portfolio_and_signal_net_together(self) -> None:
        # A PORTFOLIO long + a SIGNAL long on the same symbol stack in the net.
        from feelies.execution.portfolio_netter import standing_target_from_desired
        from feelies.execution.position_manager import desired_from_signal

        orch = self._orch()
        orch._net_shadow_sink = []
        orch._record_portfolio_net_shadow(self._intent(10_000.0))  # +100
        # add a SIGNAL alpha standing target of +60 directly
        sig_desired = desired_from_signal(
            _make_signal(_make_quote(), SignalDirection.LONG),
            60,
        )
        orch._desired_target_book.put(
            standing_target_from_desired(
                sig_desired,
                strategy_id="sig_a",
                signal_timestamp_ns=1000,
                horizon_seconds=0,
                staleness_k=1.0,
            )
        )
        net = orch._portfolio_netter.net("AAPL", now_ns=1000)
        assert net.target_qty == 160  # 100 (portfolio) + 60 (signal)


# ── G-4: lot ledger integration ───────────────────────────────────────


class TestLotLedgerIntegration:
    """Fills mirror into the FIFO lot ledger beside the avg-cost store,
    with per-lot provenance; the ledger net always tracks the position."""

    def test_fills_populate_lot_ledger_with_provenance(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        pos = MemoryPositionStore()
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(),
            position_store=pos,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
        )
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.LONG),
        )
        _boot_to_backtest(orch)
        q = _make_quote()
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)

        led = orch.lot_ledger
        position_qty = pos.get("AAPL").quantity
        assert position_qty > 0
        # The ledger's net mirrors the avg-cost book's quantity.
        assert led.net_quantity("AAPL") == position_qty
        lots = led.lots("AAPL")
        assert len(lots) == 1
        assert lots[0].quantity == position_qty
        assert lots[0].intent == "ENTRY_LONG"  # per-lot provenance captured

    def test_exit_empties_lot_ledger(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        pos = MemoryPositionStore()
        pos.update("AAPL", 50, Decimal("100"))
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
        # seed the ledger to mirror the preloaded position
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=bt_router,
                mode="BACKTEST",
            ),
            risk_engine=_StubRiskEngine(),
            position_store=pos,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
        )
        orch.lot_ledger.apply_fill(
            "AAPL",
            50,
            Decimal("100"),
            timestamp_ns=900,
            intent="ENTRY_LONG",
        )
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.FLAT),
        )
        _boot_to_backtest(orch)
        q = _make_quote()
        orch._backend.order_router.on_quote(q)  # type: ignore[attr-defined]
        orch._process_tick(q)
        assert pos.get("AAPL").quantity == 0
        assert orch.lot_ledger.net_quantity("AAPL") == 0
        assert orch.lot_ledger.lots("AAPL") == ()


# ── B5: reversal combined-edge guard ──────────────────────────────────


def _make_short_signal_with_edge(quote: NBBOQuote, edge_bps: float) -> Signal:
    """SHORT signal with explicit edge — drives a REVERSE_LONG_TO_SHORT."""
    return Signal(
        timestamp_ns=quote.timestamp_ns,
        correlation_id=quote.correlation_id,
        sequence=quote.sequence,
        symbol=quote.symbol,
        strategy_id="test_strat",
        direction=SignalDirection.SHORT,
        strength=0.8,
        edge_estimate_bps=edge_bps,
    )


class TestReversalEdgeGuard:
    """B5: a reversal flips only when edge clears combined exit+entry cost.

    Against a +50 long, a SHORT signal translates to REVERSE_LONG_TO_SHORT
    with default sizing (target 150 → exit 50, entry 100).  The guard prices
    the round-trip cost of *both* legs and suppresses the entry (flatten-
    only) unless the edge clears ``multiplier × combined_cost``.
    """

    def _build(
        self,
        clock: SimulatedClock,
        signal: Signal,
        *,
        multiplier: float,
    ) -> tuple[Orchestrator, EventBus, list[OrderRequest], list[Alert]]:
        from feelies.execution.cost_model import (
            DefaultCostModel,
            DefaultCostModelConfig,
        )

        bus = EventBus()
        orders: list[OrderRequest] = []
        alerts: list[Alert] = []
        bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]
        bus.subscribe(Alert, alerts.append)  # type: ignore[arg-type]
        pos_store = MemoryPositionStore()
        pos_store.update("AAPL", 50, Decimal("100"))  # +50 long
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
        backend = ExecutionBackend(
            market_data=_StubMarketData(),
            order_router=bt_router,
            mode="BACKTEST",
        )
        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=backend,
            risk_engine=_StubRiskEngine(),
            position_store=pos_store,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
            cost_model=DefaultCostModel(DefaultCostModelConfig()),
        )
        _publish_signal_on_quote(bus, signal)
        orch._reversal_min_edge_cost_multiplier = multiplier
        _boot_to_backtest(orch)
        return orch, bus, orders, alerts

    @staticmethod
    def _quote() -> NBBOQuote:
        # Tight spread → combined round-trip cost ≈ 8.3 bps, required ≈ 16.7
        # bps at multiplier 2.0 (edge 5 fails, edge 30 passes).
        return _make_quote(bid="99.99", ask="100.01")

    def test_reversal_blocked_when_edge_insufficient(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        quote = self._quote()
        signal = _make_short_signal_with_edge(quote, edge_bps=5.0)
        orch, _bus, orders, alerts = self._build(clock, signal, multiplier=2.0)
        orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
        orch._process_tick(quote)

        # Only the exit (flatten) leg of 50 shares is submitted; no entry.
        assert len(orders) == 1
        assert orders[0].quantity == 50
        assert orders[0].side == Side.SELL
        assert any(a.alert_name == "reversal_edge_insufficient" for a in alerts)

    def test_reversal_allowed_when_edge_sufficient(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        quote = self._quote()
        signal = _make_short_signal_with_edge(quote, edge_bps=30.0)
        orch, _bus, orders, alerts = self._build(clock, signal, multiplier=2.0)
        orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
        orch._process_tick(quote)

        # Both legs submit: exit 50 + entry 100.
        assert len(orders) == 2
        quantities = sorted(o.quantity for o in orders)
        assert quantities == [50, 100]
        assert not any(a.alert_name == "reversal_edge_insufficient" for a in alerts)

    def test_reversal_exit_never_suppressed_by_edge_guard(self) -> None:
        # Inv-11: extreme multiplier blocks the entry, but the exit must
        # still flatten the existing position.
        clock = SimulatedClock(start_ns=1000)
        quote = self._quote()
        signal = _make_short_signal_with_edge(quote, edge_bps=30.0)
        orch, _bus, orders, alerts = self._build(clock, signal, multiplier=100.0)
        orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
        orch._process_tick(quote)

        assert len(orders) == 1  # exit only
        assert orders[0].quantity == 50
        assert orders[0].side == Side.SELL
        assert any(a.alert_name == "reversal_edge_insufficient" for a in alerts)
        # The existing long was flattened (exit filled), not flipped short.
        assert orch._positions.get("AAPL").quantity == 0


# ── F1: Resting-order guard placed AFTER signal/risk evaluation ───────────


class _CancelRecordingBacktestRouter(BacktestOrderRouter):
    """``BacktestOrderRouter`` that records cancels and emits a CANCELLED ack.

    The market backtest router has no resting limit book of its own, so a
    seeded passive cover lives only in the orchestrator's order tracker.
    This subclass lets ``_cancel_resting_for_symbol`` drive that tracked
    order to a terminal CANCELLED state (parity with the passive router),
    so the forced-exit supersede path can be exercised end-to-end.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.cancelled_order_ids: list[str] = []

    def cancel_order(self, order_id: str) -> bool:
        if super().cancel_order(order_id):
            return True
        self.cancelled_order_ids.append(order_id)
        self._pending_acks.append(
            OrderAck(
                timestamp_ns=self._clock.now_ns(),
                correlation_id="cancel-ack",
                sequence=self._ack_seq.next(),
                order_id=order_id,
                symbol="AAPL",
                status=OrderAckStatus.CANCELLED,
                reason="client_cancel",
            )
        )
        return True


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
        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
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

    def test_stop_exit_does_not_submit_duplicate_exit_while_pending(self) -> None:
        """Synthetic stop-exit should not pile up another exit on top of one already pending."""
        clock = SimulatedClock(start_ns=1000)
        quote = _make_quote(ts=2000, bid="147.50", ask="148.50", seq=7)

        position_store = MemoryPositionStore()
        position_store.update("AAPL", 100, Decimal("150.00"))

        orch = _build_orchestrator(clock, position_store=position_store)
        orch._stop_loss_per_share = 1.0
        _boot_to_backtest(orch)

        fake_order = OrderRequest(
            timestamp_ns=clock.now_ns(),
            correlation_id="fake-cid-stop",
            sequence=999,
            order_id="fake-stop-order",
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.MARKET,
            quantity=100,
            limit_price=None,
            strategy_id="__stop_exit__",
        )
        orch._track_order(fake_order.order_id, fake_order.side, fake_order)

        new_orders: list[OrderRequest] = []
        orch._bus.subscribe(OrderRequest, new_orders.append)

        orch._backend.order_router.on_quote(quote)  # type: ignore[attr-defined]
        orch._process_tick(quote)

        assert new_orders == []

    def test_stop_exit_supersedes_resting_passive_cover(self) -> None:
        """Inv-11: a hard-stop MARKET exit cancels a stale passive cover and crosses.

        Regression for ``docs/pending issues/app_backtest_2026-06-01_*``: a
        gate-OFF FLAT passive LIMIT cover left resting must not subordinate a
        breached hard stop.  Previously the resting-order guard treated the
        pending cover as a pending exit and suppressed every ``__stop_exit__``
        MARKET attempt until the passive order expired (~57 minutes later),
        turning a configured 1.0% stop into a 1.49% realized loss.  The stop
        must now cancel the resting cover and fill a MARKET close in the same
        tick.
        """
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()

        position_store = MemoryPositionStore()
        position_store.update("AAPL", -50, Decimal("599.50"))  # short 50 @ 599.50

        router = _CancelRecordingBacktestRouter(clock=clock, cost_model=ZeroCostModel())
        orch = _build_orchestrator(
            clock,
            bus=bus,
            position_store=position_store,
            order_router=router,
        )
        orch._stop_loss_pct = 0.01
        orch._use_passive_entries = True
        _boot_to_backtest(orch)

        # Seed a resting passive BUY cover (mimics the alpha gate-OFF FLAT leg).
        cover = OrderRequest(
            timestamp_ns=clock.now_ns(),
            correlation_id="cover-cid",
            sequence=999,
            order_id="cover-001",
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=50,
            limit_price=Decimal("600.00"),
            strategy_id="sig_benign_midcap_v1",
        )
        orch._track_order(cover.order_id, Side.BUY, cover, trading_intent="EXIT")
        # Mirror a real resting passive order: SUBMITTED → ACKNOWLEDGED so a
        # broker CANCELLED ack is a valid (non-terminal → terminal) transition.
        orch._transition_order(cover.order_id, OrderState.SUBMITTED, "submitted")
        orch._transition_order(cover.order_id, OrderState.ACKNOWLEDGED, "acknowledged")
        assert orch._has_pending_order_for_symbol("AAPL")

        alerts: list[Alert] = []
        new_orders: list[OrderRequest] = []
        bus.subscribe(Alert, alerts.append)
        bus.subscribe(OrderRequest, new_orders.append)

        # Quote runs through the 1% hard stop (599.50 × 1.01 = 605.495); mid 608.42.
        stop_quote = _make_quote(ts=2000, bid="608.00", ask="608.84", seq=7)
        router.on_quote(stop_quote)
        orch._process_tick(stop_quote)

        # The resting cover was cancelled so the MARKET stop could cross.
        assert "cover-001" in router.cancelled_order_ids
        assert not orch._has_pending_order_for_symbol("AAPL")
        # A forced MARKET exit was submitted and filled → position flat.
        assert any(o.strategy_id == "__stop_exit__" for o in new_orders)
        assert position_store.get("AAPL").quantity == 0
        # Operator-visible forensic marker distinguishes the cancel-and-cross.
        assert any(a.alert_name == "forced_exit_supersedes_pending_order" for a in alerts)


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

        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
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

        bt_router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
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


class TestHaltModeling:
    """BT-5: LULD halt suppression + post-resolution entry blackout."""

    _HALT_ON = (5,)
    _HALT_OFF = (6,)

    @staticmethod
    def _trade(ts: int, seq: int, conditions: tuple[int, ...]) -> Trade:
        return Trade(
            timestamp_ns=ts,
            correlation_id=f"AAPL:{ts}:{seq}",
            sequence=seq,
            symbol="AAPL",
            price=Decimal("150.00"),
            size=100,
            exchange_timestamp_ns=ts - 100,
            conditions=conditions,
        )

    @staticmethod
    def _build(
        clock: SimulatedClock,
        bus: EventBus,
        position_store: MemoryPositionStore,
        *,
        blackout_ns: int,
    ) -> tuple[Orchestrator, BacktestOrderRouter]:
        bt_router = BacktestOrderRouter(clock=clock)
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
        _boot_to_backtest(orch)
        # _MinimalConfig carries no halt fields, so set the cached codes
        # directly (bootstrap threads these from PlatformConfig in prod).
        orch._halt_on_codes = frozenset({5})
        orch._halt_off_codes = frozenset({6})
        orch._halt_blackout_ns = blackout_ns
        return orch, bt_router

    def test_halt_on_suppresses_entry_and_emits_event(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        halts: list[SymbolHalted] = []
        bus.subscribe(SymbolHalted, halts.append)  # type: ignore[arg-type]
        position_store = MemoryPositionStore()
        orch, bt_router = self._build(
            clock,
            bus,
            position_store,
            blackout_ns=1000,
        )
        # Absent the halt gate, every quote would emit a LONG entry signal.
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.LONG),
        )

        orch._process_trade(self._trade(ts=1500, seq=2, conditions=self._HALT_ON))
        assert "AAPL" in orch._halted_symbols
        assert [h.halted for h in halts] == [True]

        q = _make_quote(ts=1700, seq=3)
        bt_router.on_quote(q)
        orch._process_tick(q)

        # Halted → quote skipped, no entry fill, position stays flat.
        assert position_store.get("AAPL").quantity == 0

    def test_resume_blackout_suppresses_entry_then_lifts(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        position_store = MemoryPositionStore()
        orch, bt_router = self._build(
            clock,
            bus,
            position_store,
            blackout_ns=1000,
        )
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.LONG),
        )

        orch._process_trade(self._trade(ts=1500, seq=2, conditions=self._HALT_ON))
        orch._process_trade(self._trade(ts=2000, seq=4, conditions=self._HALT_OFF))
        assert "AAPL" not in orch._halted_symbols
        assert orch._in_halt_blackout("AAPL", 2500)  # inside window
        assert not orch._in_halt_blackout("AAPL", 3000)  # deadline = 2000+1000

        # Entry during blackout → suppressed.
        q_bl = _make_quote(ts=2500, seq=5)
        bt_router.on_quote(q_bl)
        orch._process_tick(q_bl)
        assert position_store.get("AAPL").quantity == 0

        # Entry after the blackout lifts → fills.
        q_after = _make_quote(ts=3500, seq=6)
        bt_router.on_quote(q_after)
        orch._process_tick(q_after)
        assert position_store.get("AAPL").quantity > 0

    def test_exit_permitted_during_blackout(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        position_store = MemoryPositionStore()
        orch, bt_router = self._build(
            clock,
            bus,
            position_store,
            blackout_ns=1000,
        )

        # Open long on the first quote, flatten on the blackout-window quote.
        def emit(quote: NBBOQuote) -> None:
            direction = SignalDirection.LONG if quote.sequence == 1 else SignalDirection.FLAT
            bus.publish(_make_signal(quote, direction))

        bus.subscribe(NBBOQuote, emit)  # type: ignore[arg-type]

        q0 = _make_quote(ts=1000, seq=1)
        bt_router.on_quote(q0)
        orch._process_tick(q0)
        assert position_store.get("AAPL").quantity > 0

        orch._process_trade(self._trade(ts=1500, seq=2, conditions=self._HALT_ON))
        orch._process_trade(self._trade(ts=2000, seq=3, conditions=self._HALT_OFF))
        assert orch._in_halt_blackout("AAPL", 2500)

        # Exit during the blackout is always permitted → position closes.
        q_exit = _make_quote(ts=2500, seq=5)
        bt_router.on_quote(q_exit)
        orch._process_tick(q_exit)
        assert position_store.get("AAPL").quantity == 0


def _ssr_intent(
    intent: TradingIntent,
    direction: SignalDirection,
    *,
    current_quantity: int = 0,
    symbol: str = "AAPL",
) -> OrderIntent:
    sig = Signal(
        timestamp_ns=1000,
        correlation_id="c",
        sequence=1,
        symbol=symbol,
        strategy_id="s",
        direction=direction,
        strength=0.8,
        edge_estimate_bps=5.0,
    )
    return OrderIntent(
        intent=intent,
        symbol=symbol,
        strategy_id="s",
        target_quantity=10,
        current_quantity=current_quantity,
        signal=sig,
    )


class TestSSRBlocksIntent:
    """BT-6: _ssr_blocks_intent only refuses short-opening orders."""

    def _orch(self) -> Orchestrator:
        orch = _build_orchestrator(SimulatedClock(start_ns=1000))
        _boot_to_backtest(orch)
        orch._ssr_active = {"AAPL"}
        return orch

    def test_inactive_symbol_never_blocked(self) -> None:
        orch = _build_orchestrator(SimulatedClock(start_ns=1000))
        _boot_to_backtest(orch)  # _ssr_active empty
        assert not orch._ssr_blocks_intent(
            _ssr_intent(TradingIntent.ENTRY_SHORT, SignalDirection.SHORT),
        )

    def test_entry_short_blocked(self) -> None:
        assert self._orch()._ssr_blocks_intent(
            _ssr_intent(TradingIntent.ENTRY_SHORT, SignalDirection.SHORT),
        )

    def test_reverse_long_to_short_blocked(self) -> None:
        assert self._orch()._ssr_blocks_intent(
            _ssr_intent(
                TradingIntent.REVERSE_LONG_TO_SHORT,
                SignalDirection.SHORT,
                current_quantity=50,
            ),
        )

    def test_scale_up_short_blocked(self) -> None:
        assert self._orch()._ssr_blocks_intent(
            _ssr_intent(
                TradingIntent.SCALE_UP,
                SignalDirection.SHORT,
                current_quantity=-50,
            ),
        )

    def test_entry_long_allowed(self) -> None:
        assert not self._orch()._ssr_blocks_intent(
            _ssr_intent(TradingIntent.ENTRY_LONG, SignalDirection.LONG),
        )

    def test_exit_allowed(self) -> None:
        assert not self._orch()._ssr_blocks_intent(
            _ssr_intent(
                TradingIntent.EXIT,
                SignalDirection.FLAT,
                current_quantity=50,
            ),
        )

    def test_scale_up_long_allowed(self) -> None:
        assert not self._orch()._ssr_blocks_intent(
            _ssr_intent(
                TradingIntent.SCALE_UP,
                SignalDirection.LONG,
                current_quantity=50,
            ),
        )

    def test_reverse_short_to_long_allowed(self) -> None:
        assert not self._orch()._ssr_blocks_intent(
            _ssr_intent(
                TradingIntent.REVERSE_SHORT_TO_LONG,
                SignalDirection.LONG,
                current_quantity=-50,
            ),
        )


class TestSSRRefuseShort:
    """BT-6: end-to-end short-entry suppression under SSR."""

    @staticmethod
    def _trade(ts: int, seq: int, conditions: tuple[int, ...]) -> Trade:
        return Trade(
            timestamp_ns=ts,
            correlation_id=f"AAPL:{ts}:{seq}",
            sequence=seq,
            symbol="AAPL",
            price=Decimal("150.00"),
            size=100,
            exchange_timestamp_ns=ts - 100,
            conditions=conditions,
        )

    @staticmethod
    def _build(
        clock: SimulatedClock,
        bus: EventBus,
        position_store: MemoryPositionStore,
    ) -> tuple[Orchestrator, BacktestOrderRouter]:
        bt_router = BacktestOrderRouter(clock=clock)
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
        _boot_to_backtest(orch)
        return orch, bt_router

    def test_short_fills_when_ssr_inactive(self) -> None:
        # Control: without SSR a short entry fills (proves the gate is the
        # cause of suppression in the other tests).
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        position_store = MemoryPositionStore()
        orch, bt_router = self._build(clock, bus, position_store)
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.SHORT),
        )
        q = _make_quote(ts=1000, seq=1)
        bt_router.on_quote(q)
        orch._process_tick(q)
        assert position_store.get("AAPL").quantity < 0

    def test_daily_list_suppresses_short_entry(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)  # type: ignore[arg-type]
        position_store = MemoryPositionStore()
        orch, bt_router = self._build(clock, bus, position_store)
        orch._ssr_active = {"AAPL"}  # daily SSR list seed
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.SHORT),
        )
        q = _make_quote(ts=1000, seq=1)
        bt_router.on_quote(q)
        orch._process_tick(q)
        assert position_store.get("AAPL").quantity == 0
        assert any(a.alert_name == "ssr_short_suppressed" for a in alerts)

    def test_intraday_trigger_then_short_suppressed(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        position_store = MemoryPositionStore()
        orch, bt_router = self._build(clock, bus, position_store)
        orch._ssr_codes = frozenset({7})
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.SHORT),
        )

        # Tape trigger flips AAPL SSR-active.
        orch._process_trade(self._trade(ts=900, seq=1, conditions=(7,)))
        assert "AAPL" in orch._ssr_active

        q = _make_quote(ts=1000, seq=2)
        bt_router.on_quote(q)
        orch._process_tick(q)
        assert position_store.get("AAPL").quantity == 0

    def test_long_entry_and_long_exit_allowed_under_ssr(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        position_store = MemoryPositionStore()
        orch, bt_router = self._build(clock, bus, position_store)
        orch._ssr_active = {"AAPL"}

        # LONG entry is a BUY → never an SSR short sale → fills.
        def emit(quote: NBBOQuote) -> None:
            direction = SignalDirection.LONG if quote.sequence == 1 else SignalDirection.FLAT
            bus.publish(_make_signal(quote, direction))

        bus.subscribe(NBBOQuote, emit)  # type: ignore[arg-type]

        q0 = _make_quote(ts=1000, seq=1)
        bt_router.on_quote(q0)
        orch._process_tick(q0)
        assert position_store.get("AAPL").quantity > 0

        # Long-side EXIT (a sell to close a long) is not a short sale → fills.
        q1 = _make_quote(ts=2000, seq=2)
        bt_router.on_quote(q1)
        orch._process_tick(q1)
        assert position_store.get("AAPL").quantity == 0


class TestBorrowAvailability:
    """BT-7: locate-unavailable suppression + hard-tier HTB flag."""

    @staticmethod
    def _build(
        clock: SimulatedClock,
        bus: EventBus,
        position_store: MemoryPositionStore,
    ) -> tuple[Orchestrator, BacktestOrderRouter]:
        bt_router = BacktestOrderRouter(clock=clock)
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
        _boot_to_backtest(orch)
        return orch, bt_router

    def test_unavailable_suppresses_short_entry(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)  # type: ignore[arg-type]
        position_store = MemoryPositionStore()
        orch, bt_router = self._build(clock, bus, position_store)
        orch._borrow_tier = {"AAPL": BorrowTier.UNAVAILABLE}
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.SHORT),
        )
        q = _make_quote(ts=1000, seq=1)
        bt_router.on_quote(q)
        orch._process_tick(q)
        assert position_store.get("AAPL").quantity == 0
        assert any(a.alert_name == "locate_unavailable" for a in alerts)

    def test_available_allows_short_fill(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        position_store = MemoryPositionStore()
        orch, bt_router = self._build(clock, bus, position_store)
        orch._borrow_tier = {"AAPL": BorrowTier.AVAILABLE}
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.SHORT),
        )
        q = _make_quote(ts=1000, seq=1)
        bt_router.on_quote(q)
        orch._process_tick(q)
        assert position_store.get("AAPL").quantity < 0

    def test_hard_tier_sets_is_short_on_order(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        orders: list[OrderRequest] = []
        bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]
        position_store = MemoryPositionStore()
        orch, bt_router = self._build(clock, bus, position_store)
        orch._borrow_tier = {"AAPL": BorrowTier.HARD}
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.SHORT),
        )
        q = _make_quote(ts=1000, seq=1)
        bt_router.on_quote(q)
        orch._process_tick(q)
        assert orders
        assert orders[0].is_short is True

    def test_available_tier_omits_is_short_on_short_entry(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        orders: list[OrderRequest] = []
        bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]
        position_store = MemoryPositionStore()
        orch, bt_router = self._build(clock, bus, position_store)
        orch._borrow_tier = {"AAPL": BorrowTier.AVAILABLE}
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.SHORT),
        )
        q = _make_quote(ts=1000, seq=1)
        bt_router.on_quote(q)
        orch._process_tick(q)
        assert orders
        assert orders[0].is_short is False

    def test_long_entry_allowed_when_unavailable(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        position_store = MemoryPositionStore()
        orch, bt_router = self._build(clock, bus, position_store)
        orch._borrow_tier = {"AAPL": BorrowTier.UNAVAILABLE}
        _publish_signal_on_quote(
            bus,
            _make_signal(_make_quote(), SignalDirection.LONG),
        )
        q = _make_quote(ts=1000, seq=1)
        bt_router.on_quote(q)
        orch._process_tick(q)
        assert position_store.get("AAPL").quantity > 0
