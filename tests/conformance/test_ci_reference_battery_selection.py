"""The synthetic reference-battery step covers member and reference tests."""

from __future__ import annotations

import shlex
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_JOB = "reference-battery"
_PATTERNS = (
    "tests/position_engine/test_battery_m*.py",
    "tests/position_engine/test_reference_*.py",
)


def _expand(pattern: str) -> set[str]:
    return {
        match.relative_to(_ROOT).as_posix() for match in _ROOT.glob(pattern) if match.is_file()
    }


def test_reference_battery_covers_members_and_reference_tests() -> None:
    workflow = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    job = jobs[_JOB]
    assert isinstance(job, dict)
    steps = job["steps"]
    assert isinstance(steps, list)
    saw_step = False
    saw_marker = False
    covered: set[str] = set()
    for step in steps:
        assert isinstance(step, dict)
        run = step.get("run")
        if not isinstance(run, str):
            continue
        tokens = shlex.split(run)
        if "pytest" not in tokens:
            continue
        saw_step = True
        rest = tokens[tokens.index("pytest") + 1 :]
        index = 0
        while index < len(rest):
            token = rest[index]
            if token == "-m":
                assert index + 1 < len(rest)
                marker = rest[index + 1]
                assert marker == "not battery_real"
                saw_marker = True
                index += 2
                continue
            if token.startswith("-"):
                index += 1
                continue
            covered.update(_expand(token))
            index += 1
    assert saw_step
    assert saw_marker
    expected: set[str] = set()
    for pattern in _PATTERNS:
        expected.update(_expand(pattern))
    missing = sorted(expected - covered)
    assert not missing, missing
