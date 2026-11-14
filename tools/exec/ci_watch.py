"""CI-watch reference, sigma and threshold from a run set (D-209)."""

from __future__ import annotations

import csv
import math
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple


class Run(NamedTuple):
    created_utc: str
    tests_passed: int
    ratio: float


class Derived(NamedTuple):
    reference: float
    sigma: float
    threshold: float
    runs: int
    groups: int


def load(path: Path) -> list[Run]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        runs: list[Run] = []
        for row in reader:
            runs.append(
                Run(
                    created_utc=row["created_utc"],
                    tests_passed=int(row["tests_passed"]),
                    ratio=float(row["ratio"]),
                )
            )
        return runs


def derive(
    runs: Sequence[Run],
    window: int = 12,
    z: float = 3.0,
    per_check: int = 2,
) -> Derived:
    count = len(runs)
    if count < window:
        raise ValueError(f"need at least {window} runs, got {count}")
    grouped: dict[int, list[float]] = defaultdict(list)
    for run in runs:
        grouped[run.tests_passed].append(math.log(run.ratio))
    groups = len(grouped)
    if count - groups < 1:
        raise ValueError("degrees of freedom must be at least 1")
    total = 0.0
    for logs in grouped.values():
        mean = sum(logs) / len(logs)
        for value in logs:
            total += (value - mean) ** 2
    sigma = math.sqrt(total / (count - groups))
    newest = sorted(runs, key=lambda run: run.created_utc)[-window:]
    reference = math.exp(sum(math.log(run.ratio) for run in newest) / window)
    threshold = reference * math.exp(z * sigma / math.sqrt(per_check))
    return Derived(
        reference=reference,
        sigma=sigma,
        threshold=threshold,
        runs=count,
        groups=groups,
    )


def format_line(derived: Derived) -> str:
    return (
        f"reference {derived.reference:.2f} sigma {derived.sigma:.4f} "
        f"threshold {derived.threshold:.2f} runs {derived.runs} groups {derived.groups}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 2 and args[0] == "derive":
        print(format_line(derive(load(Path(args[1])))))
        return 0
    print("usage: ci_watch.py derive <csv>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
