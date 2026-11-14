"""Trace table completeness. Engine rows are P-22a2; rail rows are P-22a1.

Every behaviour row names a contract cite, a function that exists in the reference
package, and a test function that exists under tests/position_engine.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_TRACE = _ROOT / "tests" / "position_engine" / "reference" / "trace.md"
_REFERENCE = _ROOT / "tests" / "position_engine" / "reference"
_TEST_FILES = (
    _ROOT / "tests" / "position_engine" / "test_reference_engine.py",
    _ROOT / "tests" / "position_engine" / "test_reference_trace.py",
    _ROOT / "tests" / "position_engine" / "test_reference_rail.py",
)

# D-ids in the bound set that govern reference engine or rail behaviour.
# The complement is harness, campaign, or execution-path text and is not a
# behaviour row. The two sets partition the bound set.
_GOVERNS = frozenset(
    {
        "D-40",
        "D-41",
        "D-42",
        "D-43",
        "D-44",
        "D-45",
        "D-46",
        "D-47",
        "D-62",
        "D-76",
        "D-77",
        "D-78",
        "D-79",
        "D-80",
        "D-81",
        "D-82",
        "D-83",
        "D-84",
        "D-86",
        "D-87",
        "D-95",
        "D-96",
        "D-97",
        "D-98",
        "D-99",
        "D-100",
        "D-101",
        "D-102",
        "D-103",
        "D-104",
        "D-106",
        "D-109",
    }
)
_EXCLUDED = frozenset(
    {
        "D-85",
        "D-88",
        "D-89",
        "D-90",
        "D-91",
        "D-92",
        "D-93",
        "D-94",
        "D-105",
        "D-107",
        "D-108",
    }
)
_BOUND = frozenset(
    {f"D-{number}" for number in range(40, 48)}
    | {"D-62"}
    | {f"D-{number}" for number in range(76, 110)}
)


def _rows(text: str) -> list[list[str]]:
    found: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or all(set(cell) <= set("-: ") for cell in cells):
            continue
        if cells[0] == "Behaviour":
            continue
        found.append(cells)
    return found


def _test_ids() -> set[str]:
    found: set[str] = set()
    for path in _TEST_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                found.add(node.name)
    return found


def _resolve(spec: str) -> None:
    file_name, _, qual = spec.partition(":")
    assert file_name.endswith(".py") and qual, spec
    module = importlib.import_module(f"tests.position_engine.reference.{file_name[:-3]}")
    obj: object = module
    for part in qual.split("."):
        obj = getattr(obj, part)


def test_trace_covers_governing_decisions() -> None:
    """D-40..D-47, D-62, D-76..D-109: governing ids appear; the rest are excluded.

    D-107 and D-108 are the stage-gate order and the rung-audit rule. They do
    not govern engine or rail behaviour. D-106 and D-109 do: re-emission, and
    the END_OF_TAPE price the engine writes.
    """
    assert _GOVERNS | _EXCLUDED == _BOUND
    assert not (_GOVERNS & _EXCLUDED)
    text = _TRACE.read_text(encoding="utf-8")
    missing = sorted(name for name in _GOVERNS if name not in text)
    assert not missing, "trace.md missing governing D-id: " + ", ".join(missing)


def test_trace_rows_name_functions_and_tests() -> None:
    """Each behaviour row names an existing reference function and test id."""
    rows = _rows(_TRACE.read_text(encoding="utf-8"))
    assert rows, "trace.md has no behaviour rows"
    tests = _test_ids()
    problems: list[str] = []
    for cells in rows:
        if len(cells) != 4:
            problems.append(f"expected 4 columns, got {cells!r}")
            continue
        behaviour, _contract, function, test_id = cells
        if not re.fullmatch(r"[A-Za-z0-9_.]+:[A-Za-z0-9_.]+", function):
            problems.append(f"{behaviour}: function {function!r}")
            continue
        try:
            _resolve(function)
        except (AttributeError, ModuleNotFoundError) as exc:
            problems.append(f"{behaviour}: {function} ({exc})")
        if test_id not in tests:
            problems.append(f"{behaviour}: unknown test {test_id}")
    assert not problems, "; ".join(problems)
