"""Application-facing service layer for the trading workbench UI.

Transforms the existing backtest pipeline into a reusable API that can be
consumed by a web UI or other operator tooling without scraping terminal
output. The current platform executes end-to-end only in BACKTEST mode, so
the workbench exposes paper/live posture as capabilities rather than trying
to simulate functionality that is not implemented yet.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, TypeVar

from feelies.bootstrap import build_platform
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    Alert,
    AlertSeverity,
    Event,
    FeatureVector,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    PositionUpdate,
    Signal,
    SignalDirection,
    StateTransition,
    Trade,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.ingestion.massive_ingestor import IngestResult
from feelies.kernel.macro import MacroState
from feelies.monitoring.in_memory import InMemoryMetricCollector
from feelies.storage.disk_event_cache import DiskEventCache
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.storage.trade_journal import TradeRecord

T = TypeVar("T", bound=Event)

_DEFAULT_CONFIG_PATH = Path("platform.yaml")
_DEFAULT_CAPABILITIES = {
    "BACKTEST": {"available": True, "reason": "Fully implemented end-to-end."},
    "PAPER": {
        "available": False,
        "reason": "Paper execution backend is defined in the architecture but not wired in bootstrap.",
    },
    "LIVE": {
        "available": False,
        "reason": "Live execution backend is defined in the architecture but not wired in bootstrap.",
    },
}

_DEMO_TICKS: list[dict[str, str | int]] = [
    {"bid": "150.00", "ask": "150.01", "ts": 1_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 2_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 3_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 4_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 5_000_000_000},
    {"bid": "160.00", "ask": "160.01", "ts": 6_000_000_000},
    {"bid": "160.00", "ask": "160.01", "ts": 7_000_000_000},
    {"bid": "140.00", "ask": "140.01", "ts": 8_000_000_000},
]


class WorkbenchError(RuntimeError):
    """Raised when a workbench request cannot be fulfilled."""


@dataclass(slots=True)
class BusRecorder:
    """Captures the event stream emitted on the bus for UI summarization."""

    events: list[Event] = field(default_factory=list)
    by_type: dict[type[Event], list[Event]] = field(default_factory=lambda: defaultdict(list))

    def __call__(self, event: Event) -> None:
        self.events.append(event)
        self.by_type[type(event)].append(event)

    def of_type(self, event_type: type[T]) -> list[T]:
        return self.by_type[event_type]  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class DaySource:
    """Provenance for one ingested symbol/day pair."""

    symbol: str
    date: str
    source: str
    event_count: int


@dataclass(frozen=True, slots=True)
class BacktestRunRequest:
    """Operator request accepted by the workbench."""

    demo: bool = False
    config_path: str = "platform.yaml"
    symbols: tuple[str, ...] = ()
    start_date: str | None = None
    end_date: str | None = None
    cache_dir: str | None = None
    no_cache: bool = False
    api_key: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> BacktestRunRequest:
        symbols_raw = payload.get("symbols", [])
        symbols = tuple(
            str(symbol).strip().upper()
            for symbol in symbols_raw
            if str(symbol).strip()
        )
        return cls(
            demo=bool(payload.get("demo", False)),
            config_path=str(payload.get("configPath") or payload.get("config_path") or "platform.yaml"),
            symbols=symbols,
            start_date=_optional_str(payload.get("startDate") or payload.get("start_date")),
            end_date=_optional_str(payload.get("endDate") or payload.get("end_date")),
            cache_dir=_optional_str(payload.get("cacheDir") or payload.get("cache_dir")),
            no_cache=bool(payload.get("noCache", payload.get("no_cache", False))),
            api_key=_optional_str(payload.get("apiKey") or payload.get("api_key")),
        )


def load_workbench_bootstrap(config_path: str = "platform.yaml") -> dict[str, Any]:
    """Return static posture and config metadata needed to render the UI shell."""
    path = Path(config_path)
    config_exists = path.exists()
    config_summary: dict[str, Any] = {
        "path": str(path),
        "exists": config_exists,
        "defaults": {
            "demo": True,
            "startDate": None,
            "endDate": None,
            "symbols": [],
            "noCache": False,
        },
    }

    alpha_specs: list[dict[str, Any]] = []
    if config_exists:
        config = PlatformConfig.from_yaml(path)
        config_summary["defaults"] = {
            "demo": False,
            "startDate": None,
            "endDate": None,
            "symbols": sorted(config.symbols),
            "noCache": False,
        }
        config_summary["platform"] = {
            "author": config.author,
            "version": config.version,
            "mode": config.mode.name,
            "symbols": sorted(config.symbols),
            "regimeEngine": config.regime_engine,
            "risk": {
                "maxPositionPerSymbol": config.risk_max_position_per_symbol,
                "maxGrossExposurePct": config.risk_max_gross_exposure_pct,
                "maxDrawdownPct": config.risk_max_drawdown_pct,
                "accountEquity": config.account_equity,
            },
        }
        alpha_specs = _discover_alpha_specs(path.parent, config)

    return {
        "capabilities": _DEFAULT_CAPABILITIES,
        "topology": {
            "macro": [
                "INIT",
                "DATA_SYNC",
                "READY",
                "BACKTEST_MODE",
                "PAPER_TRADING_MODE",
                "LIVE_TRADING_MODE",
                "DEGRADED",
                "RISK_LOCKDOWN",
                "SHUTDOWN",
            ],
            "micro": [
                "WAITING_FOR_MARKET_EVENT",
                "MARKET_EVENT_RECEIVED",
                "STATE_UPDATE",
                "FEATURE_COMPUTE",
                "SIGNAL_EVALUATE",
                "RISK_CHECK",
                "ORDER_DECISION",
                "ORDER_SUBMIT",
                "ORDER_ACK",
                "POSITION_UPDATE",
                "LOG_AND_METRICS",
            ],
        },
        "config": config_summary,
        "alphaSpecs": alpha_specs,
        "notes": [
            "The deterministic micro-state pipeline is shared across backtest, paper, and live modes.",
            "Only backtest is currently executable end-to-end because paper and live execution backends are not wired in bootstrap.",
            "The workbench surfaces the real event bus, trade journal, metrics, alerts, and state transitions from a run snapshot.",
        ],
    }


def run_workbench(request: BacktestRunRequest) -> dict[str, Any]:
    """Execute a backtest request and return a structured UI snapshot."""
    if request.demo:
        run_data = _run_demo_backtest(request)
    else:
        run_data = _run_historical_backtest(request)
    return _build_workbench_snapshot(**run_data)


def _run_demo_backtest(request: BacktestRunRequest) -> dict[str, Any]:
    alpha_src = _resolve_project_root() / "alphas" / "mean_reversion.alpha.yaml"
    tmp_dir = tempfile.mkdtemp(prefix="feelies_demo_")
    try:
        alpha_dst = Path(tmp_dir) / alpha_src.name
        shutil.copy2(alpha_src, alpha_dst)

        config = PlatformConfig(
            symbols=frozenset(["AAPL"]),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=Path(tmp_dir),
            regime_engine=None,
            account_equity=100_000.0,
            parameter_overrides={
                "mean_reversion": {"ewma_span": 5, "zscore_entry": 1.0},
            },
        )

        event_log = InMemoryEventLog()
        for quote in _make_demo_quotes():
            event_log.append(quote)

        orchestrator, config = build_platform(config, event_log=event_log)
        recorder = BusRecorder()
        orchestrator._bus.subscribe_all(recorder)  # type: ignore[attr-defined]

        orchestrator.boot(config)
        orchestrator.run_backtest()

        ingest_result = IngestResult(
            events_ingested=len(_DEMO_TICKS),
            pages_processed=1,
            symbols_with_gaps=0,
            duplicates_filtered=0,
            symbols_completed=frozenset(["AAPL"]),
        )

        return {
            "request": request,
            "orchestrator": orchestrator,
            "recorder": recorder,
            "ingest_result": ingest_result,
            "config": config,
            "symbol_str": "AAPL",
            "date_range": "DEMO (synthetic)",
            "day_sources": [],
            "mode_note": "Demo mode uses the synthetic eight-tick replay path.",
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _run_historical_backtest(request: BacktestRunRequest) -> dict[str, Any]:
    if not request.start_date:
        raise WorkbenchError("startDate is required for non-demo runs.")

    config_path = Path(request.config_path)
    if not config_path.exists():
        raise WorkbenchError(f"Config file not found: {config_path}")

    api_key = request.api_key or os.getenv("MASSIVE_API_KEY")
    if not api_key:
        raise WorkbenchError("MASSIVE_API_KEY is not set. Use demo mode or provide an API key.")

    config = PlatformConfig.from_yaml(config_path)
    config.mode = OperatingMode.BACKTEST
    if request.symbols:
        config.symbols = frozenset(request.symbols)

    symbols = sorted(config.symbols)
    if not symbols:
        raise WorkbenchError("No symbols are configured for the run.")

    start_date = request.start_date
    end_date = request.end_date or start_date
    cache_dir = Path(request.cache_dir) if request.cache_dir else None
    event_log, ingest_result, day_sources = ingest_data(
        api_key,
        symbols,
        start_date,
        end_date,
        cache_dir=cache_dir,
        no_cache=request.no_cache,
    )

    orchestrator, config = build_platform(config, event_log=event_log)
    recorder = BusRecorder()
    orchestrator._bus.subscribe_all(recorder)  # type: ignore[attr-defined]
    orchestrator.boot(config)
    if orchestrator.macro_state != MacroState.READY:
        raise WorkbenchError(
            f"Boot failed: macro state is {orchestrator.macro_state.name}, expected READY."
        )

    orchestrator.run_backtest()
    date_range = start_date if start_date == end_date else f"{start_date} to {end_date}"
    return {
        "request": request,
        "orchestrator": orchestrator,
        "recorder": recorder,
        "ingest_result": ingest_result,
        "config": config,
        "symbol_str": ", ".join(symbols),
        "date_range": date_range,
        "day_sources": [asdict(day_source) for day_source in day_sources],
        "mode_note": "Historical mode replays cached or downloaded Massive quotes through the deterministic pipeline.",
    }


def _build_workbench_snapshot(
    *,
    request: BacktestRunRequest,
    orchestrator: object,
    recorder: BusRecorder,
    ingest_result: IngestResult,
    config: PlatformConfig,
    symbol_str: str,
    date_range: str,
    day_sources: list[dict[str, Any]],
    mode_note: str,
) -> dict[str, Any]:
    quotes = recorder.of_type(NBBOQuote)
    features = recorder.of_type(FeatureVector)
    signals = recorder.of_type(Signal)
    orders = recorder.of_type(OrderRequest)
    acks = recorder.of_type(OrderAck)
    position_updates = recorder.of_type(PositionUpdate)
    transitions = recorder.of_type(StateTransition)

    filled_acks = [ack for ack in acks if ack.status == OrderAckStatus.FILLED]
    rejected_acks = [ack for ack in acks if ack.status == OrderAckStatus.REJECTED]
    long_signals = [signal for signal in signals if signal.direction == SignalDirection.LONG]
    short_signals = [signal for signal in signals if signal.direction == SignalDirection.SHORT]
    warmup_features = [feature for feature in features if not feature.warm]

    positions = orchestrator._positions  # type: ignore[attr-defined]
    all_positions = positions.all_positions()
    starting_equity = float(orchestrator._account_equity)  # type: ignore[attr-defined]
    realized_pnl = sum((position.realized_pnl for position in all_positions.values()), Decimal("0"))
    unrealized_pnl = sum((position.unrealized_pnl for position in all_positions.values()), Decimal("0"))
    gross_pnl = realized_pnl + unrealized_pnl
    fees = sum((ack.fees for ack in filled_acks), Decimal("0"))
    net_pnl = gross_pnl - fees
    final_equity = Decimal(str(starting_equity)) + net_pnl
    return_pct = float(net_pnl) / starting_equity * 100.0 if starting_equity else 0.0

    journal = orchestrator._trade_journal  # type: ignore[attr-defined]
    trade_records: list[TradeRecord] = list(journal.query())
    open_positions = sum(1 for position in all_positions.values() if position.quantity != 0)

    winning_pnls: list[Decimal] = []
    losing_pnls: list[Decimal] = []
    for record in trade_records:
        if record.realized_pnl > 0:
            winning_pnls.append(record.realized_pnl)
        elif record.realized_pnl < 0:
            losing_pnls.append(record.realized_pnl)

    total_shares = sum(abs(ack.filled_quantity) for ack in filled_acks)
    win_count = len(winning_pnls)
    loss_count = len(losing_pnls)
    resolved_count = win_count + loss_count
    win_rate = (win_count / resolved_count * 100.0) if resolved_count else 0.0
    avg_win = sum(winning_pnls, Decimal("0")) / len(winning_pnls) if winning_pnls else Decimal("0")
    avg_loss = sum(losing_pnls, Decimal("0")) / len(losing_pnls) if losing_pnls else Decimal("0")
    largest_win = max(winning_pnls) if winning_pnls else Decimal("0")
    largest_loss = min(losing_pnls) if losing_pnls else Decimal("0")
    pnl_per_share = float(realized_pnl) / total_shares if total_shares else 0.0

    max_exposure = Decimal("0")
    per_symbol_exposure: dict[str, Decimal] = {}
    for update in position_updates:
        per_symbol_exposure[update.symbol] = abs(Decimal(str(update.quantity)) * update.avg_price)
        total_exposure = sum(per_symbol_exposure.values())
        if total_exposure > max_exposure:
            max_exposure = total_exposure
    max_exposure_pct = float(max_exposure) / starting_equity * 100.0 if starting_equity else 0.0

    equity_curve = _build_equity_curve(position_updates, starting_equity)
    max_drawdown = min((Decimal(point["drawdown"]) for point in equity_curve), default=Decimal("0"))
    max_drawdown_pct = float(max_drawdown) / starting_equity * 100.0 if starting_equity else 0.0

    metrics: InMemoryMetricCollector = orchestrator._metrics  # type: ignore[attr-defined]
    tick_summary = metrics.get_summary("kernel", "tick_to_decision_latency_ns")
    feature_summary = metrics.get_summary("kernel", "feature_compute_ns")
    signal_summary = metrics.get_summary("kernel", "signal_evaluate_ns")
    avg_tick_ns = tick_summary.mean if tick_summary else 0.0
    max_tick_ns = tick_summary.max_value if tick_summary else 0.0
    avg_feature_ns = feature_summary.mean if feature_summary else 0.0
    avg_signal_ns = signal_summary.mean if signal_summary else 0.0

    alert_manager = orchestrator._alert_manager  # type: ignore[attr-defined]
    all_alerts = alert_manager.all_alerts if alert_manager is not None else []
    active_alerts = alert_manager.active_alerts() if alert_manager is not None else []
    kill_switch = orchestrator._kill_switch  # type: ignore[attr-defined]

    verification = _run_verification(recorder, ingest_result, orchestrator)

    payload = {
        "request": {
            "demo": request.demo,
            "configPath": request.config_path,
            "symbols": list(request.symbols),
            "startDate": request.start_date,
            "endDate": request.end_date,
            "noCache": request.no_cache,
        },
        "capabilities": _DEFAULT_CAPABILITIES,
        "runMeta": {
            "symbolScope": symbol_str,
            "dateRange": date_range,
            "modeNote": mode_note,
            "configChecksum": getattr(orchestrator, "config_snapshot").checksum,
            "alphaCount": len(orchestrator._alpha_registry) if orchestrator._alpha_registry else 0,  # type: ignore[attr-defined]
        },
        "system": {
            "macroState": orchestrator.macro_state.name,
            "microState": orchestrator.micro_state.name,
            "riskLevel": orchestrator.risk_level.name,
            "killSwitchActive": kill_switch.is_active,
            "activeOrders": len(orchestrator._active_orders),  # type: ignore[attr-defined]
            "activeAlerts": len(active_alerts),
        },
        "summary": {
            "startingEquity": starting_equity,
            "finalEquity": _float(final_equity),
            "grossPnl": _float(gross_pnl),
            "netPnl": _float(net_pnl),
            "fees": _float(fees),
            "returnPct": return_pct,
            "maxExposure": _float(max_exposure),
            "maxExposurePct": max_exposure_pct,
            "maxDrawdown": _float(max_drawdown),
            "maxDrawdownPct": max_drawdown_pct,
            "ordersSubmitted": len(orders),
            "ordersFilled": len(filled_acks),
            "ordersRejected": len(rejected_acks),
            "signalsEmitted": len(signals),
            "longSignals": len(long_signals),
            "shortSignals": len(short_signals),
            "featureVectors": len(features),
            "warmupTicks": len(warmup_features),
            "quotesProcessed": len(quotes),
            "totalEvents": ingest_result.events_ingested,
            "totalShares": total_shares,
            "openPositions": open_positions,
            "winRate": win_rate,
            "avgWin": _float(avg_win),
            "avgLoss": _float(avg_loss),
            "largestWin": _float(largest_win),
            "largestLoss": _float(largest_loss),
            "pnlPerShare": pnl_per_share,
            "avgTickLatencyMs": avg_tick_ns / 1_000_000,
            "maxTickLatencyMs": max_tick_ns / 1_000_000,
            "avgFeatureLatencyMs": avg_feature_ns / 1_000_000,
            "avgSignalLatencyMs": avg_signal_ns / 1_000_000,
        },
        "ingestion": {
            "eventsIngested": ingest_result.events_ingested,
            "pagesProcessed": ingest_result.pages_processed,
            "symbolsWithGaps": ingest_result.symbols_with_gaps,
            "duplicatesFiltered": ingest_result.duplicates_filtered,
            "daySources": day_sources,
        },
        "config": {
            "author": config.author,
            "version": config.version,
            "symbols": sorted(config.symbols),
            "mode": config.mode.name,
            "regimeEngine": config.regime_engine,
            "risk": {
                "maxPositionPerSymbol": config.risk_max_position_per_symbol,
                "maxGrossExposurePct": config.risk_max_gross_exposure_pct,
                "maxDrawdownPct": config.risk_max_drawdown_pct,
                "accountEquity": config.account_equity,
            },
            "parameterOverrides": config.parameter_overrides,
        },
        "charts": {
            "equityCurve": [{
                "timestampNs": point["timestamp_ns"],
                "equity": _float(Decimal(point["equity"])),
                "drawdown": _float(Decimal(point["drawdown"])),
            } for point in equity_curve],
            "signalTimeline": [
                {
                    "timestampNs": signal.timestamp_ns,
                    "symbol": signal.symbol,
                    "direction": signal.direction.name,
                    "strength": signal.strength,
                    "edgeEstimateBps": signal.edge_estimate_bps,
                }
                for signal in signals[-120:]
            ],
            "fillsTimeline": [
                {
                    "timestampNs": ack.timestamp_ns,
                    "symbol": ack.symbol,
                    "filledQuantity": ack.filled_quantity,
                    "fillPrice": _float(ack.fill_price or Decimal("0")),
                    "status": ack.status.name,
                }
                for ack in filled_acks[-120:]
            ],
            "eventMix": [
                {"eventType": event_type, "count": count}
                for event_type, count in sorted(Counter(type(event).__name__ for event in recorder.events).items())
            ],
        },
        "tables": {
            "positions": [
                {
                    "symbol": symbol,
                    "quantity": position.quantity,
                    "avgEntryPrice": _float(position.avg_entry_price),
                    "realizedPnl": _float(position.realized_pnl),
                    "unrealizedPnl": _float(position.unrealized_pnl),
                }
                for symbol, position in sorted(all_positions.items())
            ],
            "orders": _build_order_rows(orders, acks),
            "trades": [_trade_record_to_row(record) for record in trade_records],
            "alerts": [_alert_to_row(alert, alert in active_alerts) for alert in all_alerts],
            "stateTransitions": [
                {
                    "timestampNs": transition.timestamp_ns,
                    "machine": transition.machine_name,
                    "from": transition.from_state,
                    "to": transition.to_state,
                    "trigger": transition.trigger,
                }
                for transition in transitions[-80:]
            ],
        },
        "verification": verification,
        "notes": [
            mode_note,
            "Signals are produced only from feature vectors; raw market events do not bypass the pipeline.",
            "Risk escalation can force flatten positions and activate the kill switch before any new order submissions continue.",
        ],
    }
    return payload


def _run_verification(
    recorder: BusRecorder,
    ingest_result: IngestResult,
    orchestrator: object,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    results.append({
        "name": "Events ingested",
        "passed": ingest_result.events_ingested > 0,
        "detail": f"{ingest_result.events_ingested} events",
    })

    signals = recorder.of_type(Signal)
    results.append({
        "name": "Signals fired",
        "passed": len(signals) > 0,
        "detail": f"{len(signals)} signals",
    })

    fills = [ack for ack in recorder.of_type(OrderAck) if ack.status == OrderAckStatus.FILLED]
    results.append({
        "name": "Fills occurred",
        "passed": len(fills) >= 1,
        "detail": f"{len(fills)} fills",
    })

    positions = orchestrator._positions  # type: ignore[attr-defined]
    all_positions = positions.all_positions()
    has_pnl = any(position.realized_pnl is not None for position in all_positions.values()) if all_positions else True
    results.append({
        "name": "P&L computable",
        "passed": has_pnl,
        "detail": "realized_pnl tracked" if has_pnl else "missing",
    })

    journal = orchestrator._trade_journal  # type: ignore[attr-defined]
    record_count = len(journal)
    results.append({
        "name": "Trade journal",
        "passed": record_count >= 1,
        "detail": f"{record_count} records",
    })

    results.append({
        "name": "Macro state",
        "passed": orchestrator.macro_state == MacroState.READY,
        "detail": orchestrator.macro_state.name,
    })

    kill_switch = orchestrator._kill_switch  # type: ignore[attr-defined]
    results.append({
        "name": "Kill switch",
        "passed": not kill_switch.is_active,
        "detail": "INACTIVE" if not kill_switch.is_active else "ACTIVE",
    })
    return results


def _build_equity_curve(
    position_updates: list[PositionUpdate],
    starting_equity: float,
) -> list[dict[str, str | int]]:
    peak_equity = Decimal(str(starting_equity))
    per_symbol_pnl: dict[str, Decimal] = {}
    curve: list[dict[str, str | int]] = []
    for update in position_updates:
        per_symbol_pnl[update.symbol] = update.realized_pnl
        current_equity = Decimal(str(starting_equity)) + sum(per_symbol_pnl.values())
        if current_equity > peak_equity:
            peak_equity = current_equity
        drawdown = current_equity - peak_equity
        curve.append({
            "timestamp_ns": update.timestamp_ns,
            "equity": str(current_equity),
            "drawdown": str(drawdown),
        })
    if not curve:
        curve.append({
            "timestamp_ns": 0,
            "equity": str(Decimal(str(starting_equity))),
            "drawdown": "0",
        })
    return curve


def _build_order_rows(
    orders: list[OrderRequest],
    acks: list[OrderAck],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ack_map: dict[str, list[OrderAck]] = defaultdict(list)
    for ack in acks:
        ack_map[ack.order_id].append(ack)

    for order in orders:
        order_acks = ack_map.get(order.order_id, [])
        latest_ack = order_acks[-1] if order_acks else None
        rows.append({
            "timestampNs": order.timestamp_ns,
            "orderId": order.order_id,
            "symbol": order.symbol,
            "side": order.side.name,
            "quantity": order.quantity,
            "strategyId": order.strategy_id,
            "status": latest_ack.status.name if latest_ack is not None else "SUBMITTED",
            "filledQuantity": latest_ack.filled_quantity if latest_ack is not None else 0,
            "fillPrice": _float(latest_ack.fill_price or Decimal("0")) if latest_ack is not None else None,
            "fees": _float(latest_ack.fees) if latest_ack is not None else 0.0,
            "reason": latest_ack.reason if latest_ack is not None else "",
        })
    return rows


def _trade_record_to_row(record: TradeRecord) -> dict[str, Any]:
    return {
        "orderId": record.order_id,
        "symbol": record.symbol,
        "strategyId": record.strategy_id,
        "side": record.side.name,
        "requestedQuantity": record.requested_quantity,
        "filledQuantity": record.filled_quantity,
        "fillPrice": _float(record.fill_price or Decimal("0")),
        "realizedPnl": _float(record.realized_pnl),
        "fees": _float(record.fees),
        "slippageBps": _float(record.slippage_bps),
        "fillTimestampNs": record.fill_timestamp_ns,
    }


def _alert_to_row(alert: Alert, is_active: bool) -> dict[str, Any]:
    return {
        "timestampNs": alert.timestamp_ns,
        "severity": alert.severity.name,
        "layer": alert.layer,
        "alertName": alert.alert_name,
        "message": alert.message,
        "active": is_active,
        "context": {key: _stringify(value) for key, value in alert.context.items()},
    }


def _discover_alpha_specs(base_dir: Path, config: PlatformConfig) -> list[dict[str, Any]]:
    spec_paths: list[Path] = []
    if config.alpha_spec_dir is not None:
        alpha_dir = (base_dir / config.alpha_spec_dir).resolve() if not config.alpha_spec_dir.is_absolute() else config.alpha_spec_dir
        if alpha_dir.exists():
            spec_paths.extend(sorted(alpha_dir.glob("*.alpha.yaml")))
    spec_paths.extend(path if path.is_absolute() else (base_dir / path).resolve() for path in config.alpha_specs)

    seen: set[Path] = set()
    specs: list[dict[str, Any]] = []
    for path in spec_paths:
        resolved = path.resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        specs.append({
            "name": resolved.name,
            "path": str(resolved),
        })
    return specs


def _resolve_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float(value: Decimal | float | int) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _stringify(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, AlertSeverity):
        return value.name
    return str(value)


def _make_demo_quotes() -> list[NBBOQuote]:
    quotes: list[NBBOQuote] = []
    for index, tick in enumerate(_DEMO_TICKS, start=1):
        timestamp_ns = int(tick["ts"])
        quotes.append(NBBOQuote(
            timestamp_ns=timestamp_ns,
            exchange_timestamp_ns=timestamp_ns,
            correlation_id=f"AAPL-{timestamp_ns}-{index}",
            sequence=index,
            symbol="AAPL",
            bid=Decimal(str(tick["bid"])),
            ask=Decimal(str(tick["ask"])),
            bid_size=100,
            ask_size=100,
        ))
    return quotes


def _iter_dates(start_date: str, end_date: str) -> list[str]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    dates: list[str] = []
    current = start
    while current <= end:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def _resequence(events: list[NBBOQuote | Trade]) -> list[NBBOQuote | Trade]:
    from feelies.core.identifiers import SequenceGenerator, make_correlation_id

    events.sort(key=lambda event: event.exchange_timestamp_ns)
    sequence = SequenceGenerator()
    result: list[NBBOQuote | Trade] = []
    for event in events:
        next_seq = sequence.next()
        correlation_id = make_correlation_id(event.symbol, event.exchange_timestamp_ns, next_seq)
        result.append(replace(event, sequence=next_seq, correlation_id=correlation_id))
    return result


def ingest_data(
    api_key: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
    *,
    cache_dir: Path | None = None,
    no_cache: bool = False,
) -> tuple[InMemoryEventLog, IngestResult, list[DaySource]]:
    """Load historical data using the same replay path as the CLI runner."""
    from feelies.ingestion.massive_ingestor import MassiveHistoricalIngestor
    from feelies.ingestion.massive_normalizer import MassiveNormalizer

    cache: DiskEventCache | None = None
    if not no_cache:
        resolved_dir = cache_dir or Path.home() / ".feelies" / "cache"
        cache = DiskEventCache(resolved_dir)

    dates = _iter_dates(start_date, end_date)
    all_events: list[NBBOQuote | Trade] = []
    day_sources: list[DaySource] = []

    total_events_from_api = 0
    total_pages = 0
    total_gaps = 0
    total_dupes = 0

    for symbol in symbols:
        for day in dates:
            if cache is not None and cache.exists(symbol, day):
                loaded = cache.load(symbol, day)
                if loaded is not None:
                    all_events.extend(loaded)
                    day_sources.append(DaySource(symbol=symbol, date=day, source="cache", event_count=len(loaded)))
                    continue

            clock = SimulatedClock(start_ns=1_000_000_000)
            normalizer = MassiveNormalizer(clock)
            day_log = InMemoryEventLog()

            ingestor = MassiveHistoricalIngestor(
                api_key=api_key,
                normalizer=normalizer,
                event_log=day_log,
                clock=clock,
            )

            result = ingestor.ingest([symbol], day, day)
            total_events_from_api += result.events_ingested
            total_pages += result.pages_processed
            total_gaps += result.symbols_with_gaps
            total_dupes += result.duplicates_filtered

            day_events: list[NBBOQuote | Trade] = list(day_log.replay())  # type: ignore[arg-type]
            if cache is not None:
                cache.save(symbol, day, day_events)

            all_events.extend(day_events)
            day_sources.append(DaySource(symbol=symbol, date=day, source="api", event_count=len(day_events)))

    resequenced = _resequence(all_events)
    event_log = InMemoryEventLog()
    event_log.append_batch(resequenced)

    ingest_result = IngestResult(
        events_ingested=len(resequenced),
        pages_processed=total_pages,
        symbols_with_gaps=total_gaps,
        duplicates_filtered=total_dupes,
        symbols_completed=frozenset(symbols),
    )
    return event_log, ingest_result, day_sources