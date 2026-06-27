#!/usr/bin/env python3
"""Compare paper session artefacts against a backtest run-dir."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _fill_rate(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    filled = sum(1 for r in rows if r.get("status") == "FILLED")
    return filled / len(rows)


def _rejection_rate(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    rejected = sum(1 for r in rows if r.get("status") == "REJECTED")
    return rejected / len(rows)


def compare_runs(paper_dir: Path, backtest_dir: Path) -> dict[str, Any]:
    """Compare a paper session run-dir against a backtest run-dir.

    Honesty note: the backtest ``fills.jsonl`` contains FILLED acks only (it
    has no rejected/cancelled rows), so a true *fill rate* is not computable
    for the backtest side and the old ``len/len`` formula was identically 1.0.
    We therefore report the paper fill/rejection rates (which ARE computable
    from ``order_acks.jsonl``) plus raw counts, and mark the cross-run
    divergence metrics (slippage, latency KS, PnL compression) as *unavailable*
    rather than emitting hardcoded placeholder constants.  Only the paper
    rejection rate gates here; this tool is **not** promotion-grade until the
    slippage/latency/PnL comparisons are implemented against matched streams.
    """
    paper_acks = _load_jsonl(paper_dir / "order_acks.jsonl")
    backtest_fills = _load_jsonl(backtest_dir / "fills.jsonl")
    paper_fills = _load_jsonl(paper_dir / "fills.jsonl")
    paper_meta = (
        json.loads((paper_dir / "metadata.json").read_text(encoding="utf-8"))
        if (paper_dir / "metadata.json").is_file()
        else {}
    )
    backtest_meta = (
        json.loads((backtest_dir / "metadata.json").read_text(encoding="utf-8"))
        if (backtest_dir / "metadata.json").is_file()
        else {}
    )

    paper_fill_rate = _fill_rate(paper_acks)  # filled / all acks — real rate
    rejection_rate_pct = _rejection_rate(paper_acks) * 100.0

    # Metrics not yet implemented against matched streams — surfaced as null so
    # downstream consumers cannot mistake a placeholder constant for a measurement.
    unavailable = [
        "slippage_residual_bps",
        "latency_ks_p",
        "pnl_compression_ratio",
        "anomalous_event_count",
        "fill_rate_drift_pct",  # backtest stream is fills-only; no denominator
    ]

    have_anchors = bool(
        paper_meta.get("session_open_ns") and backtest_meta.get("first_timestamp_ns")
    )
    have_paper_acks = bool(paper_acks)
    comparison_confidence = "LOW" if (have_anchors and have_paper_acks) else "INSUFFICIENT"

    report: dict[str, Any] = {
        "comparison_confidence": comparison_confidence,
        "promotion_grade": False,
        "paper": {
            "order_acks": len(paper_acks),
            "fills": len(paper_fills),
            "fill_rate": paper_fill_rate,
            "rejection_rate_pct": rejection_rate_pct,
        },
        "backtest": {
            "fills": len(backtest_fills),
        },
        "unavailable_metrics": unavailable,
        "order_rejection_rate_pct": rejection_rate_pct,
        "blocking_alerts": [],
    }

    if rejection_rate_pct > 8.0:
        report["blocking_alerts"].append("order_rejection_rate > 8%")

    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compare paper vs backtest run dirs")
    p.add_argument("--paper-run-dir", type=Path, required=True)
    p.add_argument("--backtest-run-dir", type=Path, required=True)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    report = compare_runs(args.paper_run_dir, args.backtest_run_dir)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        paper = report["paper"]
        print(f"comparison_confidence: {report['comparison_confidence']}")
        print(f"promotion_grade: {report['promotion_grade']}")
        print(f"paper order_acks: {paper['order_acks']}  fills: {paper['fills']}")
        print(f"paper fill_rate: {paper['fill_rate']:.3f}")
        print(f"paper rejection_rate_pct: {paper['rejection_rate_pct']:.2f}")
        print(f"backtest fills: {report['backtest']['fills']}")
        print(f"unavailable_metrics: {', '.join(report['unavailable_metrics'])}")
        if report["blocking_alerts"]:
            print("BLOCKING:", ", ".join(report["blocking_alerts"]))

    return 3 if report["blocking_alerts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
