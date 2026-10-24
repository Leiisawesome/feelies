"""The real reference-battery job selects battery_real by marker, not a file list."""

from __future__ import annotations

import shlex
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_JOB = "reference-battery-real"


def _pytest_invocations(job: dict[str, object]) -> list[str]:
    steps = job["steps"]
    assert isinstance(steps, list)
    found: list[str] = []
    for step in steps:
        assert isinstance(step, dict)
        run = step.get("run")
        if not isinstance(run, str):
            continue
        if "pytest" in shlex.split(run):
            found.append(run)
    return found


def test_real_job_selects_battery_real_by_marker() -> None:
    workflow = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    job = jobs[_JOB]
    assert isinstance(job, dict)
    invocations = _pytest_invocations(job)
    assert len(invocations) == 1
    tokens = shlex.split(invocations[0])
    assert tokens[:3] == ["uv", "run", "pytest"]
    rest = tokens[3:]
    saw_marker = False
    index = 0
    while index < len(rest):
        token = rest[index]
        if token == "-m":
            assert index + 1 < len(rest)
            assert rest[index + 1] == "battery_real"
            saw_marker = True
            index += 2
            continue
        if token == "-m=battery_real":
            saw_marker = True
            index += 1
            continue
        assert token.startswith("-"), token
        index += 1
    assert saw_marker
