#!/usr/bin/env python3
"""Backtest runner — connects real Massive data to the platform pipeline.

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
import time
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
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
    Trade,
)
from feelies.core.identifiers import SequenceGenerator, make_correlation_id
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.ingestion.massive_ingestor import IngestResult
from feelies.kernel.macro import MacroState
from feelies.monitoring.in_memory import InMemoryMetricCollector
from feelies.storage.disk_event_cache import DiskEventCache
from feelies.storage.memory_event_log import InMemoryEventLog

T = TypeVar("T", bound=Event)

# ── Report layout constants ──────────────────────────────────────────

_W = 62
_RULE_HEAVY = "=" * _W
_RULE_LIGHT = "-" * _W


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


# ── Progress reporter ────────────────────────────────────────────────


class _ProgressReporter:
    """Subscribes to the bus and prints periodic progress during replay."""

    def __init__(self, total_events: int, interval: int = 100_000) -> None:
        self._total = total_events
        self._interval = interval
        self._count = 0
        self._t0 = time.monotonic()
        self._last_print = self._t0

    def __call__(self, event: Event) -> None:
        if not isinstance(event, NBBOQuote):
            return
        self._count += 1
        if self._count % self._interval == 0:
            elapsed = time.monotonic() - self._t0
            pct = self._count / self._total * 100.0 if self._total else 0.0
            rate = self._count / elapsed if elapsed > 0 else 0.0
            remaining = (self._total - self._count) / rate if rate > 0 else 0.0
            print(
                f"  [{pct:5.1f}%]  {self._count:>10,} / {self._total:,} quotes  "
                f"({rate:,.0f} q/s, ~{remaining:.0f}s remaining)",
                flush=True,
            )
            self._last_print = time.monotonic()

    def summary(self) -> str:
        elapsed = time.monotonic() - self._t0
        rate = self._count / elapsed if elapsed > 0 else 0.0
        return f"{self._count:,} quotes in {elapsed:.1f}s ({rate:,.0f} q/s)"


def _step(msg: str, t0: float | None = None) -> float:
    """Print a progress step with optional elapsed time from a prior step."""
    now = time.monotonic()
    if t0 is not None:
        dt = now - t0
        print(f"  OK ({dt:.1f}s)", flush=True)
    print(f"  {msg} ...", end="", flush=True)
    return now


# ── CLI ──────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run a historical backtest with real Massive L1 data.",
    )
    p.add_argument(
        "--symbol",
        type=str,
        nargs="+",
        default=None,
        help="Trading symbol(s), space-separated (default: from platform.yaml)",
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
        help="Run with synthetic 8-tick data (no Massive API key required)",
    )
    p.add_argument(
        "--cache-dir",
        type=str,
        default=None,
        help="Disk cache directory (default: ~/.feelies/cache/)",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Force re-download, skip disk cache",
    )
    return p.parse_args(argv)


# ── Ingestion ────────────────────────────────────────────────────────


def _iter_dates(start_date: str, end_date: str) -> list[str]:
    """Generate YYYY-MM-DD strings for each calendar date in [start, end]."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    dates: list[str] = []
    current = start
    while current <= end:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def _resequence(
    events: list[NBBOQuote | Trade],
) -> list[NBBOQuote | Trade]:
    """Sort by exchange time and assign globally monotonic sequences.

    Multi-symbol events may arrive concatenated (all AAPL then all MSFT).
    Sorting by exchange_timestamp_ns ensures the SimulatedClock advances
    correctly and all components see chronologically ordered ticks.
    """
    events.sort(key=lambda e: e.exchange_timestamp_ns)
    seq = SequenceGenerator()
    result: list[NBBOQuote | Trade] = []
    for event in events:
        new_seq = seq.next()
        new_cid = make_correlation_id(
            event.symbol, event.exchange_timestamp_ns, new_seq,
        )
        result.append(replace(event, sequence=new_seq, correlation_id=new_cid))
    return result


@dataclass(frozen=True)
class DaySource:
    """Provenance for a single (symbol, date) ingestion."""
    symbol: str
    date: str
    source: str
    event_count: int


def ingest_data(
    api_key: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
    *,
    cache_dir: Path | None = None,
    no_cache: bool = False,
) -> tuple[InMemoryEventLog, IngestResult, list[DaySource]]:
    """Download historical data with per-day cache and parallel download."""
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
                    day_sources.append(DaySource(
                        symbol=symbol, date=day,
                        source="cache", event_count=len(loaded),
                    ))
                    print(f"  {symbol} {day}: {len(loaded):,} events (cache)", flush=True)
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

            print(f"  {symbol} {day}: fetching from API ...", flush=True)
            _fetch_t0 = time.monotonic()

            def _on_page(
                feed_type: str, page_num: int, total: int, elapsed: float,
                _sym: str = symbol, _day: str = day,
            ) -> None:
                if page_num == 1 or page_num % 25 == 0:
                    print(
                        f"    {feed_type:6s}  p{page_num:<4d}  {total:>9,} records"
                        f"  ({elapsed:.1f}s)",
                        flush=True,
                    )

            result = ingestor.ingest([symbol], day, day, on_page=_on_page)
            total_events_from_api += result.events_ingested
            total_pages += result.pages_processed
            total_gaps += result.symbols_with_gaps
            total_dupes += result.duplicates_filtered

            day_events: list[NBBOQuote | Trade] = list(day_log.replay())  # type: ignore[arg-type]

            if cache is not None:
                cache.save(symbol, day, day_events)

            all_events.extend(day_events)
            day_sources.append(DaySource(
                symbol=symbol, date=day,
                source="api", event_count=len(day_events),
            ))
            print(
                f"  {symbol} {day}: {len(day_events):,} events (api, {result.pages_processed} pages)",
                flush=True,
            )

    resequenced = _resequence(all_events)

    event_log = InMemoryEventLog()
    event_log.append_batch(resequenced)

    total_event_count = len(resequenced)
    completed = frozenset(symbols)

    ingest_result = IngestResult(
        events_ingested=total_event_count,
        pages_processed=total_pages,
        symbols_with_gaps=total_gaps,
        duplicates_filtered=total_dupes,
        symbols_completed=completed,
    )

    return event_log, ingest_result, day_sources


# ── Demo mode (synthetic 8-tick data) ────────────────────────────────

_DEMO_TICKS: list[dict] = [
    {"bid": "150.00", "ask": "150.02", "ts": 1_000_000_000},
    {"bid": "150.00", "ask": "150.02", "ts": 2_000_000_000},
    {"bid": "150.00", "ask": "150.02", "ts": 3_000_000_000},
    {"bid": "150.00", "ask": "150.02", "ts": 4_000_000_000},
    {"bid": "150.00", "ask": "150.02", "ts": 5_000_000_000},
    {"bid": "150.10", "ask": "150.20", "ts": 6_000_000_000},
    {"bid": "149.80", "ask": "150.00", "ts": 7_000_000_000},
    {"bid": "149.80", "ask": "150.00", "ts": 8_000_000_000},
]

_ALPHA_SRC_DIR = _PROJECT_ROOT / "alphas" / "h002_sde_pde_mu_drift"


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
    """Run the backtest with synthetic 8-tick data (no Massive API needed)."""
    tmp_dir = tempfile.mkdtemp(prefix="feelies_demo_")
    try:
        alpha_dst = Path(tmp_dir) / "h002_sde_pde_mu_drift"
        shutil.copytree(_ALPHA_SRC_DIR, alpha_dst)

        config = PlatformConfig(
            symbols=frozenset(["AAPL"]),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=Path(tmp_dir),
            regime_engine=None,
            account_equity=100_000.0,
            risk_max_position_per_symbol=50_000,
            risk_max_gross_exposure_pct=200.0,
            parameter_overrides={
                "h002_sde_pde_mu_drift": {"mu_threshold": 0.0005},
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
            symbols_with_gaps=0,
            duplicates_filtered=0,
            symbols_completed=frozenset(["AAPL"]),
        )

        return orchestrator, recorder, ingest_result, config, "AAPL", "DEMO (synthetic)"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Report formatting helpers ────────────────────────────────────────


def _header(title: str, symbol: str, date_range: str) -> str:
    lines = [
        "",
        _RULE_HEAVY,
        f"  BACKTEST REPORT  |  {title}",
        f"  Symbol: {symbol}  |  Date: {date_range}",
        _RULE_HEAVY,
    ]
    return "\n".join(lines)


def _section(name: str) -> str:
    return f"\n  [{name.upper()}]"


def _kv(key: str, value: str, indent: int = 4) -> str:
    label = f"{key}"
    return f"{' ' * indent}{label:<24s}{value}"


def _sub_kv(key: str, value: str) -> str:
    label = f"{key}"
    return f"{'':6s}{label:<22s}{value}"


def _divider() -> str:
    return f"  {'- ' * 29}-"


def _money(v: Decimal) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def _pct(v: float) -> str:
    return f"{v:.2f}%"


def _ns_to_ms(ns: float) -> str:
    return f"{ns / 1_000_000:.3f} ms"


# ── Report generation ────────────────────────────────────────────────


def generate_report(
    *,
    recorder: BusRecorder,
    ingest_result: IngestResult,
    config: PlatformConfig,
    orchestrator: object,
    symbol_str: str,
    date_range: str,
    day_sources: list[DaySource] | None = None,
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
    fees = sum(
        (a.fees for a in filled_acks),
        Decimal("0"),
    )
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

    total_fills = len(records)
    win_count = len(winning_pnls)
    loss_count = len(losing_pnls)
    resolved_count = win_count + loss_count
    win_rate = (win_count / resolved_count * 100.0) if resolved_count else 0.0
    avg_win = sum(winning_pnls, Decimal("0")) / len(winning_pnls) if winning_pnls else Decimal("0")
    avg_loss = sum(losing_pnls, Decimal("0")) / len(losing_pnls) if losing_pnls else Decimal("0")
    largest_win = max(winning_pnls) if winning_pnls else Decimal("0")
    largest_loss = min(losing_pnls) if losing_pnls else Decimal("0")
    pnl_per_share = float(realized_pnl) / total_shares if total_shares else 0.0

    # ── Risk ─────────────────────────────────────────────────────
    # Track per-symbol exposure and sum for portfolio-wide max.
    max_exposure = Decimal("0")
    per_symbol_exposure: dict[str, Decimal] = {}
    for pu in pos_updates:
        per_symbol_exposure[pu.symbol] = abs(Decimal(str(pu.quantity)) * pu.avg_price)
        total_exposure = sum(per_symbol_exposure.values())
        if total_exposure > max_exposure:
            max_exposure = total_exposure
    max_exposure_pct = float(max_exposure) / starting_equity * 100.0 if starting_equity else 0.0

    # Drawdown: track net equity curve from position updates.
    # Net equity = starting + gross_pnl - cumulative_fees.
    peak_equity = Decimal(str(starting_equity))
    max_drawdown = Decimal("0")
    per_symbol_pnl: dict[str, Decimal] = {}
    per_symbol_fees: dict[str, Decimal] = {}
    for pu in pos_updates:
        per_symbol_pnl[pu.symbol] = pu.realized_pnl
        per_symbol_fees[pu.symbol] = pu.cumulative_fees
        current_equity = (
            Decimal(str(starting_equity))
            + sum(per_symbol_pnl.values())
            - sum(per_symbol_fees.values())
        )
        if current_equity > peak_equity:
            peak_equity = current_equity
        dd = current_equity - peak_equity
        if dd < max_drawdown:
            max_drawdown = dd
    max_dd_pct = float(max_drawdown) / starting_equity * 100.0 if starting_equity else 0.0

    kill_switch = orchestrator._kill_switch  # type: ignore[attr-defined]
    ks_status = "ACTIVATED" if kill_switch.is_active else "NOT ACTIVATED"

    # ── Performance metrics ──────────────────────────────────────
    metrics: InMemoryMetricCollector = orchestrator._metrics  # type: ignore[attr-defined]

    tick_summary = metrics.get_summary("kernel", "tick_to_decision_latency_ns")
    feat_summary = metrics.get_summary("kernel", "feature_compute_ns")
    sig_summary = metrics.get_summary("kernel", "signal_evaluate_ns")

    avg_tick_ns = tick_summary.mean if tick_summary else 0.0
    max_tick_ns = tick_summary.max_value if tick_summary else 0.0
    avg_feat_ns = feat_summary.mean if feat_summary else 0.0
    avg_sig_ns = sig_summary.mean if sig_summary else 0.0

    # ── Assemble report ──────────────────────────────────────────
    lines: list[str] = []
    lines.append(_header(strategy_id, symbol_str, date_range))

    # Ingestion
    lines.append(_section("Data Ingestion"))
    lines.append(_kv("Events ingested", f"{ingest_result.events_ingested:,}"))
    lines.append(_kv("Pages processed", f"{ingest_result.pages_processed}"))
    lines.append(_kv("Symbols with gaps", f"{ingest_result.symbols_with_gaps}"))
    lines.append(_kv("Duplicates filtered", f"{ingest_result.duplicates_filtered}"))
    if day_sources:
        lines.append("")
        for ds in day_sources:
            lines.append(_sub_kv(f"{ds.symbol} {ds.date}", f"{ds.event_count:,} ({ds.source})"))

    lines.append(_divider())

    # Pipeline
    lines.append(_section("Signal Pipeline"))
    lines.append(_kv("Quotes processed", f"{len(quotes):,}"))
    lines.append(_kv("Feature vectors", f"{len(features):,}"))
    lines.append(_kv("Warm-up ticks", f"{len(warmup_features)}"))
    lines.append(_kv("Signals emitted", f"{len(signals):,}"))
    lines.append(_sub_kv("Long", f"{len(long_signals):,}"))
    lines.append(_sub_kv("Short", f"{len(short_signals):,}"))

    lines.append(_divider())

    # Execution
    lines.append(_section("Execution"))
    lines.append(_kv("Orders submitted", f"{len(orders):,}"))
    lines.append(_kv("Orders filled", f"{len(filled_acks):,}"))
    lines.append(_kv("Orders rejected", f"{len(rejected_acks):,}"))
    lines.append(_kv("Total shares traded", f"{total_shares:,}"))

    lines.append(_divider())

    # P&L
    lines.append(_section("P&L"))
    lines.append(_kv("Starting equity", _money(Decimal(str(starting_equity)))))
    lines.append(_kv("Gross P&L", _money(gross_pnl)))
    lines.append(_sub_kv("Realized", _money(realized_pnl)))
    lines.append(_sub_kv("Unrealized", _money(unrealized_pnl)))
    lines.append(_kv("Fees", _money(fees)))
    lines.append(_kv("Net P&L", _money(net_pnl)))
    lines.append(_kv("Final equity", _money(final_equity)))
    lines.append(_kv("Return", _pct(return_pct)))

    lines.append(_divider())

    # Trade summary
    lines.append(_section("Trade Analysis"))
    lines.append(_kv("Total fills", f"{total_fills:,}"))
    lines.append(_kv("Closing fills", f"{resolved_count:,}"))
    lines.append(_kv("Open positions", f"{open_positions}"))
    win_rate_str = f"{win_rate:.1f}% ({win_count}/{resolved_count})" if resolved_count else "N/A"
    lines.append(_kv("Win rate", win_rate_str))
    lines.append(_kv("Avg winner", _money(avg_win)))
    lines.append(_kv("Avg loser", _money(avg_loss)))
    lines.append(_kv("Largest win", _money(largest_win)))
    lines.append(_kv("Largest loss", _money(largest_loss)))
    lines.append(_kv("P&L per share", f"${pnl_per_share:.4f}"))

    lines.append(_divider())

    # Risk
    lines.append(_section("Risk"))
    lines.append(_kv("Max exposure", f"{_money(max_exposure)} ({_pct(max_exposure_pct)})"))
    lines.append(_kv("Max drawdown", f"{_money(max_drawdown)} ({_pct(max_dd_pct)})"))
    lines.append(_kv("Kill switch", ks_status))

    lines.append(_divider())

    # Performance
    lines.append(_section("Latency"))
    lines.append(_kv("Avg tick-to-decision", _ns_to_ms(avg_tick_ns)))
    lines.append(_kv("Max tick-to-decision", _ns_to_ms(max_tick_ns)))
    lines.append(_kv("Avg feature compute", _ns_to_ms(avg_feat_ns)))
    lines.append(_kv("Avg signal evaluate", _ns_to_ms(avg_sig_ns)))

    lines.append("")
    lines.append(_RULE_HEAVY)
    lines.append("")

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
    print(_section("Verification"))
    all_passed = True
    for name, passed, detail in results:
        tag = "PASS" if passed else "FAIL"
        print(f"    [{tag}]  {name:<22s}{detail}")
        if not passed:
            all_passed = False
    print()
    passed_count = sum(1 for _, p, _ in results if p)
    total = len(results)
    if all_passed:
        print(f"    Result: {passed_count}/{total} checks passed.")
    else:
        print(f"    Result: {passed_count}/{total} checks passed. Review failures above.")
    print()
    return all_passed


# ── Main ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # ── Demo mode: synthetic data, no Massive API needed ─────────
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

    # ── Live mode: requires Massive API key ──────────────────────
    if not args.date:
        print("ERROR: --date is required (or use --demo for synthetic data)", file=sys.stderr)
        return 1

    # 1. Load .env
    try:
        from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]
        load_dotenv()
    except ImportError:
        pass  # dotenv is optional; env vars can be set directly

    api_key = os.getenv("MASSIVE_API_KEY")
    if not api_key:
        print(
            "ERROR: MASSIVE_API_KEY not set.\n"
            "Set it in your environment or in a .env file.\n"
            "  export MASSIVE_API_KEY=your_key_here",
            file=sys.stderr,
        )
        return 1

    # 2. Load platform config
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        return 1

    config = PlatformConfig.from_yaml(config_path)

    # Override symbols if provided via CLI
    if args.symbol:
        config.symbols = frozenset(s.upper() for s in args.symbol)

    symbols = sorted(config.symbols)
    if not symbols:
        print("ERROR: No symbols specified (use --symbol or set in platform.yaml)", file=sys.stderr)
        return 1

    start_date = args.date
    end_date = args.end_date or start_date
    date_range = start_date if start_date == end_date else f"{start_date} to {end_date}"
    symbol_str = ", ".join(symbols)
    run_t0 = time.monotonic()

    print(f"\n  Backtest: {symbol_str}  |  {date_range}", flush=True)
    print(f"  {_RULE_LIGHT}", flush=True)

    # ── Phase 1: Data ingestion ───────────────────────────────
    step_t = _step("Loading market data")
    print(flush=True)

    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    no_cache: bool = args.no_cache

    try:
        event_log, ingest_result, day_sources = ingest_data(
            api_key, symbols, start_date, end_date,
            cache_dir=cache_dir, no_cache=no_cache,
        )
    except ImportError as exc:
        print(
            f"\n  ERROR: {exc}\n"
            "  Install the massive extra: pip install 'feelies[massive]'",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"\n  ERROR: Ingestion failed: {exc}", file=sys.stderr)
        return 1

    cache_days = sum(1 for ds in day_sources if ds.source == "cache")
    api_days = sum(1 for ds in day_sources if ds.source == "api")
    dt = time.monotonic() - step_t
    src = []
    if api_days:
        src.append(f"{api_days}d API")
    if cache_days:
        src.append(f"{cache_days}d cache")
    src_str = ", ".join(src)
    print(
        f"  OK - {ingest_result.events_ingested:,} events ({src_str}) [{dt:.1f}s]",
        flush=True,
    )

    # ── Phase 2: Platform bootstrap ───────────────────────────
    step_t = _step("Composing platform (alphas, engines, risk)")
    orchestrator, config = build_platform(config, event_log=event_log)
    alpha_count = len(orchestrator._alpha_registry) if orchestrator._alpha_registry else 0  # type: ignore[attr-defined]
    dt = time.monotonic() - step_t
    print(f"  OK - {alpha_count} alpha(s) registered [{dt:.1f}s]", flush=True)

    # ── Phase 3: Attach recorder ──────────────────────────────
    recorder = BusRecorder()
    orchestrator._bus.subscribe_all(recorder)  # type: ignore[attr-defined]

    # ── Phase 4: Boot ─────────────────────────────────────────
    step_t = _step("Booting orchestrator (integrity checks, warm-start)")
    orchestrator.boot(config)
    macro = orchestrator.macro_state
    dt = time.monotonic() - step_t
    print(f"  OK - macro state: {macro.name} [{dt:.1f}s]", flush=True)

    if macro != MacroState.READY:
        print(f"  ERROR: Boot failed — macro state is {macro.name}, expected READY",
              file=sys.stderr)
        return 1

    # ── Phase 5: Run pipeline ─────────────────────────────────
    n_quotes = sum(1 for e in event_log.replay() if isinstance(e, NBBOQuote))
    progress = _ProgressReporter(total_events=n_quotes, interval=100_000)
    orchestrator._bus.subscribe(NBBOQuote, progress)  # type: ignore[attr-defined]

    step_t = _step(f"Replaying {n_quotes:,} quotes through pipeline")
    print(flush=True)
    orchestrator.run_backtest()
    dt = time.monotonic() - step_t
    print(f"  Pipeline complete - {progress.summary()}", flush=True)

    # ── Phase 6: Report ───────────────────────────────────────
    step_t = _step("Generating report")
    report = generate_report(
        recorder=recorder,
        ingest_result=ingest_result,
        config=config,
        orchestrator=orchestrator,
        symbol_str=symbol_str,
        date_range=date_range,
        day_sources=day_sources,
    )
    dt = time.monotonic() - step_t
    print(f"  OK [{dt:.1f}s]", flush=True)
    print(report)

    # ── Phase 7: Verification ─────────────────────────────────
    results = run_verification(
        recorder=recorder,
        ingest_result=ingest_result,
        orchestrator=orchestrator,
    )
    all_passed = print_verification(results)

    total_elapsed = time.monotonic() - run_t0
    print(f"  Total elapsed: {total_elapsed:.1f}s\n", flush=True)

    return 0 if all_passed else 2


if __name__ == "__main__":
    sys.exit(main())
