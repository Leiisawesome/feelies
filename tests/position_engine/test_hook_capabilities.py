"""D-192 hook cases. Each case is a fresh pytest process with its own stage file."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_CONFTEST = Path("tests/position_engine/conftest.py")

_MARK = (
    "import pytest\n"
    "@pytest.mark.battery_member(member=2, green_from='{green}', red_reason='^NONVACUOUS')\n"
    "def test_member():\n"
    "    {body}\n"
)


def _run(tmp_path: Path, stage: str, body: str, *, green: str) -> subprocess.CompletedProcess[str]:
    stage_file = tmp_path / "stage.txt"
    stage_file.write_text(stage, encoding="utf-8")
    (tmp_path / "conftest.py").write_text(_CONFTEST.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "test_case.py").write_text(
        _MARK.format(green=green, body=body),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["FEELIES_STAGE_FILE"] = str(stage_file)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("FEELIES_ENGINE", None)
    env.pop("FEELIES_RAIL", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "-q", "-p", "no:cacheprovider"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _out(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout + proc.stderr


def test_h1_pass_before_green_from_is_hook_error(tmp_path: Path) -> None:
    proc = _run(tmp_path, "A", "assert True", green="C")
    text = _out(proc)
    assert proc.returncode == 1, text
    assert "hook error" in text
    assert "passed before its stage" in text


def test_h2_non_assertion_before_green_from_is_hook_error(tmp_path: Path) -> None:
    proc = _run(tmp_path, "A", "raise ValueError('boom')", green="C")
    text = _out(proc)
    assert proc.returncode == 1, text
    assert "hook error" in text


def test_h3_untagged_assertion_before_green_from_is_hook_error(tmp_path: Path) -> None:
    proc = _run(tmp_path, "A", "raise AssertionError('other')", green="C")
    text = _out(proc)
    assert proc.returncode == 1, text
    assert "hook error" in text


def test_h4_tag_at_or_before_current_stage_is_hook_error(tmp_path: Path) -> None:
    """birth_touch delivers at D. Current D is not later than D."""
    proc = _run(tmp_path, "D", "raise AssertionError('CAP:birth_touch: stale')", green="E")
    text = _out(proc)
    assert proc.returncode == 1, text
    assert "hook error" in text


def test_h5_later_capability_is_accepted(tmp_path: Path) -> None:
    """favorable_fire delivers at E, which is later than A."""
    proc = _run(tmp_path, "A", "raise AssertionError('CAP:favorable_fire: not fire')", green="E")
    assert proc.returncode == 0, _out(proc)


def test_h6_nonvacuous_before_green_from_is_accepted(tmp_path: Path) -> None:
    proc = _run(tmp_path, "A", "raise AssertionError('NONVACUOUS: none')", green="C")
    assert proc.returncode == 0, _out(proc)


def test_h7_failure_at_green_from_stays_a_failure(tmp_path: Path) -> None:
    proc = _run(tmp_path, "E", "raise AssertionError('NONVACUOUS: none')", green="E")
    text = _out(proc)
    assert proc.returncode == 1, text
    assert "hook error" not in text
    assert "NONVACUOUS: none" in text


def test_h8_tag_later_than_green_from_is_hook_error(tmp_path: Path) -> None:
    """favorable_fire delivers at E, later than green_from C."""
    proc = _run(
        tmp_path,
        "B",
        "raise AssertionError('CAP:favorable_fire: ...')",
        green="C",
    )
    text = _out(proc)
    assert proc.returncode == 1, text
    assert "hook error" in text
    assert "D-192" in text


def test_h9_tag_at_green_from_is_accepted(tmp_path: Path) -> None:
    """dwell_window delivers at C, which is this node's green_from."""
    proc = _run(
        tmp_path,
        "B",
        "raise AssertionError('CAP:dwell_window: ...')",
        green="C",
    )
    assert proc.returncode == 0, _out(proc)
