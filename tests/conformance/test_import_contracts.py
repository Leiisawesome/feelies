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

_SRC_FEELIES = Path(__file__).resolve().parents[2] / "src" / "feelies"
_WALK_EXCLUDE = frozenset({"kernel", "bus", "core", "cli"})

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
        ("feelies.kernel", "feelies.risk"),
        ("feelies.kernel", "feelies.execution"),
        ("feelies.kernel", "feelies.storage"),
    }
)

# Residual engine→kernel imports. Equality, not a subset:
# a fifteenth pair fails immediately. Five-tier and S2 both
# permit this direction; the pin is the remaining detector.
_KERNEL_IMPORT_RESIDUALS = frozenset(
    {
        ("feelies.ingestion.massive_ws", "feelies.kernel.exception_taxonomy"),
        ("feelies.sensors.horizon_scheduler", "feelies.kernel.exception_taxonomy"),
        ("feelies.alpha.registry", "feelies.kernel.exception_taxonomy"),
        ("feelies.risk.engine", "feelies.kernel.macro"),
        ("feelies.risk.forced_exit_clamp", "feelies.kernel.forced_exit_reasons"),
        ("feelies.risk.forced_exit_clamp", "feelies.kernel.order_states"),
        ("feelies.execution.order_policy", "feelies.kernel.macro"),
        ("feelies.execution.order_policy", "feelies.kernel.micro"),
        (
            "feelies.forensics.gate_close_attribution",
            "feelies.kernel.forced_exit_reasons",
        ),
        ("feelies.harness.backtest_runner", "feelies.kernel.orchestrator"),
        ("feelies.harness.backtest_runner", "feelies.kernel.signal_order_trace"),
        ("feelies.harness.backtest_runner", "feelies.kernel.macro"),
        ("feelies.harness.backtest_report", "feelies.kernel.macro"),
        ("feelies.harness.backtest_report", "feelies.kernel.orchestrator"),
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


def _module_from_path(path: Path) -> str:
    rel = path.relative_to(_SRC_FEELIES)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return "feelies." + ".".join(parts)


def _engine_kernel_import_pairs() -> frozenset[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for pkg_dir in sorted(p for p in _SRC_FEELIES.iterdir() if p.is_dir()):
        if pkg_dir.name in _WALK_EXCLUDE or pkg_dir.name == "__pycache__":
            continue
        for path in pkg_dir.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            mod = _module_from_path(path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.name
                        if name == "feelies.kernel" or name.startswith(
                            "feelies.kernel."
                        ):
                            pairs.add((mod, name))
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = node.module
                    if imported == "feelies.kernel" or imported.startswith(
                        "feelies.kernel."
                    ):
                        pairs.add((mod, imported))
    return frozenset(pairs)


def test_engine_kernel_imports_equal_pin() -> None:
    pairs = _engine_kernel_import_pairs()
    assert pairs == _KERNEL_IMPORT_RESIDUALS, (
        f"unexpected {sorted(pairs - _KERNEL_IMPORT_RESIDUALS)}; "
        f"missing {sorted(_KERNEL_IMPORT_RESIDUALS - pairs)}"
    )
