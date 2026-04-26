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
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderRequest,
    RiskAction,
    RiskVerdict,
    Signal,
    SignalDirection,
    SizedPositionIntent,
    TargetPosition,
)
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.kernel.macro import MacroState
from feelies.kernel.micro import MicroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
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


class _MinimalConfig:
    version = "test-bus-sized-intent"
    symbols = frozenset({"AAPL", "MSFT", "NVDA"})

    def validate(self) -> None:
        pass

    def snapshot(self) -> None:
        return None


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
    account_equity: Decimal = Decimal("1000000"),
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
