"""S6 — no fail-quiet exception handler.

Promotes ``tools.arch.gatescan.fail_quiet_handlers``.  An ``except``
whose body neither raises, returns, nor logs is a gate that silently
passed.  G20, G23, G36.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tools.arch.gatescan import fail_quiet_handlers

_ORCHESTRATOR = Path("src/feelies/kernel/orchestrator.py")
_ORCHESTRATOR_POSIX = "src/feelies/kernel/orchestrator.py"


@pytest.mark.xfail(strict=True, reason="GAP G36")
def test_no_fail_quiet_exception_handler() -> None:
    quiet = fail_quiet_handlers()
    assert quiet is not None
    assert not quiet, (
        f"{len(quiet)} fail-quiet except handler(s). First: "
        f"{quiet[0]['path']}:{quiet[0]['line']} except {quiet[0]['exc_type']}"
    )


def test_composition_position_lookup_handler_is_not_fail_quiet() -> None:
    """X7 — G20 only. The tree-wide scan above stays xfailed on G36 residue."""
    quiet = fail_quiet_handlers()
    hits = [
        h
        for h in quiet
        if h["path"].replace("\\", "/").endswith("src/feelies/composition/engine.py")
        and "current_positions" in h["body"]
    ]
    assert not hits, (
        "composition position-lookup handler is still fail-quiet: "
        f"{hits[0]['path']}:{hits[0]['line']} except {hits[0]['exc_type']}"
    )


def test_orchestrator_tick_handler_is_not_fail_quiet() -> None:
    """S-30a — the decision-path handler this step owns is no longer fail-quiet."""
    quiet = fail_quiet_handlers()
    hits = [
        h
        for h in quiet
        if h["path"].replace("\\", "/").endswith(_ORCHESTRATOR_POSIX)
    ]
    assert not hits, (
        "orchestrator still has fail-quiet except handler(s): "
        f"{hits[0]['path']}:{hits[0]['line']} except {hits[0]['exc_type']}"
    )


def test_kernel_fault_taxonomy_kinds() -> None:
    """S-30a taxonomy: one public type; later §F steps fail into Kind members."""
    from feelies.core.errors import FailureMode, FeeliesError
    from feelies.kernel.exception_taxonomy import KernelFault

    assert issubclass(KernelFault, FeeliesError)
    assert KernelFault.failure_mode is FailureMode.DEGRADE
    kinds = {member.name for member in KernelFault.Kind}
    assert kinds == {
        "TICK_PIPELINE",
        "SESSION_HALT",
        "UNIVERSE",
        "HORIZON_GRID",
        "INGRESS_ADMIT",
        "SYMBOL_IDENTITY",
    }


def test_process_tick_fails_into_kernel_fault() -> None:
    """``_process_tick`` must except KernelFault and construct it — not a comment."""
    tree = ast.parse(_ORCHESTRATOR.read_text(encoding="utf-8"))
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_process_tick"
    )
    handler_types = [
        ast.unparse(n.type)
        for n in ast.walk(fn)
        if isinstance(n, ast.ExceptHandler) and n.type is not None
    ]
    ctor = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and ast.unparse(n.func) == "KernelFault"
    ]
    assert any("KernelFault" in t for t in handler_types), (
        "_process_tick has no except KernelFault handler; "
        f"handlers={handler_types!r}"
    )
    assert ctor, "_process_tick never constructs KernelFault"
