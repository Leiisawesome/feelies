"""Pin runtime dependencies required by the core installation contract."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_DISTRIBUTION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def _core_dependency_names() -> set[str]:
    project = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]
    names: set[str] = set()
    for requirement in project["dependencies"]:
        match = _DISTRIBUTION_NAME.match(requirement)
        assert match is not None, f"invalid core dependency requirement: {requirement!r}"
        names.add(match.group().lower().replace("_", "-"))
    return names


def test_numpy_is_a_direct_core_dependency() -> None:
    """Fallback composition paths must not rely on an optional extra."""

    assert "numpy" in _core_dependency_names(), (
        "NumPy is imported by the core factor-neutralizer and turnover-optimizer "
        "fallback paths, so it must be declared in project.dependencies"
    )


def test_tzdata_is_a_windows_only_core_dependency() -> None:
    """Windows must receive IANA data without changing other platforms."""

    project = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert "tzdata>=2026.3; sys_platform == 'win32'" in project["dependencies"]


def test_pyarrow_belongs_only_to_the_portfolio_extra() -> None:
    """Retired and development extras must not duplicate portfolio tooling."""

    project = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]
    extras = project["optional-dependencies"]
    pyarrow_groups = {
        name for name, requirements in extras.items() if "pyarrow>=15.0" in requirements
    }
    assert "health" not in extras
    assert pyarrow_groups == {"portfolio"}
