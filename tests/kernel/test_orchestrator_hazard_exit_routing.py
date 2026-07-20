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
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.kernel import orchestrator as _orchestrator_mod
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.risk.hazard_exit import HAZARD_EXIT_REASONS, HAZARD_EXIT_SOURCE_LAYER
from feelies.storage.memory_event_log import InMemoryEventLog


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

    def submit(self, request: OrderRequest) -> None:
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
) -> tuple[Orchestrator, _RecordingRouter, MemoryPositionStore]:
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
) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=2000,
        correlation_id="hz-corr-1",
        sequence=sequence,
        source_layer=source_layer,
        order_id=order_id,
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
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
            _make_hazard_order(
                source_layer="RISK",
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
