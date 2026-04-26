"""Mechanical proof that §18.3 #3 is closed — ``mypy --strict`` clean.

Closes the ``mypy --strict`` half of §18.3 of
``design_docs/three_layer_architecture.md`` by running ``mypy`` as a
subprocess against the entire ``src/feelies`` tree and asserting a
zero exit code.

Strict-mode coverage is governed by the ``[tool.mypy]`` block in
``pyproject.toml``:

* ``strict = true`` is the platform default and applies to **every**
  module under ``src/feelies/`` — there are **no** per-module
  ``ignore_errors = true`` overrides.  Workstream **gap-Z** closed the
  historical 8-module override block by tightening the legacy modules
  in place (``bootstrap``, ``execution.passive_limit_router``,
  ``ingestion.massive_*``, ``kernel.orchestrator``,
  ``storage.disk_event_cache``, ``storage.memory_trade_journal``).

This test is the load-bearing artefact behind the matrix row, in two
parts:

1. ``test_mypy_strict_clean_on_src_feelies`` — runs ``mypy`` on the
   full source tree and asserts a zero exit code.  A new strict-mode
   error in any module fails the test loudly.
2. ``test_no_strict_overrides_in_pyproject`` — parses
   ``pyproject.toml`` and asserts that no ``[[tool.mypy.overrides]]``
   block sets ``ignore_errors = true`` on any ``feelies.*`` module.
   This locks the gap-Z invariant: a contributor who silences a new
   strict-mode failure by re-introducing an override fails the test
   even if mypy itself is happy.

Marked ``slow`` because cold-cache mypy on the full source tree is
several seconds — well beyond the per-test budget of the default
``pytest tests/`` invocation but still trivial in the CI slow lane.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src" / "feelies"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


pytestmark = pytest.mark.slow


def test_mypy_strict_clean_on_src_feelies() -> None:
    assert _SRC.exists(), (
        f"src/feelies not found at {_SRC}; this test is anchored to the "
        "repository layout described in design_docs/three_layer_architecture.md"
    )

    proc = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-incremental", str(_SRC)],
        cwd=str(_REPO_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    if proc.returncode != 0:
        pytest.fail(
            "mypy --strict failed on src/feelies — §18.3 #3 acceptance "
            "criterion no longer satisfied.  Annotate the new errors "
            "away — DO NOT extend the [[tool.mypy.overrides]] block in "
            "pyproject.toml; workstream gap-Z deleted that block "
            "permanently and the companion test "
            "``test_no_strict_overrides_in_pyproject`` enforces "
            "no-overrides going forward.\n\n"
            f"STDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}"
        )


def test_no_strict_overrides_in_pyproject() -> None:
    """Lock the gap-Z invariant: no ``feelies.*`` strict-mode overrides.

    A contributor who silences a new strict-mode failure by adding a
    ``[[tool.mypy.overrides]] module = "feelies.foo" ignore_errors =
    true`` block fails this test even if mypy is happy.  The only
    exemption shape allowed is for **third-party** modules that lack a
    ``py.typed`` marker (e.g. ``"massive"``); those are typed
    ``ignore_missing_imports``, not ``ignore_errors``, and target the
    third-party module — never ``feelies.*``.
    """
    raw = _PYPROJECT.read_bytes()
    data: dict[str, Any] = tomllib.loads(raw.decode("utf-8"))

    tool = data.get("tool", {})
    mypy_section = tool.get("mypy", {})
    overrides = mypy_section.get("overrides", [])

    offenders: list[str] = []
    for entry in overrides:
        if not entry.get("ignore_errors"):
            continue
        modules = entry.get("module")
        names: list[str] = (
            [modules] if isinstance(modules, str)
            else list(modules) if isinstance(modules, list)
            else []
        )
        for name in names:
            if isinstance(name, str) and name.startswith("feelies"):
                offenders.append(name)

    assert offenders == [], (
        "gap-Z invariant violation: pyproject.toml re-introduced "
        "``ignore_errors = true`` for the following ``feelies.*`` "
        f"modules: {offenders}.  Tighten the modules to pass "
        "``mypy --strict`` instead.  See workstream gap-Z notes in "
        "docs/acceptance/v02_v03_matrix.md."
    )
