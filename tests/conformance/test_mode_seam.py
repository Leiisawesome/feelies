"""S7 — mode branches only at the composition root and the declared seam.

Promotes ``tools.arch.coupling.mode_branches``.  Composition-root
backend construction (``bootstrap.py::_create_backend``) is legitimate;
in-engine ``OperatingMode`` branches are G26.  The root is an explicit
allowlist, not a hard-coded ``{execution, broker}`` set.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tools.arch.coupling import mode_branches

_ROOT = Path(__file__).resolve().parents[2]
_SEAM_PREFIXES = ("src/feelies/execution/", "src/feelies/broker/")
_COMPOSITION_ROOT = "src/feelies/bootstrap.py"
_COMPOSITION_ROOT_FN = "_create_backend"


def _innermost_function(path: str, line: int) -> str | None:
    source = (_ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=path)
    owning: tuple[int, int, str] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = node.end_lineno or node.lineno
        if node.lineno <= line <= end:
            span = end - node.lineno
            if owning is None or span < (owning[1] - owning[0]):
                owning = (node.lineno, end, node.name)
    return None if owning is None else owning[2]


def _allowed(path: str, line: int) -> bool:
    if path.startswith(_SEAM_PREFIXES):
        return True
    return (
        path == _COMPOSITION_ROOT
        and _innermost_function(path, line) == _COMPOSITION_ROOT_FN
    )


def test_mode_branches_only_at_composition_root() -> None:
    hits = [h for h in mode_branches() if h["kind"] == "operating_mode"]
    assert hits, "scanner found no OperatingMode branch — the seam check is vacuous"
    outside = [h for h in hits if not _allowed(h["path"], h["line"])]
    assert not outside, (
        f"{len(outside)} OperatingMode branch(es) outside "
        f"{_COMPOSITION_ROOT}::{_COMPOSITION_ROOT_FN} and mode seam: "
        + "; ".join(f"{h['path']}:{h['line']} {h['test']}" for h in outside)
    )
