"""Keep the full ``src/feelies`` tree clean under ``mypy --strict``.

One test runs mypy over the source tree. The other rejects per-module
``ignore_errors`` overrides for ``feelies.*``. The module is marked slow because
a cold mypy run takes several seconds.
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
        "repository layout described in docs/three_layer_architecture.md"
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


def _load_mypy_section() -> dict[str, Any]:
    raw = _PYPROJECT.read_bytes()
    data: dict[str, Any] = tomllib.loads(raw.decode("utf-8"))
    tool: dict[str, Any] = data.get("tool", {})
    section: dict[str, Any] = tool.get("mypy", {})
    return section


def _override_module_names(entry: dict[str, Any]) -> list[str]:
    modules = entry.get("module")
    if isinstance(modules, str):
        return [modules]
    if isinstance(modules, list):
        return [m for m in modules if isinstance(m, str)]
    return []


# Per-module overrides may not weaken any boolean enabled by strict mode.
# ``implicit_reexport`` weakens strictness when True and is checked separately.
_STRICT_BOOL_FALSE_FLAGS: tuple[str, ...] = (
    "disallow_any_generics",
    "disallow_subclassing_any",
    "disallow_untyped_calls",
    "disallow_untyped_defs",
    "disallow_incomplete_defs",
    "check_untyped_defs",
    "disallow_untyped_decorators",
    "warn_redundant_casts",
    "warn_unused_ignores",
    "warn_return_any",
    "strict_equality",
    "strict_bytes",
    "extra_checks",
)


# Report every per-module setting that weakens strict mode.
def _strict_weakening_reasons(entry: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if entry.get("ignore_errors"):
        reasons.append("ignore_errors=true")
    # Per-module ``strict = false`` disables the entire strict bundle in
    # one step — stronger than toggling any single flag below.
    if entry.get("strict") is False:
        reasons.append("strict=false")
    # Booleans that strict mode sets to ``true``; flipping any to ``false``
    # re-admits the corresponding class of un-checked code.
    for flag in _STRICT_BOOL_FALSE_FLAGS:
        if entry.get(flag) is False:
            reasons.append(f"{flag}=false")
    # ``implicit_reexport`` is mypy's config key for ``--no-implicit-reexport``
    # (a --strict flag); its *weakening* direction is True, the inverse of
    # the pattern above.
    if entry.get("implicit_reexport") is True:
        reasons.append("implicit_reexport=true")
    if entry.get("disable_error_code"):
        reasons.append(f"disable_error_code={entry['disable_error_code']!r}")
    if entry.get("follow_imports") in {"skip", "silent"}:
        reasons.append(f"follow_imports={entry['follow_imports']!r}")
    return reasons


def test_strict_mode_enabled_in_pyproject() -> None:
    """Lock the linchpin: ``[tool.mypy] strict = true`` must be set.

    ``test_mypy_strict_clean_on_src_feelies`` runs
    ``mypy --no-incremental src/feelies`` with **no** ``--strict`` on the
    CLI — strictness comes entirely from this key.  Without this assertion
    a contributor can flip ``strict = false`` (or delete it) and *both*
    scope-lock tests stay green while the entire strict regime evaporates.
    ``python_version`` is pinned too so the checked dialect cannot drift
    silently.
    """
    mypy_section = _load_mypy_section()
    assert mypy_section.get("strict") is True, (
        "pyproject.toml [tool.mypy] must set ``strict = true`` — it is the "
        "sole source of strictness for test_mypy_strict_clean_on_src_feelies "
        f"(found strict={mypy_section.get('strict')!r})."
    )
    assert isinstance(mypy_section.get("python_version"), str), (
        "pyproject.toml [tool.mypy] must pin ``python_version`` so the "
        f"checked dialect is explicit (found {mypy_section.get('python_version')!r})."
    )


def test_no_strict_overrides_in_pyproject() -> None:
    """Lock the gap-Z invariant: no ``feelies.*`` strict-mode overrides.

    A contributor who silences a new strict-mode failure by adding a
    ``[[tool.mypy.overrides]] module = "feelies.foo"`` block that sets
    ``ignore_errors = true`` — **or** any other strictness knob
    (``disable_error_code``, ``disallow_untyped_defs = false``,
    ``check_untyped_defs = false``, ``warn_return_any = false``,
    ``follow_imports = "skip"``, …) — fails this test even if mypy is
    happy.  The only exemption shape allowed is for **third-party** modules
    that lack a ``py.typed`` marker (e.g. ``"massive"``, ``"cvxpy"``);
    those are typed ``ignore_missing_imports`` (which is *not* a strictness
    knob) and target the third-party module — never ``feelies.*``.
    """
    mypy_section = _load_mypy_section()
    overrides = mypy_section.get("overrides", [])

    offenders: list[str] = []
    for entry in overrides:
        reasons = _strict_weakening_reasons(entry)
        if not reasons:
            continue
        for name in _override_module_names(entry):
            if name.startswith("feelies"):
                offenders.append(f"{name} ({', '.join(reasons)})")

    assert offenders == [], (
        "gap-Z invariant violation: pyproject.toml weakened strict mode "
        "for the following ``feelies.*`` modules: "
        f"{offenders}.  Tighten the modules to pass ``mypy --strict`` "
        "instead of overriding.  See workstream gap-Z notes in "
        "docs/acceptance/v02_v03_matrix.md."
    )
