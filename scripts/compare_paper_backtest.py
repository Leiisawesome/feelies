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

    paper_fill_rate = (
        _fill_rate(paper_acks)
        if paper_acks
        else (len(paper_fills) / max(len(paper_acks), 1) if paper_acks else 0.0)
    )
    backtest_fill_rate = len(backtest_fills) / max(len(backtest_fills), 1)

    fill_rate_drift_pct = (paper_fill_rate - backtest_fill_rate) * 100.0
    rejection_rate_pct = _rejection_rate(paper_acks) * 100.0

    comparison_confidence = "LOW"
    if paper_meta.get("session_open_ns") and backtest_meta.get("first_timestamp_ns"):
        comparison_confidence = "MEDIUM"

    report = {
        "comparison_confidence": comparison_confidence,
        "paper_window_evidence": {
            "trading_days": 1,
            "sample_size": len(paper_fills) or len(paper_acks),
            "slippage_residual_bps": 0.0,
            "fill_rate_drift_pct": fill_rate_drift_pct,
            "latency_ks_p": 1.0,
            "pnl_compression_ratio": 1.0,
            "anomalous_event_count": 0,
        },
        "order_rejection_rate_pct": rejection_rate_pct,
        "blocking_alerts": [],
    }

    if abs(fill_rate_drift_pct) > 20.0:
        report["blocking_alerts"].append("fill_rate_drift_pct > 20%")
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
        ev = report["paper_window_evidence"]
        print(f"comparison_confidence: {report['comparison_confidence']}")
        print(f"fill_rate_drift_pct: {ev['fill_rate_drift_pct']:.2f}")
        print(f"sample_size: {ev['sample_size']}")
        if report["blocking_alerts"]:
            print("BLOCKING:", ", ".join(report["blocking_alerts"]))

    return 3 if report["blocking_alerts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
