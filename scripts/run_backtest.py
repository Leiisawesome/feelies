#!/usr/bin/env python3
"""Backtest runner — connects real Polygon data to the platform pipeline.

Usage:
    python scripts/run_backtest.py --symbol AAPL --date 2024-01-15
    python scripts/run_backtest.py --symbol AAPL --date 2024-01-15 --end-date 2024-01-16
    python scripts/run_backtest.py --config platform.yaml  # uses symbols from config
    python scripts/run_backtest.py --demo  # run with synthetic 8-tick data
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TypeVar

# Ensure the project root is on sys.path so `feelies` is importable
# when running the script directly (e.g. `python scripts/run_backtest.py`).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from feelies.bootstrap import build_platform
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    Event,
    FeatureVector,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    PositionUpdate,
    Signal,
    SignalDirection,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.ingestion.polygon_ingestor import IngestResult
from feelies.kernel.macro import MacroState
from feelies.monitoring.in_memory import InMemoryMetricCollector
from feelies.storage.memory_event_log import InMemoryEventLog

T = TypeVar("T", bound=Event)

# ── Box-drawing constants ────────────────────────────────────────────

_W = 57  # inner width of the report box
_DOUBLE = "═"
_SINGLE = "─"


# ── BusRecorder (same pattern as test_backtest_e2e.py) ───────────────


@dataclass
class BusRecorder:
    events: list[Event] = field(default_factory=list)
    by_type: dict[type, list[Event]] = field(default_factory=lambda: defaultdict(list))

    def __call__(self, event: Event) -> None:
        self.events.append(event)
        self.by_type[type(event)].append(event)

    def of_type(self, t: type[T]) -> list[T]:
        return self.by_type[t]  # type: ignore[return-value]


# ── CLI ──────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run a historical backtest with real Polygon L1 data.",
    )
    p.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Override trading symbol (default: from platform.yaml)",
    )
    p.add_argument(
        "--date",
        type=str,
        default=None,
        help="Start date in YYYY-MM-DD format (required unless --demo)",
    )
    p.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date in YYYY-MM-DD (default: same as --date)",
    )
    p.add_argument(
        "--config",
        type=str,
        default="platform.yaml",
        help="Path to platform.yaml (default: platform.yaml)",
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="Run with synthetic 8-tick data (no Polygon API key required)",
    )
    return p.parse_args(argv)


# ── Ingestion ────────────────────────────────────────────────────────


def ingest_data(
    api_key: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
) -> tuple[InMemoryEventLog, IngestResult]:
    """Download historical data from Polygon and return a populated event log."""
    from feelies.ingestion.polygon_ingestor import PolygonHistoricalIngestor
    from feelies.ingestion.polygon_normalizer import PolygonNormalizer

    clock = SimulatedClock(start_ns=1_000_000_000)
    normalizer = PolygonNormalizer(clock)
    event_log = InMemoryEventLog()

    ingestor = PolygonHistoricalIngestor(
        api_key=api_key,
        normalizer=normalizer,
        event_log=event_log,
        clock=clock,
    )

    result = ingestor.ingest(symbols, start_date, end_date)
    return event_log, result


# ── Demo mode (synthetic 8-tick data) ────────────────────────────────

_DEMO_TICKS: list[dict] = [
    {"bid": "150.00", "ask": "150.01", "ts": 1_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 2_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 3_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 4_000_000_000},
    {"bid": "150.00", "ask": "150.01", "ts": 5_000_000_000},
    {"bid": "160.00", "ask": "160.01", "ts": 6_000_000_000},
    {"bid": "160.00", "ask": "160.01", "ts": 7_000_000_000},
    {"bid": "140.00", "ask": "140.01", "ts": 8_000_000_000},
]

_ALPHA_SRC = _PROJECT_ROOT / "alphas" / "mean_reversion.alpha.yaml"


def _make_demo_quotes() -> list[NBBOQuote]:
    quotes: list[NBBOQuote] = []
    for i, td in enumerate(_DEMO_TICKS, start=1):
        quotes.append(NBBOQuote(
            timestamp_ns=td["ts"],
            exchange_timestamp_ns=td["ts"],
            correlation_id=f"AAPL-{td['ts']}-{i}",
            sequence=i,
            symbol="AAPL",
            bid=Decimal(td["bid"]),
            ask=Decimal(td["ask"]),
            bid_size=100,
            ask_size=100,
        ))
    return quotes


def run_demo() -> tuple[object, BusRecorder, IngestResult, PlatformConfig, str, str]:
    """Run the backtest with synthetic 8-tick data (no Polygon needed)."""
    tmp_dir = tempfile.mkdtemp(prefix="feelies_demo_")
    try:
        alpha_dst = Path(tmp_dir) / "mean_reversion.alpha.yaml"
        shutil.copy2(_ALPHA_SRC, alpha_dst)

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
        for q in _make_demo_quotes():
            event_log.append(q)

        orchestrator, config = build_platform(config, event_log=event_log)

        recorder = BusRecorder()
        orchestrator._bus.subscribe_all(recorder)  # type: ignore[attr-defined]

        orchestrator.boot(config)
        orchestrator.run_backtest()

        ingest_result = IngestResult(
            events_ingested=len(_DEMO_TICKS),
            pages_processed=1,
            gaps_detected=0,
            duplicates_filtered=0,
            symbols_completed=frozenset(["AAPL"]),
        )

        return orchestrator, recorder, ingest_result, config, "AAPL", "DEMO (synthetic)"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Report formatting helpers ────────────────────────────────────────


def _header(title: str, symbol: str, date_range: str) -> str:
    lines = [
        _DOUBLE * _W,
        f"  BACKTEST REPORT — {title}",
        f"  Symbol: {symbol} | Date: {date_range}",
        _DOUBLE * _W,
    ]
    return "\n".join(lines)


def _section(name: str) -> str:
    padding = _W - len(name) - 4
    return f"── {name} " + _SINGLE * max(padding, 1)


def _kv(key: str, value: str, indent: int = 2) -> str:
    label = f"{key}:"
    return f"{' ' * indent}{label:<21s}{value}"


def _sub_kv(key: str, value: str) -> str:
    """Indented sub-item (e.g. LONG/SHORT under Signals emitted)."""
    label = f"{key}:"
    return f"    {label:<19s}{value}"


def _money(v: Decimal) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def _pct(v: float) -> str:
    return f"{v:.2f}%"


def _ns_to_ms(ns: float) -> str:
    return f"{ns / 1_000_000:.3f}ms"


# ── Report generation ────────────────────────────────────────────────


def generate_report(
    *,
    recorder: BusRecorder,
    ingest_result: IngestResult,
    config: PlatformConfig,
    orchestrator: object,
    symbol_str: str,
    date_range: str,
) -> str:
    """Build the full backtest report string."""
    from feelies.storage.trade_journal import TradeRecord

    quotes = recorder.of_type(NBBOQuote)
    features = recorder.of_type(FeatureVector)
    signals = recorder.of_type(Signal)
    orders = recorder.of_type(OrderRequest)
    acks = recorder.of_type(OrderAck)
    pos_updates = recorder.of_type(PositionUpdate)

    filled_acks = [a for a in acks if a.status == OrderAckStatus.FILLED]
    rejected_acks = [a for a in acks if a.status == OrderAckStatus.REJECTED]

    long_signals = [s for s in signals if s.direction == SignalDirection.LONG]
    short_signals = [s for s in signals if s.direction == SignalDirection.SHORT]

    warmup_features = [f for f in features if not f.warm]

    total_shares = sum(abs(a.filled_quantity) for a in filled_acks)

    # Strategy ID from first signal, or fallback
    strategy_id = signals[0].strategy_id if signals else "unknown"

    # ── P&L from position store ──────────────────────────────────
    positions = orchestrator._positions  # type: ignore[attr-defined]
    all_pos = positions.all_positions()
    starting_equity = float(orchestrator._account_equity)  # type: ignore[attr-defined]

    realized_pnl = sum(
        (p.realized_pnl for p in all_pos.values()),
        Decimal("0"),
    )
    unrealized_pnl = sum(
        (p.unrealized_pnl for p in all_pos.values()),
        Decimal("0"),
    )
    gross_pnl = realized_pnl + unrealized_pnl
    fees = Decimal("0")
    net_pnl = gross_pnl - fees
    final_equity = Decimal(str(starting_equity)) + net_pnl
    return_pct = float(net_pnl) / starting_equity * 100.0 if starting_equity else 0.0

    # ── Trade summary ────────────────────────────────────────────
    journal = orchestrator._trade_journal  # type: ignore[attr-defined]
    records: list[TradeRecord] = list(journal.query())

    open_positions = sum(1 for p in all_pos.values() if p.quantity != 0)

    winning_pnls: list[Decimal] = []
    losing_pnls: list[Decimal] = []
    for rec in records:
        if rec.realized_pnl > 0:
            winning_pnls.append(rec.realized_pnl)
        elif rec.realized_pnl < 0:
            losing_pnls.append(rec.realized_pnl)

    round_trips = len(records)
    win_count = len(winning_pnls)
    win_rate = (win_count / round_trips * 100.0) if round_trips else 0.0
    avg_win = sum(winning_pnls, Decimal("0")) / len(winning_pnls) if winning_pnls else Decimal("0")
    avg_loss = sum(losing_pnls, Decimal("0")) / len(losing_pnls) if losing_pnls else Decimal("0")
    largest_win = max(winning_pnls) if winning_pnls else Decimal("0")
    largest_loss = min(losing_pnls) if losing_pnls else Decimal("0")
    pnl_per_share = float(realized_pnl) / total_shares if total_shares else 0.0

    # ── Risk ─────────────────────────────────────────────────────
    max_exposure = Decimal("0")
    running_exposure = Decimal("0")
    for pu in pos_updates:
        running_exposure = abs(Decimal(str(pu.quantity)) * pu.avg_price)
        if running_exposure > max_exposure:
            max_exposure = running_exposure
    max_exposure_pct = float(max_exposure) / starting_equity * 100.0 if starting_equity else 0.0

    # Drawdown: track equity curve from position updates
    peak_equity = Decimal(str(starting_equity))
    max_drawdown = Decimal("0")
    running_equity = Decimal(str(starting_equity))
    for pu in pos_updates:
        running_equity += pu.realized_pnl
        if running_equity > peak_equity:
            peak_equity = running_equity
        dd = running_equity - peak_equity
        if dd < max_drawdown:
            max_drawdown = dd
    max_dd_pct = float(max_drawdown) / starting_equity * 100.0 if starting_equity else 0.0

    kill_switch = orchestrator._kill_switch  # type: ignore[attr-defined]
    ks_status = "ACTIVATED" if kill_switch.is_active else "NOT ACTIVATED"

    # ── Performance metrics ──────────────────────────────────────
    metrics: InMemoryMetricCollector = orchestrator._metrics  # type: ignore[attr-defined]

    tick_summary = metrics.get_summary("tick", "tick_to_decision_latency_ns")
    feat_summary = metrics.get_summary("feature", "feature_compute_ns")
    sig_summary = metrics.get_summary("signal", "signal_evaluate_ns")

    avg_tick_ns = tick_summary.mean if tick_summary else 0.0
    p99_tick_ns = tick_summary.max_value if tick_summary else 0.0
    avg_feat_ns = feat_summary.mean if feat_summary else 0.0
    avg_sig_ns = sig_summary.mean if sig_summary else 0.0

    # ── Assemble report ──────────────────────────────────────────
    lines: list[str] = []
    lines.append("")
    lines.append(_header(strategy_id, symbol_str, date_range))
    lines.append("")

    # Ingestion
    lines.append(_section("Ingestion"))
    lines.append(_kv("Events ingested", f"{ingest_result.events_ingested:,}"))
    lines.append(_kv("Pages processed", f"{ingest_result.pages_processed}"))
    lines.append(_kv("Gaps detected", f"{ingest_result.gaps_detected}"))
    lines.append(_kv("Duplicates filtered", f"{ingest_result.duplicates_filtered}"))
    lines.append("")

    # Pipeline
    lines.append(_section("Pipeline"))
    lines.append(_kv("Quotes processed", f"{len(quotes):,}"))
    lines.append(_kv("Feature vectors", f"{len(features):,}"))
    lines.append(_kv("Warm-up ticks", f"{len(warmup_features)}"))
    lines.append(_kv("Signals emitted", f"{len(signals)}"))
    lines.append(_sub_kv("LONG", f"{len(long_signals)}"))
    lines.append(_sub_kv("SHORT", f"{len(short_signals)}"))
    lines.append("")

    # Execution
    lines.append(_section("Execution"))
    lines.append(_kv("Orders submitted", f"{len(orders)}"))
    lines.append(_kv("Orders filled", f"{len(filled_acks)}"))
    lines.append(_kv("Orders rejected", f"{len(rejected_acks)}"))
    lines.append(_kv("Total shares traded", f"{total_shares:,}"))
    lines.append("")

    # P&L
    lines.append(_section("P&L Statement"))
    lines.append(_kv("Starting equity", _money(Decimal(str(starting_equity)))))
    lines.append(_kv("Realized P&L", _money(realized_pnl)))
    lines.append(_kv("Unrealized P&L", _money(unrealized_pnl)))
    lines.append(_kv("Gross P&L", _money(gross_pnl)))
    lines.append(_kv("Fees", _money(fees)))
    lines.append(_kv("Net P&L", _money(net_pnl)))
    lines.append(_kv("Final equity", _money(final_equity)))
    lines.append(_kv("Return", _pct(return_pct)))
    lines.append("")

    # Trade summary
    lines.append(_section("Trade Summary"))
    lines.append(_kv("Round trips closed", f"{round_trips}"))
    lines.append(_kv("Open positions", f"{open_positions}"))
    win_rate_str = f"{win_rate:.1f}% ({win_count}/{round_trips})" if round_trips else "N/A"
    lines.append(_kv("Win rate", win_rate_str))
    lines.append(_kv("Avg winning trade", _money(avg_win)))
    lines.append(_kv("Avg losing trade", _money(avg_loss)))
    lines.append(_kv("Largest win", _money(largest_win)))
    lines.append(_kv("Largest loss", _money(largest_loss)))
    lines.append(_kv("P&L per share", f"${pnl_per_share:.2f}"))
    lines.append("")

    # Risk
    lines.append(_section("Risk"))
    lines.append(_kv("Max exposure", _money(max_exposure)))
    lines.append(_kv("Max exposure %", _pct(max_exposure_pct)))
    lines.append(_kv("Max drawdown", f"{_money(max_drawdown)} ({_pct(max_dd_pct)})"))
    lines.append(_kv("Kill switch", ks_status))
    lines.append("")

    # Performance
    lines.append(_section("Performance"))
    lines.append(_kv("Avg tick latency", _ns_to_ms(avg_tick_ns)))
    lines.append(_kv("p99 tick latency", _ns_to_ms(p99_tick_ns)))
    lines.append(_kv("Feature compute", f"{_ns_to_ms(avg_feat_ns)} avg"))
    lines.append(_kv("Signal evaluate", f"{_ns_to_ms(avg_sig_ns)} avg"))
    lines.append("")
    lines.append(_DOUBLE * _W)

    return "\n".join(lines)


# ── Verification checks ─────────────────────────────────────────────


def run_verification(
    *,
    recorder: BusRecorder,
    ingest_result: IngestResult,
    orchestrator: object,
) -> list[tuple[str, bool, str]]:
    """Run moderate verification criteria. Returns (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []

    # 1. Events ingested > 0
    n = ingest_result.events_ingested
    results.append(("Events ingested", n > 0, f"{n} events"))

    # 2. Signals fired > 0
    sigs = recorder.of_type(Signal)
    results.append(("Signals fired", len(sigs) > 0, f"{len(sigs)} signals"))

    # 3. Fills occurred >= 1
    acks = recorder.of_type(OrderAck)
    fills = [a for a in acks if a.status == OrderAckStatus.FILLED]
    results.append(("Fills occurred", len(fills) >= 1, f"{len(fills)} fills"))

    # 4. P&L computable
    positions = orchestrator._positions  # type: ignore[attr-defined]
    all_pos = positions.all_positions()
    has_pnl = any(p.realized_pnl is not None for p in all_pos.values()) if all_pos else False
    # Also pass if no positions were taken (realized_pnl stays at 0)
    if not all_pos:
        has_pnl = True  # vacuously true — no trades means no PnL to compute
    results.append(("P&L computable", has_pnl, "realized_pnl tracked" if has_pnl else "missing"))

    # 5. Trade journal >= 1
    journal = orchestrator._trade_journal  # type: ignore[attr-defined]
    n_records = len(journal)
    results.append(("Trade journal", n_records >= 1, f"{n_records} records"))

    # 6. Macro state == READY
    macro = orchestrator.macro_state
    results.append(("Macro state", macro == MacroState.READY, macro.name))

    # 7. Kill switch not activated
    ks = orchestrator._kill_switch  # type: ignore[attr-defined]
    results.append(("Kill switch", not ks.is_active, "INACTIVE" if not ks.is_active else "ACTIVE"))

    return results


def print_verification(results: list[tuple[str, bool, str]]) -> bool:
    """Print verification table. Returns True if all passed."""
    print()
    print(_section("Verification"))
    all_passed = True
    for name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        marker = "✓" if passed else "✗"
        print(f"  {marker} [{status}] {name:<20s} {detail}")
        if not passed:
            all_passed = False
    print()
    if all_passed:
        print("  All checks PASSED.")
    else:
        print("  Some checks FAILED — review the report above.")
    print()
    return all_passed


# ── Main ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # ── Demo mode: synthetic data, no Polygon needed ─────────────
    if args.demo:
        print("Running demo backtest with synthetic 8-tick data ...", flush=True)
        orchestrator, recorder, ingest_result, config, symbol_str, date_range = run_demo()

        report = generate_report(
            recorder=recorder,
            ingest_result=ingest_result,
            config=config,
            orchestrator=orchestrator,
            symbol_str=symbol_str,
            date_range=date_range,
        )
        print(report)

        results = run_verification(
            recorder=recorder,
            ingest_result=ingest_result,
            orchestrator=orchestrator,
        )
        all_passed = print_verification(results)
        return 0 if all_passed else 2

    # ── Live mode: requires Polygon API key ──────────────────────
    if not args.date:
        print("ERROR: --date is required (or use --demo for synthetic data)", file=sys.stderr)
        return 1

    # 1. Load .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # dotenv is optional; env vars can be set directly

    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        print(
            "ERROR: POLYGON_API_KEY not set.\n"
            "Set it in your environment or in a .env file.\n"
            "  export POLYGON_API_KEY=your_key_here",
            file=sys.stderr,
        )
        return 1

    # 2. Load platform config
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        return 1

    config = PlatformConfig.from_yaml(config_path)

    # Override symbol if provided via CLI
    if args.symbol:
        config.symbols = frozenset([args.symbol.upper()])

    symbols = sorted(config.symbols)
    if not symbols:
        print("ERROR: No symbols specified (use --symbol or set in platform.yaml)", file=sys.stderr)
        return 1

    start_date = args.date
    end_date = args.end_date or start_date
    date_range = start_date if start_date == end_date else f"{start_date} → {end_date}"
    symbol_str = ", ".join(symbols)

    # 3–5. Ingest data
    print(f"Ingesting {symbol_str} from {date_range} ...", flush=True)
    try:
        event_log, ingest_result = ingest_data(api_key, symbols, start_date, end_date)
    except ImportError as exc:
        print(
            f"ERROR: {exc}\n"
            "Install the polygon extra: pip install 'feelies[polygon]'",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"ERROR: Ingestion failed: {exc}", file=sys.stderr)
        return 1

    print(f"  Ingested {ingest_result.events_ingested:,} events "
          f"({ingest_result.pages_processed} pages, "
          f"{ingest_result.duplicates_filtered} duplicates filtered)")

    # 6. Build platform
    orchestrator, config = build_platform(config, event_log=event_log)

    # 7. Attach BusRecorder
    recorder = BusRecorder()
    orchestrator._bus.subscribe_all(recorder)  # type: ignore[attr-defined]

    # 8. Boot + run
    print("Running backtest ...", flush=True)
    orchestrator.boot(config)
    orchestrator.run_backtest()

    # 9. Report
    report = generate_report(
        recorder=recorder,
        ingest_result=ingest_result,
        config=config,
        orchestrator=orchestrator,
        symbol_str=symbol_str,
        date_range=date_range,
    )
    print(report)

    # 10. Verification
    results = run_verification(
        recorder=recorder,
        ingest_result=ingest_result,
        orchestrator=orchestrator,
    )
    all_passed = print_verification(results)

    return 0 if all_passed else 2


if __name__ == "__main__":
    sys.exit(main())
