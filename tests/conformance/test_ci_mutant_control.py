"""The mutant-kill job runs the kill and then the reference control per shard (D-211)."""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_KILL = "uv run python tests/position_engine/kill.py --shard ${{ matrix.shard }}"
_CONTROL = _KILL + " --control"


def test_mutant_kill_job_runs_the_control() -> None:
    workflow = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    job = jobs["mutant-kill"]
    assert isinstance(job, dict)
    strategy = job["strategy"]
    assert isinstance(strategy, dict)
    matrix = strategy["matrix"]
    assert isinstance(matrix, dict)
    assert matrix["shard"] == ["A", "B"]
    steps = job["steps"]
    assert isinstance(steps, list)
    runs: list[str] = []
    control = None
    for step in steps:
        assert isinstance(step, dict)
        run = step.get("run")
        if not isinstance(run, str):
            continue
        runs.append(run)
        if run == _CONTROL:
            control = step
    assert _KILL in runs
    assert _CONTROL in runs
    assert runs.index(_KILL) < runs.index(_CONTROL)
    assert control is not None
    assert control.get("continue-on-error") is not True
