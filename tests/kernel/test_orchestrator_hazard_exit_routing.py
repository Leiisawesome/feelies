"""The orchestrator must route bus-published hazard ``OrderRequest``
events to ``backend.order_router.submit``.

Pre-R1 ``HazardExitController._emit_exit`` only called
``self._bus.publish(order)``; no production component subscribed to
``OrderRequest`` and bridged to a router, so the entire hazard-exit
subsystem was inert in any composed deployment (the only existing
subscriber was ``HorizonMetricsCollector`` for metrics).

These tests assert the post-R1 contract:

* A bus-published ``OrderRequest`` with the controller's signature
  (``source_layer="RISK"`` AND ``reason in {"HAZARD_SPIKE",
  "HARD_EXIT_AGE"}``) is submitted to the router and reconciled into
  the position store.
* PORTFOLIO and SIGNAL ``OrderRequest`` events that are *also*
  published on the bus (by the orchestrator's own dispatch sites)
  must NOT be re-submitted by the hazard handler — preventing the
  obvious double-fill regression.
* The handler is idempotent against duplicate publishes of the same
  ``order_id`` (defence in depth — the controller already enforces
  episode-suppression).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    Alert,
    AlertSeverity,
    DeRiskRequirement,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    PositionUpdate,
    RiskAction,
    RiskVerdict,
    Side,
)
from feelies.execution.backend import ExecutionBackend
from feelies.execution.order_state import OrderState
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.kernel import orchestrator as _orchestrator_mod
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.risk.hazard_exit import HAZARD_EXIT_REASONS, HAZARD_EXIT_SOURCE_LAYER
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.storage.memory_trade_journal import InMemoryTradeJournal


class _NoOpMetricCollector:
    def record(self, _metric: Any) -> None:
        pass

    def flush(self) -> None:
        pass


class _StubMarketData:
    def events(self):
        return iter([])


class _RecordingRouter:
    """Minimal OrderRouter that fills every order at the submitted side.

    Matches the ``BacktestOrderRouter`` ack shape — ACKNOWLEDGED then
    FILLED — so the orchestrator's reconcile path doesn't get
    surprised by a single-ack flow.
    """

    def __init__(self, fill_price: Decimal = Decimal("150.00")) -> None:
        self.submitted: list[OrderRequest] = []
        self._pending: list[OrderAck] = []
        self._fill_price = fill_price

    def submit(
        self, request: OrderRequest, triggering_quote: NBBOQuote | None = None
    ) -> None:
        self.submitted.append(request)
        self._pending.append(
            OrderAck(
                timestamp_ns=request.timestamp_ns + 1,
                correlation_id=request.correlation_id,
                sequence=request.sequence,
                order_id=request.order_id,
                symbol=request.symbol,
                status=OrderAckStatus.ACKNOWLEDGED,
            )
        )
        self._pending.append(
            OrderAck(
                timestamp_ns=request.timestamp_ns + 2,
                correlation_id=request.correlation_id,
                sequence=request.sequence,
                order_id=request.order_id,
                symbol=request.symbol,
                status=OrderAckStatus.FILLED,
                filled_quantity=request.quantity,
                fill_price=self._fill_price,
            )
        )

    def poll_acks(self) -> list[OrderAck]:
        acks = list(self._pending)
        self._pending.clear()
        return acks


_TERMINAL_STATES = _orchestrator_mod._TERMINAL_ORDER_STATES


class _CancellingRouter(_RecordingRouter):
    """Router that supports cancellation, like the real backtest/passive routers.

    ``cancel_order`` emits a CANCELLED ack so ``_cancel_resting_for_symbol``'s
    poll-and-reconcile actually drives the order state machine terminal — the
    base ``_RecordingRouter`` has no ``cancel_order`` at all, so the
    orchestrator's ``getattr`` probe silently no-ops against it.

    ``auto_fill=False`` leaves submitted orders live (ACKNOWLEDGED only) so a
    test can observe a mandated exit that is still in flight.
    """

    def __init__(self, auto_fill: bool = True, fill_on_cancel: bool = False) -> None:
        super().__init__()
        self.cancelled: list[str] = []
        self._auto_fill = auto_fill
        # ``fill_on_cancel`` models the venue race: the resting order had already
        # filled when the cancel arrived, so the poll returns a FILL, not a CANCEL.
        self._fill_on_cancel = fill_on_cancel
        self._live: dict[str, OrderRequest] = {}

    def submit(
        self, request: OrderRequest, triggering_quote: NBBOQuote | None = None
    ) -> None:
        self._live[request.order_id] = request
        if self._auto_fill:
            super().submit(request, triggering_quote=triggering_quote)
            return
        self.submitted.append(request)
        self._pending.append(
            OrderAck(
                timestamp_ns=request.timestamp_ns + 1,
                correlation_id=request.correlation_id,
                sequence=request.sequence,
                order_id=request.order_id,
                symbol=request.symbol,
                status=OrderAckStatus.ACKNOWLEDGED,
            )
        )

    def register_resting(self, request: OrderRequest) -> None:
        """Make a pre-seeded resting order cancellable."""
        self._live[request.order_id] = request

    def cancel_order(self, order_id: str) -> bool:
        self.cancelled.append(order_id)
        request = self._live.pop(order_id, None)
        if request is None:
            return False
        if self._fill_on_cancel:
            self._pending.append(
                OrderAck(
                    timestamp_ns=request.timestamp_ns + 1,
                    correlation_id=request.correlation_id,
                    sequence=request.sequence,
                    order_id=order_id,
                    symbol=request.symbol,
                    status=OrderAckStatus.FILLED,
                    filled_quantity=request.quantity,
                    fill_price=Decimal("150.00"),
                )
            )
            return True
        self._pending.append(
            OrderAck(
                timestamp_ns=request.timestamp_ns + 1,
                correlation_id=request.correlation_id,
                sequence=request.sequence,
                order_id=order_id,
                symbol=request.symbol,
                status=OrderAckStatus.CANCELLED,
            )
        )
        return True


class _MinimalConfig:
    version = "test-r1-hazard"
    symbols = frozenset({"AAPL"})

    def validate(self) -> None:
        pass

    def snapshot(self) -> None:
        return None


def _build_orchestrator(
    *,
    bus: EventBus | None = None,
    positions: MemoryPositionStore | None = None,
    router: _RecordingRouter | None = None,
    strategy_positions: StrategyPositionStore | None = None,
    trade_journal: InMemoryTradeJournal | None = None,
) -> tuple[Orchestrator, _RecordingRouter, MemoryPositionStore]:
    """Build an orchestrator wired for the forced-exit bridge.

    ``strategy_positions`` defaults to ``None``, which is how every test in this
    module ran before: and that made the slice-scoped half of
    ``_forced_exit_closable_quantity`` unreachable, since it is guarded on
    ``self._strategy_positions is not None``.  The ``max(symbol-net, slice)``
    branch — the one that lets a slice-scoped exit legitimately cross zero — was
    therefore dead code in the only module that puts a resting order in the book
    at mandated-exit time.  Pass a store to exercise it.
    """
    clock = SimulatedClock(start_ns=1000)
    bus = bus or EventBus()
    positions = positions or MemoryPositionStore()
    router = router or _RecordingRouter()
    backend = ExecutionBackend(
        market_data=_StubMarketData(),
        order_router=router,  # type: ignore[arg-type]
        mode="BACKTEST",
    )
    orch = Orchestrator(
        clock=clock,
        bus=bus,
        backend=backend,
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
        strategy_positions=strategy_positions,
        trade_journal=trade_journal,
        account_equity=Decimal("1000000"),
    )
    orch.boot(_MinimalConfig())
    orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
    orch._micro.reset(trigger="session_start:test")
    return orch, router, positions


def _make_hazard_order(
    *,
    symbol: str = "AAPL",
    side: Side = Side.SELL,
    quantity: int = 100,
    order_id: str = "hz-1",
    reason: str = "HAZARD_SPIKE",
    source_layer: str = "RISK",
    sequence: int = 1,
) -> DeRiskRequirement:
    return DeRiskRequirement(
        timestamp_ns=2000,
        correlation_id="hz-corr-1",
        sequence=sequence,
        source_layer=source_layer,
        order_id=order_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        strategy_id="test_alpha",
        reason=reason,
    )


class TestHazardOrderRouting:
    def test_hazard_spike_order_is_submitted(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        _, router, _ = _build_orchestrator(bus=bus, positions=positions)
        order = _make_hazard_order(reason="HAZARD_SPIKE")
        bus.publish(order)

        assert len(router.submitted) == 1
        assert router.submitted[0].order_id == order.order_id
        assert router.submitted[0].reason == "HAZARD_SPIKE"

    def test_hard_exit_age_order_is_submitted(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        _, router, _ = _build_orchestrator(bus=bus, positions=positions)
        order = _make_hazard_order(reason="HARD_EXIT_AGE")
        bus.publish(order)

        assert len(router.submitted) == 1
        assert router.submitted[0].reason == "HARD_EXIT_AGE"

    def test_hazard_fill_reconciles_into_position_store(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        _, _, positions = _build_orchestrator(
            bus=bus,
            positions=positions,
        )
        bus.publish(_make_hazard_order(reason="HAZARD_SPIKE"))

        # 100 long → SELL 100 → flat
        assert positions.get("AAPL").quantity == 0

    def test_position_update_event_published(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        captured: list[PositionUpdate] = []
        bus.subscribe(PositionUpdate, captured.append)  # type: ignore[arg-type]
        _build_orchestrator(bus=bus, positions=positions)
        bus.publish(_make_hazard_order(reason="HAZARD_SPIKE"))

        # Reconciliation must publish a PositionUpdate so downstream
        # forensics / metrics can attribute the exit.
        assert any(u.symbol == "AAPL" for u in captured)


class TestHandlerFiltersOutNonHazardOrders:
    """The handler MUST NOT re-submit orders from the orchestrator's
    own dispatch sites, which also publish OrderRequest on the bus."""

    def test_portfolio_layer_order_ignored(self) -> None:
        bus = EventBus()
        _, router, _ = _build_orchestrator(bus=bus)

        # PORTFOLIO orders are stamped source_layer="PORTFOLIO" by
        # BasicRiskEngine.check_sized_intent.
        bus.publish(
            _make_hazard_order(
                source_layer="PORTFOLIO",
                reason="PORTFOLIO",
            )
        )

        assert router.submitted == []

    def test_signal_layer_order_ignored(self) -> None:
        bus = EventBus()
        _, router, _ = _build_orchestrator(bus=bus)

        # SIGNAL-walk orders default to source_layer="" (no explicit
        # tagging in the orchestrator); they MUST NOT be re-submitted.
        bus.publish(
            _make_hazard_order(
                source_layer="",
                reason="entry",
            )
        )

        assert router.submitted == []

    def test_risk_layer_with_non_hazard_reason_ignored(self) -> None:
        bus = EventBus()
        _, router, _ = _build_orchestrator(bus=bus)

        bus.publish(
            OrderRequest(
                timestamp_ns=2000,
                correlation_id="hz-corr-1",
                sequence=1,
                source_layer="RISK",
                order_id="hz-1",
                symbol="AAPL",
                side=Side.SELL,
                order_type=OrderType.MARKET,
                quantity=100,
                strategy_id="test_alpha",
                reason="some_other_risk_event",
            )
        )

        assert router.submitted == []


def _make_reject_verdict(order: OrderRequest) -> RiskVerdict:
    return RiskVerdict(
        timestamp_ns=order.timestamp_ns,
        correlation_id=order.correlation_id,
        sequence=order.sequence,
        symbol=order.symbol,
        action=RiskAction.REJECT,
        reason="stubbed reject for test",
    )


class TestHazardHandlerAuthoritativeReject:
    """A formal check_order REJECT is honored unless the order verifiably
    reduces the live position — the Inv-11 exit fail-safe is exit-only,
    so it must not launder a non-reducing order past a rejecting gate."""

    def test_reducing_exit_submits_despite_reject(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        orch, router, _ = _build_orchestrator(bus=bus, positions=positions)

        def _reject(order: OrderRequest, _positions: object, **_kw: object) -> RiskVerdict:
            return _make_reject_verdict(order)

        orch._risk_engine.check_order = _reject  # type: ignore[method-assign]
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)  # type: ignore[arg-type]

        # 100 long -> SELL 100 reduces to flat: exit fail-safe submits anyway.
        bus.publish(_make_hazard_order(side=Side.SELL, quantity=100))

        assert len(router.submitted) == 1
        assert any(a.alert_name == "hazard_exit_defensive_check_order_reject" for a in alerts)

    def test_nonreducing_hazard_order_blocked_on_reject(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        orch, router, _ = _build_orchestrator(bus=bus, positions=positions)

        def _reject(order: OrderRequest, _positions: object, **_kw: object) -> RiskVerdict:
            return _make_reject_verdict(order)

        orch._risk_engine.check_order = _reject  # type: ignore[method-assign]
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)  # type: ignore[arg-type]

        # A hazard-tagged order that INCREASES the long (100 -> 150) has no
        # exit fail-safe claim: REJECT is authoritative and must block.
        bus.publish(_make_hazard_order(side=Side.BUY, quantity=50, order_id="hz-bad"))

        assert router.submitted == []
        assert any(
            a.alert_name == "hazard_exit_nonreducing_reject_blocked"
            and a.severity == AlertSeverity.CRITICAL
            for a in alerts
        )


class TestRestingOrderGuard:
    """A mandated RISK-layer exit must clear the book before it crosses.

    ``execution_mode: passive_limit`` is the platform-wide default
    (``platform.yaml``), so resting limit orders are the normal state of the
    book.  The SIGNAL path's forced-exit branch cancels them and refuses to
    stack a second aggressive leg; the bus bridge did neither, so a resting
    entry could fill *after* a safety exit flattened and silently re-open the
    exposure that exit had just closed (Inv-11).
    """

    @staticmethod
    def _rest_order(
        orch: Orchestrator,
        router: _CancellingRouter,
        *,
        order_id: str = "resting-limit-1",
        side: Side = Side.BUY,
        symbol: str = "AAPL",
        quantity: int = 100,
    ) -> OrderRequest:
        resting = OrderRequest(
            timestamp_ns=1500,
            correlation_id="resting-corr",
            sequence=99,
            source_layer="SIGNAL",
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("149.00"),
            quantity=quantity,
            strategy_id="sig_alpha_v1",
            reason="",
        )
        orch._track_order(resting.order_id, resting.side, resting)
        orch._transition_order(resting.order_id, OrderState.SUBMITTED, "submitted")
        router.register_resting(resting)
        return resting

    def test_hazard_exit_cancels_resting_passive_order(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        router = _CancellingRouter()
        orch, _, _ = _build_orchestrator(bus=bus, positions=positions, router=router)
        resting = self._rest_order(orch, router)
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)  # type: ignore[arg-type]

        bus.publish(_make_hazard_order(reason="HAZARD_SPIKE", order_id="hz-1"))

        assert router.cancelled == [resting.order_id]
        # The exit still crosses — cancelling is a precondition, not a substitute.
        assert [o.order_id for o in router.submitted] == ["hz-1"]
        # Inv-13: the supersede is attributable to the safety control.
        assert any(a.alert_name == "forced_exit_supersedes_pending_order" for a in alerts)
        # The resting order is terminal, so it cannot fill and re-open the book.
        entry = orch._active_orders.get(resting.order_id)
        assert entry is None or entry[0].state in _TERMINAL_STATES

    def test_hazard_exit_does_not_stack_on_pending_forced_exit(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 200, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        router = _CancellingRouter(auto_fill=False)
        orch, _, _ = _build_orchestrator(bus=bus, positions=positions, router=router)

        bus.publish(_make_hazard_order(order_id="hz-first", quantity=100))
        assert [o.order_id for o in router.submitted] == ["hz-first"]

        # A second mandated exit while the first is still in flight would
        # overshoot the position it is closing.
        bus.publish(_make_hazard_order(order_id="hz-second", quantity=100))
        assert [o.order_id for o in router.submitted] == ["hz-first"]

    def test_blocked_hazard_order_does_not_cancel_resting_orders(self) -> None:
        """The guard runs only once the exit is committed to submitting.

        Cancelling a resting *cover* and then bailing out would leave the book
        more exposed than before — the opposite of the fail-safe intent.
        """
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        router = _CancellingRouter()
        orch, _, _ = _build_orchestrator(bus=bus, positions=positions, router=router)
        resting = self._rest_order(orch, router)

        def _reject(order: OrderRequest, _positions: object, **_kw: object) -> RiskVerdict:
            return _make_reject_verdict(order)

        orch._risk_engine.check_order = _reject  # type: ignore[method-assign]

        # Non-reducing + REJECT ⇒ blocked before the resting-order guard.
        bus.publish(_make_hazard_order(side=Side.BUY, quantity=50, order_id="hz-bad"))

        assert router.submitted == []
        assert router.cancelled == []
        entry = orch._active_orders.get(resting.order_id)
        assert entry is not None and entry[0].state not in _TERMINAL_STATES

    def test_exit_stands_down_when_cancel_settles_a_closing_fill(self) -> None:
        """The cancel can settle a fill that already flattened the book.

        ``_cancel_resting_for_symbol`` polls acks *by order id* and reconciles
        whatever comes back — a resting order that had already filled at the venue
        returns a FILL, not a CANCEL.  The exit's quantity was fixed by the
        controller before that, so crossing it into an already-flat book would open
        the opposite side: a fail-safe control increasing exposure, which is the
        precise failure Inv-11 forbids.
        """
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        router = _CancellingRouter(fill_on_cancel=True)
        orch, _, _ = _build_orchestrator(bus=bus, positions=positions, router=router)
        # A resting passive SELL 100 — a passive exit covering the whole long.
        self._rest_order(orch, router, order_id="resting-sell-1", side=Side.SELL)
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)  # type: ignore[arg-type]

        bus.publish(_make_hazard_order(side=Side.SELL, quantity=100, order_id="hz-1"))

        # The resting SELL filled during the cancel and flattened the book, so the
        # mandated exit must stand down rather than cross a stale quantity.
        assert positions.get("AAPL").quantity == 0
        assert router.submitted == []
        # Inv-13: a mandated exit that never reached the router must be visible.
        assert any(a.alert_name == "forced_exit_stood_down_after_cancel" for a in alerts)

    def test_partial_cover_resizes_the_exit_instead_of_overshooting(self) -> None:
        """A *partial* resting cover must not let the exit cross zero.

        The full-cover case above leaves the book at exactly flat, which a
        magnitude-shrinkage test happens to catch.  A partial cover does not:
        ``SELL 100`` into a book the cover has already taken to long 70 shrinks
        the magnitude while flipping to short 30 — a fail-safe control opening
        exposure, which Inv-11 forbids.  The exit is clamped to the residual
        rather than stood down, because the residual still needs closing and the
        hazard controller will not re-emit within the same episode.
        """
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        router = _CancellingRouter(fill_on_cancel=True)
        orch, _, _ = _build_orchestrator(bus=bus, positions=positions, router=router)
        # Resting passive SELL 30 — covers part of the long, not all of it.
        self._rest_order(orch, router, order_id="resting-sell-30", side=Side.SELL, quantity=30)
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)  # type: ignore[arg-type]

        bus.publish(_make_hazard_order(side=Side.SELL, quantity=100, order_id="hz-1"))

        # Flat, not short: the exit closed the residual and stopped there.
        assert positions.get("AAPL").quantity == 0
        assert [o.order_id for o in router.submitted] == ["hz-1"]
        assert router.submitted[0].quantity == 70
        # Inv-13: the submitted size differs from what the controller authored.
        assert any(a.alert_name == "forced_exit_resized_after_cancel" for a in alerts)

    def test_resized_exit_records_the_announced_quantity_on_the_trade(self) -> None:
        """A clamped fill must not read as a partial of the announced order.

        The controller published its ``OrderRequest`` before the kernel clamped
        it, and the kernel re-uses the same ``order_id`` rather than minting a
        second order — deliberately, since it is one mandated decision resized.
        The consequence is that the bus carries 100 while the router received 70,
        so anything joining the order stream to the fill sees a 70-of-100 partial
        fill instead of a completed 70-share exit.

        The trade row is where that join lands, so it carries what was announced
        alongside what was requested (Inv-13).
        """
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        journal = InMemoryTradeJournal()
        router = _CancellingRouter(fill_on_cancel=True)
        orch, _, _ = _build_orchestrator(
            bus=bus, positions=positions, router=router, trade_journal=journal
        )
        self._rest_order(orch, router, order_id="resting-sell-30", side=Side.SELL, quantity=30)

        bus.publish(_make_hazard_order(side=Side.SELL, quantity=100, order_id="hz-1"))

        exit_rows = [r for r in journal.query() if r.order_id == "hz-1"]
        assert len(exit_rows) == 1
        row = exit_rows[0]
        assert row.filled_quantity == 70
        # What the kernel actually asked the router for...
        assert row.requested_quantity == 70
        # ...and what the bus was told before the clamp.
        assert row.metadata.get("forced_exit_announced_quantity") == "100"

    def test_unclamped_exit_records_no_announced_quantity(self) -> None:
        """The marker is absent when nothing was resized, so its presence means something."""
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        journal = InMemoryTradeJournal()
        orch, router, _ = _build_orchestrator(bus=bus, positions=positions, trade_journal=journal)
        assert orch is not None

        bus.publish(_make_hazard_order(side=Side.SELL, quantity=100, order_id="hz-1"))

        exit_rows = [r for r in journal.query() if r.order_id == "hz-1"]
        assert len(exit_rows) == 1
        assert exit_rows[0].requested_quantity == 100
        assert "forced_exit_announced_quantity" not in exit_rows[0].metadata

    def test_partial_cover_on_a_short_resizes_symmetrically(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", -100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        router = _CancellingRouter(fill_on_cancel=True)
        orch, _, _ = _build_orchestrator(bus=bus, positions=positions, router=router)
        self._rest_order(orch, router, order_id="resting-buy-30", side=Side.BUY, quantity=30)

        bus.publish(_make_hazard_order(side=Side.BUY, quantity=100, order_id="hz-1"))

        assert positions.get("AAPL").quantity == 0
        assert router.submitted[0].quantity == 70


class TestIdempotency:
    def test_duplicate_order_id_not_resubmitted(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        _, router, _ = _build_orchestrator(
            bus=bus,
            positions=positions,
        )
        order = _make_hazard_order()
        bus.publish(order)
        bus.publish(order)  # republish with identical order_id

        assert len(router.submitted) == 1


class TestHazardSignatureSingleSourceOfTruth:
    """The bridge filter and controller share one
    definition of the hazard-exit signature, so they cannot drift.

    ``Orchestrator._on_bus_hazard_order`` imports ``HAZARD_EXIT_REASONS`` and
    ``HAZARD_EXIT_SOURCE_LAYER`` from ``feelies.risk.hazard_exit`` — the sole
    writer — rather than re-declaring the literals.  Adding a new hazard reason
    to the writer's set therefore automatically extends what the bridge routes;
    a stale or typo'd literal would fail these tests rather than silently
    dropping a real exit (Inv-11 fail-safe)."""

    def test_bridge_imports_the_writers_constants(self) -> None:
        # Identity, not equality: the kernel must reference the *same* objects
        # the controller exports, so a future edit to the writer's set is the
        # single source of truth for the bridge's membership test.
        assert _orchestrator_mod.HAZARD_EXIT_REASONS is HAZARD_EXIT_REASONS
        assert _orchestrator_mod.HAZARD_EXIT_SOURCE_LAYER == HAZARD_EXIT_SOURCE_LAYER

    def test_every_writer_reason_is_routed_by_the_bridge(self) -> None:
        # Each reason the controller may emit must be routed when carried on an
        # order with the controller's source_layer.  Iterating the shared
        # frozenset means a new reason cannot be added to the writer without
        # this assertion covering it.
        for reason in sorted(HAZARD_EXIT_REASONS):
            bus = EventBus()
            positions = MemoryPositionStore()
            positions.update("AAPL", 100, Decimal("150.00"))
            positions.update_mark("AAPL", Decimal("150.00"))
            _, router, _ = _build_orchestrator(bus=bus, positions=positions)

            bus.publish(
                _make_hazard_order(
                    reason=reason,
                    source_layer=HAZARD_EXIT_SOURCE_LAYER,
                    order_id=f"hz-{reason}",
                )
            )

            assert [o.reason for o in router.submitted] == [reason], (
                f"hazard reason {reason!r} from HAZARD_EXIT_REASONS was not "
                f"routed by Orchestrator._on_bus_hazard_order"
            )


class TestOutOfBandSettleIsDeliberate:
    """The RISK-layer bridge settles without walking the micro state machine.

    That asymmetry is structural, not an oversight, and it is pinned here so it
    is neither widened by accident nor "fixed" into an illegal transition:
    ``POSITION_UPDATE`` is reachable only from ``ORDER_ACK`` (see
    ``feelies.kernel.micro``), and the bridge fires re-entrantly during
    ``bus.publish(quote)`` while micro sits in ``MARKET_EVENT_RECEIVED``.  Making
    it walk M8 -> M9 from there would be an illegal transition.

    This costs less than it first appears.  ``StateTransition`` has no consumer
    anywhere in ``forensics/``, ``harness/`` or ``monitoring/`` — it is an
    operator/debug stream, not the provenance record.  Inv-13 for a mandated exit
    is carried by the durable chain instead: the ``OrderRequest``
    (``source_layer="RISK"`` plus its reason token), the ``OrderAck``, and the
    ``TradeRecord`` whose metadata keeps ``order_reason``,
    ``order_source_layer`` and ``forced_exit_strategy_id``.
    ``forensics/gate_close_attribution.py`` reconstructs from exactly those.
    """

    def test_micro_state_machine_forbids_the_walk_the_bridge_would_need(self) -> None:
        from feelies.kernel.micro import MicroState, create_micro_state_machine

        sm = create_micro_state_machine(SimulatedClock(start_ns=0))
        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick", correlation_id="c")

        # The state the bridge fires from cannot reach POSITION_UPDATE.
        assert not sm.can_transition(MicroState.POSITION_UPDATE)

    def test_bridge_emits_no_state_transition(self) -> None:
        from feelies.core.events import StateTransition

        bus = EventBus()
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, Decimal("150.00"))
        positions.update_mark("AAPL", Decimal("150.00"))

        _orch, router, _ = _build_orchestrator(bus=bus, positions=positions)
        transitions: list[StateTransition] = []
        bus.subscribe(StateTransition, transitions.append)  # type: ignore[arg-type]

        bus.publish(_make_hazard_order(reason="HAZARD_SPIKE", order_id="hz-1"))

        # The exit reached the router...
        assert [o.order_id for o in router.submitted] == ["hz-1"]
        # ...without pretending to be a tick-pipeline step.
        assert [t for t in transitions if t.machine_name == "tick_pipeline"] == []


class TestSliceScopedForcedExitClamp:
    """The ``max(symbol-net, slice)`` half of ``_forced_exit_closable_quantity``.

    Every other test in this module leaves ``strategy_positions=None``, so this
    branch has never executed here — and this is the only module that puts a
    resting order in the book at mandated-exit time.  The two behaviours below are
    therefore correct today by an ordering and a branch that nothing asserted:
    the review that produced this file found five separate defects hiding in
    exactly that situation.
    """

    @staticmethod
    def _seed(
        *, slice_qty: int, other_qty: int = 0
    ) -> tuple[MemoryPositionStore, StrategyPositionStore]:
        entry = Decimal("150.00")
        positions = MemoryPositionStore()
        strategy_positions = StrategyPositionStore()
        positions.update("AAPL", slice_qty, entry)
        strategy_positions.update("test_alpha", "AAPL", slice_qty, entry)
        if other_qty:
            positions.update("AAPL", other_qty, entry)
            strategy_positions.update("other_alpha", "AAPL", other_qty, entry)
        positions.update_mark("AAPL", entry)
        return positions, strategy_positions

    def test_same_slice_cancel_fill_resizes_the_mandated_exit(self) -> None:
        """A cover owned by the exiting slice must shrink the exit, not flip it.

        The clamp reads the slice book *after* ``_cancel_resting_for_symbol``
        reconciles the queued fill.  Nothing pinned that ordering: were the clamp
        to read first, it would take ``max(70, 100) = 100`` off a stale slice and
        cross 100 into a book holding 70, leaving a 30-share short — a fail-safe
        control opening exposure (Inv-11).
        """
        positions, strategy_positions = self._seed(slice_qty=100)
        router = _CancellingRouter(fill_on_cancel=True)
        orch, _router, _pos = _build_orchestrator(
            positions=positions,
            router=router,
            strategy_positions=strategy_positions,
        )

        resting = OrderRequest(
            timestamp_ns=1500,
            correlation_id="resting-corr",
            sequence=99,
            source_layer="SIGNAL",
            order_id="resting-sell-30",
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("151.00"),
            quantity=30,
            strategy_id="test_alpha",
            reason="",
        )
        orch._track_order(resting.order_id, resting.side, resting)
        orch._transition_order(resting.order_id, OrderState.SUBMITTED, "submitted")
        router.register_resting(resting)

        orch._bus.publish(
            _make_hazard_order(side=Side.SELL, quantity=100, reason="MAX_HOLD_AFTER_SAFE_OFF")
        )

        assert router.cancelled == ["resting-sell-30"]
        # Resized to the residual, not stood down and not crossed at full size.
        assert [(o.order_id, o.quantity) for o in router.submitted] == [("hz-1", 70)]
        assert positions.get("AAPL").quantity == 0
        assert strategy_positions.get("test_alpha", "AAPL").quantity == 0

    def test_slice_scoped_exit_closes_its_slice_through_a_flat_net(self) -> None:
        """The case the ``max`` exists for: net flat, mandated slice still open.

        Another strategy holding the opposite side leaves symbol-net at zero while
        the mandated slice is long.  Clamping to net would stand the exit down and
        strand the slice, so a slice-scoped author takes the larger basis and the
        net moves through zero on purpose (design §3.3).
        """
        positions, strategy_positions = self._seed(slice_qty=100, other_qty=-100)
        assert positions.get("AAPL").quantity == 0

        router = _CancellingRouter(fill_on_cancel=False)
        orch, _router, _pos = _build_orchestrator(
            positions=positions, router=router, strategy_positions=strategy_positions
        )

        # A resting order must be in the book for the clamp to run at all: it lives
        # inside the ``_has_pending_order_for_symbol`` branch.  Without one this
        # test passed while never reaching ``max(symbol-net, slice)`` — confirmed by
        # mutation, since deleting the max left it green.  This order belongs to the
        # *other* strategy and cancels without filling, so the mandated slice is
        # untouched and symbol-net stays flat.
        resting = OrderRequest(
            timestamp_ns=1500,
            correlation_id="resting-corr",
            sequence=99,
            source_layer="SIGNAL",
            order_id="resting-other-buy",
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("149.00"),
            quantity=10,
            strategy_id="other_alpha",
            reason="",
        )
        orch._track_order(resting.order_id, resting.side, resting)
        orch._transition_order(resting.order_id, OrderState.SUBMITTED, "submitted")
        router.register_resting(resting)

        orch._bus.publish(
            _make_hazard_order(side=Side.SELL, quantity=100, reason="MAX_HOLD_AFTER_SAFE_OFF")
        )

        assert router.cancelled == ["resting-other-buy"]
        assert [(o.order_id, o.quantity) for o in router.submitted] == [("hz-1", 100)]
        # The mandated slice is closed; the other strategy's short is untouched.
        assert strategy_positions.get("test_alpha", "AAPL").quantity == 0
        assert strategy_positions.get("other_alpha", "AAPL").quantity == -100
        assert positions.get("AAPL").quantity == -100


class TestForcedExitClampAppliesWithoutARestingOrder:
    """The clamp guards the ordinary path, not only the resting-order branch.

    It used to run only inside ``if self._has_pending_order_for_symbol(...)``.
    ``order_reduces`` is computed above it but gates nothing, so on the ordinary
    path nothing stopped a mandated exit from crossing into a book that could not
    absorb it.  What kept that safe was a property of four *other* files -- every
    shipped controller sizes from a live non-zero position and returns early when
    flat -- rather than anything at the submit site.
    """

    def test_symbol_net_exit_stands_down_when_the_net_is_already_flat(self) -> None:
        """Two strategies on opposite sides leave net flat; a symbol-net exit must not fire.

        Before the clamp was hoisted this submitted the full 100: net went to
        -100 and the *other* strategy was driven from -100 to -150 by the
        proportional split.  A fail-safe control both opening exposure and
        deepening an unrelated slice's short is precisely Inv-11's prohibition.
        """
        entry = Decimal("150.00")
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, entry)
        positions.update("AAPL", -100, entry)
        positions.update_mark("AAPL", entry)
        strategy_positions = StrategyPositionStore()
        strategy_positions.update("test_alpha", "AAPL", 100, entry)
        strategy_positions.update("other_alpha", "AAPL", -100, entry)
        assert positions.get("AAPL").quantity == 0

        orch, router, _pos = _build_orchestrator(
            positions=positions, strategy_positions=strategy_positions
        )
        # No resting order: the clamp only reaches this order once hoisted.
        assert not orch._has_pending_order_for_symbol("AAPL")

        orch._bus.publish(_make_hazard_order(side=Side.SELL, quantity=100, reason="HAZARD_SPIKE"))

        assert router.submitted == []
        assert positions.get("AAPL").quantity == 0
        # Neither slice moved — especially not the one that was never mandated.
        assert strategy_positions.get("test_alpha", "AAPL").quantity == 100
        assert strategy_positions.get("other_alpha", "AAPL").quantity == -100

    def test_slice_scoped_exit_still_crosses_a_flat_net_without_a_resting_order(
        self,
    ) -> None:
        """Guarding the path must not cost slice-scoped authors their latitude."""
        entry = Decimal("150.00")
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, entry)
        positions.update("AAPL", -100, entry)
        positions.update_mark("AAPL", entry)
        strategy_positions = StrategyPositionStore()
        strategy_positions.update("test_alpha", "AAPL", 100, entry)
        strategy_positions.update("other_alpha", "AAPL", -100, entry)

        orch, router, _pos = _build_orchestrator(
            positions=positions, strategy_positions=strategy_positions
        )
        orch._bus.publish(
            _make_hazard_order(side=Side.SELL, quantity=100, reason="MAX_HOLD_AFTER_SAFE_OFF")
        )

        assert [(o.order_id, o.quantity) for o in router.submitted] == [("hz-1", 100)]
        assert strategy_positions.get("test_alpha", "AAPL").quantity == 0
        assert strategy_positions.get("other_alpha", "AAPL").quantity == -100

    def test_a_well_formed_exit_is_untouched_by_the_clamp(self) -> None:
        """The common case stays a no-op: closable equals the requested quantity."""
        entry = Decimal("150.00")
        positions = MemoryPositionStore()
        positions.update("AAPL", 100, entry)
        positions.update_mark("AAPL", entry)

        orch, router, _pos = _build_orchestrator(positions=positions)
        orch._bus.publish(_make_hazard_order(side=Side.SELL, quantity=100, reason="HAZARD_SPIKE"))

        assert [(o.order_id, o.quantity) for o in router.submitted] == [("hz-1", 100)]
        assert positions.get("AAPL").quantity == 0


class TestSymbolNetSplitAcrossMixedSignSlices:
    """A reducing symbol-net fill must not deepen a slice on the other side.

    ``_distribute_fill_to_strategies`` used to take every non-zero slice
    regardless of sign, weight by ``abs(q)``, and apply one uniform direction.
    The aggregate reconciled exactly, which is why nothing caught it: the damage
    was entirely in the per-slice book, and no fixture held slices on both sides
    of a symbol at once.

    A mixed-sign book is contemplated by design — the netting notes in
    ``platform_config`` describe one strategy holding the opposite side while
    another's slice stays open — and the slice book feeds the per-alpha risk
    budgets, the Stage-0 deferral cap, and the exit composer's scoping.
    """

    @staticmethod
    def _seed(a_qty: int, b_qty: int) -> tuple[MemoryPositionStore, StrategyPositionStore]:
        entry = Decimal("150.00")
        positions = MemoryPositionStore()
        strategy_positions = StrategyPositionStore()
        for sid, qty in (("alpha_a", a_qty), ("alpha_b", b_qty)):
            positions.update("AAPL", qty, entry)
            strategy_positions.update(sid, "AAPL", qty, entry)
        positions.update_mark("AAPL", entry)
        return positions, strategy_positions

    def test_sell_closes_the_long_slice_and_leaves_the_short_alone(self) -> None:
        """alpha_a +150, alpha_b -50, net +100; a mandated SELL 100.

        Before: alpha_a kept 75 and alpha_b was driven -50 -> -75, deepened by 25
        shares on a fill whose whole purpose was to reduce exposure.
        """
        positions, strategy_positions = self._seed(150, -50)
        assert positions.get("AAPL").quantity == 100

        orch, router, _pos = _build_orchestrator(
            positions=positions, strategy_positions=strategy_positions
        )
        orch._bus.publish(_make_hazard_order(side=Side.SELL, quantity=100, reason="HAZARD_SPIKE"))

        assert [(o.order_id, o.quantity) for o in router.submitted] == [("hz-1", 100)]
        assert positions.get("AAPL").quantity == 0
        # The whole close comes out of the slice that created the net long.
        assert strategy_positions.get("alpha_a", "AAPL").quantity == 50
        assert strategy_positions.get("alpha_b", "AAPL").quantity == -50
        # And the slice book still sums to symbol-net.
        assert (
            strategy_positions.get("alpha_a", "AAPL").quantity
            + strategy_positions.get("alpha_b", "AAPL").quantity
            == positions.get("AAPL").quantity
        )

    def test_buy_closes_the_short_slice_and_leaves_the_long_alone(self) -> None:
        """The mirror: a BUY must reduce shorts, not add to longs."""
        positions, strategy_positions = self._seed(50, -150)
        assert positions.get("AAPL").quantity == -100

        orch, router, _pos = _build_orchestrator(
            positions=positions, strategy_positions=strategy_positions
        )
        orch._bus.publish(_make_hazard_order(side=Side.BUY, quantity=100, reason="HAZARD_SPIKE"))

        assert [(o.order_id, o.quantity) for o in router.submitted] == [("hz-1", 100)]
        assert positions.get("AAPL").quantity == 0
        assert strategy_positions.get("alpha_b", "AAPL").quantity == -50
        assert strategy_positions.get("alpha_a", "AAPL").quantity == 50

    def test_same_sign_slices_are_unaffected(self) -> None:
        """The common case must keep splitting across every holder."""
        positions, strategy_positions = self._seed(150, 50)
        orch, router, _pos = _build_orchestrator(
            positions=positions, strategy_positions=strategy_positions
        )
        orch._bus.publish(_make_hazard_order(side=Side.SELL, quantity=200, reason="HAZARD_SPIKE"))

        assert positions.get("AAPL").quantity == 0
        assert strategy_positions.get("alpha_a", "AAPL").quantity == 0
        assert strategy_positions.get("alpha_b", "AAPL").quantity == 0

    def test_no_slice_is_ever_pushed_further_from_flat(self) -> None:
        """The invariant behind the two cases above, stated directly."""
        for a_qty, b_qty, side, qty in (
            (150, -50, Side.SELL, 100),
            (50, -150, Side.BUY, 100),
            (200, -50, Side.SELL, 150),
            (150, 50, Side.SELL, 200),
        ):
            positions, strategy_positions = self._seed(a_qty, b_qty)
            orch, _router, _pos = _build_orchestrator(
                positions=positions, strategy_positions=strategy_positions
            )
            orch._bus.publish(_make_hazard_order(side=side, quantity=qty, reason="HAZARD_SPIKE"))
            for sid, before in (("alpha_a", a_qty), ("alpha_b", b_qty)):
                after = strategy_positions.get(sid, "AAPL").quantity
                assert abs(after) <= abs(before), (
                    f"{sid} moved {before} -> {after} on a reducing "
                    f"{side.name} {qty}: a fail-safe fill grew a slice"
                )
