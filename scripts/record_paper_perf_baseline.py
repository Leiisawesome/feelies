#!/usr/bin/env python3
"""Record paper-RTH perf baseline into v02_baseline.json."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

_BASELINE = (
    Path(__file__).resolve().parent.parent / "tests" / "perf" / "baselines" / "v02_baseline.json"
)


def _p99(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    sorted_v = sorted(values)
    idx = int(0.99 * (len(sorted_v) - 1))
    return sorted_v[idx]


def _parse_timing(run_dir: Path) -> dict[str, float]:
    path = run_dir / "timing.jsonl"
    if not path.is_file():
        return {}
    tick_ns: list[float] = []
    drain_ns: list[float] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        kind = row.get("kind")
        dur = float(row.get("duration_ns", 0))
        if kind == "tick_process":
            tick_ns.append(dur)
        elif kind == "drain_async_fills":
            drain_ns.append(dur)
    # An empty timing run cannot produce a meaningful latency baseline.
    if not tick_ns:
        return {}
    return {
        "tick_processing_p99_s": _p99(tick_ns) / 1e9,
        "drain_p99_s": _p99(drain_ns) / 1e9 if drain_ns else 0.0,
        "fill_to_position_p99_s": 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Record paper-RTH perf baseline")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--host-label", required=True)
    args = p.parse_args(argv)

    metrics = _parse_timing(args.run_dir)
    if not metrics:
        print(
            "No tick_process timing samples found in run-dir (missing "
            "timing.jsonl, or the run ended before producing any) — refusing "
            "to record a baseline from an incomplete/aborted run",
            file=sys.stderr,
        )
        return 1

    if _BASELINE.is_file():
        data = json.loads(_BASELINE.read_text(encoding="utf-8"))
    else:
        data = {"schema_version": "1.0.0", "hosts": {}}

    hosts = data.setdefault("hosts", {})
    host_blob = hosts.setdefault(args.host_label, {})
    host_blob["paper_rth"] = metrics
    _BASELINE.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Recorded paper_rth baseline for host={args.host_label!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
