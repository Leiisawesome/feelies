#!/usr/bin/env python3
"""Report whether every required symbol-day file is in the event cache.

Stdlib only. This script does not import ingest code and does not open a
network connection. A missing file is a non-zero exit. The workflow, not
this script, decides whether a fetch is allowed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.]{0,15}\Z")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def _parse_symbol_day(spec: str) -> tuple[str, str]:
    symbol, sep, day = spec.partition("/")
    if sep != "/" or _SYMBOL.fullmatch(symbol) is None or _DAY.fullmatch(day) is None:
        raise ValueError(f"symbol-day must be SYMBOL/YYYY-MM-DD, got {spec!r}")
    return symbol, day


def missing_files(cache_dir: Path, symbol_days: list[str]) -> list[Path]:
    """Paths that are not present as regular files, in argument order."""
    missing: list[Path] = []
    for spec in symbol_days:
        symbol, day = _parse_symbol_day(spec)
        path = cache_dir / symbol / f"{day}.jsonl.gz"
        if not path.is_file():
            missing.append(path)
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail closed when an event-cache day is absent.")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("symbol_days", nargs="+", help="SYMBOL/YYYY-MM-DD")
    args = parser.parse_args(argv)
    try:
        missing = missing_files(args.cache_dir, list(args.symbol_days))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not missing:
        print("complete")
        return 0
    for path in missing:
        print(path)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
