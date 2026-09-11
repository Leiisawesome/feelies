"""S2 — import-linter contracts: five tiers, twelve engines independent.

Does not trust ``lint-imports``'s exit code.  The CLI has been observed to
exit 0 with contracts broken; this test parses
``Contracts: N kept, M broken`` and the per-contract KEPT/BROKEN lines.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

_FILL_RECONCILIATION = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "feelies"
    / "portfolio"
    / "fill_reconciliation.py"
)

_SUMMARY = re.compile(r"Contracts:\s*(\d+)\s*kept,\s*(\d+)\s*broken")
_STATUS = re.compile(r"^(Five import tiers|Twelve engine module sets)\s+(KEPT|BROKEN)\s*$", re.M)
_LAYER_PAIR = re.compile(
    r"^(feelies\.[a-z0-9_]+) is not allowed to import (feelies\.[a-z0-9_]+):",
    re.M,
)

# Residual Five-import-tiers breaks: kernel→engine dispatch.
# Equality, not a subset:
# a twelfth pair fails immediately. G40's close does not
# require this set to change.
_TIER_RESIDUALS = frozenset(
    {
        ("feelies.kernel", "feelies.ingestion"),
        ("feelies.kernel", "feelies.portfolio"),
        ("feelies.kernel", "feelies.risk"),
        ("feelies.kernel", "feelies.monitoring"),
        ("feelies.kernel", "feelies.execution"),
        ("feelies.kernel", "feelies.storage"),
    }
)


def _lint_imports_cmd() -> list[str]:
    bindir = Path(sys.executable).parent
    for name in ("lint-imports.exe", "lint-imports"):
        candidate = bindir / name
        if candidate.exists():
            return [str(candidate), "--no-cache"]
    found = shutil.which("lint-imports")
    if found:
        return [found, "--no-cache"]
    raise FileNotFoundError("lint-imports is not installed; add import-linter to the dev extra")


def run_import_linter() -> tuple[str, int, int, dict[str, str]]:
    proc = subprocess.run(
        _lint_imports_cmd(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    match = _SUMMARY.search(out)
    assert match is not None, (
        "lint-imports produced no 'Contracts: N kept, M broken' line:\n" + out
    )
    kept, broken = int(match.group(1)), int(match.group(2))
    statuses = {name: status for name, status in _STATUS.findall(out)}
    return out, kept, broken, statuses


def _broken_layer_pairs(out: str, heading: str, stop: str) -> frozenset[tuple[str, str]]:
    broken_at = out.find("Broken contracts")
    section = out[broken_at:] if broken_at >= 0 else out
    start = section.find(heading)
    if start < 0:
        return frozenset()
    rest = section[start:]
    end = rest.find(stop)
    if end >= 0:
        rest = rest[:end]
    return frozenset((a, b) for a, b in _LAYER_PAIR.findall(rest))


def test_five_import_tiers() -> None:
    out, _kept, _broken, statuses = run_import_linter()
    assert "Five import tiers" in statuses, out
    pairs = _broken_layer_pairs(out, "Five import tiers", "Twelve engine module sets")
    assert pairs == _TIER_RESIDUALS, (
        f"unexpected {sorted(pairs - _TIER_RESIDUALS)}; "
        f"missing {sorted(_TIER_RESIDUALS - pairs)}\n{out}"
    )


def test_twelve_engine_independence() -> None:
    out, _kept, _broken, statuses = run_import_linter()
    assert "Twelve engine module sets" in statuses, out
    assert statuses["Twelve engine module sets"] == "KEPT", out


def test_fill_reconciliation_does_not_import_orchestrator() -> None:
    """Engine 7 must not import the kernel module that imports it."""
    tree = ast.parse(
        _FILL_RECONCILIATION.read_text(encoding="utf-8"),
        filename=str(_FILL_RECONCILIATION),
    )
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if mod == "feelies.kernel.orchestrator" or mod.startswith(
                "feelies.kernel.orchestrator."
            ):
                hits.append(f"{_FILL_RECONCILIATION.as_posix()}:{node.lineno} import {mod}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == "feelies.kernel.orchestrator" or name.startswith(
                    "feelies.kernel.orchestrator."
                ):
                    hits.append(
                        f"{_FILL_RECONCILIATION.as_posix()}:{node.lineno} import {name}"
                    )
    assert not hits, (
        "fill_reconciliation imports kernel.orchestrator:\n" + "\n".join(hits)
    )
