#!/usr/bin/env python
"""Aggregate the ``NETDIV_JSONL`` stream from ``--emit-net-divergence-jsonl``.

Quantifies how often, and by how much, the budget-weighted portfolio net would
differ from today's winner-take-all decision (G-5 measurement) — the evidence
to decide whether to enable cross-alpha netting (N2) and build the PORTFOLIO
drive-bridge (N3b).

Input: one JSON object per line (from ``run_backtest.py
--emit-net-divergence-jsonl``).  Lines may keep or drop the ``NETDIV_JSONL ``
prefix; both are accepted, so either of these works:

    run_backtest.py ... --emit-net-divergence-jsonl | grep '^NETDIV_JSONL ' \\
        | sed 's/^NETDIV_JSONL //' > netdiv.jsonl
    python scripts/analyze_net_divergence.py netdiv.jsonl

    run_backtest.py ... --emit-net-divergence-jsonl | \\
        python scripts/analyze_net_divergence.py -

Each record: symbol, winner_strategy_id, winner_target_qty (w),
net_target_qty (n), magnitude (n − w), contributing_alphas.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


_PREFIX = "NETDIV_JSONL "
_ET = ZoneInfo("America/New_York")


def _et_date(ns: int) -> str:
    """Epoch ns → trading-day date (US/Eastern), e.g. ``2026-06-01``."""
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).astimezone(_ET).date().isoformat()


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def classify(w: int, n: int) -> str:
    """Classify a divergence by how the net (n) differs from the winner (w)."""
    if n == 0 and w != 0:
        return "net_flat"  # opposing desires cancel to flat
    if w == 0 and n != 0:
        return "net_opens"  # winner flat, portfolio wants a position
    if _sign(n) != _sign(w):
        return "flip"  # net flips direction vs the winner
    if abs(n) > abs(w):
        return "stack"  # same direction, net larger (reinforced)
    if abs(n) < abs(w):
        return "shrink"  # same direction, net smaller (offset)
    return "equal"  # |n|==|w| same sign (shouldn't be emitted)


def parse_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    if line.startswith(_PREFIX):
        line = line[len(_PREFIX) :]
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(rec, dict):
        return None
    if "net_target_qty" not in rec or "winner_target_qty" not in rec:
        return None
    return rec


def summarize(records: list[dict[str, Any]], total_decisions: int | None) -> str:
    out: list[str] = []
    n = len(records)
    out.append("=" * 60)
    out.append("  CROSS-ALPHA NET-DIVERGENCE SUMMARY (G-5)")
    out.append("=" * 60)
    if n == 0:
        out.append("\n  No divergent decisions recorded.")
        out.append("  (single-alpha run, or alphas never overlapped on a symbol)")
        return "\n".join(out)

    mags = [int(r["net_target_qty"]) - int(r["winner_target_qty"]) for r in records]
    abs_mags = [abs(m) for m in mags]
    classes = Counter(
        classify(int(r["winner_target_qty"]), int(r["net_target_qty"])) for r in records
    )
    by_symbol = Counter(r.get("symbol", "?") for r in records)
    by_winner = Counter(r.get("winner_strategy_id", "?") for r in records)
    contrib = Counter(int(r.get("contributing_alphas", 0)) for r in records)

    out.append(f"\n  Divergent decisions       {n:,}")
    if total_decisions:
        rate = n / total_decisions * 100.0
        out.append(f"  Total decisions           {total_decisions:,}")
        out.append(f"  Divergence rate           {rate:.2f}%")
    else:
        out.append(
            "  Divergence rate           n/a "
            "(pass --total-decisions N from the run's signal count)"
        )

    out.append("\n  Magnitude |net − winner| (shares)")
    out.append(f"    mean    {statistics.mean(abs_mags):.1f}")
    out.append(f"    median  {statistics.median(abs_mags):.0f}")
    out.append(f"    p95     {_pct(abs_mags, 0.95):.0f}")
    out.append(f"    max     {max(abs_mags)}")
    out.append(
        f"    >0 (net bigger/flip)  "
        f"{sum(1 for m in mags if m > 0):,}   "
        f"<0 (net smaller)  {sum(1 for m in mags if m < 0):,}"
    )

    out.append("\n  Decision shift (what netting would change)")
    for kind, label in (
        ("stack", "stack   — same dir, net LARGER (conviction reinforced)"),
        ("shrink", "shrink  — same dir, net SMALLER (cross-alpha offset)"),
        ("net_flat", "to-flat — opposing desires cancel (no trade)"),
        ("flip", "flip    — net flips direction vs the winner"),
        ("net_opens", "opens   — winner flat, portfolio wants a position"),
        ("equal", "equal   — |net|==|winner| (unexpected)"),
    ):
        c = classes.get(kind, 0)
        if c:
            out.append(f"    {label:<52s} {c:>7,} ({c / n * 100:.1f}%)")

    out.append("\n  By symbol")
    for sym, c in by_symbol.most_common(15):
        out.append(f"    {sym:<10s} {c:>7,} ({c / n * 100:.1f}%)")

    out.append("\n  By winning alpha (whose target the net displaced)")
    for sid, c in by_winner.most_common(15):
        out.append(f"    {sid:<28s} {c:>7,} ({c / n * 100:.1f}%)")

    out.append("\n  Contributing alphas per divergent decision")
    for k in sorted(contrib):
        c = contrib[k]
        out.append(f"    {k} alphas   {c:>7,} ({c / n * 100:.1f}%)")

    # Per trading day (ET) — only when records carry a timestamp.  Shows the
    # day-to-day spread of divergence count + the dominant shift, so a multi-
    # day run reveals whether the pattern is stable (no per-day RATE: this
    # stream has no per-day decision count; pass single days for that).
    dated = [r for r in records if int(r.get("timestamp_ns", 0)) > 0]
    if dated:
        by_day: dict[str, Counter[str]] = {}
        for r in dated:
            day = _et_date(int(r["timestamp_ns"]))
            by_day.setdefault(day, Counter())[
                classify(int(r["winner_target_qty"]), int(r["net_target_qty"]))
            ] += 1
        out.append("\n  By trading day (ET)   [count | dominant shift]")
        for day in sorted(by_day):
            cc = by_day[day]
            total = sum(cc.values())
            top, topn = cc.most_common(1)[0]
            out.append(
                f"    {day}   {total:>5,}   {top} {topn}/{total} ({topn / total * 100:.0f}%)"
            )

    out.append("")
    return "\n".join(out)


def _pct(values: list[int], q: float) -> float:
    s = sorted(values)
    return float(s[min(len(s) - 1, int(q * len(s)))])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "path",
        help="NETDIV_JSONL file, or '-' for stdin.",
    )
    ap.add_argument(
        "--total-decisions",
        type=int,
        default=None,
        help="Total decisions in the run (e.g. signals emitted) → divergence rate.",
    )
    args = ap.parse_args(argv)

    stream = sys.stdin if args.path == "-" else open(args.path, encoding="utf-8")
    try:
        records = [r for r in (parse_line(ln) for ln in stream) if r is not None]
    finally:
        if stream is not sys.stdin:
            stream.close()

    print(summarize(records, args.total_decisions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
