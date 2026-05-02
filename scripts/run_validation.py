#!/usr/bin/env python3
"""Run pytest tests marked ``backtest_validation`` (thin wrapper).

Equivalent core invocation::

    pytest -m backtest_validation

Usage:
    python scripts/run_validation.py              # marker suite (verbose)
    python scripts/run_validation.py --quick       # same subset but excludes ``slow``
    python scripts/run_validation.py -k drawdown   # filter by keyword

Note:
    ``--quick`` expands to ``-m \"backtest_validation and not slow\"``.  Today no
    ``backtest_validation`` module also carries ``slow``, so it matches the default
    suite unless that overlap is introduced later.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Run tests with pytest marker "backtest_validation".',
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help=(
            'Same as default but adds "and not slow" (perf/mypy tests '
            "that also carry backtest_validation would be skipped)"
        ),
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

    if args.quick:
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
