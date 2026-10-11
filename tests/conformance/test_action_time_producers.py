"""Ratchet for action-time constructors. A new non-clock stamp fails.

D-1 classified every constructor of a T1 action-time type. E-1 moved the
risk-wrapper sites onto the publication clock. Everything D-1 left non-clock
is named here. Line numbers are not part of the key, so a reformat does not
open or close the list.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"

_ACTION = frozenset(
    {
        "OrderRequest",
        "RiskVerdict",
        "OrderAck",
        "PositionUpdate",
        "SlicePositionUpdate",
        "PositionClosed",
        "RegimeState",
        "StateTransition",
        "MetricEvent",
        "Alert",
    }
)

# Expression texts D-1 classified as the publication clock, including locals
# that hold that clock. A text that also appears on a known non-clock site
# still approves the sites D-1 accepted; the known site stays on the list.
_APPROVED = frozenset(
    {
        "self._clock.now_ns()",
        "clock.now_ns()",
        "_ib_clock.now_ns()",
        "published_ts",
        "ack_ts",
        "fill_ts",
        "now_ns",
        "timestamp_ns",
        "ack.timestamp_ns",
        "record.timestamp_ns",
        "event.timestamp_ns",
        "order.timestamp_ns",
    }
)

_CLOCK_CALLS = frozenset(
    {
        "self._clock.now_ns()",
        "clock.now_ns()",
        "_ib_clock.now_ns()",
    }
)

# Remaining D-1 FIX sites after E-1. (path from repo root, function, type).
_KNOWN_NONCLOCK = frozenset(
    {
        ("src/feelies/broker/ib/router.py", "_fill_to_ack", "OrderAck"),
        ("src/feelies/execution/sized_intent_legs.py", "_mint", "OrderRequest"),
        ("src/feelies/risk/sized_intent_orders.py", "_mint", "OrderRequest"),
        ("src/feelies/sensors/registry.py", "_emit_reading_metrics", "MetricEvent"),
        ("src/feelies/sensors/registry.py", "_emit_nonfinite_metric", "MetricEvent"),
    }
)


def _enclosing(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current: ast.AST | None = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
            return current.name
    return "<module>"


def _sites(src_root: Path) -> list[tuple[str, str, str, str]]:
    found: list[tuple[str, str, str, str]] = []
    for path in sorted(src_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        rel = path.relative_to(_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            else:
                continue
            if name not in _ACTION:
                continue
            expr = None
            for keyword in node.keywords:
                if keyword.arg == "timestamp_ns":
                    expr = ast.get_source_segment(text, keyword.value)
            assert expr is not None, (rel, node.lineno, name)
            found.append((rel, _enclosing(node, parents), name, expr))
    return found


def test_action_time_constructors_are_approved_or_known() -> None:
    """Every action-time constructor is an approved clock expression or a known site.

    Each known site must still exist and must still carry a non-clock stamp,
    so fixing one requires deleting its row and adding one fails the scan.
    """
    sites = _sites(_SRC)
    seen: set[tuple[str, str, str]] = set()
    for rel, func, name, expr in sites:
        key = (rel, func, name)
        if key in _KNOWN_NONCLOCK:
            seen.add(key)
            continue
        assert expr in _APPROVED, (rel, func, name, expr)
    assert seen == _KNOWN_NONCLOCK
    by_key: dict[tuple[str, str, str], list[str]] = {}
    for rel, func, name, expr in sites:
        by_key.setdefault((rel, func, name), []).append(expr)
    for key in _KNOWN_NONCLOCK:
        exprs = by_key[key]
        assert any(expr not in _CLOCK_CALLS for expr in exprs), key
