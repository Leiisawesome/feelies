#!/usr/bin/env python3
"""Parameter sweep for max_hold_ticks and max_hold_ns.

Runs backtest across a grid of timeout combos and prints a ranked table.

Usage:
    python scripts/sweep_timeouts.py --symbol AAPL --date 2026-03-18
"""

from __future__ import annotations

import os
import sys
import time
from decimal import Decimal
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from run_backtest import BusRecorder, ingest_data, parse_args

from feelies.bootstrap import build_platform
from feelies.core.events import (
    OrderAck,
    OrderAckStatus,
    Signal,
    SignalDirection,
)
from feelies.core.platform_config import PlatformConfig
from feelies.storage.trade_journal import TradeRecord


def run_one(
    config: PlatformConfig,
    event_log,
    tick_timeout: int,
    time_timeout_ns: int,
) -> dict:
    """Run a single backtest with specific timeout params, return summary."""
    cfg = PlatformConfig(
        symbols=config.symbols,
        mode=config.mode,
        alpha_spec_dir=config.alpha_spec_dir,
        alpha_specs=config.alpha_specs,
        regime_engine=config.regime_engine,
        account_equity=config.account_equity,
        risk_max_position_per_symbol=config.risk_max_position_per_symbol,
        risk_max_gross_exposure_pct=config.risk_max_gross_exposure_pct,
        parameter_overrides={
            "h002_drift_fade": {
                "max_hold_ticks": tick_timeout,
                "max_hold_ns": time_timeout_ns,
            },
        },
    )

    orchestrator, cfg = build_platform(cfg, event_log=event_log)
    recorder = BusRecorder()
    orchestrator._bus.subscribe_all(recorder)
    orchestrator.boot(cfg)
    orchestrator.run_backtest()

    signals = recorder.of_type(Signal)
    acks = recorder.of_type(OrderAck)
    filled = [a for a in acks if a.status == OrderAckStatus.FILLED]
    records: list[TradeRecord] = list(orchestrator._trade_journal.query())

    positions = orchestrator._positions
    all_pos = positions.all_positions()

    realized = sum((p.realized_pnl for p in all_pos.values()), Decimal("0"))
    fees = sum((a.fees for a in filled), Decimal("0"))
    net = realized - fees
    total_shares = sum(abs(a.filled_quantity) for a in filled)

    winners = [r for r in records if r.realized_pnl > 0]
    losers = [r for r in records if r.realized_pnl < 0]
    closing = len(winners) + len(losers) + len([r for r in records if r.realized_pnl == 0])
    # Exclude entry records — only count closing fills
    # Actually records include both entries and exits. Entries have realized_pnl=0 typically.
    # For round-trip count, we use signals: entries are LONG/SHORT, exits are FLAT
    entry_sigs = [s for s in signals if s.direction != SignalDirection.FLAT]
    exit_sigs = [s for s in signals if s.direction == SignalDirection.FLAT]
    n_round_trips = len(exit_sigs)

    win_count = len(winners)
    loss_count = len(losers)
    resolved = win_count + loss_count
    win_rate = win_count / resolved * 100 if resolved else 0

    largest_loss = min((r.realized_pnl for r in records), default=Decimal("0"))

    return {
        "tick_to": tick_timeout,
        "time_to_s": time_timeout_ns / 1e9,
        "round_trips": n_round_trips,
        "signals": len(signals),
        "win_rate": win_rate,
        "gross": float(realized),
        "fees": float(fees),
        "net": float(net),
        "shares": total_shares,
        "largest_loss": float(largest_loss),
        "pnl_per_share": float(realized) / total_shares if total_shares else 0,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.date:
        print("ERROR: --date required", file=sys.stderr)
        return 1

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    api_key = os.getenv("MASSIVE_API_KEY")
    if not api_key:
        print("ERROR: MASSIVE_API_KEY not set.", file=sys.stderr)
        return 1

    config = PlatformConfig.from_yaml(Path(args.config))
    if args.symbol:
        config.symbols = frozenset(s.upper() for s in args.symbol)

    start_date = args.date
    end_date = args.end_date or start_date
    cache_dir = Path(args.cache_dir) if args.cache_dir else None

    print("Loading market data ...", flush=True)
    event_log, ingest_result, _ = ingest_data(
        api_key, sorted(config.symbols), start_date, end_date,
        cache_dir=cache_dir, no_cache=args.no_cache,
    )
    print(f"{ingest_result.events_ingested:,} events loaded.\n", flush=True)

    # ── Grid ──────────────────────────────────────────────────
    tick_values = [200, 250, 300, 350, 400, 500, 600, 800, 1000]
    time_values_s = [2, 3, 4, 5, 7, 10, 15, 25]

    results = []
    total = len(tick_values) * len(time_values_s)
    i = 0

    for tick_to in tick_values:
        for time_s in time_values_s:
            i += 1
            time_ns = int(time_s * 1e9)
            t0 = time.monotonic()
            r = run_one(config, event_log, tick_to, time_ns)
            dt = time.monotonic() - t0
            results.append(r)
            print(
                f"  [{i:3d}/{total}] ticks={tick_to:5d}  time={time_s:3d}s  "
                f"rt={r['round_trips']:3d}  win={r['win_rate']:5.1f}%  "
                f"gross={r['gross']:+8.2f}  fees={r['fees']:7.2f}  "
                f"net={r['net']:+8.2f}  maxloss={r['largest_loss']:+8.2f}  "
                f"[{dt:.1f}s]",
                flush=True,
            )

    # ── Rank by net P&L ──────────────────────────────────────
    results.sort(key=lambda r: r["net"], reverse=True)

    print(f"\n{'=' * 100}")
    print(f"  TOP 15 CONFIGURATIONS (ranked by net P&L)")
    print(f"{'=' * 100}")
    print(
        f"  {'Rank':>4s}  {'Ticks':>6s}  {'Time':>5s}  {'RTs':>4s}  "
        f"{'Win%':>6s}  {'Gross':>9s}  {'Fees':>8s}  {'Net':>9s}  "
        f"{'MaxLoss':>9s}  {'P&L/sh':>8s}"
    )
    print(f"  {'-'*4}  {'-'*6}  {'-'*5}  {'-'*4}  {'-'*6}  {'-'*9}  {'-'*8}  {'-'*9}  {'-'*9}  {'-'*8}")

    for rank, r in enumerate(results[:15], 1):
        print(
            f"  {rank:4d}  {r['tick_to']:6d}  {r['time_to_s']:5.0f}s  {r['round_trips']:4d}  "
            f"{r['win_rate']:5.1f}%  {r['gross']:+9.2f}  {r['fees']:8.2f}  {r['net']:+9.2f}  "
            f"{r['largest_loss']:+9.2f}  {r['pnl_per_share']:8.4f}"
        )

    # Also show worst 5
    print(f"\n  BOTTOM 5:")
    print(f"  {'-'*4}  {'-'*6}  {'-'*5}  {'-'*4}  {'-'*6}  {'-'*9}  {'-'*8}  {'-'*9}  {'-'*9}  {'-'*8}")
    for rank, r in enumerate(results[-5:], len(results) - 4):
        print(
            f"  {rank:4d}  {r['tick_to']:6d}  {r['time_to_s']:5.0f}s  {r['round_trips']:4d}  "
            f"{r['win_rate']:5.1f}%  {r['gross']:+9.2f}  {r['fees']:8.2f}  {r['net']:+9.2f}  "
            f"{r['largest_loss']:+9.2f}  {r['pnl_per_share']:8.4f}"
        )

    print(f"\n{'=' * 100}")

    # Best config
    best = results[0]
    print(f"\n  BEST: max_hold_ticks={best['tick_to']}, max_hold_ns={best['time_to_s']:.0f}s")
    print(f"         {best['round_trips']} round-trips, {best['win_rate']:.1f}% win, "
          f"gross {best['gross']:+.2f}, net {best['net']:+.2f}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
