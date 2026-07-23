"""Trade-path HorizonTicks must not outrun the first RegimeState publish.

RTH open often starts with auction prints (Trade) before the first NBBOQuote.
The trade path drives ``HorizonScheduler`` without calling ``_update_regime``
(regime engines require quotes).  Emitting those ticks cold leaves
``HorizonSignalEngine`` with an empty regime cache and logs:

    gate suppressed … P(normal) referenced but no RegimeState is available

This suite locks the deferral: skip ``on_event`` on the trade path until a
quote has published ``RegimeState`` for that symbol; the first quote still
emits the opening boundary because the scheduler cursor was not advanced.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import HorizonTick, NBBOQuote, Trade
from feelies.core.identifiers import SequenceGenerator
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.storage.memory_event_log import InMemoryEventLog

SESSION_OPEN_NS = 1_000_000_000_000_000_000


class _NoOpMetricCollector:
    def record(self, _metric: Any) -> None:
        pass

    def flush(self) -> None:
        pass


class _StubMarketData:
    def events(self) -> Any:
        return iter(())


class _StubRiskEngine:
    def check_signal(self, signal: Any, positions: Any) -> Any:
        raise AssertionError("risk engine unused in this suite")

    def check_order(self, order: Any, positions: Any) -> Any:
        raise AssertionError("risk engine unused in this suite")

    def check_sized_intent(self, intent: Any, positions: Any) -> Any:
        raise AssertionError("risk engine unused in this suite")


class _StubRegimeEngine:
    """Minimal RegimeEngine so ``_update_regime`` can publish."""

    state_names = ("normal", "stressed", "crisis")
    n_states = 3
    calibrated = True
    discriminability = 10.0

    def posterior(self, quote: NBBOQuote) -> list[float]:
        del quote
        return [0.9, 0.05, 0.05]

    def current_state(self, symbol: str) -> list[float] | None:
        del symbol
        return [0.9, 0.05, 0.05]


class _BootConfig:
    version: str = "t"
    symbols: frozenset[str] = frozenset({"AAPL"})
    degrade_on_data_gap: bool = False
    strict_normalizer_symbol_coverage: bool = False

    def validate(self) -> None:
        pass

    def snapshot(self) -> None:
        return None


def _quote(ts: int, seq: int = 1) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"AAPL:{ts}:{seq}",
        sequence=seq,
        symbol="AAPL",
        bid=Decimal("149.50"),
        ask=Decimal("150.50"),
        bid_size=100,
        ask_size=200,
        exchange_timestamp_ns=ts,
    )


def _trade(ts: int, seq: int = 1) -> Trade:
    return Trade(
        timestamp_ns=ts,
        correlation_id=f"AAPL:{ts}:{seq}",
        sequence=seq,
        symbol="AAPL",
        price=Decimal("150.00"),
        size=100,
        exchange_timestamp_ns=ts,
    )


def _build_orch(*, with_regime: bool) -> tuple[Orchestrator, EventBus, list[HorizonTick]]:
    clock = SimulatedClock(start_ns=SESSION_OPEN_NS)
    bus = EventBus()
    ticks: list[HorizonTick] = []
    bus.subscribe(HorizonTick, ticks.append)

    scheduler = HorizonScheduler(
        horizons=frozenset({30, 120}),
        session_id="TEST_RTH",
        symbols=frozenset({"AAPL"}),
        session_open_ns=SESSION_OPEN_NS,
        sequence_generator=SequenceGenerator(),
    )
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
        risk_engine=_StubRiskEngine(),
        position_store=MemoryPositionStore(),
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
        regime_engine=_StubRegimeEngine() if with_regime else None,
        regime_engine_registry_name="hmm_3state_fractional" if with_regime else None,
        horizon_scheduler=scheduler,
    )
    orch.boot(_BootConfig())
    orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
    orch._micro.reset(trigger="session_start:test")
    orch._reset_regime_session_state()
    return orch, bus, ticks


def test_trade_before_first_quote_defers_horizon_ticks_when_regime_wired() -> None:
    orch, _bus, ticks = _build_orch(with_regime=True)

    orch._process_trade(_trade(SESSION_OPEN_NS, seq=1))
    assert ticks == [], (
        "trade-path HorizonTicks must wait for a quote-driven RegimeState "
        f"publish; got {ticks!r}"
    )
    assert "AAPL" not in orch._regime_bus_published_symbols


def test_first_quote_publishes_regime_and_emits_opening_boundary() -> None:
    orch, _bus, ticks = _build_orch(with_regime=True)

    orch._process_trade(_trade(SESSION_OPEN_NS, seq=1))
    assert ticks == []

    orch._process_tick(_quote(SESSION_OPEN_NS + 156_000_000, seq=2))
    assert "AAPL" in orch._regime_bus_published_symbols
    assert ticks, "first quote must emit the opening boundary the trade deferred"
    assert {t.boundary_index for t in ticks} == {0}
    assert {t.horizon_seconds for t in ticks} >= {30, 120}


def test_trade_after_quote_emits_horizon_ticks() -> None:
    orch, _bus, ticks = _build_orch(with_regime=True)

    orch._process_tick(_quote(SESSION_OPEN_NS, seq=1))
    ticks.clear()

    # Next 30s boundary crossed by a trade.
    orch._process_trade(_trade(SESSION_OPEN_NS + 30_000_000_000, seq=2))
    assert any(t.horizon_seconds == 30 and t.boundary_index == 1 for t in ticks), (
        f"expected trade-path tick at boundary 1 after regime warm; got {ticks!r}"
    )


def test_trade_path_emits_when_regime_engine_absent() -> None:
    """No regime engine → no RegimeState dependency; keep prior trade-path behaviour."""
    _orch, _bus, ticks = _build_orch(with_regime=False)

    _orch._process_trade(_trade(SESSION_OPEN_NS, seq=1))
    assert ticks, "without a regime engine, trade-path HorizonTicks must still emit"
