#!/usr/bin/env python3
"""Run the full backtest validation suite.

Usage:
    python scripts/run_validation.py            # all tests (including benchmarks)
    python scripts/run_validation.py --quick    # skip slow performance benchmarks
    python scripts/run_validation.py --new      # only new validation tests
    python scripts/run_validation.py -k drawdown  # filter by keyword
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the backtest validation suite.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Skip slow performance benchmarks",
    )
    parser.add_argument(
        "--new",
        action="store_true",
        help="Run only the new tests/validation/ tests",
    )
    parser.add_argument(
        "-k",
        dest="keyword",
        default="",
        help="Only run tests matching this keyword expression",
    )
    parser.add_argument(
        "-x",
        action="store_true",
        help="Stop on first failure",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Minimal output (no per-test lines)",
    )
    args = parser.parse_args()

    cmd = [sys.executable, "-m", "pytest"]

    if args.new:
        cmd.append("tests/validation/")
    elif args.quick:
        cmd.extend(["-m", "backtest_validation and not slow"])
    else:
        cmd.extend(["-m", "backtest_validation"])

    if not args.quiet:
        cmd.append("-v")

    if args.x:
        cmd.append("-x")

    if args.keyword:
        cmd.extend(["-k", args.keyword])

    cmd.append("--tb=short")

    print(f"$ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    raise SystemExit(main())
