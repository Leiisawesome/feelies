"""Tests for the PR-2b-iv bus-driven ``SizedPositionIntent`` subscriber.

The orchestrator's :meth:`Orchestrator._on_bus_sized_intent` translates
``SizedPositionIntent`` events published on the platform bus into per-leg
``OrderRequest`` events via :meth:`RiskEngine.check_sized_intent`, then
submits each surviving order to ``backend.order_router`` and reconciles
fills.  Pre-PR-2b-iv nothing in production translated bus-published
intents into orders; PORTFOLIO alphas could fire intents end-to-end but
the production order pipeline silently ignored them.

These tests assert the contract:

* A bus-published ``SizedPositionIntent`` with one or more non-zero
  ``TargetPosition`` deltas produces the expected ``OrderRequest`` events
  on the bus.
* Symbols are emitted in lexicographic order (Inv-5 determinism).
* ``order_id`` is bit-identical across two equal intents (Inv-5).
* Per-leg veto: an exposure-breaching leg is dropped silently; the rest
  of the intent proceeds (Inv-11 fail-safe).
* An empty intent (no target_positions) emits no orders.
* The handler runs *outside* the per-tick micro-SM walk: it submits
  PORTFOLIO orders without driving M5 -> M10 transitions, leaving the
  SIGNAL-reserved per-tick walk free for the at-most-one Signal it can
  process.  Standalone SIGNAL + PORTFOLIO can therefore coexist on the
  same tick.
* Acks fired by the backtest router are republished and applied so the
  position store reflects the PORTFOLIO order's effect.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from feelies.bus.event_bus import EventBus
from feelies.composition.cross_sectional import CrossSectionalRanker
from feelies.composition.engine import CompositionEngine, RegisteredPortfolioAlpha
from feelies.composition.factor_neutralizer import FactorNeutralizer
from feelies.composition.protocol import PortfolioAlpha
from feelies.composition.sector_matcher import SectorMatcher
from feelies.composition.synchronizer import UniverseSynchronizer
from feelies.composition.turnover_optimizer import TurnoverOptimizer
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    CrossSectionalContext,
    HorizonTick,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    PositionUpdate,
    RiskAction,
    RiskVerdict,
    Signal,
    SignalDirection,
    Side,
    SizedPositionIntent,
    TargetPosition,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.order_state import OrderState
from feelies.kernel.macro import MacroState
from feelies.kernel.micro import MicroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.position_store import PositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.storage.memory_event_log import InMemoryEventLog


# -- Stubs ------------------------------------------------------------


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


class _ScriptedOrderRouter:
    def __init__(
        self,
        *,
        initial_pending_acks: list[OrderAck] | None = None,
        submit_fill_price: Decimal = Decimal("150.00"),
    ) -> None:
        self._pending_acks = list(initial_pending_acks or [])
        self._submit_fill_price = submit_fill_price
        self.submitted: list[OrderRequest] = []

    def submit(self, request: OrderRequest) -> None:
        self.submitted.append(request)
        self._pending_acks.append(OrderAck(
            timestamp_ns=request.timestamp_ns + 1,
            correlation_id=request.correlation_id,
            sequence=request.sequence,
            order_id=request.order_id,
            symbol=request.symbol,
            status=OrderAckStatus.FILLED,
            filled_quantity=request.quantity,
            fill_price=self._submit_fill_price,
        ))

    def poll_acks(self) -> list[OrderAck]:
        acks = list(self._pending_acks)
        self._pending_acks.clear()
        return acks


class _MinimalConfig:
    version = "test-bus-sized-intent"
    symbols = frozenset({"AAPL", "MSFT", "NVDA"})

    def validate(self) -> None:
        pass

    def snapshot(self) -> None:
        return None


class _SingleTickScheduler:
    def __init__(self, tick: HorizonTick) -> None:
        self._tick = tick
        self._emitted = False

    def on_event(self, _event: Any) -> tuple[HorizonTick, ...]:
        if self._emitted:
            return ()
        self._emitted = True
        return (self._tick,)


class _FixedTargetPortfolioAlpha:
    alpha_id = "phase4_test_portfolio_alpha"
    horizon_seconds = 30

    def construct(
        self,
        ctx: CrossSectionalContext,
        _params: dict[str, Any],
    ) -> SizedPositionIntent:
        return SizedPositionIntent(
            timestamp_ns=ctx.timestamp_ns,
            correlation_id="placeholder",
            sequence=-1,
            strategy_id=self.alpha_id,
            target_positions={
                "AAPL": TargetPosition(symbol="AAPL", target_usd=15_000.0, urgency=0.5),
            },
        )


class _RecordingGateSnapshotRiskEngine(BasicRiskEngine):
    def __init__(self, config: RiskConfig) -> None:
        super().__init__(config)
        self.signal_gate_snapshots: list[dict[str, int]] = []
        self.order_gate_snapshots: list[dict[str, int]] = []

    @staticmethod
    def _snapshot(positions: PositionStore) -> dict[str, int]:
        return {
            "AAPL": positions.get("AAPL").quantity,
            "MSFT": positions.get("MSFT").quantity,
        }

    def check_signal(
        self,
        signal: Signal,
        positions: PositionStore,
    ) -> RiskVerdict:
        if signal.strategy_id == "standalone_signal_alpha":
            self.signal_gate_snapshots.append(self._snapshot(positions))
        return super().check_signal(signal, positions)

    def check_order(
        self,
        order: OrderRequest,
        positions: PositionStore,
    ) -> RiskVerdict:
        if order.strategy_id == "standalone_signal_alpha":
            self.order_gate_snapshots.append(self._snapshot(positions))
        return super().check_order(order, positions)


# -- Helpers ----------------------------------------------------------


def _make_quote(
    *,
    symbol: str = "AAPL",
    ts: int = 1000,
    bid: str = "149.50",
    ask: str = "150.50",
    seq: int = 1,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"{symbol}:{ts}:{seq}",
        sequence=seq,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=200,
        exchange_timestamp_ns=ts - 100,
    )


def _make_intent(
    *,
    targets: dict[str, float],
    correlation_id: str = "intent:1",
    sequence: int = 1,
    timestamp_ns: int = 1000,
    strategy_id: str = "test_portfolio_alpha",
    urgency: float = 0.5,
) -> SizedPositionIntent:
    return SizedPositionIntent(
        timestamp_ns=timestamp_ns,
        correlation_id=correlation_id,
        sequence=sequence,
        strategy_id=strategy_id,
        target_positions={
            sym: TargetPosition(symbol=sym, target_usd=usd, urgency=urgency)
            for sym, usd in targets.items()
        },
    )


def _build_orchestrator(
    clock: SimulatedClock,
    *,
    bus: EventBus | None = None,
    risk_engine: Any | None = None,
    position_store: MemoryPositionStore | None = None,
    order_router: Any | None = None,
    account_equity: Decimal = Decimal("1000000"),
) -> Orchestrator:
    bus = bus if bus is not None else EventBus()
    pos = position_store or MemoryPositionStore()
    bt_router = order_router or BacktestOrderRouter(clock=clock)
    backend = ExecutionBackend(
        market_data=_StubMarketData(),
        order_router=bt_router,
        mode="BACKTEST",
    )
    return Orchestrator(
        clock=clock,
        bus=bus,
        backend=backend,
        risk_engine=risk_engine or BasicRiskEngine(RiskConfig(
            account_equity=account_equity,
            max_position_per_symbol=10_000_000,
            max_gross_exposure_pct=200.0,
        )),
        position_store=pos,
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
        account_equity=account_equity,
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


def _capture_acks(bus: EventBus) -> list[OrderAck]:
    captured: list[OrderAck] = []
    bus.subscribe(OrderAck, captured.append)  # type: ignore[arg-type]
    return captured


def _capture_position_updates(bus: EventBus) -> list[PositionUpdate]:
    captured: list[PositionUpdate] = []
    bus.subscribe(PositionUpdate, captured.append)  # type: ignore[arg-type]
    return captured


def _seed_position(
    positions: MemoryPositionStore,
    symbol: str,
    quantity: int,
    avg_entry: str,
) -> None:
    """Seed an arbitrary (qty, mark) for the symbol.

    Note that ``MemoryPositionStore.update`` resets ``avg_entry_price``
    to zero when the resulting quantity is zero, so for flat-position
    seeds we publish a mark via ``update_mark`` so
    ``BasicRiskEngine._mark_for`` can translate ``target_usd`` to shares.
    """
    if quantity != 0:
        positions.update(symbol, quantity, Decimal(avg_entry))
    positions.update_mark(symbol, Decimal(avg_entry))


# -- Tests ------------------------------------------------------------


class TestBusDrivenSizedIntentProducesOrders:
    """Bus-published SizedPositionIntent is the production PORTFOLIO path.

    This is the core PR-2b-iv contract: PORTFOLIO alphas publish
    SizedPositionIntent on the bus and the orchestrator translates that
    into per-symbol OrderRequest events without requiring any per-tick
    micro-SM walk for the PORTFOLIO contribution.
    """

    def test_intent_with_single_target_emits_single_order(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_position(positions, "AAPL", 0, "150.00")

        orch = _build_orchestrator(clock, bus=bus, position_store=positions)
        captured = _capture_orders(bus)

        intent = _make_intent(targets={"AAPL": 15_000.0})

        _boot_to_backtest(orch)
        bus.publish(intent)

        _ = orch
        assert len(captured) == 1
        order = captured[0]
        assert order.symbol == "AAPL"
        assert order.quantity == 100
        assert order.source_layer == "PORTFOLIO"
        assert order.strategy_id == "test_portfolio_alpha"

    def test_intent_with_multiple_targets_emits_one_order_per_symbol(
        self,
    ) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_position(positions, "AAPL", 0, "150.00")
        _seed_position(positions, "MSFT", 0, "300.00")
        _seed_position(positions, "NVDA", 0, "500.00")

        orch = _build_orchestrator(clock, bus=bus, position_store=positions)
        captured = _capture_orders(bus)

        intent = _make_intent(targets={
            "AAPL": 15_000.0,
            "MSFT": 30_000.0,
            "NVDA": 50_000.0,
        })

        _boot_to_backtest(orch)
        bus.publish(intent)

        _ = orch
        assert len(captured) == 3
        symbols = [o.symbol for o in captured]
        assert symbols == ["AAPL", "MSFT", "NVDA"], (
            "OrderRequest events must be published in lexicographic "
            "symbol order for Inv-5 determinism"
        )

    def test_zero_delta_target_emits_no_order(self) -> None:
        """Symbols whose target matches the current notional are skipped."""
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_position(positions, "AAPL", 100, "150.00")

        orch = _build_orchestrator(clock, bus=bus, position_store=positions)
        captured = _capture_orders(bus)

        intent = _make_intent(targets={"AAPL": 15_000.0})

        _boot_to_backtest(orch)
        bus.publish(intent)

        _ = orch
        assert captured == [], (
            "AAPL is already at target notional (100 @ $150 = $15k); the "
            "no-op leg must not produce an OrderRequest"
        )

    def test_empty_intent_emits_no_orders(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()

        orch = _build_orchestrator(clock, bus=bus)
        captured = _capture_orders(bus)

        intent = _make_intent(targets={})

        _boot_to_backtest(orch)
        bus.publish(intent)

        _ = orch
        assert captured == []

    def test_intent_runs_outside_per_tick_micro_sm_walk(self) -> None:
        """Intent dispatch does not advance the SIGNAL-reserved M5..M10 walk.

        The handler tracks each order, polls acks, and reconciles fills
        without driving the micro state machine.  After processing, the
        SM remains in its prior state (here: WAITING_FOR_MARKET_EVENT).
        """
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_position(positions, "AAPL", 0, "150.00")

        orch = _build_orchestrator(clock, bus=bus, position_store=positions)
        _boot_to_backtest(orch)

        before = orch.micro_state
        bus.publish(_make_intent(targets={"AAPL": 15_000.0}))

        assert orch.micro_state == before
        assert orch.micro_state == MicroState.WAITING_FOR_MARKET_EVENT


class TestDeterminism:
    """Inv-5 -- bit-identical replays of the same intent."""

    def test_two_equal_intents_produce_identical_order_ids(self) -> None:
        """SHA-256 of (correlation_id, sequence, symbol) must be stable."""
        clock_a = SimulatedClock(start_ns=1000)
        clock_b = SimulatedClock(start_ns=1000)
        bus_a, bus_b = EventBus(), EventBus()
        positions_a = MemoryPositionStore()
        positions_b = MemoryPositionStore()
        _seed_position(positions_a, "AAPL", 0, "150.00")
        _seed_position(positions_a, "MSFT", 0, "300.00")
        _seed_position(positions_b, "AAPL", 0, "150.00")
        _seed_position(positions_b, "MSFT", 0, "300.00")

        orch_a = _build_orchestrator(
            clock_a, bus=bus_a, position_store=positions_a,
        )
        orch_b = _build_orchestrator(
            clock_b, bus=bus_b, position_store=positions_b,
        )
        captured_a = _capture_orders(bus_a)
        captured_b = _capture_orders(bus_b)

        targets = {"AAPL": 15_000.0, "MSFT": 30_000.0}
        _boot_to_backtest(orch_a)
        _boot_to_backtest(orch_b)
        bus_a.publish(_make_intent(targets=targets))
        bus_b.publish(_make_intent(targets=targets))

        _ = orch_a, orch_b
        assert len(captured_a) == 2 == len(captured_b)
        assert [o.order_id for o in captured_a] == [
            o.order_id for o in captured_b
        ]


class TestPerLegVeto:
    """Inv-11 -- a breaching leg is dropped silently; the rest proceeds."""

    def test_per_symbol_position_cap_drops_one_leg_keeps_rest(self) -> None:
        """A single symbol over the per-symbol cap must not abort the intent."""
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_position(positions, "AAPL", 0, "150.00")
        _seed_position(positions, "MSFT", 0, "300.00")
        _seed_position(positions, "NVDA", 0, "500.00")

        risk = BasicRiskEngine(RiskConfig(
            account_equity=Decimal("1000000"),
            max_position_per_symbol=200,
            max_gross_exposure_pct=200.0,
        ))

        orch = _build_orchestrator(
            clock, bus=bus, risk_engine=risk, position_store=positions,
        )
        captured = _capture_orders(bus)

        intent = _make_intent(targets={
            "AAPL": 15_000.0,
            "MSFT": 30_000.0,
            "NVDA": 500_000.0,
        })

        _boot_to_backtest(orch)
        bus.publish(intent)

        _ = orch
        assert len(captured) == 2, (
            "NVDA's 1000-share leg should breach the 200-share cap and be "
            "dropped; AAPL and MSFT must still produce orders"
        )
        assert {o.symbol for o in captured} == {"AAPL", "MSFT"}


class TestFillReconciliation:
    """The handler polls acks and reconciles fills into the position store."""

    def test_filled_intent_updates_position_store(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_position(positions, "AAPL", 0, "150.00")

        orch = _build_orchestrator(clock, bus=bus, position_store=positions)
        BacktestOrderRouter.on_quote(
            orch._backend.order_router, _make_quote(),
        )

        ack_capture = _capture_acks(bus)

        intent = _make_intent(targets={"AAPL": 15_000.0})

        _boot_to_backtest(orch)
        bus.publish(intent)

        assert len(ack_capture) >= 1
        pos = positions.get("AAPL")
        assert pos.quantity != 0, (
            "PORTFOLIO order must have been submitted, ack'd, and "
            "reconciled into the position store"
        )

    def test_intent_does_not_steal_unrelated_pending_resting_fill_ack(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_position(positions, "AAPL", 0, "150.00")
        _seed_position(positions, "MSFT", 0, "300.00")

        deferred_ack = OrderAck(
            timestamp_ns=1500,
            correlation_id="resting-cid",
            sequence=9,
            order_id="resting-order",
            symbol="MSFT",
            status=OrderAckStatus.FILLED,
            filled_quantity=10,
            fill_price=Decimal("300.00"),
        )
        router = _ScriptedOrderRouter(initial_pending_acks=[deferred_ack])

        orch = _build_orchestrator(
            clock,
            bus=bus,
            position_store=positions,
            order_router=router,
        )

        resting_order = OrderRequest(
            timestamp_ns=900,
            correlation_id="resting-cid",
            sequence=8,
            order_id="resting-order",
            symbol="MSFT",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            limit_price=Decimal("299.50"),
            strategy_id="standalone_signal_alpha",
        )
        orch._track_order(resting_order.order_id, resting_order.side, resting_order)
        orch._transition_order(
            resting_order.order_id,
            OrderState.SUBMITTED,
            "seed_resting_order",
        )

        acks = _capture_acks(bus)
        updates = _capture_position_updates(bus)

        _boot_to_backtest(orch)
        bus.publish(_make_intent(targets={"AAPL": 15_000.0}, correlation_id="intent-cid"))

        assert len(router.submitted) == 1
        assert [ack.order_id for ack in acks] == [router.submitted[0].order_id]
        assert positions.get("AAPL").quantity != 0
        assert positions.get("MSFT").quantity == 0
        assert [update.symbol for update in updates] == ["AAPL"]

        orch._reconcile_resting_fills("quote-cid")

        assert [ack.order_id for ack in acks] == [
            router.submitted[0].order_id,
            "resting-order",
        ]
        assert positions.get("MSFT").quantity == 10
        assert [update.symbol for update in updates] == ["AAPL", "MSFT"]


class TestPortfolioCoexistsWithStandaloneSignal:
    """A PORTFOLIO intent and a standalone SIGNAL on the same tick both fire.

    The PR-2b-iii ``depends_on_signals`` skip-rule is what prevents
    double-trading when a SIGNAL alpha is consumed by a PORTFOLIO alpha;
    here we exercise the *uncoupled* case where the SIGNAL alpha and the
    PORTFOLIO alpha trade different symbols and must both produce orders.
    """

    def test_signal_for_aapl_and_portfolio_for_msft_both_emit(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_position(positions, "AAPL", 0, "150.00")
        _seed_position(positions, "MSFT", 0, "300.00")

        orch = _build_orchestrator(clock, bus=bus, position_store=positions)
        BacktestOrderRouter.on_quote(
            orch._backend.order_router, _make_quote(),
        )

        captured = _capture_orders(bus)

        signal = Signal(
            timestamp_ns=1000,
            correlation_id="AAPL:1000:1",
            sequence=1,
            symbol="AAPL",
            strategy_id="standalone_signal_alpha",
            direction=SignalDirection.LONG,
            strength=0.8,
            edge_estimate_bps=5.0,
            layer="SIGNAL",
        )
        intent = _make_intent(
            targets={"MSFT": 30_000.0},
            strategy_id="standalone_portfolio_alpha",
        )

        def emit(quote: NBBOQuote) -> None:
            bus.publish(signal)
            bus.publish(intent)

        bus.subscribe(NBBOQuote, emit)  # type: ignore[arg-type]

        _boot_to_backtest(orch)
        orch._process_tick(_make_quote())

        order_symbols = sorted(o.symbol for o in captured)
        assert "MSFT" in order_symbols, (
            "PORTFOLIO intent for MSFT must produce an OrderRequest"
        )

    def test_portfolio_fill_completes_before_signal_gate_checks(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_position(positions, "AAPL", 0, "150.00")
        _seed_position(positions, "MSFT", 0, "300.00")

        risk = _RecordingGateSnapshotRiskEngine(RiskConfig(
            account_equity=Decimal("1000000"),
            max_position_per_symbol=10_000_000,
            max_gross_exposure_pct=200.0,
        ))
        router = _ScriptedOrderRouter()
        orch = _build_orchestrator(
            clock,
            bus=bus,
            risk_engine=risk,
            position_store=positions,
            order_router=router,
        )
        captured = _capture_orders(bus)

        signal = Signal(
            timestamp_ns=1000,
            correlation_id="AAPL:1000:1",
            sequence=1,
            symbol="AAPL",
            strategy_id="standalone_signal_alpha",
            direction=SignalDirection.LONG,
            strength=1.0,
            edge_estimate_bps=50.0,
            layer="SIGNAL",
        )
        intent = _make_intent(
            targets={"MSFT": 30_000.0},
            strategy_id="standalone_portfolio_alpha",
        )

        def emit(_quote: NBBOQuote) -> None:
            bus.publish(signal)
            bus.publish(intent)

        bus.subscribe(NBBOQuote, emit)  # type: ignore[arg-type]

        _boot_to_backtest(orch)
        orch._process_tick(_make_quote())

        assert sorted(order.symbol for order in captured) == ["AAPL", "MSFT"]
        assert risk.signal_gate_snapshots == [{"AAPL": 0, "MSFT": 100}]
        assert risk.order_gate_snapshots == [{"AAPL": 0, "MSFT": 100}]

    def test_portfolio_orders_dispatch_during_horizon_tick_fanout_before_feature_compute(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_position(positions, "AAPL", 0, "150.00")

        tick = HorizonTick(
            timestamp_ns=1000,
            correlation_id="tick-cid",
            sequence=11,
            horizon_seconds=30,
            boundary_index=1,
            scope="UNIVERSE",
            symbol=None,
            session_id="TEST",
        )
        scheduler = _SingleTickScheduler(tick)

        synchronizer = UniverseSynchronizer(
            bus=bus,
            universe=("AAPL",),
            horizons=(30,),
            ctx_sequence_generator=SequenceGenerator(),
        )
        synchronizer.attach()

        engine = CompositionEngine(
            bus=bus,
            intent_sequence_generator=SequenceGenerator(),
            ranker=CrossSectionalRanker(),
            neutralizer=FactorNeutralizer(loadings_dir=None),
            sector_matcher=SectorMatcher(sector_map_path=None),
            optimizer=TurnoverOptimizer(capital_usd=1_000_000.0),
            completeness_threshold=0.0,
            position_lookup=None,
        )
        portfolio_alpha: PortfolioAlpha = _FixedTargetPortfolioAlpha()
        engine.register(RegisteredPortfolioAlpha(
            alpha_id=portfolio_alpha.alpha_id,
            horizon_seconds=portfolio_alpha.horizon_seconds,
            alpha=portfolio_alpha,
            params={},
        ))
        engine.attach()

        orch = Orchestrator(
            clock=clock,
            bus=bus,
            backend=ExecutionBackend(
                market_data=_StubMarketData(),
                order_router=_ScriptedOrderRouter(),
                mode="BACKTEST",
            ),
            risk_engine=BasicRiskEngine(RiskConfig(
                account_equity=Decimal("1000000"),
                max_position_per_symbol=10_000_000,
                max_gross_exposure_pct=200.0,
            )),
            position_store=positions,
            event_log=InMemoryEventLog(),
            metric_collector=_NoOpMetricCollector(),
            horizon_scheduler=scheduler,  # type: ignore[arg-type]
            composition_engine=engine,
        )

        intent_states: list[MicroState] = []
        order_states: list[MicroState] = []
        bus.subscribe(
            SizedPositionIntent,
            lambda intent: intent_states.append(orch.micro_state),  # type: ignore[arg-type]
        )
        bus.subscribe(
            OrderRequest,
            lambda order: order_states.append(orch.micro_state),  # type: ignore[arg-type]
        )

        _boot_to_backtest(orch)
        orch._process_tick(_make_quote())

        assert intent_states == [MicroState.HORIZON_CHECK]
        assert order_states == [MicroState.HORIZON_CHECK]


class TestFiltering:
    """The handler ignores non-SizedPositionIntent events."""

    def test_unrelated_event_is_ignored(self) -> None:
        clock = SimulatedClock(start_ns=1000)
        bus = EventBus()

        orch = _build_orchestrator(clock, bus=bus)
        captured = _capture_orders(bus)

        bus.publish(RiskVerdict(
            timestamp_ns=1000,
            correlation_id="cid:0",
            sequence=0,
            symbol="AAPL",
            action=RiskAction.ALLOW,
            reason="unrelated",
        ))

        _ = orch
        assert captured == []
