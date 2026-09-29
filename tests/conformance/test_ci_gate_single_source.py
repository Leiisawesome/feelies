"""The check job and the local pre-push read one marker expression."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_EXPR = "not functional and not paper_rth and not battery_real"


def test_ci_gate_is_single_source() -> None:
    expr_path = _ROOT / "scripts" / "ci_gate_expr.txt"
    prepush = _ROOT / "scripts" / "prepush.py"
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert expr_path.is_file()
    expr = expr_path.read_text(encoding="utf-8").strip()
    assert expr == _EXPR
    assert "scripts/ci_gate_expr.txt" in ci
    assert _EXPR not in ci
    assert "scripts/prepush.py --fast" in ci
    assert "ci_gate_expr.txt" in prepush.read_text(encoding="utf-8")
