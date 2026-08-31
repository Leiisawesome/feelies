"""G31 — engine 5 is the sole writer of universe membership.

Universe definition had no single owner: PlatformConfig.symbols, the
PORTFOLIO module.universe union in bootstrap, and
UniverseSynchronizer._universe_sorted were competing membership sources.
C2 remains accounting conservation; this file is the G31 scan.

Writes of the membership store (``_universe_sorted``,
``_universe_frozenset``) may only appear in
``src/feelies/alpha/registry.py``. ``KernelFault(kind=UNIVERSE)`` must be
constructed — a taxonomy member with no caller is an unused seam.
"""

from __future__ import annotations

import ast
from pathlib import Path

from feelies.kernel.exception_taxonomy import KernelFault

_SRC = Path(__file__).resolve().parents[2] / "src" / "feelies"
_REPO = _SRC.parents[1]
_AUTHORITY = "src/feelies/alpha/registry.py"

_STORE_ATTRS = frozenset({"_universe_sorted", "_universe_frozenset"})
_MUTATORS = frozenset({"add", "discard", "clear", "pop", "update", "remove"})


def _rel(path: Path) -> str:
    return path.relative_to(_REPO).as_posix()


def _is_setter(fn: ast.FunctionDef) -> bool:
    for dec in fn.decorator_list:
        if isinstance(dec, ast.Attribute) and dec.attr == "setter":
            return True
    return False


def _store_attr(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr in _STORE_ATTRS:
        return node.attr
    if isinstance(node, ast.Subscript):
        return _store_attr(node.value)
    return None


def _universe_store_write_sites() -> list[tuple[str, int, str]]:
    """Production mutations of the universe-membership store."""
    sites: list[tuple[str, int, str]] = []
    for path in sorted(_SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = _rel(path)
        setter_ranges: list[tuple[int, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and _is_setter(node):
                setter_ranges.append((node.lineno, node.end_lineno or node.lineno))

        def in_setter(lineno: int) -> bool:
            return any(start <= lineno <= end for start, end in setter_ranges)

        for node in ast.walk(tree):
            lineno = getattr(node, "lineno", None)
            if lineno is None or in_setter(lineno):
                continue
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    attr = _store_attr(target)
                    if attr is not None:
                        sites.append((rel, node.lineno, f"assign {attr}"))
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                attr = _store_attr(node.target)
                if attr is not None:
                    sites.append((rel, node.lineno, f"ann-assign {attr}"))
            elif isinstance(node, ast.AugAssign):
                attr = _store_attr(node.target)
                if attr is not None:
                    sites.append((rel, node.lineno, f"aug-assign {attr}"))
            elif isinstance(node, ast.Call):
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr not in _MUTATORS:
                    continue
                attr = _store_attr(func.value)
                if attr is not None:
                    sites.append((rel, node.lineno, f"{attr}.{func.attr}"))
    return sites


def _universe_kind_constructions() -> list[str]:
    hits: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = _rel(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if ast.unparse(node.func).split(".")[-1] != "KernelFault":
                continue
            for kw in node.keywords:
                if kw.arg != "kind":
                    continue
                if "UNIVERSE" in ast.unparse(kw.value):
                    hits.append(f"{rel}:{node.lineno}")
    return hits


def test_g31_engine_5_is_sole_universe_membership_writer() -> None:
    """Membership-store mutations outside engine 5's registry module fail G31."""
    sites = _universe_store_write_sites()
    assert sites, "G31 scan found no universe-store writes — the guard would be vacuous"
    illegal = [f"{path}:{line} {kind}" for path, line, kind in sites if path != _AUTHORITY]
    assert not illegal, (
        "universe membership has a writer outside engine 5 "
        f"({_AUTHORITY}). First: {illegal[0]}"
    )


def test_g31_universe_kind_is_constructed() -> None:
    """UNIVERSE must be raised, not left as an unused Kind member."""
    hits = _universe_kind_constructions()
    assert hits, (
        "KernelFault(kind=UNIVERSE) is never constructed in src/feelies; "
        "S-30a left the Kind unused for this step to fail into"
    )
    assert any(h.startswith(_AUTHORITY) for h in hits), (
        f"UNIVERSE is constructed, but not in the engine-5 authority: {hits}"
    )


def test_g31_missing_snapshot_raises_universe() -> None:
    from feelies.alpha.registry import _require_universe

    try:
        _require_universe(None)
    except KernelFault as fault:
        assert fault.kind is KernelFault.Kind.UNIVERSE
    else:
        raise AssertionError("missing universe snapshot must raise KernelFault(UNIVERSE)")


def test_g31_conflict_raises_universe() -> None:
    from feelies.alpha.registry import _publish_universe

    try:
        _publish_universe(("AAPL",), peer=("MSFT",))
    except KernelFault as fault:
        assert fault.kind is KernelFault.Kind.UNIVERSE
    else:
        raise AssertionError("disagreeing universe membership must raise KernelFault(UNIVERSE)")


def test_g31_empty_raises_universe() -> None:
    from feelies.alpha.registry import _publish_universe

    try:
        _publish_universe(())
    except KernelFault as fault:
        assert fault.kind is KernelFault.Kind.UNIVERSE
    else:
        raise AssertionError("empty universe must raise KernelFault(UNIVERSE)")
