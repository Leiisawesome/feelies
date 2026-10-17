"""Own-symbol release of a held single-alpha signal.

A signal buffered between quotes is released only by an NBBOQuote of its
own symbol, and that quote prices the order. A quote of another symbol
leaves the signal held. Horizon expiry is unchanged: the window is
``quote.timestamp_ns - signal.timestamp_ns`` against ``horizon_seconds``,
and ``signal.timestamp_ns`` is the trigger stamp. An expired signal leaves
the buffer and produces no order.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from feelies.alpha.loader import AlphaLoader
from feelies.bootstrap import build_platform
from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.composition.selection_policy import Top1SelectionPolicy
from feelies.core.events import (
    NBBOQuote,
    OrderRequest,
    RiskAction,
    RiskVerdict,
    Signal,
    SignalDirection,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import ZeroCostModel
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.kernel.signal_order_trace import SignalOrderTraceRow
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.position_store import PositionStore
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.position_engine.scenarios import T0, _FIXTURE, _sensors
from tests.position_engine.tapes import make_tape

_BASE_NS = 1_000_000_000_000
_HORIZON_S = 30
_NS = 1_000_000_000


class _NoOpMetricCollector:
    def record(self, _metric: Any) -> None:
        return None

    def flush(self) -> None:
        return None


class _StubMarketData:
    def events(self) -> Any:
        return iter(())


class _StubRiskEngine:
    def check_signal(self, signal: Signal, _positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=signal.timestamp_ns,
            correlation_id=signal.correlation_id,
            sequence=signal.sequence,
            symbol=signal.symbol,
            action=RiskAction.ALLOW,
            reason="own-quote-test",
        )

    def check_order(self, order: OrderRequest, _positions: PositionStore) -> RiskVerdict:
        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=RiskAction.ALLOW,
            reason="own-quote-test",
        )


class _Config:
    version = "p23c2-own-quote"
    symbols = frozenset({"AAA", "BBB"})
    execution_mode = "passive_limit"
    signal_min_edge_cost_ratio = 0.0

    def validate(self) -> None:
        return None

    def snapshot(self) -> None:
        return None


def _quote(symbol: str, ts: int, seq: int, bid: str) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"{symbol}:{ts}:{seq}",
        sequence=seq,
        symbol=symbol,
        bid=Decimal(bid),
        ask=Decimal(bid) + Decimal("0.01"),
        bid_size=100,
        ask_size=200,
        exchange_timestamp_ns=ts,
    )


def _signal(symbol: str, ts: int) -> Signal:
    return Signal(
        timestamp_ns=ts,
        correlation_id=f"sig:{symbol}:{ts}",
        sequence=90_001,
        symbol=symbol,
        strategy_id="own_quote_alpha",
        direction=SignalDirection.LONG,
        strength=0.8,
        edge_estimate_bps=5.0,
        layer="SIGNAL",
        horizon_seconds=_HORIZON_S,
    )


def _orchestrator() -> tuple[Orchestrator, list[OrderRequest], list[SignalOrderTraceRow]]:
    clock = SimulatedClock(start_ns=_BASE_NS)
    bus = EventBus()
    orders: list[OrderRequest] = []
    sink: list[SignalOrderTraceRow] = []
    router = BacktestOrderRouter(clock=clock, cost_model=ZeroCostModel())
    backend = ExecutionBackend(
        market_data=_StubMarketData(),
        order_router=router,
        mode="BACKTEST",
    )
    orch = Orchestrator(
        clock=clock,
        bus=bus,
        backend=backend,
        risk_engine=_StubRiskEngine(),
        position_store=MemoryPositionStore(),
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
        selection_policy=Top1SelectionPolicy(),
    )
    orch._signal_order_trace_sink = sink
    bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]
    orch.boot(_Config())
    assert orch.macro_state == MacroState.READY
    orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
    orch._micro.reset(trigger="session_start:test")
    return orch, orders, sink


def _tick(orch: Orchestrator, quote: NBBOQuote) -> None:
    orch._clock.set_time(quote.timestamp_ns)
    BacktestOrderRouter.on_quote(orch._backend.order_router, quote)
    orch._process_tick(quote)


def _hold(orch: Orchestrator) -> Signal:
    """Buffer one AAA signal after its own quote, while no tick is in flight."""
    opening = _quote("AAA", _BASE_NS, 1, "20.00")
    _tick(orch, opening)
    held = _signal("AAA", _BASE_NS)
    orch._bus.publish(held)
    assert held.sequence in orch._carryover_signal_sequences
    assert any(item.sequence == held.sequence for item in orch._signal_buffer)
    return held


def test_held_signal_is_priced_from_its_own_quote() -> None:
    orch, orders, _sink = _orchestrator()
    _hold(orch)
    _tick(orch, _quote("BBB", _BASE_NS + 10 * _NS, 2, "10.00"))
    _tick(orch, _quote("AAA", _BASE_NS + 11 * _NS, 3, "20.00"))
    assert len(orders) == 1, [(order.symbol, order.limit_price) for order in orders]
    order = orders[0]
    assert order.symbol == "AAA"
    assert order.limit_price == Decimal("20.00")


def test_foreign_quote_does_not_release_a_held_signal() -> None:
    orch, orders, _sink = _orchestrator()
    held = _hold(orch)
    _tick(orch, _quote("BBB", _BASE_NS + 10 * _NS, 2, "10.00"))
    assert orders == []
    assert any(item.sequence == held.sequence for item in orch._signal_buffer)


def test_held_signal_expires_when_horizon_elapses_without_own_quote() -> None:
    """Regression guard. The anchor is the trigger stamp, ``signal.timestamp_ns``.

    The compare is ``quote.timestamp_ns - signal.timestamp_ns`` at
    ``orchestrator.py`` against ``horizon_seconds``. A quote past that window
    drops the signal. The dropped signal produces no order. With a trace
    sink the row is ``NO_ORDER`` and
    ``signal_buffer_cleared_unprocessed_at_tick_boundary``.
    """
    orch, orders, sink = _orchestrator()
    held = _hold(orch)
    # Age == horizon is still fresh. One nanosecond past expires.
    late = _BASE_NS + _HORIZON_S * _NS + 1
    _tick(orch, _quote("BBB", late, 2, "10.00"))
    assert orders == []
    assert all(item.sequence != held.sequence for item in orch._signal_buffer)
    evicted = [
        row
        for row in sink
        if row.signal_sequence == held.sequence
        and "signal_buffer_cleared_unprocessed_at_tick_boundary" in row.reasons
    ]
    assert len(evicted) == 1
    assert evicted[0].outcome == "NO_ORDER"


def _diff_count(left: list[Any], right: list[Any]) -> int:
    shared = min(len(left), len(right))
    changes = sum(1 for index in range(shared) if left[index] != right[index])
    return changes + abs(len(left) - len(right))


def _p4_spec() -> dict[str, object]:
    spec = copy.deepcopy(yaml.safe_load(_FIXTURE.read_text(encoding="utf-8")))
    risk = spec.setdefault("risk_budget", {})
    assert isinstance(risk, dict)
    risk["capital_allocation_pct"] = 10.0
    risk["max_gross_exposure_pct"] = 80.0
    risk["max_position_per_symbol"] = 500
    risk["max_drawdown_pct"] = 100.0
    return spec


def _p4_fills(tape: list[NBBOQuote], symbols: tuple[str, ...]) -> list[tuple[Any, ...]]:
    spec = _p4_spec()
    original = AlphaLoader.load

    def _load(
        self: AlphaLoader,
        path: object,
        param_overrides: dict[str, object] | None = None,
    ) -> object:
        if Path(str(path)) == _FIXTURE:
            return self.load_from_dict(spec, source=str(_FIXTURE))
        return original(self, path, param_overrides)

    log = InMemoryEventLog()
    log.append_batch(list(tape))
    config = PlatformConfig(
        symbols=frozenset(symbols),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_FIXTURE],
        sensor_specs=_sensors(),  # type: ignore[arg-type]
        regime_engine=None,
        enforce_trend_mechanism=False,
        session_open_ns=T0,
        risk_max_gross_exposure_pct=80.0,
        account_equity=50_000.0,
    )
    AlphaLoader.load = _load  # type: ignore[method-assign]
    try:
        orchestrator, resolved = build_platform(config, event_log=log)
        orchestrator.boot(resolved)
        orchestrator.run_backtest()
        journal = orchestrator.trade_journal
        assert journal is not None
        rows = [
            (
                record.symbol,
                record.fill_timestamp_ns,
                str(record.fill_price),
                record.filled_quantity,
                record.side.name,
            )
            for record in journal.query()
        ]
    finally:
        AlphaLoader.load = original  # type: ignore[method-assign]
    return rows


def test_joint_run_fills_equal_solo_run_fills() -> None:
    """P4. Each symbol's joint-run fills equal its solo-run fills.

    The unpatched negative control is a BBB diff of 3 (E0). This test
    asserts the property: both diffs are 0, and each solo run trades.
    """
    aaa = make_tape(seed=11, n=8000, symbol="AAA", start_ns=T0, size=1000)
    bbb = make_tape(
        seed=12,
        n=8000,
        symbol="BBB",
        start_ns=T0 + 50_000_000,
        size=1000,
        start_sequence=1_000_001,
    )
    joint_tape = sorted([*aaa, *bbb], key=lambda quote: quote.timestamp_ns)
    alone_a = _p4_fills(aaa, ("AAA",))
    alone_b = _p4_fills(bbb, ("BBB",))
    joint = _p4_fills(joint_tape, ("AAA", "BBB"))
    assert alone_a, "solo AAA produced no fills"
    assert alone_b, "solo BBB produced no fills"

    def _of(rows: list[tuple[Any, ...]], symbol: str) -> list[tuple[Any, ...]]:
        return [row[1:] for row in rows if row[0] == symbol]

    changes = {
        "AAA": _diff_count(_of(alone_a, "AAA"), _of(joint, "AAA")),
        "BBB": _diff_count(_of(alone_b, "BBB"), _of(joint, "BBB")),
    }
    assert changes == {"AAA": 0, "BBB": 0}, changes
