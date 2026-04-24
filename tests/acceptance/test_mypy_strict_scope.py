"""Mechanical proof that §18.3 #3 is closed — ``mypy --strict`` clean.

Closes the ``mypy --strict`` half of §18.3 of
``design_docs/three_layer_architecture.md`` by running ``mypy`` as a
subprocess against the entire ``src/feelies`` tree and asserting a
zero exit code.

Strict-mode coverage is governed by the ``[tool.mypy]`` block in
``pyproject.toml``:

* ``strict = true`` is the platform default, applied to every module
  introduced or rewritten by Phases 1–5.1 (v0.2 + v0.3 — sensors,
  composition, regime, layered alpha loader, signal-layer module,
  portfolio-layer module, layer validator, signal regime gate,
  horizon aggregator + signal engine, etc.).
* A small ``[[tool.mypy.overrides]] ignore_errors = true`` block
  scopes-out a few pre-Phase-1.1 legacy modules whose strict-mode
  errors are pre-existing structural debt unrelated to the v0.2/v0.3
  contract.  These are tracked under the future "type-tightening"
  workstream (gap-Z in the matrix) and MUST NOT grow.

This test is the load-bearing artefact behind the matrix row.  If a
contributor adds a new non-strict module to the override list without
updating ``docs/acceptance/v02_v03_matrix.md``, the matrix's audit
discipline is undermined; if they remove the override entirely (good)
the test still passes; if they introduce a new strict-mode error in a
post-refactor module, the test fails loudly.

Marked ``slow`` because cold-cache mypy on the full source tree is
several seconds — well beyond the per-test budget of the default
``pytest tests/`` invocation but still trivial in the CI slow lane.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src" / "feelies"


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
            "criterion no longer satisfied.  Either annotate the new "
            "errors away (preferred) or, if the failure is in genuinely "
            "legacy code, extend the [[tool.mypy.overrides]] block in "
            "pyproject.toml AND add a row to gap-Z in "
            "docs/acceptance/v02_v03_matrix.md.\n\n"
            f"STDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}"
        )
