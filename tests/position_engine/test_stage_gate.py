"""Stage-gate hook self-tests. Each case is a fresh pytest process."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_CONFTEST = Path("tests/position_engine/conftest.py")


def _run(tmp_path: Path, stage: str, source: str) -> subprocess.CompletedProcess[str]:
    stage_file = tmp_path / "stage.txt"
    stage_file.write_text(stage, encoding="utf-8")
    if _CONFTEST.is_file():
        (tmp_path / "conftest.py").write_text(
            _CONFTEST.read_text(encoding="utf-8"), encoding="utf-8"
        )
    (tmp_path / "test_case.py").write_text(source, encoding="utf-8")
    env = os.environ.copy()
    env["FEELIES_STAGE_FILE"] = str(stage_file)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
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


def test_h1_expected_red_is_passed(tmp_path: Path) -> None:
    proc = _run(
        tmp_path,
        "A",
        "import pytest\n"
        "@pytest.mark.battery_member(member=1, green_from='B', red_reason='^NONVACUOUS')\n"
        "def test_member():\n"
        "    raise AssertionError('NONVACUOUS: none')\n",
    )
    assert proc.returncode == 0, _out(proc)


def test_h2_pass_before_stage_fails(tmp_path: Path) -> None:
    proc = _run(
        tmp_path,
        "A",
        "import pytest\n"
        "@pytest.mark.battery_member(member=1, green_from='B', red_reason='^NONVACUOUS')\n"
        "def test_member():\n"
        "    assert True\n",
    )
    assert proc.returncode == 1, _out(proc)
    assert "passed before its stage" in _out(proc)


def test_h3_value_error_is_wrong_reason(tmp_path: Path) -> None:
    proc = _run(
        tmp_path,
        "A",
        "import pytest\n"
        "@pytest.mark.battery_member(member=1, green_from='B', red_reason='^NONVACUOUS')\n"
        "def test_member():\n"
        "    raise ValueError('boom')\n",
    )
    assert proc.returncode == 1, _out(proc)
    assert "red for the wrong reason" in _out(proc)


def test_h4_unmatched_assertion_is_wrong_reason(tmp_path: Path) -> None:
    proc = _run(
        tmp_path,
        "A",
        "import pytest\n"
        "@pytest.mark.battery_member(member=1, green_from='B', red_reason='^NONVACUOUS')\n"
        "def test_member():\n"
        "    raise AssertionError('other')\n",
    )
    assert proc.returncode == 1, _out(proc)
    assert "red for the wrong reason" in _out(proc)


def test_h5_at_stage_assertion_stays_failed(tmp_path: Path) -> None:
    proc = _run(
        tmp_path,
        "B",
        "import pytest\n"
        "@pytest.mark.battery_member(member=1, green_from='B', red_reason='^NONVACUOUS')\n"
        "def test_member():\n"
        "    raise AssertionError('NONVACUOUS: none')\n",
    )
    text = _out(proc)
    assert proc.returncode == 1, text
    assert "red for the wrong reason" not in text
    assert "passed before its stage" not in text


def test_h6_at_stage_pass_stays_passed(tmp_path: Path) -> None:
    proc = _run(
        tmp_path,
        "B",
        "import pytest\n"
        "@pytest.mark.battery_member(member=1, green_from='B', red_reason='^NONVACUOUS')\n"
        "def test_member():\n"
        "    assert True\n",
    )
    assert proc.returncode == 0, _out(proc)


def test_h7_unmarked_failure_untouched(tmp_path: Path) -> None:
    proc = _run(
        tmp_path,
        "A",
        "def test_plain():\n    raise AssertionError('plain failure')\n",
    )
    text = _out(proc)
    assert proc.returncode == 1, text
    assert "red for the wrong reason" not in text
    assert "passed before its stage" not in text
    assert "plain failure" in text


def test_h8_bad_stage_letter(tmp_path: Path) -> None:
    proc = _run(tmp_path, "Z", "def test_plain():\n    assert True\n")
    text = _out(proc)
    assert proc.returncode != 0, text
    assert "stage.txt" in text or "stage file" in text


def test_h9_bad_green_from(tmp_path: Path) -> None:
    proc = _run(
        tmp_path,
        "A",
        "import pytest\n"
        "@pytest.mark.battery_member(member=1, green_from='Q', red_reason='^NONVACUOUS')\n"
        "def test_member():\n"
        "    assert True\n",
    )
    text = _out(proc)
    assert proc.returncode != 0, text
    assert "UsageError" in text or "green_from" in text
