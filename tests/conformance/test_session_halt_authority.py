"""G33 — engine 1 is the sole writer of halt/session tradeability.

Session/halt tradeability had no single owner: writer functions lived in
``ingestion/data_integrity.py`` while the store, config copy, reset, and
``_in_halt_blackout`` stayed on Orchestrator, and ``MassiveNormalizer`` kept
a second ``_halt_on_codes``. C3 remains ingress conservation; this file is
the G33 scan.

Writes of the halt-tradeability store (halted-symbol set, post-resume
blackout map, halt on/off codes, blackout duration) may only appear in
``src/feelies/ingestion/data_integrity.py``. Orchestrator ``@*.setter``
methods that rebind attributes onto that engine-1 object are wiring for
existing tests, not a second tape writer. ``KernelFault(kind=SESSION_HALT)``
must be constructed — a taxonomy member with no caller is an unused seam.
"""

from __future__ import annotations

import ast
from pathlib import Path

from feelies.core.clock import SimulatedClock
from feelies.ingestion.data_integrity import (
    DataHealth,
    _HaltTradeability,
    _data_health_blocks_trading,
)
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.kernel.exception_taxonomy import KernelFault

_SRC = Path(__file__).resolve().parents[2] / "src" / "feelies"
_REPO = _SRC.parents[1]
_AUTHORITY = "src/feelies/ingestion/data_integrity.py"

_STORE_ATTRS = frozenset(
    {
        "_halted_symbols",
        "_halt_blackout_until_ns",
        "_halt_on_codes",
        "_halt_off_codes",
        "_halt_blackout_ns",
        "halted_symbols",
        "blackout_until_ns",
        "on_codes",
        "off_codes",
        "blackout_ns",
    }
)
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


def _halt_store_write_sites() -> list[tuple[str, int, str]]:
    """Production mutations of the halt-tradeability store."""
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


def _session_halt_constructions() -> list[str]:
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
                if "SESSION_HALT" in ast.unparse(kw.value):
                    hits.append(f"{rel}:{node.lineno}")
    return hits


def test_g33_engine_1_is_sole_halt_tradeability_writer() -> None:
    """Halt-store mutations outside engine 1's data_integrity module fail G33."""
    sites = _halt_store_write_sites()
    assert sites, "G33 scan found no halt-store writes — the guard would be vacuous"
    illegal = [f"{path}:{line} {kind}" for path, line, kind in sites if path != _AUTHORITY]
    assert not illegal, (
        "halt/session tradeability has a writer outside engine 1 "
        f"({_AUTHORITY}). First: {illegal[0]}"
    )


def test_g33_session_halt_kind_is_constructed() -> None:
    """SESSION_HALT must be raised, not left as an unused Kind member."""
    hits = _session_halt_constructions()
    assert hits, (
        "KernelFault(kind=SESSION_HALT) is never constructed in src/feelies; "
        "S-30a left the Kind unused for this step to fail into"
    )
    assert any(h.startswith(_AUTHORITY) for h in hits), (
        f"SESSION_HALT is constructed, but not in the engine-1 authority: {hits}"
    )


def test_g33_missing_authority_raises_session_halt() -> None:
    from feelies.ingestion.data_integrity import _require_halt_authority

    class _Missing:
        pass

    try:
        _require_halt_authority(_Missing())
    except KernelFault as fault:
        assert fault.kind is KernelFault.Kind.SESSION_HALT
    else:
        raise AssertionError("missing halt authority must raise KernelFault(SESSION_HALT)")


def _is_datahealth_halted(node: ast.AST) -> bool:
    text = ast.unparse(node)
    return text == "DataHealth.HALTED" or text.endswith(".DataHealth.HALTED")


def _health_halted_transition_sites() -> list[tuple[str, int]]:
    """Production ``transition(DataHealth.HALTED)`` calls."""
    sites: list[tuple[str, int]] = []
    for path in sorted(_SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = _rel(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "transition":
                continue
            for arg in node.args:
                if _is_datahealth_halted(arg):
                    sites.append((rel, node.lineno))
            for kw in node.keywords:
                if kw.arg == "trigger":
                    continue
                if _is_datahealth_halted(kw.value):
                    sites.append((rel, node.lineno))
    return sites


def test_g33_health_halted_transition_goes_through_the_store() -> None:
    """A DataHealth.HALTED trading write outside engine 1 fails G33."""
    sites = _health_halted_transition_sites()
    assert sites, "G33 scan found no DataHealth.HALTED transitions — the guard would be vacuous"
    illegal = [f"{path}:{line}" for path, line in sites if path != _AUTHORITY]
    assert not illegal, (
        "health HALTED transition must go through the engine-1 halt store "
        f"({_AUTHORITY}). First: {illegal[0]}"
    )


def test_g33_health_halted_xor_empty_store_raises_session_halt() -> None:
    """Bound trade-feed HALTED with an empty store is a trading-decision fault."""
    clock = SimulatedClock(start_ns=10_000)
    authority = _HaltTradeability()
    normalizer = MassiveNormalizer(clock, halt_tradeability=authority)
    sm = normalizer._ensure_health_machine("AAPL", MassiveNormalizer._FEED_TRADE)
    sm.transition(DataHealth.HALTED, trigger="test_split")

    class _Orch:
        _halt_tradeability = authority
        _normalizer = normalizer
        _config = None

    try:
        _data_health_blocks_trading(_Orch(), "AAPL", "cid")
    except KernelFault as fault:
        assert fault.kind is KernelFault.Kind.SESSION_HALT
    else:
        raise AssertionError("health HALTED xor empty store must raise KernelFault(SESSION_HALT)")


def test_g33_store_membership_xor_healthy_feed_raises_session_halt() -> None:
    """Store membership with a bound HEALTHY trade-feed is a trading-decision fault."""
    clock = SimulatedClock(start_ns=10_000)
    authority = _HaltTradeability()
    authority.halted_symbols.add("AAPL")
    normalizer = MassiveNormalizer(clock, halt_tradeability=authority)
    normalizer._ensure_health_machine("AAPL", MassiveNormalizer._FEED_TRADE)

    class _Orch:
        _halt_tradeability = authority
        _normalizer = normalizer
        _config = None

    try:
        _data_health_blocks_trading(_Orch(), "AAPL", "cid")
    except KernelFault as fault:
        assert fault.kind is KernelFault.Kind.SESSION_HALT
    else:
        raise AssertionError(
            "store membership xor HEALTHY trade-feed must raise KernelFault(SESSION_HALT)"
        )


def test_g33_codebook_conflict_raises_session_halt() -> None:
    from feelies.ingestion.data_integrity import _HaltTradeability

    authority = _HaltTradeability()
    try:
        authority.configure(
            frozenset({1}),
            frozenset({2}),
            0,
            peer_on=frozenset({9}),
            peer_off=frozenset({2}),
        )
    except KernelFault as fault:
        assert fault.kind is KernelFault.Kind.SESSION_HALT
    else:
        raise AssertionError("disagreeing halt codebooks must raise KernelFault(SESSION_HALT)")
