"""Event-cache guard and the workflow that calls it.

T1–T4 exercise scripts/ci_event_cache_guard.py. T5–T9 parse ci.yml.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "ci_event_cache_guard.py"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_DAYS = ("APP/2026-03-25", "APP/2026-03-26")
_ENFORCED = ("check", "parity-oracle", "reference-battery-real")
_NETWORK_ROOTS = frozenset(
    {
        "socket",
        "ssl",
        "urllib",
        "http",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
        "massive",
        "ftplib",
        "smtplib",
        "xmlrpc",
    }
)
_INGEST_PREFIXES = (
    "feelies.ingestion",
    "feelies.harness",
    "feelies.broker",
)


def _run(cache_dir: Path, *specs: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--cache-dir", str(cache_dir), *specs],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _touch(cache_dir: Path, spec: str) -> None:
    symbol, day = spec.split("/", 1)
    path = cache_dir / symbol / f"{day}.jsonl.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def test_complete_cache_exits_zero(tmp_path: Path) -> None:
    for spec in _DAYS:
        _touch(tmp_path, spec)
    result = _run(tmp_path, *_DAYS)
    assert result.returncode == 0
    assert "complete" in result.stdout


def test_one_missing_file_is_named(tmp_path: Path) -> None:
    _touch(tmp_path, "APP/2026-03-26")
    result = _run(tmp_path, *_DAYS)
    assert result.returncode != 0
    assert "2026-03-25.jsonl.gz" in result.stdout
    assert "2026-03-26.jsonl.gz" not in result.stdout


def test_empty_dir_names_every_file(tmp_path: Path) -> None:
    result = _run(tmp_path, *_DAYS)
    assert result.returncode != 0
    for spec in _DAYS:
        day = spec.split("/", 1)[1]
        assert f"{day}.jsonl.gz" in result.stdout


def _imported_modules(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.append(node.module)
    return found


def test_guard_imports_no_network_or_ingest() -> None:
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    for name in _imported_modules(tree):
        root = name.split(".", 1)[0]
        assert root not in _NETWORK_ROOTS, name
        assert not name.startswith(_INGEST_PREFIXES), name


def _workflow() -> dict[str, object]:
    loaded = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _jobs(workflow: dict[str, object]) -> dict[str, dict[str, object]]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _steps(job: dict[str, object]) -> list[dict[str, object]]:
    steps = job["steps"]
    assert isinstance(steps, list)
    return steps


def test_check_tests_step_runs_with_n4() -> None:
    job = _jobs(_workflow())["check"]
    tests = [step for step in _steps(job) if step.get("name") == "Tests"]
    assert len(tests) == 1
    run = tests[0].get("run")
    assert isinstance(run, str)
    assert "-n 4" in run


def _references_vendor_secret(step: dict[str, object]) -> bool:
    run = step.get("run")
    if isinstance(run, str) and "MASSIVE_API_KEY" in run:
        return True
    env = step.get("env")
    if isinstance(env, dict):
        for key, value in env.items():
            if "MASSIVE_API_KEY" in str(key) or "MASSIVE_API_KEY" in str(value):
                return True
    return False


def _fetch_gated(step: dict[str, object]) -> bool:
    cond = step.get("if")
    if not isinstance(cond, str):
        return False
    text = " ".join(cond.split())
    has_event = (
        "github.event_name == 'workflow_dispatch'" in text
        or 'github.event_name == "workflow_dispatch"' in text
    )
    has_input = "inputs.allow_fetch" in text and "true" in text
    return has_event and has_input


def test_vendor_secret_steps_require_authorised_dispatch() -> None:
    found = False
    for job in _jobs(_workflow()).values():
        for step in _steps(job):
            if not _references_vendor_secret(step):
                continue
            found = True
            assert _fetch_gated(step), step.get("name")
    assert found


def test_allow_fetch_defaults_false() -> None:
    workflow = _workflow()
    trigger = workflow.get("on", workflow.get(True))
    assert isinstance(trigger, dict)
    dispatch = trigger.get("workflow_dispatch")
    assert isinstance(dispatch, dict)
    inputs = dispatch.get("inputs")
    assert isinstance(inputs, dict)
    spec = inputs.get("allow_fetch")
    assert isinstance(spec, dict)
    assert spec.get("type") == "boolean"
    assert spec.get("default") is False


def _uses(step: dict[str, object]) -> str:
    uses = step.get("uses")
    return uses if isinstance(uses, str) else ""


def _is_event_cache(step: dict[str, object]) -> bool:
    body = step.get("with")
    if not isinstance(body, dict):
        return False
    path = body.get("path")
    return isinstance(path, str) and ".feelies/cache" in path


def _is_ingest(step: dict[str, object]) -> bool:
    run = step.get("run")
    return isinstance(run, str) and "ingest_data" in run


def test_event_cache_restore_only_one_save_after_ingest() -> None:
    for job_id, job in _jobs(_workflow()).items():
        steps = _steps(job)
        saves: list[int] = []
        ingest_at: int | None = None
        for index, step in enumerate(steps):
            uses = _uses(step)
            if uses.startswith("actions/cache@"):
                raise AssertionError(f"{job_id} uses the combined cache action")
            if _is_event_cache(step):
                assert uses.startswith("actions/cache/restore@") or uses.startswith(
                    "actions/cache/save@"
                ), uses
            if uses.startswith("actions/cache/save@"):
                saves.append(index)
            if _is_ingest(step):
                assert ingest_at is None
                ingest_at = index
        assert len(saves) <= 1, job_id
        if saves:
            assert ingest_at is not None
            assert saves[0] > ingest_at


def _guard_indexes(steps: list[dict[str, object]]) -> list[int]:
    found: list[int] = []
    for index, step in enumerate(steps):
        run = step.get("run")
        if isinstance(run, str) and "ci_event_cache_guard.py" in run:
            found.append(index)
    return found


def _pytest_indexes(steps: list[dict[str, object]]) -> list[int]:
    found: list[int] = []
    for index, step in enumerate(steps):
        run = step.get("run")
        if isinstance(run, str) and "pytest" in run:
            found.append(index)
    return found


def test_guard_precedes_tests_and_failure_fails_the_job() -> None:
    jobs = _jobs(_workflow())
    for job_id in _ENFORCED:
        steps = _steps(jobs[job_id])
        guards = _guard_indexes(steps)
        pytest_at = _pytest_indexes(steps)
        assert guards, job_id
        assert pytest_at, job_id
        assert min(guards) < min(pytest_at), job_id
        for index in guards:
            assert steps[index].get("continue-on-error") is not True
