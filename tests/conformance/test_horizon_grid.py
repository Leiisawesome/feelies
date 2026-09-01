"""Engine 2 is the sole writer of the horizon-grid store.

Three private sorted-horizon views were not replicas of one set:
``HorizonScheduler._horizons_sorted`` held ``PlatformConfig.horizons_seconds``,
``UniverseSynchronizer._signal_horizons_sorted`` held the PORTFOLIO YAML
union plus upstream SIGNAL horizons, and bootstrap
``_composition_signal_horizons`` produced that union. This file is the
scan. No Phase 5 gap ID.

Writes of ``_horizons_sorted`` may only appear inside ``HorizonGrid`` in
``src/feelies/sensors/horizon_scheduler.py``. ``_signal_horizons_sorted``
and ``_composition_signal_horizons`` must not exist.
``KernelFault(kind=HORIZON_GRID)`` must be constructed — a taxonomy
member with no caller is an unused seam.
"""

from __future__ import annotations

import ast
from pathlib import Path

from feelies.kernel.exception_taxonomy import KernelFault

_SRC = Path(__file__).resolve().parents[2] / "src" / "feelies"
_REPO = _SRC.parents[1]
_AUTHORITY = "src/feelies/sensors/horizon_scheduler.py"

_STORE_ATTRS = frozenset({"_horizons_sorted", "_signal_horizons_sorted"})
_MUTATORS = frozenset({"add", "discard", "clear", "pop", "update", "remove"})


def _rel(path: Path) -> str:
    return path.relative_to(_REPO).as_posix()


def _horizon_grid_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "HorizonGrid":
            ranges.append((node.lineno, node.end_lineno or node.lineno))
    return ranges


def _in_horizon_grid(lineno: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= lineno <= end for start, end in ranges)


def _store_attr(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr in _STORE_ATTRS:
        return node.attr
    if isinstance(node, ast.Subscript):
        return _store_attr(node.value)
    return None


def _horizon_store_write_sites() -> list[tuple[str, int, str]]:
    """Production mutations of the sorted-horizon store, plus the named bootstrap view."""
    sites: list[tuple[str, int, str]] = []
    for path in sorted(_SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = _rel(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_composition_signal_horizons":
                sites.append((rel, node.lineno, "def _composition_signal_horizons"))
            lineno = getattr(node, "lineno", None)
            if lineno is None:
                continue
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    attr = _store_attr(target)
                    if attr is not None:
                        sites.append((rel, lineno, f"assign {attr}"))
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                attr = _store_attr(node.target)
                if attr is not None:
                    sites.append((rel, lineno, f"ann-assign {attr}"))
            elif isinstance(node, ast.AugAssign):
                attr = _store_attr(node.target)
                if attr is not None:
                    sites.append((rel, lineno, f"aug-assign {attr}"))
            elif isinstance(node, ast.Call):
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr not in _MUTATORS:
                    continue
                attr = _store_attr(func.value)
                if attr is not None:
                    sites.append((rel, lineno, f"{attr}.{func.attr}"))
    return sites


def _horizon_kind_constructions() -> list[str]:
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
                if "HORIZON_GRID" in ast.unparse(kw.value):
                    hits.append(f"{rel}:{node.lineno}")
    return hits


def test_engine_2_is_sole_horizon_grid_writer() -> None:
    """Sorted-horizon store mutations outside HorizonGrid fail the scan."""
    sites = _horizon_store_write_sites()
    assert sites, "horizon-grid scan found no store writes — the guard would be vacuous"
    authority = _REPO / _AUTHORITY
    grid_ranges = _horizon_grid_ranges(
        ast.parse(authority.read_text(encoding="utf-8"), filename=_AUTHORITY)
    )
    illegal = []
    for path, line, kind in sites:
        if kind == "def _composition_signal_horizons" or "_signal_horizons_sorted" in kind:
            illegal.append(f"{path}:{line} {kind}")
            continue
        if path != _AUTHORITY or not _in_horizon_grid(line, grid_ranges):
            illegal.append(f"{path}:{line} {kind}")
    assert not illegal, (
        f"horizon grid has a writer outside HorizonGrid ({_AUTHORITY}). First: {illegal[0]}"
    )


def test_horizon_grid_kind_is_constructed() -> None:
    """HORIZON_GRID must be raised, not left as an unused Kind member."""
    hits = _horizon_kind_constructions()
    assert hits, (
        "KernelFault(kind=HORIZON_GRID) is never constructed in src/feelies; "
        "S-30a left the Kind unused for this step to fail into"
    )
    assert any(h.startswith(_AUTHORITY) for h in hits), (
        f"HORIZON_GRID is constructed, but not in the engine-2 authority: {hits}"
    )


def test_missing_grid_raises_horizon_grid() -> None:
    from feelies.sensors.horizon_scheduler import _require_horizon_grid

    try:
        _require_horizon_grid(None)
    except KernelFault as fault:
        assert fault.kind is KernelFault.Kind.HORIZON_GRID
    else:
        raise AssertionError("missing horizon grid must raise KernelFault(HORIZON_GRID)")


def test_conflict_raises_horizon_grid() -> None:
    from feelies.sensors.horizon_scheduler import _publish_horizon_grid

    try:
        _publish_horizon_grid((30,), peer=(120,))
    except KernelFault as fault:
        assert fault.kind is KernelFault.Kind.HORIZON_GRID
    else:
        raise AssertionError("disagreeing horizon membership must raise KernelFault(HORIZON_GRID)")
