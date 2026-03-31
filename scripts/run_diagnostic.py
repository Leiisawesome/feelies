#!/usr/bin/env python3
"""Trade-level diagnostic — decomposes alpha edge by exit reason, direction, timing.

Usage:
    python scripts/run_diagnostic.py --symbol AAPL --date 2026-03-18
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from run_backtest import (
    BusRecorder,
    _RULE_HEAVY,
    _RULE_LIGHT,
    _header,
    _money,
    _section,
    ingest_data,
    parse_args,
)

from feelies.bootstrap import build_platform
from feelies.core.events import (
    FeatureVector,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    PositionUpdate,
    Signal,
    SignalDirection,
)
from feelies.core.platform_config import PlatformConfig
from feelies.storage.trade_journal import TradeRecord


# ── Round-trip data structure ────────────────────────────────────────


@dataclass
class RoundTrip:
    """A paired entry + exit with computed fields."""

    trade_num: int
    direction: str  # "LONG" or "SHORT"

    # Entry
    entry_seq: int
    entry_ts_ns: int
    entry_price: Decimal
    entry_quantity: int
    entry_z: float
    entry_drift_bps: float
    entry_imb_delta: float
    entry_spread_bp: float
    entry_spread_z: float
    entry_tradability: float
    entry_strength: float
    entry_edge_bps: float

    # Exit
    exit_seq: int = 0
    exit_ts_ns: int = 0
    exit_price: Decimal = Decimal("0")
    exit_z: float = 0.0
    exit_spread_bp: float = 0.0
    exit_spread_z: float = 0.0
    exit_reason: str = "unknown"

    # P&L (from TradeRecord)
    gross_pnl: Decimal = Decimal("0")
    entry_fees: Decimal = Decimal("0")
    exit_fees: Decimal = Decimal("0")
    net_pnl: Decimal = Decimal("0")

    # Computed
    hold_ticks: int = 0
    hold_time_s: float = 0.0


def _classify_exit(
    features_at_exit: dict[str, float],
    hold_ticks: int,
    hold_time_ns: int,
    params: dict,
) -> str:
    """Infer exit reason from features at exit time.
    
    Checks conditions in the same order as the signal logic so the
    first matching condition is the one that actually triggered.
    """
    mu = features_at_exit.get("mu_ema", 0.0)
    spread_bp = features_at_exit.get("current_spread_bp", 0.0)
    spread_z = features_at_exit.get("spread_z", 0.0)

    exit_drift = params.get("exit_drift_z", 0.5)
    max_hold = params.get("max_hold_ticks", 5000)
    max_hold_ns = params.get("max_hold_ns", 25_000_000_000)
    max_spread = params.get("max_spread_bp", 3.0)

    # Same order as signal evaluate() exit block
    if abs(mu) < exit_drift:
        return "reversion"
    if hold_ticks >= max_hold:
        return "tick_timeout"
    if hold_time_ns >= max_hold_ns:
        return "time_timeout"
    if spread_bp > max_spread * 2.0:
        return "spread_blowout"
    if spread_z > 2.0:
        return "structural_break"
    return "unknown"


# ── Build round-trips from events ────────────────────────────────────


def build_round_trips(
    signals: list[Signal],
    features_by_seq: dict[int, FeatureVector],
    trade_records: list[TradeRecord],
    params: dict,
) -> list[RoundTrip]:
    """Pair entry/exit signals with fills and features."""

    # Index trade records by sequence (fill_timestamp_ns serves as proxy)
    # Map: correlation_id -> TradeRecord
    records_by_corr: dict[str, TradeRecord] = {}
    for rec in trade_records:
        records_by_corr[rec.correlation_id] = rec

    # Also build a list indexed by order of occurrence
    records_list = sorted(trade_records, key=lambda r: r.fill_timestamp_ns or 0)

    round_trips: list[RoundTrip] = []
    current_entry: Signal | None = None
    entry_features: dict[str, float] | None = None
    entry_rec: TradeRecord | None = None
    trade_num = 0

    # Walk signals chronologically
    for sig in sorted(signals, key=lambda s: s.sequence):
        fv = features_by_seq.get(sig.sequence)
        fvals = fv.values if fv else {}

        if sig.direction in (SignalDirection.LONG, SignalDirection.SHORT):
            # New entry
            current_entry = sig
            entry_features = dict(fvals)
            # Find matching trade record
            entry_rec = records_by_corr.get(sig.correlation_id)

        elif sig.direction == SignalDirection.FLAT and current_entry is not None:
            # Exit — close the round-trip
            trade_num += 1
            exit_rec = records_by_corr.get(sig.correlation_id)

            hold_ticks = sig.sequence - current_entry.sequence
            hold_time_ns = sig.timestamp_ns - current_entry.timestamp_ns

            exit_reason = _classify_exit(fvals, hold_ticks, hold_time_ns, params)

            entry_fill_price = Decimal("0")
            exit_fill_price = Decimal("0")
            entry_qty = 0

            if entry_rec:
                entry_fill_price = entry_rec.fill_price or Decimal("0")
                entry_qty = entry_rec.filled_quantity

            gross = Decimal("0")
            entry_fee = entry_rec.fees if entry_rec else Decimal("0")
            exit_fee = exit_rec.fees if exit_rec else Decimal("0")

            if exit_rec:
                exit_fill_price = exit_rec.fill_price or Decimal("0")
                gross = exit_rec.realized_pnl

            ef = entry_features or {}
            rt = RoundTrip(
                trade_num=trade_num,
                direction="LONG" if current_entry.direction == SignalDirection.LONG else "SHORT",
                entry_seq=current_entry.sequence,
                entry_ts_ns=current_entry.timestamp_ns,
                entry_price=entry_fill_price,
                entry_quantity=entry_qty,
                entry_z=ef.get("mu_ema", 0.0),
                entry_drift_bps=ef.get("drift_bps", 0.0),
                entry_imb_delta=ef.get("imbalance_delta", 0.0),
                entry_spread_bp=ef.get("current_spread_bp", 0.0),
                entry_spread_z=ef.get("spread_z", 0.0),
                entry_tradability=ef.get("tradability_score", 0.0),
                entry_strength=current_entry.strength,
                entry_edge_bps=current_entry.edge_estimate_bps,
                exit_seq=sig.sequence,
                exit_ts_ns=sig.timestamp_ns,
                exit_price=exit_fill_price,
                exit_z=fvals.get("mu_ema", 0.0),
                exit_spread_bp=fvals.get("current_spread_bp", 0.0),
                exit_spread_z=fvals.get("spread_z", 0.0),
                exit_reason=exit_reason,
                gross_pnl=gross,
                entry_fees=entry_fee,
                exit_fees=exit_fee,
                net_pnl=gross - entry_fee - exit_fee,
                hold_ticks=hold_ticks,
                hold_time_s=hold_time_ns / 1e9,
            )
            round_trips.append(rt)
            current_entry = None
            entry_features = None
            entry_rec = None

    return round_trips


# ── Analysis ─────────────────────────────────────────────────────────


def _fmt_pnl(v: Decimal) -> str:
    sign = "-" if v < 0 else "+"
    return f"{sign}${abs(v):,.2f}"


def _pct(num: int, denom: int) -> str:
    return f"{num / denom * 100:.1f}%" if denom else "N/A"


def _avg(vals: list) -> float:
    return statistics.mean(vals) if vals else 0.0


def _median(vals: list) -> float:
    return statistics.median(vals) if vals else 0.0


def _stdev(vals: list) -> float:
    return statistics.stdev(vals) if len(vals) >= 2 else 0.0


def print_diagnostic(rts: list[RoundTrip]) -> None:
    """Print comprehensive trade diagnostic."""
    if not rts:
        print("No round-trips to analyze.")
        return

    W = 66
    print(f"\n{'=' * W}")
    print(f"  TRADE-LEVEL DIAGNOSTIC  |  {len(rts)} round-trips")
    print(f"{'=' * W}")

    # ── 1. Overall summary ────────────────────────────────────
    winners = [rt for rt in rts if rt.gross_pnl > 0]
    losers = [rt for rt in rts if rt.gross_pnl < 0]
    flat = [rt for rt in rts if rt.gross_pnl == 0]

    total_gross = sum(rt.gross_pnl for rt in rts)
    total_fees = sum(rt.entry_fees + rt.exit_fees for rt in rts)
    total_net = total_gross - total_fees

    print(_section("OVERALL"))
    print(f"    {'Round-trips':<28s}{len(rts)}")
    print(f"    {'Winners':<28s}{len(winners)} ({_pct(len(winners), len(rts))})")
    print(f"    {'Losers':<28s}{len(losers)} ({_pct(len(losers), len(rts))})")
    print(f"    {'Breakeven':<28s}{len(flat)}")
    print(f"    {'Total gross P&L':<28s}{_fmt_pnl(total_gross)}")
    print(f"    {'Total fees':<28s}{_money(total_fees)}")
    print(f"    {'Total net P&L':<28s}{_fmt_pnl(total_net)}")
    print(f"    {'Avg gross/trade':<28s}{_fmt_pnl(total_gross / len(rts))}")
    print(f"    {'Avg fees/trade':<28s}{_money(total_fees / len(rts))}")
    print(f"    {'Avg net/trade':<28s}{_fmt_pnl(total_net / len(rts))}")

    if winners:
        avg_w = sum(rt.gross_pnl for rt in winners) / len(winners)
        print(f"    {'Avg winner (gross)':<28s}{_fmt_pnl(avg_w)}")
    if losers:
        avg_l = sum(rt.gross_pnl for rt in losers) / len(losers)
        print(f"    {'Avg loser (gross)':<28s}{_fmt_pnl(avg_l)}")
    if winners and losers:
        print(f"    {'Win/Loss ratio':<28s}{float(avg_w) / abs(float(avg_l)):.2f}")

    # Largest
    if rts:
        best = max(rts, key=lambda r: r.gross_pnl)
        worst = min(rts, key=lambda r: r.gross_pnl)
        print(f"    {'Largest winner':<28s}{_fmt_pnl(best.gross_pnl)} (trade #{best.trade_num})")
        print(f"    {'Largest loser':<28s}{_fmt_pnl(worst.gross_pnl)} (trade #{worst.trade_num})")

    # ── 2. By direction ───────────────────────────────────────
    print(_section("BY DIRECTION"))
    for direction in ("LONG", "SHORT"):
        subset = [rt for rt in rts if rt.direction == direction]
        if not subset:
            continue
        w = [rt for rt in subset if rt.gross_pnl > 0]
        l = [rt for rt in subset if rt.gross_pnl < 0]
        g = sum(rt.gross_pnl for rt in subset)
        f = sum(rt.entry_fees + rt.exit_fees for rt in subset)
        print(f"\n    {direction}:")
        print(f"      {'Count':<26s}{len(subset)}")
        print(f"      {'Win rate':<26s}{_pct(len(w), len(subset))}")
        print(f"      {'Gross P&L':<26s}{_fmt_pnl(g)}")
        print(f"      {'Fees':<26s}{_money(f)}")
        print(f"      {'Net P&L':<26s}{_fmt_pnl(g - f)}")
        print(f"      {'Avg gross/trade':<26s}{_fmt_pnl(g / len(subset))}")

    # ── 3. By exit reason ─────────────────────────────────────
    print(_section("BY EXIT REASON"))
    reasons = sorted(set(rt.exit_reason for rt in rts))
    for reason in reasons:
        subset = [rt for rt in rts if rt.exit_reason == reason]
        w = [rt for rt in subset if rt.gross_pnl > 0]
        g = sum(rt.gross_pnl for rt in subset)
        f = sum(rt.entry_fees + rt.exit_fees for rt in subset)
        avg_hold = _avg([rt.hold_ticks for rt in subset])
        avg_hold_s = _avg([rt.hold_time_s for rt in subset])
        print(f"\n    {reason.upper()}:")
        print(f"      {'Count':<26s}{len(subset)} ({_pct(len(subset), len(rts))})")
        print(f"      {'Win rate':<26s}{_pct(len(w), len(subset))}")
        print(f"      {'Gross P&L':<26s}{_fmt_pnl(g)}")
        print(f"      {'Net P&L':<26s}{_fmt_pnl(g - f)}")
        print(f"      {'Avg hold (ticks)':<26s}{avg_hold:.0f}")
        print(f"      {'Avg hold (seconds)':<26s}{avg_hold_s:.1f}s")
        print(f"      {'Avg entry |z|':<26s}{_avg([abs(rt.entry_z) for rt in subset]):.2f}")

    # ── 4. Hold time analysis ─────────────────────────────────
    print(_section("HOLD TIME DISTRIBUTION"))
    ticks_list = [rt.hold_ticks for rt in rts]
    time_list = [rt.hold_time_s for rt in rts]
    print(f"    {'Mean (ticks)':<28s}{_avg(ticks_list):.0f}")
    print(f"    {'Median (ticks)':<28s}{_median(ticks_list):.0f}")
    print(f"    {'Stdev (ticks)':<28s}{_stdev(ticks_list):.0f}")
    print(f"    {'Min (ticks)':<28s}{min(ticks_list)}")
    print(f"    {'Max (ticks)':<28s}{max(ticks_list)}")
    print(f"    {'Mean (seconds)':<28s}{_avg(time_list):.1f}s")
    print(f"    {'Median (seconds)':<28s}{_median(time_list):.1f}s")

    # Buckets: short, medium, long holds
    short_holds = [rt for rt in rts if rt.hold_ticks <= 200]
    med_holds = [rt for rt in rts if 200 < rt.hold_ticks <= 1000]
    long_holds = [rt for rt in rts if rt.hold_ticks > 1000]
    for label, bucket in [("Short (<=200)", short_holds), ("Medium (201-1000)", med_holds), ("Long (>1000)", long_holds)]:
        if not bucket:
            continue
        w = len([rt for rt in bucket if rt.gross_pnl > 0])
        g = sum(rt.gross_pnl for rt in bucket)
        print(f"\n    {label}: {len(bucket)} trades, win rate {_pct(w, len(bucket))}, gross {_fmt_pnl(g)}")

    # ── 5. Entry z-score analysis ─────────────────────────────
    print(_section("ENTRY Z-SCORE ANALYSIS"))
    z_values = [abs(rt.entry_z) for rt in rts]
    print(f"    {'Mean |z| at entry':<28s}{_avg(z_values):.2f}")
    print(f"    {'Median |z| at entry':<28s}{_median(z_values):.2f}")
    print(f"    {'Min |z| at entry':<28s}{min(z_values):.2f}")
    print(f"    {'Max |z| at entry':<28s}{max(z_values):.2f}")

    # z-score buckets
    for lo, hi in [(2.0, 3.0), (3.0, 4.0), (4.0, 6.0), (6.0, float("inf"))]:
        bucket = [rt for rt in rts if lo <= abs(rt.entry_z) < hi]
        if not bucket:
            continue
        w = len([rt for rt in bucket if rt.gross_pnl > 0])
        g = sum(rt.gross_pnl for rt in bucket)
        label = f"|z| [{lo:.0f}, {hi:.0f})" if hi != float("inf") else f"|z| >= {lo:.0f}"
        print(f"\n    {label}: {len(bucket)} trades, win rate {_pct(w, len(bucket))}, gross {_fmt_pnl(g)}")

    # ── 6. Fee impact analysis ────────────────────────────────
    print(_section("FEE IMPACT"))
    gross_positive = [rt for rt in rts if rt.gross_pnl > 0]
    gross_positive_but_net_negative = [rt for rt in gross_positive if rt.net_pnl < 0]
    print(f"    {'Winners turned to losers by fees':<36s}{len(gross_positive_but_net_negative)}")
    total_shares = sum(rt.entry_quantity * 2 for rt in rts)  # entry + exit
    print(f"    {'Total shares (est)':<36s}{total_shares:,}")
    if total_shares:
        print(f"    {'Avg cost/share (all-in)':<36s}${float(total_fees) / total_shares:.4f}")
    print(f"    {'Fees as % of gross edge':<36s}", end="")
    if total_gross > 0:
        print(f"{float(total_fees) / float(total_gross) * 100:.1f}%")
    else:
        print("N/A (gross <= 0)")

    # ── 7. Spread at entry distribution ───────────────────────
    print(_section("SPREAD AT ENTRY"))
    spread_vals = [rt.entry_spread_bp for rt in rts]
    print(f"    {'Mean spread (bps)':<28s}{_avg(spread_vals):.2f}")
    print(f"    {'Median spread (bps)':<28s}{_median(spread_vals):.2f}")
    print(f"    {'Min spread (bps)':<28s}{min(spread_vals):.2f}")
    print(f"    {'Max spread (bps)':<28s}{max(spread_vals):.2f}")

    # ── 8. Worst trades detail ────────────────────────────────
    print(_section("TOP 5 WORST TRADES"))
    worst5 = sorted(rts, key=lambda r: r.gross_pnl)[:5]
    for rt in worst5:
        print(f"\n    Trade #{rt.trade_num}: {rt.direction}")
        print(f"      Gross P&L: {_fmt_pnl(rt.gross_pnl)}, Fees: {_money(rt.entry_fees + rt.exit_fees)}")
        print(f"      Entry z={rt.entry_z:.2f}, spread={rt.entry_spread_bp:.2f}bp, qty={rt.entry_quantity}")
        print(f"      Exit z={rt.exit_z:.2f}, spread={rt.exit_spread_bp:.2f}bp, reason={rt.exit_reason}")
        print(f"      Hold: {rt.hold_ticks} ticks ({rt.hold_time_s:.1f}s)")
        print(f"      Entry ${rt.entry_price} -> Exit ${rt.exit_price}")

    # ── 9. Top 5 best trades ─────────────────────────────────
    print(_section("TOP 5 BEST TRADES"))
    best5 = sorted(rts, key=lambda r: r.gross_pnl, reverse=True)[:5]
    for rt in best5:
        print(f"\n    Trade #{rt.trade_num}: {rt.direction}")
        print(f"      Gross P&L: {_fmt_pnl(rt.gross_pnl)}, Fees: {_money(rt.entry_fees + rt.exit_fees)}")
        print(f"      Entry z={rt.entry_z:.2f}, spread={rt.entry_spread_bp:.2f}bp, qty={rt.entry_quantity}")
        print(f"      Exit z={rt.exit_z:.2f}, spread={rt.exit_spread_bp:.2f}bp, reason={rt.exit_reason}")
        print(f"      Hold: {rt.hold_ticks} ticks ({rt.hold_time_s:.1f}s)")

    # ── 10. Concise round-trip table ──────────────────────────
    print(_section("ALL ROUND-TRIPS (CONCISE)"))
    print(f"    {'#':>3s} {'Dir':>5s} {'Entry Z':>8s} {'ExitRsn':>12s} {'Hold':>6s} "
          f"{'Gross':>9s} {'Fees':>8s} {'Net':>9s} {'Spread':>7s}")
    print(f"    {'-'*3} {'-'*5} {'-'*8} {'-'*12} {'-'*6} {'-'*9} {'-'*8} {'-'*9} {'-'*7}")
    for rt in rts:
        fees = rt.entry_fees + rt.exit_fees
        print(f"    {rt.trade_num:3d} {rt.direction:>5s} {rt.entry_z:8.2f} {rt.exit_reason:>12s} "
              f"{rt.hold_ticks:6d} {float(rt.gross_pnl):9.2f} {float(fees):8.2f} "
              f"{float(rt.net_pnl):9.2f} {rt.entry_spread_bp:7.2f}")

    print(f"\n{'=' * W}\n")


# ── Main ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.demo:
        print("Diagnostic does not support --demo. Use real data.", file=sys.stderr)
        return 1

    if not args.date:
        print("ERROR: --date is required", file=sys.stderr)
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

    config_path = Path(args.config)
    config = PlatformConfig.from_yaml(config_path)

    if args.symbol:
        config.symbols = frozenset(s.upper() for s in args.symbol)

    symbols = sorted(config.symbols)
    start_date = args.date
    end_date = args.end_date or start_date
    cache_dir = Path(args.cache_dir) if args.cache_dir else None

    print(f"\n  Diagnostic: {', '.join(symbols)}  |  {start_date}", flush=True)
    print(f"  {_RULE_LIGHT}", flush=True)

    # ── Ingest ────────────────────────────────────────────────
    print("  Loading market data ...", flush=True)
    event_log, ingest_result, _ = ingest_data(
        api_key, symbols, start_date, end_date,
        cache_dir=cache_dir, no_cache=args.no_cache,
    )
    print(f"  {ingest_result.events_ingested:,} events loaded.", flush=True)

    # ── Bootstrap ─────────────────────────────────────────────
    print("  Building platform ...", flush=True)
    orchestrator, config = build_platform(config, event_log=event_log)

    recorder = BusRecorder()
    orchestrator._bus.subscribe_all(recorder)

    orchestrator.boot(config)
    print("  Running backtest ...", flush=True)
    orchestrator.run_backtest()
    print("  Backtest complete.", flush=True)

    # ── Extract data ──────────────────────────────────────────
    signals = recorder.of_type(Signal)
    features = recorder.of_type(FeatureVector)
    trade_records = list(orchestrator._trade_journal.query())

    # Build feature lookup by sequence number
    features_by_seq: dict[int, FeatureVector] = {}
    for fv in features:
        features_by_seq[fv.sequence] = fv

    # Get alpha parameters
    alpha_reg = orchestrator._alpha_registry
    params: dict = {}
    for alpha in alpha_reg.active_alphas():
        if alpha.manifest.alpha_id == "h002_drift_fade":
            params = dict(alpha.manifest.parameters)
            break

    print(f"  {len(signals)} signals, {len(trade_records)} trade records.", flush=True)
    print(f"  Building round-trips ...", flush=True)

    round_trips = build_round_trips(signals, features_by_seq, trade_records, params)
    print(f"  {len(round_trips)} round-trips built.", flush=True)

    # ── Print diagnostic ──────────────────────────────────────
    print_diagnostic(round_trips)

    return 0


if __name__ == "__main__":
    sys.exit(main())
