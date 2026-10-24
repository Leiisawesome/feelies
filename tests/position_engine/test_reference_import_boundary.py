"""AST guard: the reference may not import the engines it judges (D-92)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_REFERENCE = _ROOT / "tests" / "position_engine" / "reference"
_SRC = _ROOT / "src" / "feelies"
_ALLOWED_FEELIES = frozenset(
    {
        "feelies.core.events",
        "feelies.core.mark_rail",
        "feelies.core.quote_quality",
        "feelies.core.exit_policy",
        "feelies.core.identifiers",
        "feelies.bus.event_bus",
    }
)
_FORBIDDEN_PREFIXES = (
    "feelies.position",
    "feelies.portfolio",
    "feelies.kernel",
    "feelies.risk",
    "feelies.execution",
)


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def _is_stdlib(name: str) -> bool:
    top = name.split(".", 1)[0]
    if top in sys.stdlib_module_names:
        return True
    return top in {"__future__"}


def test_reference_imports_only_the_allowed_set() -> None:
    offenders: list[str] = []
    for path in sorted(_REFERENCE.rglob("*.py")):
        for name in _imported_modules(path):
            if name.startswith("feelies"):
                if name not in _ALLOWED_FEELIES or any(
                    name.startswith(prefix) for prefix in _FORBIDDEN_PREFIXES
                ):
                    offenders.append(f"{path.name}: {name}")
                continue
            if name.startswith("tests"):
                offenders.append(f"{path.name}: {name}")
                continue
            if not _is_stdlib(name):
                offenders.append(f"{path.name}: {name}")
    assert not offenders, "reference import outside the allowed set: " + "; ".join(offenders)


def test_src_does_not_import_tests() -> None:
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        for name in _imported_modules(path):
            if name == "tests" or name.startswith("tests."):
                offenders.append(f"{path.relative_to(_ROOT)}: {name}")
    assert not offenders, "src imports tests: " + "; ".join(offenders)
