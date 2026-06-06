#!/usr/bin/env python3
"""Long-running paper soak harness (weekly operator runs)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Paper trading soak harness")
    p.add_argument("--config", default="configs/paper_smoke_rth.yaml")
    p.add_argument("--duration-s", type=int, default=7200)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--snapshot-interval-s", type=int, default=300)
    args = p.parse_args(argv)

    args.run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.run_dir / "soak_summary.jsonl"
    repo = Path(__file__).resolve().parent.parent
    cmd = [
        sys.executable,
        str(repo / "scripts" / "run_paper.py"),
        "--config", str(repo / args.config),
        "--run-dir", str(args.run_dir),
        "--max-runtime-s", str(args.duration_s),
        "--emit-timing-jsonl",
        "--emit-order-acks-jsonl",
        "--emit-signals-jsonl",
        "--emit-fills-jsonl",
    ]

    proc = subprocess.Popen(cmd, cwd=str(repo))
    start = time.monotonic()
    try:
        while proc.poll() is None:
            elapsed = time.monotonic() - start
            row = {
                "timestamp_ns": int(datetime.now(UTC).timestamp() * 1e9),
                "elapsed_s": elapsed,
                "pid": proc.pid,
            }
            with summary_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
            if elapsed >= args.duration_s:
                break
            time.sleep(args.snapshot_interval_s)
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=60)

    return proc.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
