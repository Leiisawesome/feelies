#!/usr/bin/env python3
"""Local gate in the same order as the CI check job. Stops at the first failure."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPR_PATH = ROOT / "scripts" / "ci_gate_expr.txt"


def _step(name: str, args: list[str]) -> None:
    print(f"==> {name}", flush=True)
    result = subprocess.run(args, cwd=ROOT, check=False)
    if result.returncode != 0:
        print(f"FAILED: {name}", flush=True)
        raise SystemExit(result.returncode)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    fast = "--fast" in args
    py = sys.executable
    expr = EXPR_PATH.read_text(encoding="utf-8").strip()
    _step("ruff check", [py, "-m", "ruff", "check", "src/", "tests/", "scripts/"])
    _step(
        "ruff format",
        [py, "-m", "ruff", "format", "--check", "src/", "tests/", "scripts/"],
    )
    _step("mypy", [py, "-m", "mypy", "src/feelies"])
    _step(
        "lint-imports",
        [
            py,
            "-c",
            "from importlinter.cli import lint_imports; "
            "raise SystemExit(lint_imports(no_cache=True))",
        ],
    )
    steps = "ruff check, ruff format, mypy, lint-imports"
    if not fast:
        _step("pytest", [py, "-m", "pytest", "-m", expr, "-q"])
        steps = f"{steps}, pytest"
    print(f"prepush: ok ({steps})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
