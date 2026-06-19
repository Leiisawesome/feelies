"""Strategy-ownership filter for standalone SIGNAL arbitration."""

from __future__ import annotations

from decimal import Decimal

from dataclasses import replace

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderRequest,
    Signal,
    SignalDirection,
)
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import ZeroCostModel
from feelies.kernel.orchestrator import (
    Orchestrator,
    collision_is_harmless_flat_gate_close,
    is_redundant_gate_close_flat,
    standalone_signal_actionable_for_strategy,
)
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.storage.memory_event_log import InMemoryEventLog

from tests.kernel.test_orchestrator_bus_signal import (
    _NoOpMetricCollector,
    _StubMarketData,
    _StubRiskEngine,
    _boot_to_backtest,
    _make_quote,
    _make_signal,
)


class TestStandaloneSignalActionableForStrategy:
    def test_gate_close_flat_requires_strategy_position(self) -> None:
        assert not standalone_signal_actionable_for_strategy(
            _flat_signal(),
            strategy_qty=0,
            aggregate_qty=-50,
            alpha_has_prior_fill=False,
        )
        assert standalone_signal_actionable_for_strategy(
            _flat_signal(),
            strategy_qty=-50,
            aggregate_qty=-50,
            alpha_has_prior_fill=True,
        )

    def test_gate_close_flat_allowed_when_book_flat(self) -> None:
        assert standalone_signal_actionable_for_strategy(
            _flat_signal(),
            strategy_qty=0,
            aggregate_qty=0,
            alpha_has_prior_fill=False,
        )

    def test_gate_close_flat_allowed_after_alpha_has_filled(self) -> None:
        assert standalone_signal_actionable_for_strategy(
            _flat_signal(),
            strategy_qty=0,
            aggregate_qty=-50,
            alpha_has_prior_fill=True,
        )

    def test_offsetting_direction_requires_strategy_exposure(self) -> None:
        sig = _flat_signal(direction=SignalDirection.LONG)
        assert not standalone_signal_actionable_for_strategy(
            sig,
            strategy_qty=0,
            aggregate_qty=-50,
            alpha_has_prior_fill=False,
        )
        assert standalone_signal_actionable_for_strategy(
            sig,
            strategy_qty=-50,
            aggregate_qty=-50,
            alpha_has_prior_fill=True,
        )

    def test_entry_allowed_without_strategy_position(self) -> None:
        sig = _flat_signal(direction=SignalDirection.SHORT)
        assert standalone_signal_actionable_for_strategy(
            sig,
            strategy_qty=0,
            aggregate_qty=-50,
            alpha_has_prior_fill=False,
        )


class TestOrchestratorStrategyOwnershipFilter:
    def test_passive_alpha_flat_does_not_hijack_exit(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        aggregate = MemoryPositionStore()
        aggregate.update("AAPL", -50, Decimal("150.00"))
        strategy_positions = StrategyPositionStore()
        strategy_positions.update(
            "alpha_owner",
            "AAPL",
            -50,
            Decimal("150.00"),
        )
        orch = _orch(clock, bus, aggregate, strategy_positions)
        captured: list[OrderRequest] = []

        def capture_order(event: OrderRequest) -> None:
            captured.append(event)

        bus.subscribe(OrderRequest, capture_order)  # type: ignore[arg-type]

        hijacker_flat = replace(
            _make_signal(
                quote,
                strategy_id="passive_alpha",
                direction=SignalDirection.FLAT,
            ),
            regime_gate_state="OFF",
        )

        def emit_hijacker(q: NBBOQuote) -> None:
            bus.publish(
                replace(
                    hijacker_flat,
                    timestamp_ns=q.timestamp_ns,
                    correlation_id=q.correlation_id,
                    sequence=q.sequence,
                )
            )

        bus.subscribe(NBBOQuote, emit_hijacker)  # type: ignore[arg-type]

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert captured == []

    def test_owner_flat_still_exits(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        aggregate = MemoryPositionStore()
        aggregate.update("AAPL", -50, Decimal("150.00"))
        strategy_positions = StrategyPositionStore()
        strategy_positions.update(
            "alpha_owner",
            "AAPL",
            -50,
            Decimal("150.00"),
        )
        orch = _orch(clock, bus, aggregate, strategy_positions)
        captured: list[OrderRequest] = []

        def capture_order(event: OrderRequest) -> None:
            captured.append(event)

        bus.subscribe(OrderRequest, capture_order)  # type: ignore[arg-type]

        owner_flat = replace(
            _make_signal(
                quote,
                strategy_id="alpha_owner",
                direction=SignalDirection.FLAT,
            ),
            regime_gate_state="OFF",
        )

        def emit_owner(q: NBBOQuote) -> None:
            bus.publish(
                replace(
                    owner_flat,
                    timestamp_ns=q.timestamp_ns,
                    correlation_id=q.correlation_id,
                    sequence=q.sequence,
                )
            )

        bus.subscribe(NBBOQuote, emit_owner)  # type: ignore[arg-type]

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._alpha_symbols_with_fills.add(("alpha_owner", "AAPL"))
        orch._process_tick(quote)

        assert len(captured) == 1
        assert captured[0].strategy_id == "alpha_owner"


class TestRedundantGateCloseFlat:
    def test_helper_detects_inert_gate_close(self) -> None:
        sig = _flat_signal()
        assert is_redundant_gate_close_flat(
            sig,
            aggregate_qty=0,
            alpha_has_prior_fill=False,
        )
        assert not is_redundant_gate_close_flat(
            sig,
            aggregate_qty=-50,
            alpha_has_prior_fill=False,
        )
        assert not is_redundant_gate_close_flat(
            sig,
            aggregate_qty=0,
            alpha_has_prior_fill=True,
        )

    def test_redundant_gate_close_not_buffered(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        aggregate = MemoryPositionStore()
        orch = _orch(clock, bus, aggregate, StrategyPositionStore())

        passive_flat = replace(
            _make_signal(
                quote,
                strategy_id="passive_alpha",
                direction=SignalDirection.FLAT,
            ),
            regime_gate_state="OFF",
        )

        def emit_passive(q: NBBOQuote) -> None:
            bus.publish(
                replace(
                    passive_flat,
                    timestamp_ns=q.timestamp_ns,
                    correlation_id=q.correlation_id,
                    sequence=q.sequence,
                )
            )

        bus.subscribe(NBBOQuote, emit_passive)  # type: ignore[arg-type]

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._process_tick(quote)

        assert orch._signal_buffer == []


class TestArbitrationCollisionForensics:
    def test_harmless_flat_gate_close_collision_logged_at_debug(self, caplog) -> None:
        import logging

        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        quote = _make_quote()
        aggregate = MemoryPositionStore()
        orch = _orch(clock, bus, aggregate, StrategyPositionStore())

        flat_a = replace(
            _make_signal(
                quote,
                strategy_id="alpha_a",
                direction=SignalDirection.FLAT,
            ),
            regime_gate_state="OFF",
        )
        flat_b = replace(
            _make_signal(
                quote,
                strategy_id="alpha_b",
                direction=SignalDirection.FLAT,
            ),
            regime_gate_state="OFF",
        )

        def emit_both(q: NBBOQuote) -> None:
            for sig in (flat_a, flat_b):
                bus.publish(
                    replace(
                        sig,
                        timestamp_ns=q.timestamp_ns,
                        correlation_id=q.correlation_id,
                        sequence=q.sequence,
                    )
                )

        bus.subscribe(NBBOQuote, emit_both)  # type: ignore[arg-type]

        BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
        _boot_to_backtest(orch)
        orch._alpha_symbols_with_fills.add(("alpha_a", "AAPL"))
        orch._alpha_symbols_with_fills.add(("alpha_b", "AAPL"))

        with caplog.at_level(logging.DEBUG, logger="feelies.kernel.orchestrator"):
            orch._process_tick(quote)

        assert len(orch.arbitration_collisions) == 1
        assert orch.arbitration_collisions[0].harmless is True
        assert any(
            "gate-close FLAT" in r.message for r in caplog.records if r.levelname == "DEBUG"
        )
        assert not any(r.levelname == "WARNING" for r in caplog.records)

    def test_collision_is_harmless_flat_gate_close_helper(self) -> None:
        sigs = (
            _flat_signal(),
            replace(_flat_signal(), strategy_id="alpha_b"),
        )
        assert collision_is_harmless_flat_gate_close(sigs, 0)
        assert not collision_is_harmless_flat_gate_close(sigs, -50)


def _flat_signal(*, direction: SignalDirection = SignalDirection.FLAT) -> Signal:
    return Signal(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        strategy_id="alpha_a",
        direction=direction,
        strength=0.0,
        edge_estimate_bps=0.0,
        regime_gate_state="OFF",
    )


def _orch(
    clock: SimulatedClock,
    bus: EventBus,
    aggregate: MemoryPositionStore,
    strategy_positions: StrategyPositionStore,
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
        risk_engine=_StubRiskEngine(),
        position_store=aggregate,
        strategy_positions=strategy_positions,
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
    )
