#!/usr/bin/env python3
"""CLI entry point for the Grok-parity backtest harness.

Usage:
    python scripts/run_parity_backtest.py --spec alphas/spread_mean_reversion/spread_mean_reversion.alpha.yaml \
        --symbols AAPL --start 2024-01-15 --end 2024-01-15 --api-key $POLYGON_API_KEY

    python scripts/run_parity_backtest.py --spec alphas/h002.alpha.yaml \
        --symbols MSFT --start 2024-03-01 --end 2024-03-01 \
        --latency-ms 200 --fill-prob 0.5 --latency-sweep
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

# Ensure the project root is on sys.path so `feelies` is importable.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, Trade
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.research.grok_parity_backtester import (
    GrokParityBacktester,
    GrokTCConfig,
    latency_sensitivity,
)


# ── Helpers ─────────────────────────────────────────────────────────

_W = 62
_RULE_HEAVY = "=" * _W
_RULE_LIGHT = "-" * _W


def _iter_dates(start: str, end: str) -> list[str]:
    d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    dates: list[str] = []
    while d <= end_d:
        if d.weekday() < 5:  # skip weekends
            dates.append(d.isoformat())
        d += timedelta(days=1)
    return dates


def _ingest_data(
    api_key: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
) -> InMemoryEventLog:
    """Download historical data via Massive API and return an event log."""
    from feelies.ingestion.massive_normalizer import MassiveNormalizer
    from feelies.ingestion.massive_ingestor import MassiveHistoricalIngestor

    all_events: list[NBBOQuote | Trade] = []

    for symbol in symbols:
        for day in _iter_dates(start_date, end_date):
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
            result = ingestor.ingest(symbol=symbol, date=day)
            events = list(day_log.replay())
            all_events.extend(events)
            print(
                f"  {symbol} {day}: {len(events):,} events "
                f"({result.quotes:,} quotes, {result.trades:,} trades)",
                flush=True,
            )

    # Sort by exchange timestamp and load into a single event log
    all_events.sort(key=lambda e: e.exchange_timestamp_ns)
    event_log = InMemoryEventLog()
    for i, ev in enumerate(all_events):
        event_log.append(ev, sequence=i)

    return event_log


def _print_metrics(metrics):
    """Print formatted metrics table."""
    print()
    print(_RULE_HEAVY)
    print("  GROK-PARITY BACKTEST RESULTS")
    print(_RULE_HEAVY)
    print(f"  {'Trades':<30s} {metrics.n_trades:>10d}")
    print(f"  {'Signals':<30s} {metrics.n_signals:>10d}")
    print(f"  {'Fills':<30s} {metrics.n_fills:>10d}")
    print(f"  {'Rejected fills':<30s} {metrics.n_rejected_fills:>10d}")
    print(_RULE_LIGHT)
    print(f"  {'Gross PnL':<30s} {metrics.gross_pnl:>10.2f}")
    print(f"  {'Total TC':<30s} {metrics.total_tc:>10.4f}")
    print(f"  {'TC drag %':<30s} {metrics.tc_drag_pct:>10.2f}%")
    print(f"  {'Net PnL':<30s} {metrics.total_pnl:>10.2f}")
    print(_RULE_LIGHT)
    print(f"  {'Sharpe':<30s} {metrics.sharpe:>10.4f}")
    print(f"  {'Annualized Sharpe':<30s} {metrics.annualized_sharpe:>10.4f}")
    print(f"  {'Hit rate':<30s} {metrics.hit_rate:>10.2%}")
    print(f"  {'Avg PnL':<30s} {metrics.avg_pnl:>10.4f}")
    print(f"  {'Profit factor':<30s} {metrics.profit_factor:>10.4f}")
    print(f"  {'Max drawdown':<30s} {metrics.max_drawdown:>10.4f}")
    print(f"  {'Avg holding (s)':<30s} {metrics.avg_holding_seconds:>10.1f}")
    print(_RULE_LIGHT)
    print(f"  {'Latency (ms)':<30s} {metrics.latency_ms:>10.1f}")
    print(f"  {'Fill probability':<30s} {metrics.fill_probability:>10.2f}")
    print(f"  {'PnL hash':<30s} {metrics.pnl_hash:>16s}")
    print(_RULE_HEAVY)


def _print_latency_sweep(results: dict):
    """Print latency sensitivity table."""
    print()
    print(_RULE_HEAVY)
    print("  LATENCY SENSITIVITY SWEEP")
    print(_RULE_HEAVY)
    print(f"  {'Latency (ms)':>12s}  {'Trades':>8s}  {'Net PnL':>10s}  {'Sharpe':>8s}  {'Hit%':>6s}")
    print(_RULE_LIGHT)
    for lat_ms, m in sorted(results.items()):
        print(
            f"  {lat_ms:>12.0f}  {m.n_trades:>8d}  {m.total_pnl:>10.2f}"
            f"  {m.sharpe:>8.4f}  {m.hit_rate:>6.2%}"
        )
    print(_RULE_HEAVY)


# ── Main ────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a Grok-parity backtest on an alpha spec.",
    )
    parser.add_argument("--spec", required=True, help="Path to .alpha.yaml")
    parser.add_argument("--symbols", nargs="+", required=True, help="Tickers")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--api-key", default=None, help="Polygon API key")
    parser.add_argument("--latency-ms", type=float, default=100.0)
    parser.add_argument("--fill-prob", type=float, default=0.7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=None, help="JSON output path")
    parser.add_argument(
        "--latency-sweep", action="store_true",
        help="Run 5 latency levels (0, 50, 100, 200, 500 ms)",
    )
    parser.add_argument(
        "--param-overrides", default=None,
        help="JSON string of parameter overrides",
    )

    args = parser.parse_args()

    api_key = args.api_key
    if api_key is None:
        import os
        api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key:
        print("ERROR: --api-key or POLYGON_API_KEY env var required", file=sys.stderr)
        sys.exit(1)

    param_overrides = None
    if args.param_overrides:
        param_overrides = json.loads(args.param_overrides)

    # Ingest data
    print(f"\n  Ingesting data for {args.symbols} ...", flush=True)
    t0 = time.monotonic()
    event_log = _ingest_data(api_key, args.symbols, args.start, args.end)
    print(f"  Ingestion complete in {time.monotonic() - t0:.1f}s\n", flush=True)

    # Run backtest
    bt = GrokParityBacktester(
        latency_ms=args.latency_ms,
        fill_probability=args.fill_prob,
        random_seed=args.seed,
    )

    print(f"  Running parity backtest on {args.spec} ...", flush=True)
    t0 = time.monotonic()
    trades, metrics = bt.run_from_spec(
        args.spec, event_log, param_overrides=param_overrides,
    )
    elapsed = time.monotonic() - t0
    print(f"  Backtest complete in {elapsed:.1f}s", flush=True)

    _print_metrics(metrics)

    # Optional latency sweep
    if args.latency_sweep:
        from feelies.alpha.loader import AlphaLoader

        loader = AlphaLoader()
        alpha_module = loader.load(args.spec, param_overrides=param_overrides)
        sweep = latency_sensitivity(
            alpha_module, event_log,
            fill_probability=args.fill_prob,
            random_seed=args.seed,
        )
        _print_latency_sweep(sweep)

    # Optional JSON output
    if args.output:
        output = {
            "metrics": asdict(metrics),
            "trades": [asdict(t) for t in trades],
        }
        Path(args.output).write_text(json.dumps(output, indent=2))
        print(f"\n  Results written to {args.output}")


if __name__ == "__main__":
    main()
