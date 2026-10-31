"""No production code values a position at the mid, dotted or via getattr."""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path("src/feelies")
_MID_NAMES = frozenset({"latest_mark", "reference_mid"})
_ALLOW = frozenset(
    {
        "_resolve_mark",
        "resolve_mark",
        "total_exposure",
        "latest_mark",
        "reference_mid",
        "_position_lookup",
        "_record_portfolio_net_shadow",
    }
)


def _hits(tree: ast.AST, path: str) -> list[str]:
    found: list[str] = []

    def walk(node: ast.AST, enclosing: str | None) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            enclosing = node.name
        if isinstance(node, ast.Call) and _is_mid_read(node) and enclosing not in _ALLOW:
            found.append(f"{path}:{node.lineno}")
        for child in ast.iter_child_nodes(node):
            walk(child, enclosing)

    walk(tree, None)
    return found


def _is_mid_read(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in _MID_NAMES:
        return True
    return (
        isinstance(func, ast.Name)
        and func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value in _MID_NAMES
    )


def _scan_tree(root: Path) -> list[str]:
    hits: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.as_posix()
        hits.extend(_hits(tree, rel))
    return hits


def test_production_mid_readers_are_allowlisted() -> None:
    hits = _scan_tree(_SRC)
    assert hits == [], "mid reader outside the allowlist: " + ", ".join(hits)


def test_getattr_form_outside_the_allowlist_is_flagged() -> None:
    tree = ast.parse('def _value_it(book):\n    return getattr(book, "reference_mid")\n')
    hits = _hits(tree, "<synthetic>")
    assert hits == ["<synthetic>:2"]
