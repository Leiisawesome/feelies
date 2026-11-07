"""The capture's tools fingerprint covers baseline.py alone (D-212, F-P49-1)."""

from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path

import pytest

from tools.exec import baseline

_BASELINE = Path(baseline.__file__).resolve()


def _copy_into(tmp_path: Path) -> Path:
    dest = tmp_path / "baseline.py"
    shutil.copyfile(_BASELINE, dest)
    return dest


def test_unrun_tool_leaves_fingerprint_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _copy_into(tmp_path)
    monkeypatch.setattr(baseline, "EXEC_TOOLS", tmp_path)
    before = baseline.tools_fingerprint()
    (tmp_path / "other_tool.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert baseline.tools_fingerprint() == before


def test_editing_baseline_moves_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest = _copy_into(tmp_path)
    monkeypatch.setattr(baseline, "EXEC_TOOLS", tmp_path)
    before = baseline.tools_fingerprint()
    dest.write_bytes(dest.read_bytes() + b"# edited\n")
    assert baseline.tools_fingerprint()["sha256"] != before["sha256"]


def test_capture_tool_imports_only_the_standard_library() -> None:
    tree = ast.parse(_BASELINE.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module is not None, ast.dump(node)
            roots.add(node.module.split(".")[0])
    assert roots, "no imports found"
    assert sorted(roots - set(sys.stdlib_module_names)) == []
