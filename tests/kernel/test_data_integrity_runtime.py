"""Runtime data-health gates on the orchestrator (post-ingest / live normalizer)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    Alert,
    NBBOQuote,
    OrderRequest,
    RiskAction,
    RiskVerdict,
    Signal,
    Trade,
)
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.ingestion.data_integrity import DataHealth
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.position_store import PositionStore
from feelies.risk.sized_intent_result import SizedIntentRiskResult
from feelies.storage.memory_event_log import InMemoryEventLog


class _NoOpMetricCollector:
    def record(self, _metric: Any) -> None:
        pass

    def flush(self) -> None:
        pass


class _StubMarketData:
    def __init__(self, events: list[Any] | None = None) -> None:
        self._events = events or []

    def events(self) -> Any:
        return iter(self._events)


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

    def check_order(
        self,
        order: OrderRequest,
        positions: PositionStore,
    ) -> RiskVerdict:
        del positions
        return RiskVerdict(
            timestamp_ns=order.timestamp_ns,
            correlation_id=order.correlation_id,
            sequence=order.sequence,
            symbol=order.symbol,
            action=RiskAction.ALLOW,
            reason="test",
        )

    def check_sized_intent(
        self,
        intent: Any,
        positions: PositionStore,
    ) -> SizedIntentRiskResult:
        del intent, positions
        return SizedIntentRiskResult(orders=())


@dataclass
class _ConfigWithGapPolicy:
    version: str = "t"
    symbols: frozenset[str] = frozenset({"AAPL"})
    degrade_on_data_gap: bool = True
    strict_normalizer_symbol_coverage: bool = False

    def validate(self) -> None:
        pass

    def snapshot(self) -> None:
        return None


def _make_quote(ts: int = 1000, seq: int = 1) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"AAPL:{ts}:{seq}",
        sequence=seq,
        symbol="AAPL",
        bid=Decimal("149.50"),
        ask=Decimal("150.50"),
        bid_size=100,
        ask_size=200,
        exchange_timestamp_ns=ts - 100,
    )


def _make_trade(ts: int = 1000, seq: int = 1) -> Trade:
    return Trade(
        timestamp_ns=ts,
        correlation_id=f"AAPL:{ts}:{seq}",
        sequence=seq,
        symbol="AAPL",
        price=Decimal("150.00"),
        size=100,
        exchange_timestamp_ns=ts - 100,
    )


class _MutableHealthNormalizer:
    """MarketDataNormalizer stand-in for kernel tests."""

    __slots__ = ("_h",)

    def __init__(self, initial: dict[str, DataHealth]) -> None:
        self._h = dict(initial)

    def on_message(self, raw: bytes, received_ns: int, source: str) -> list:
        del raw, received_ns, source
        return []

    def health(self, symbol: str) -> DataHealth:
        return self._h.get(symbol, DataHealth.HEALTHY)

    def all_health(self) -> dict[str, DataHealth]:
        return dict(self._h)

    def set_health(self, symbol: str, state: DataHealth) -> None:
        self._h[symbol] = state


def _orch_with_normalizer(
    clock: SimulatedClock,
    normalizer: Any,
) -> Orchestrator:
    bt_router = BacktestOrderRouter(clock=clock)
    backend = ExecutionBackend(
        market_data=_StubMarketData(),
        order_router=bt_router,
        mode="BACKTEST",
    )
    return Orchestrator(
        clock=clock,
        bus=EventBus(),
        backend=backend,
        risk_engine=_StubRiskEngine(),
        position_store=MemoryPositionStore(),
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
        normalizer=normalizer,
    )


class TestDegradeOnDataGap:
    def test_gap_detected_degrades_macro_when_configured(self) -> None:
        clock = SimulatedClock(start_ns=10_000)
        norm = _MutableHealthNormalizer({"AAPL": DataHealth.HEALTHY})
        orch = _orch_with_normalizer(clock, norm)
        orch.boot(_ConfigWithGapPolicy())

        norm.set_health("AAPL", DataHealth.GAP_DETECTED)
        orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
        orch._micro.reset(trigger="session_start:test")

        orch._process_tick_inner(_make_quote(ts=20_000, seq=1))

        assert orch.macro_state == MacroState.DEGRADED


class TestBootNormalizerCoverage:
    def test_boot_fails_when_config_symbol_missing_tracked_health(self) -> None:
        clock = SimulatedClock(start_ns=10_000)
        norm = _MutableHealthNormalizer({})
        orch = _orch_with_normalizer(clock, norm)
        orch.boot(_ConfigWithGapPolicy())
        assert orch.macro_state == MacroState.DEGRADED


class TestStrictNormalizerSymbolCoverage:
    def test_untracked_symbol_degrades_when_strict(self) -> None:
        clock = SimulatedClock(start_ns=10_000)
        norm = _MutableHealthNormalizer({"AAPL": DataHealth.HEALTHY})
        orch = _orch_with_normalizer(clock, norm)
        cfg = _ConfigWithGapPolicy(strict_normalizer_symbol_coverage=True)
        orch.boot(cfg)

        orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
        orch._micro.reset(trigger="session_start:test")

        norm_empty = _MutableHealthNormalizer({})
        orch._normalizer = norm_empty  # type: ignore[assignment]

        orch._process_tick_inner(_make_quote(ts=20_000, seq=1))
        assert orch.macro_state == MacroState.DEGRADED


class TestHaltedGate:
    """M1: parse-path halt blocks the tick gate and the halt store together.

    Health HALTED without store membership is a split, not a documented
    bypass. Drive the halt through the normalizer's trade-parse write and
    require both gates to agree; a tick blocked by one and not the other
    is an exposure decision.
    """

    def test_normalizer_halted_blocks_quote_without_macro_escalation(self) -> None:
        clock = SimulatedClock(start_ns=10_000)
        norm = MassiveNormalizer(
            clock,
            halt_on_codes=frozenset({5}),
            halt_off_codes=frozenset({6}),
        )
        norm.register_symbols(frozenset({"AAPL"}))
        orch = _orch_with_normalizer(clock, norm)
        orch.boot(_ConfigWithGapPolicy())

        orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
        orch._micro.reset(trigger="session_start:test")
        orch._halt_on_codes = frozenset({5})
        orch._halt_off_codes = frozenset({6})

        norm._apply_halt_status("AAPL", (5,))

        orch._process_tick_inner(_make_quote(ts=20_000, seq=1))

        # Tick blocked, but macro stays in BACKTEST_MODE — LULD halts are
        # recoverable and must NOT escalate to DEGRADED (unlike CORRUPTED
        # / GAP). Both gates must agree: parse wrote the store too.
        assert orch.macro_state == MacroState.BACKTEST_MODE
        assert "AAPL" in orch._halted_symbols
        assert norm.health("AAPL") == DataHealth.HALTED


class TestRejectedEventAlert:
    """DI-03: a market event blocked by the data-health gate never reaches
    ``EventLog.append``, so it must be reconstructable from an Alert instead.
    """

    def test_blocked_quote_publishes_rejection_alert(self) -> None:
        clock = SimulatedClock(start_ns=10_000)
        norm = _MutableHealthNormalizer({"AAPL": DataHealth.HEALTHY})
        orch = _orch_with_normalizer(clock, norm)
        orch.boot(_ConfigWithGapPolicy())
        orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
        orch._micro.reset(trigger="session_start:test")

        norm.set_health("AAPL", DataHealth.GAP_DETECTED)
        alerts: list[Alert] = []
        orch._bus.subscribe(Alert, alerts.append)

        quote = _make_quote(ts=20_000, seq=1)
        orch._process_tick_inner(quote)

        assert orch.macro_state == MacroState.DEGRADED
        rejected = [a for a in alerts if a.alert_name == "market_event_rejected_by_data_health"]
        assert len(rejected) == 1
        assert rejected[0].context["event_type"] == "NBBOQuote"
        assert rejected[0].context["symbol"] == "AAPL"
        assert rejected[0].context["data_health_reason"] == "GAP_DETECTED"
        assert rejected[0].context["bid"] == str(quote.bid)
        assert rejected[0].context["exchange_timestamp_ns"] == quote.exchange_timestamp_ns

    def test_blocked_trade_publishes_rejection_alert(self) -> None:
        clock = SimulatedClock(start_ns=10_000)
        norm = _MutableHealthNormalizer({"AAPL": DataHealth.HEALTHY})
        orch = _orch_with_normalizer(clock, norm)
        orch.boot(_ConfigWithGapPolicy())
        orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
        orch._micro.reset(trigger="session_start:test")

        norm.set_health("AAPL", DataHealth.GAP_DETECTED)
        alerts: list[Alert] = []
        orch._bus.subscribe(Alert, alerts.append)

        trade = _make_trade(ts=20_000, seq=1)
        orch._process_trade_inner(trade)

        rejected = [a for a in alerts if a.alert_name == "market_event_rejected_by_data_health"]
        assert len(rejected) == 1
        assert rejected[0].context["event_type"] == "Trade"
        assert rejected[0].context["price"] == str(trade.price)
        assert rejected[0].context["data_health_reason"] == "GAP_DETECTED"

    def test_halted_trade_does_not_publish_rejection_alert(self) -> None:
        """HALTED trades are already logged/published via the existing
        forensic carve-out, so no rejection alert is needed for them.
        """
        clock = SimulatedClock(start_ns=10_000)
        norm = _MutableHealthNormalizer({"AAPL": DataHealth.HEALTHY})
        orch = _orch_with_normalizer(clock, norm)
        orch.boot(_ConfigWithGapPolicy())
        orch._macro.transition(MacroState.BACKTEST_MODE, trigger="CMD_BACKTEST")
        orch._micro.reset(trigger="session_start:test")

        norm.set_health("AAPL", DataHealth.HALTED)
        alerts: list[Alert] = []
        orch._bus.subscribe(Alert, alerts.append)

        orch._process_trade_inner(_make_trade(ts=20_000, seq=1))

        rejected = [a for a in alerts if a.alert_name == "market_event_rejected_by_data_health"]
        assert rejected == []
