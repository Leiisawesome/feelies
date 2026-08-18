"""S2 — import-linter contracts: five tiers, twelve engines independent.

Does not trust ``lint-imports``'s exit code.  The CLI has been observed to
exit 0 with contracts broken; this test parses
``Contracts: N kept, M broken`` and the per-contract KEPT/BROKEN lines.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SUMMARY = re.compile(r"Contracts:\s*(\d+)\s*kept,\s*(\d+)\s*broken")
_STATUS = re.compile(r"^(Five import tiers|Twelve engine module sets)\s+(KEPT|BROKEN)\s*$", re.M)


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


@pytest.mark.xfail(strict=True, reason="GAP G16")
def test_five_import_tiers() -> None:
    out, _kept, _broken, statuses = run_import_linter()
    assert "Five import tiers" in statuses, out
    assert statuses["Five import tiers"] == "KEPT", out


@pytest.mark.xfail(strict=True, reason="GAP G40")
def test_twelve_engine_independence() -> None:
    out, _kept, _broken, statuses = run_import_linter()
    assert "Twelve engine module sets" in statuses, out
    assert statuses["Twelve engine module sets"] == "KEPT", out
