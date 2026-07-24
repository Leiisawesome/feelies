"""The orchestrator must route the exit composer's flatten ``OrderRequest``
through the same non-vetoable RISK-layer bridge as hazard exits, and it must do
so synchronously on the dispatch that produced the triggering
``SafetyStateChange`` (Phase-3 acceptance; design §3.3, §3.6).

These tests assert:

* A bus-published composer ``OrderRequest`` (``source_layer="RISK"`` AND
  ``reason == "SAFETY_FAIL_CLOSED"``) is submitted to the router and reconciled.
* Routing goes through ``check_order``, never ``check_sized_intent`` — a
  cost/edge veto that suppresses an entry cannot suppress a mandated safety exit
  (Inv-11 non-vetoable exit).
* A reducing composer exit submits even when ``check_order`` returns REJECT
  (exit fail-safe), mirroring the hazard path.
* Every reason the composer may emit is routed by the bridge (single source of
  truth), and a RISK-layer order with an unrelated reason is still ignored.
* End-to-end: a ``SafetyStateChange`` error path drives the composer to emit a
  flatten that the orchestrator submits **within the same synchronous dispatch**
  (no async/batched window in which the errored gate strands an open book).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    Alert,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    RiskAction,
    RiskVerdict,
    SafetyReason,
    SafetyStateChange,
    Side,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.backend import ExecutionBackend
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.kernel import orchestrator as _orchestrator_mod
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.risk.basic_risk import BasicRiskEngine, RiskConfig
from feelies.risk.exit_composer import (
    EXIT_COMPOSER_EXIT_REASONS,
    EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED,
    EXIT_COMPOSER_SOURCE_LAYER,
    ExitComposer,
    ExitComposerPolicy,
)
from feelies.storage.memory_event_log import InMemoryEventLog

_SID = "sig_decoupled_v1"
_SYMBOL = "AAPL"


class _NoOpMetricCollector:
    def record(self, _metric: Any) -> None:
        pass

    def flush(self) -> None:
        pass


class _StubMarketData:
    def events(self):
        return iter([])


class _RecordingRouter:
    """Minimal OrderRouter that fills every order (ACKNOWLEDGED then FILLED)."""

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
    version = "test-phase3-composer"
    symbols = frozenset({_SYMBOL})

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
        strategy_positions=strategy_positions,
    )
    orch.boot(_MinimalConfig())
    orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
    orch._micro.reset(trigger="session_start:test")
    return orch, router, positions


def _composer_order(
    *,
    symbol: str = _SYMBOL,
    side: Side = Side.SELL,
    quantity: int = 100,
    order_id: str = "cx-1",
    reason: str = EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED,
    source_layer: str = EXIT_COMPOSER_SOURCE_LAYER,
    sequence: int = 1,
) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=2000,
        correlation_id="cx-corr-1",
        sequence=sequence,
        source_layer=source_layer,
        order_id=order_id,
        symbol=symbol,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        strategy_id=_SID,
        reason=reason,
    )


def _seed_long(positions: MemoryPositionStore, qty: int = 100) -> None:
    positions.update(_SYMBOL, qty, Decimal("150.00"))
    positions.update_mark(_SYMBOL, Decimal("150.00"))


# ── Routing ──────────────────────────────────────────────────────────────


class TestComposerOrderRouting:
    def test_safety_fail_closed_order_is_submitted(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_long(positions)
        _, router, _ = _build_orchestrator(bus=bus, positions=positions)

        order = _composer_order()
        bus.publish(order)

        assert len(router.submitted) == 1
        assert router.submitted[0].order_id == order.order_id
        assert router.submitted[0].reason == EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED

    def test_composer_fill_reconciles_into_position_store(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_long(positions)
        _, _, positions = _build_orchestrator(bus=bus, positions=positions)

        bus.publish(_composer_order())
        # 100 long → SELL 100 → flat.
        assert positions.get(_SYMBOL).quantity == 0

    def test_risk_layer_unrelated_reason_still_ignored(self) -> None:
        bus = EventBus()
        _, router, _ = _build_orchestrator(bus=bus)
        bus.publish(_composer_order(reason="some_other_risk_event", order_id="cx-x"))
        assert router.submitted == []


# ── Non-vetoable (bypasses check_sized_intent) ───────────────────────────


class TestComposerExitIsNonVetoable:
    def test_composer_exit_never_calls_check_sized_intent(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_long(positions)
        orch, router, _ = _build_orchestrator(bus=bus, positions=positions)

        calls: list[object] = []

        def _spy(intent: object, _positions: object) -> Any:
            calls.append(intent)
            raise AssertionError("check_sized_intent must not gate a composer exit")

        orch._risk_engine.check_sized_intent = _spy  # type: ignore[method-assign]

        bus.publish(_composer_order())

        assert len(router.submitted) == 1
        assert calls == [], "the cost/edge veto path must be bypassed for a mandated exit"

    def test_reducing_composer_exit_submits_despite_check_order_reject(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_long(positions)
        orch, router, _ = _build_orchestrator(bus=bus, positions=positions)

        def _reject(order: OrderRequest, _positions: object, **_kw: object) -> RiskVerdict:
            return RiskVerdict(
                timestamp_ns=order.timestamp_ns,
                correlation_id=order.correlation_id,
                sequence=order.sequence,
                symbol=order.symbol,
                action=RiskAction.REJECT,
                reason="stubbed reject for test",
            )

        orch._risk_engine.check_order = _reject  # type: ignore[method-assign]
        alerts: list[Alert] = []
        bus.subscribe(Alert, alerts.append)  # type: ignore[arg-type]

        # 100 long → SELL 100 reduces to flat: exit fail-safe submits anyway.
        bus.publish(_composer_order(side=Side.SELL, quantity=100))

        assert len(router.submitted) == 1
        assert any(a.alert_name == "hazard_exit_defensive_check_order_reject" for a in alerts)


# ── Single source of truth for the bridge's reason membership ─────────────


class TestComposerSignatureRouted:
    def test_bridge_imports_the_composer_constants(self) -> None:
        # The kernel's combined forced-exit set must contain the composer's
        # writer set, so a new composer reason automatically extends routing.
        assert EXIT_COMPOSER_EXIT_REASONS <= _orchestrator_mod._RISK_FORCED_EXIT_REASONS

    def test_every_composer_reason_is_routed_by_the_bridge(self) -> None:
        for reason in sorted(EXIT_COMPOSER_EXIT_REASONS):
            bus = EventBus()
            positions = MemoryPositionStore()
            _seed_long(positions)
            _, router, _ = _build_orchestrator(bus=bus, positions=positions)

            bus.publish(_composer_order(reason=reason, order_id=f"cx-{reason}"))

            assert [o.reason for o in router.submitted] == [reason], (
                f"composer reason {reason!r} was not routed by Orchestrator._on_bus_hazard_order"
            )


# ── Synchronous same-dispatch liveness (end-to-end) ──────────────────────


class TestSynchronousLiveness:
    def _wire_composer(
        self, bus: EventBus, strat: StrategyPositionStore, *, seq_start: int = 50_000
    ) -> ExitComposer:
        composer = ExitComposer(
            bus=bus,
            sequence_generator=SequenceGenerator(start=seq_start),
            position_store=strat,
            policies={_SID: ExitComposerPolicy(strategy_id=_SID, universe=(_SYMBOL,))},
        )
        composer.attach()
        return composer

    def _safety(self, reason: SafetyReason) -> SafetyStateChange:
        return SafetyStateChange(
            timestamp_ns=2000,
            correlation_id="safe-corr-1",
            sequence=0,
            source_layer="SIGNAL",
            symbol=_SYMBOL,
            strategy_id=_SID,
            safe=False,
            reason=reason,
        )

    def test_error_path_flattens_within_one_dispatch(self) -> None:
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_long(positions)  # symbol-net book for check_order + reconcile
        strat = StrategyPositionStore()
        strat.update(_SID, _SYMBOL, 100, Decimal("150.00"), timestamp_ns=0)  # slice

        _, router, positions = _build_orchestrator(
            bus=bus, positions=positions, strategy_positions=strat
        )
        self._wire_composer(bus, strat)

        # Publishing the safety event synchronously drives: composer EXIT →
        # OrderRequest → orchestrator submit — all before publish() returns.
        bus.publish(self._safety("gate_error"))

        assert len(router.submitted) == 1, "no async window: the exit is live in one dispatch"
        submitted = router.submitted[0]
        assert submitted.reason == EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED
        assert submitted.side == Side.SELL
        assert submitted.quantity == 100
        assert positions.get(_SYMBOL).quantity == 0

    def test_clean_transition_does_not_flatten(self) -> None:
        # The clean ON→OFF is a bounded HOLD; the composer emits nothing, so the
        # orchestrator submits nothing on this dispatch (the deferral cap owns the
        # eventual timed exit).
        bus = EventBus()
        positions = MemoryPositionStore()
        _seed_long(positions)
        strat = StrategyPositionStore()
        strat.update(_SID, _SYMBOL, 100, Decimal("150.00"), timestamp_ns=0)

        _, router, _ = _build_orchestrator(bus=bus, positions=positions, strategy_positions=strat)
        self._wire_composer(bus, strat)

        bus.publish(self._safety("clean_transition"))

        assert router.submitted == []
