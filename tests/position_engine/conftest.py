"""Stage gate for position-engine battery members (D-18)."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

_STAGE_ORDER = "ABCDE"
_DEFAULT_STAGE = Path("docs/architecture/target/position_engine/stage.txt")
_MARKER = "battery_member"


def _stage_path() -> Path:
    override = os.environ.get("FEELIES_STAGE_FILE")
    if override:
        return Path(override)
    return _DEFAULT_STAGE


def _read_stage(path: Path) -> str:
    if not path.is_file():
        raise pytest.UsageError(f"stage file not found: {path}")
    letter = path.read_text(encoding="utf-8").strip()
    if len(letter) != 1 or letter not in _STAGE_ORDER:
        raise pytest.UsageError(
            f"stage file {path} must contain exactly one letter A-E, got {letter!r}"
        )
    return letter


def _check_marker(mark: pytest.Mark) -> None:
    kwargs = mark.kwargs
    missing = [name for name in ("member", "green_from", "red_reason") if name not in kwargs]
    if missing:
        raise pytest.UsageError(f"battery_member missing required kwargs: {', '.join(missing)}")
    extra = sorted(set(kwargs) - {"member", "green_from", "red_reason"})
    if extra:
        raise pytest.UsageError(f"battery_member has unexpected kwargs: {', '.join(extra)}")
    member = kwargs["member"]
    green_from = kwargs["green_from"]
    red_reason = kwargs["red_reason"]
    if type(member) is not int or not 1 <= member <= 11:
        raise pytest.UsageError(f"battery_member member must be an int 1..11, got {member!r}")
    if green_from not in _STAGE_ORDER:
        raise pytest.UsageError(
            f"battery_member green_from must be one of A-E, got {green_from!r}"
        )
    if not isinstance(red_reason, str):
        raise pytest.UsageError(
            f"battery_member red_reason must be a string, got {type(red_reason).__name__}"
        )
    try:
        re.compile(red_reason)
    except re.error as exc:
        raise pytest.UsageError(f"battery_member red_reason is not a regex: {exc}") from exc


def pytest_configure(config: pytest.Config) -> None:
    config._feelies_stage = _read_stage(_stage_path())  # type: ignore[attr-defined]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    del config
    for item in items:
        mark = item.get_closest_marker(_MARKER)
        if mark is not None:
            _check_marker(mark)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    report = yield
    if report.when != "call":
        return report
    mark = item.get_closest_marker(_MARKER)
    if mark is None:
        return report
    stage = item.config._feelies_stage  # type: ignore[attr-defined]
    member = mark.kwargs["member"]
    green_from = mark.kwargs["green_from"]
    red_reason = mark.kwargs["red_reason"]
    if _STAGE_ORDER.index(stage) >= _STAGE_ORDER.index(green_from):
        return report
    if report.passed:
        report.outcome = "failed"
        report.longrepr = (
            f"battery member {member} passed before its stage {green_from} (current stage {stage})"
        )
        return report
    if report.failed:
        excinfo = call.excinfo
        if excinfo is not None and excinfo.errisinstance(AssertionError):
            message = str(excinfo.value)
            if re.search(red_reason, message):
                report.outcome = "passed"
                report.longrepr = None
                report.user_properties.append(("battery_red", f"{member}:{message}"))
                return report
        report.longrepr = f"battery member {member} red for the wrong reason: {report.longrepr}"
    return report
