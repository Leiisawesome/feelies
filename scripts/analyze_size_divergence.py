#!/usr/bin/env python
"""Aggregate the ``SIZEDIV_JSONL`` stream from ``--emit-size-divergence-jsonl``.

Quantifies how often, and by how much, the G-7 edge/vol/inventory-tilted
sizer would change the target size relative to today's single-factor
budget sizer — the evidence to decide whether to enable tilted sizing
(``sizer_tilt_drive``) and which factors carry the signal.

Input: one JSON object per line (from ``run_backtest.py
--emit-size-divergence-jsonl``).  Lines may keep or drop the
``SIZEDIV_JSONL `` prefix; both are accepted:

    run_backtest.py ... --emit-size-divergence-jsonl | grep '^SIZEDIV_JSONL ' \\
        | sed 's/^SIZEDIV_JSONL //' > sizediv.jsonl
    python scripts/analyze_size_divergence.py sizediv.jsonl

    run_backtest.py ... --emit-size-divergence-jsonl | \\
        python scripts/analyze_size_divergence.py -

Each record: symbol, strategy_id, edge_bps, base_target_qty (b),
tilted_target_qty (t), magnitude (t − b), edge/vol/inventory factors,
combined_tilt, inventory_qty.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from typing import Any


_PREFIX = "SIZEDIV_JSONL "


def classify(base: int, tilted: int) -> str:
    """Classify a divergence by how the tilted target differs from base."""
    if tilted > base:
        return "upsize"        # tilt grows the target (edge / low-vol)
    if tilted < base:
        return "downsize"      # tilt shrinks it (low edge / high-vol / inventory)
    return "equal"             # |t|==|b| (shouldn't be emitted)


def parse_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    if line.startswith(_PREFIX):
        line = line[len(_PREFIX):]
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(rec, dict):
        return None
    if "base_target_qty" not in rec or "tilted_target_qty" not in rec:
        return None
    return rec


def _pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return float(s[min(len(s) - 1, int(q * len(s)))])


def summarize(records: list[dict[str, Any]], total_decisions: int | None) -> str:
    out: list[str] = []
    out.append("=" * 60)
    out.append("  EDGE/VOL/INVENTORY SIZE-DIVERGENCE SUMMARY (G-7)")
    out.append("=" * 60)
    n = len(records)
    if n == 0:
        out.append("\n  No divergent sizes recorded.")
        out.append("  (no tilt factor enabled, or every tilt rounded to the "
                   "base target)")
        return "\n".join(out)

    mags = [
        int(r["tilted_target_qty"]) - int(r["base_target_qty"]) for r in records
    ]
    abs_mags = [abs(m) for m in mags]
    bases = [int(r["base_target_qty"]) for r in records]
    rel = [
        (int(r["tilted_target_qty"]) - b) / b * 100.0
        for r, b in zip(records, bases) if b > 0
    ]
    classes = Counter(
        classify(int(r["base_target_qty"]), int(r["tilted_target_qty"]))
        for r in records
    )
    by_symbol = Counter(r.get("symbol", "?") for r in records)
    by_alpha = Counter(r.get("strategy_id", "?") for r in records)
    tilts = [float(r.get("combined_tilt", 1.0)) for r in records]

    out.append(f"\n  Divergent sizes           {n:,}")
    if total_decisions:
        rate = n / total_decisions * 100.0
        out.append(f"  Total sized decisions     {total_decisions:,}")
        out.append(f"  Divergence rate           {rate:.2f}%")
    else:
        out.append("  Divergence rate           n/a "
                   "(pass --total-decisions N from the run's signal count)")

    out.append("\n  Magnitude |tilted − base| (shares)")
    out.append(f"    mean    {statistics.mean(abs_mags):.1f}")
    out.append(f"    median  {statistics.median(abs_mags):.0f}")
    out.append(f"    p95     {_pct([float(m) for m in abs_mags], 0.95):.0f}")
    out.append(f"    max     {max(abs_mags)}")
    if rel:
        out.append(f"    mean Δ% {statistics.mean(rel):+.1f}%   "
                   f"median Δ% {statistics.median(rel):+.1f}%")

    out.append("\n  Combined tilt")
    out.append(f"    mean    {statistics.mean(tilts):.3f}")
    out.append(f"    median  {statistics.median(tilts):.3f}")
    out.append(f"    min     {min(tilts):.3f}   max  {max(tilts):.3f}")

    out.append("\n  Direction (what tilting would change)")
    for kind, label in (
        ("upsize", "upsize   — tilt GROWS the target (edge / low-vol)"),
        ("downsize", "downsize — tilt SHRINKS it (low-edge / high-vol / inv)"),
        ("equal", "equal    — |tilted|==|base| (unexpected)"),
    ):
        c = classes.get(kind, 0)
        if c:
            out.append(f"    {label:<52s} {c:>7,} ({c / n * 100:.1f}%)")

    out.append("\n  By symbol")
    for sym, c in by_symbol.most_common(15):
        out.append(f"    {sym:<10s} {c:>7,} ({c / n * 100:.1f}%)")

    out.append("\n  By alpha")
    for sid, c in by_alpha.most_common(15):
        out.append(f"    {sid:<28s} {c:>7,} ({c / n * 100:.1f}%)")

    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", help="SIZEDIV_JSONL file, or '-' for stdin.")
    ap.add_argument(
        "--total-decisions",
        type=int,
        default=None,
        help="Total sized decisions in the run → divergence rate.",
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
