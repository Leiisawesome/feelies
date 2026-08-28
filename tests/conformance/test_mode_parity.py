"""H3 — backend substitution is composition-root construction, nothing else.

Inv-9 / CORE §C.4: ``OperatingMode`` selects an ``ExecutionBackend`` inside
``bootstrap._create_backend``. In-engine modules must not also branch on
``OperatingMode``; that is G26. H1 (fill-eligibility parity) stays in
``tests/execution/test_router_fill_timing_parity.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tools.arch.coupling import mode_branches

_ROOT = Path(__file__).resolve().parents[2]
_BOOTSTRAP = _ROOT / "src" / "feelies" / "bootstrap.py"
_SEAM_PREFIXES = ("src/feelies/execution/", "src/feelies/broker/")
_COMPOSITION_ROOT = "src/feelies/bootstrap.py"
_BUILDERS = frozenset(
    {
        "build_backtest_backend",
        "build_paper_backend",
        "build_passive_limit_backend",
    }
)


def _create_backend_fn() -> ast.FunctionDef:
    tree = ast.parse(_BOOTSTRAP.read_text(encoding="utf-8"), filename=str(_BOOTSTRAP))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_create_backend":
            return node
    raise AssertionError("bootstrap._create_backend not found")


def test_h3_backend_substitution_is_composition_root_construction_only() -> None:
    """Swapping backends changes construction at the composition root only."""
    fn = _create_backend_fn()
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    called = names | attrs
    missing = _BUILDERS - called
    assert not missing, (
        f"_create_backend does not select {sorted(missing)} — not the "
        "composition-root backend seam"
    )
    tests = [ast.unparse(n.test) for n in ast.walk(fn) if isinstance(n, ast.If)]
    assert any("OperatingMode" in t for t in tests), (
        "_create_backend does not branch on OperatingMode — backend identity "
        "is not selected there"
    )

    hits = [h for h in mode_branches() if h["kind"] == "operating_mode"]
    assert hits, "scanner found no OperatingMode branch — H3 is vacuous"
    outside = [
        h
        for h in hits
        if h["path"] != _COMPOSITION_ROOT and not h["path"].startswith(_SEAM_PREFIXES)
    ]
    assert not outside, (
        f"{len(outside)} in-engine OperatingMode branch(es); backend "
        "substitution must change construction at the composition root and "
        f"nothing else. First: {outside[0]['path']}:{outside[0]['line']} "
        f"{outside[0]['test']}"
    )
