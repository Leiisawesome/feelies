"""P-51 entry admission: one refusal per reason, plus two admission controls.

Owned means the signal strategy id is a key of the orchestrator's exit-policy
map. A refusal publishes one warning alert and no order.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.composition.selection_policy import Top1SelectionPolicy
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    Alert,
    AlertSeverity,
    MarkRailUpdate,
    MetricEvent,
    NBBOQuote,
    OrderRequest,
    RailOrientation,
    RiskAction,
    RiskVerdict,
    Signal,
    SignalDirection,
)
from feelies.core.exit_policy import AdversePolicy, ExitPolicy, FavorablePolicy, HorizonPolicy
from feelies.core.quote_quality import QuoteQuality
from feelies.core.trading_session import TradingSessionBounds, et_clock_to_ns
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.position_store import PositionStore
from feelies.portfolio.strategy_position_store import StrategyPositionStore
from feelies.storage.memory_event_log import InMemoryEventLog

_OWNED = "owned_alpha"
_OTHER = "other_alpha"
_SESSION = date(2026, 3, 26)
_NS = 1_000_000_000
_CUTOFF_NS = 60 * _NS
_CLOSE_NS = et_clock_to_ns(_SESSION, "16:00")
_AT_CUTOFF_NS = _CLOSE_NS - _CUTOFF_NS
_MID_SESSION_NS = et_clock_to_ns(_SESSION, "10:00")
_QUOTE_SEQUENCE = 7
_SLICE = 40


class _NoOpMetricCollector:
    def record(self, metric: MetricEvent) -> None:
        del metric

    def flush(self) -> None:
        return


class _StubMarketData:
    def events(self):  # type: ignore[no-untyped-def]
        return iter(())


class _StubRiskEngine:
    def check_signal(self, signal: Signal, positions: PositionStore) -> RiskVerdict:
        del positions
        return RiskVerdict(
            timestamp_ns=signal.timestamp_ns,
            correlation_id=signal.correlation_id,
            sequence=signal.sequence,
            symbol=signal.symbol,
            action=RiskAction.ALLOW,
            reason="test",
        )

    def check_order(self, order: OrderRequest, positions: PositionStore) -> RiskVerdict:
        del positions
        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=RiskAction.ALLOW,
            reason="test",
        )


class _MinimalConfig:
    version = "test-0.1"
    symbols = frozenset({"AAPL"})

    def validate(self) -> None:
        return

    def snapshot(self):  # type: ignore[no-untyped-def]
        return None


def _policy() -> ExitPolicy:
    return ExitPolicy(
        archetype="probe",
        declared_shape=None,
        curve_ref="probe",
        fee_round_trip_ticks=1,
        horizon=HorizonPolicy(T_ns=300 * _NS, cutoff_before_close_ns=_CUTOFF_NS),
        adverse=AdversePolicy(
            centre_ticks=2,
            band_ticks=2,
            lo_ticks=1,
            hi_ticks=3,
            blind_limit_ns=_NS,
        ),
        favorable=FavorablePolicy(form="fixed", quiet_limit_ns=_NS),
    )


def _orientation(*, paying_absent: bool) -> RailOrientation:
    return RailOrientation(
        paying_size=100,
        valuation_size=100,
        paying_age_ns=0,
        valuation_age_ns=0,
        paying_absent_for_ns=0,
        valuation_absent_for_ns=0,
        paying_side_absent=paying_absent,
        valuation_side_absent=False,
        dwell_window_clean=True,
    )


class _FixedRail:
    """One rail shape for every quote. Event sequence is not quote_sequence."""

    def __init__(self, *, crossed: bool, paying_absent: bool) -> None:
        self._crossed = crossed
        self._paying_absent = paying_absent

    def on_quote(self, quote: NBBOQuote, *, quality: QuoteQuality) -> MarkRailUpdate:
        del quality
        side = _orientation(paying_absent=self._paying_absent)
        return MarkRailUpdate(
            timestamp_ns=quote.timestamp_ns,
            correlation_id=quote.correlation_id,
            sequence=quote.sequence + 1000,
            symbol=quote.symbol,
            quote_sequence=quote.sequence,
            event_timestamp_ns=quote.exchange_timestamp_ns,
            long=side,
            short=side,
            symbol_quiet_ns=0,
            locked=False,
            crossed=self._crossed,
            feed_gap_before=False,
            warmed_up=True,
        )


def _quote(exchange_ns: int) -> NBBOQuote:
    ts = exchange_ns + 100
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"AAPL:{ts}:{_QUOTE_SEQUENCE}",
        sequence=_QUOTE_SEQUENCE,
        symbol="AAPL",
        bid=Decimal("149.50"),
        ask=Decimal("150.50"),
        bid_size=100,
        ask_size=200,
        exchange_timestamp_ns=exchange_ns,
    )


def _bounds() -> TradingSessionBounds:
    return TradingSessionBounds(
        session_date=_SESSION,
        rth_open_ns=et_clock_to_ns(_SESSION, "09:30"),
        rth_close_ns=_CLOSE_NS,
    )


def _boot(orch: Orchestrator) -> None:
    orch.boot(_MinimalConfig())
    orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
    orch._micro.reset(trigger="session_start:test")


def _drive(
    *,
    strategy_id: str,
    direction: SignalDirection,
    crossed: bool,
    paying_absent: bool,
    symbol_qty: int,
    slice_qty: int,
    at_cutoff: bool,
) -> tuple[list[OrderRequest], list[Alert]]:
    clock = SimulatedClock(start_ns=1000)
    bus = EventBus()
    orders: list[OrderRequest] = []
    alerts: list[Alert] = []
    bus.subscribe(OrderRequest, orders.append)
    bus.subscribe(Alert, alerts.append)
    positions = MemoryPositionStore()
    if symbol_qty != 0:
        positions.update("AAPL", symbol_qty, Decimal("150"))
    slices = StrategyPositionStore()
    if slice_qty != 0:
        slices.update(strategy_id, "AAPL", slice_qty, Decimal("150"))
    router = BacktestOrderRouter(clock=clock)
    orch = Orchestrator(
        selection_policy=Top1SelectionPolicy(),
        clock=clock,
        bus=bus,
        backend=ExecutionBackend(
            market_data=_StubMarketData(),
            order_router=router,
            mode="BACKTEST",
        ),
        risk_engine=_StubRiskEngine(),
        position_store=positions,
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
        strategy_positions=slices,
        trading_session_bounds=_bounds() if at_cutoff else None,
        mark_rail=_FixedRail(crossed=crossed, paying_absent=paying_absent),
        exit_policies={_OWNED: _policy()},
    )
    _boot(orch)

    def emit(quote: NBBOQuote) -> None:
        bus.publish(
            Signal(
                timestamp_ns=quote.timestamp_ns,
                correlation_id=quote.correlation_id,
                sequence=quote.sequence,
                symbol=quote.symbol,
                strategy_id=strategy_id,
                direction=direction,
                strength=0.8,
                edge_estimate_bps=5.0,
            )
        )

    bus.subscribe(NBBOQuote, emit)
    quote = _quote(_AT_CUTOFF_NS if at_cutoff else _MID_SESSION_NS)
    router.on_quote(quote)
    orch._process_tick(quote)
    return orders, alerts


def _assert_refused(
    orders: list[OrderRequest],
    alerts: list[Alert],
    reason: str,
    *,
    slice_quantity: int,
) -> None:
    import feelies.core.order_admission as admission

    assert getattr(admission, reason) == reason
    assert orders == []
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.alert_name == "position_entry_refused"
    assert alert.severity is AlertSeverity.WARNING
    assert dict(alert.context) == {
        "symbol": "AAPL",
        "strategy_id": _OWNED,
        "side": "BUY",
        "intent": "ENTRY_LONG",
        "refusal_reason": reason,
        "rail_quote_sequence": _QUOTE_SEQUENCE,
        "slice_quantity": slice_quantity,
    }


def test_crossed_at_birth_refuses_owned_entry() -> None:
    orders, alerts = _drive(
        strategy_id=_OWNED,
        direction=SignalDirection.LONG,
        crossed=True,
        paying_absent=True,
        symbol_qty=0,
        slice_qty=_SLICE,
        at_cutoff=True,
    )
    _assert_refused(orders, alerts, "CROSSED_AT_BIRTH", slice_quantity=_SLICE)


def test_no_paying_price_refuses_owned_entry() -> None:
    orders, alerts = _drive(
        strategy_id=_OWNED,
        direction=SignalDirection.LONG,
        crossed=False,
        paying_absent=True,
        symbol_qty=0,
        slice_qty=_SLICE,
        at_cutoff=True,
    )
    _assert_refused(orders, alerts, "NO_PAYING_PRICE", slice_quantity=_SLICE)


def test_cutoff_already_passed_refuses_owned_entry() -> None:
    orders, alerts = _drive(
        strategy_id=_OWNED,
        direction=SignalDirection.LONG,
        crossed=False,
        paying_absent=False,
        symbol_qty=0,
        slice_qty=_SLICE,
        at_cutoff=True,
    )
    _assert_refused(orders, alerts, "CUTOFF_ALREADY_PASSED", slice_quantity=_SLICE)


def test_no_scale_in_refuses_owned_entry() -> None:
    orders, alerts = _drive(
        strategy_id=_OWNED,
        direction=SignalDirection.LONG,
        crossed=False,
        paying_absent=False,
        symbol_qty=0,
        slice_qty=_SLICE,
        at_cutoff=False,
    )
    _assert_refused(orders, alerts, "NO_SCALE_IN", slice_quantity=_SLICE)


def test_owned_reduction_is_admitted() -> None:
    orders, alerts = _drive(
        strategy_id=_OWNED,
        direction=SignalDirection.FLAT,
        crossed=True,
        paying_absent=True,
        symbol_qty=100,
        slice_qty=100,
        at_cutoff=True,
    )
    assert len(orders) == 1
    assert [a for a in alerts if a.alert_name == "position_entry_refused"] == []


def test_non_owned_entry_under_crossed_rail_is_admitted() -> None:
    orders, alerts = _drive(
        strategy_id=_OTHER,
        direction=SignalDirection.LONG,
        crossed=True,
        paying_absent=True,
        symbol_qty=0,
        slice_qty=_SLICE,
        at_cutoff=True,
    )
    assert len(orders) == 1
    assert [a for a in alerts if a.alert_name == "position_entry_refused"] == []
