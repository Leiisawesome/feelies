"""Unit tests for the kill runner. Throwaway mutants stay in this file (F5)."""

from __future__ import annotations

import ast
import importlib
import os
import sys
import time
from pathlib import Path

from tests.position_engine.kill import classify, main
from tests.position_engine.mutants import REGISTRY, Mutant
from tests.position_engine.reference.engine import PositionEngine

_ROOT = Path(__file__).resolve().parents[2]
_CATCHER = "tests/position_engine/test_kill_runner.py::test_fixture_catcher"
_FIXTURES = frozenset({"NoopEngine", "CrashEngine", "SleepEngine"})
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


class NoopEngine(PositionEngine):
    """Throwaway. A subclass with no change."""


class CrashEngine(PositionEngine):
    """Throwaway. Raising in __init__ is a crash, not a kill."""

    def __init__(self, bus: object, sequence_generator: object) -> None:
        raise RuntimeError("fresh child exited")


class SleepEngine(PositionEngine):
    """Throwaway. Sleeps until the runner's timeout."""

    def __init__(self, bus: object, sequence_generator: object) -> None:
        super().__init__(bus, sequence_generator)  # type: ignore[arg-type]
        while True:
            time.sleep(1)


def test_fixture_catcher() -> None:
    """Construct the throwaway seam. The reference and the control pass."""
    dotted = os.environ.get("FEELIES_ENGINE", "")
    name = dotted.rsplit(".", 1)[-1]
    if name not in _FIXTURES:
        return
    module_name, _, cls_name = dotted.rpartition(".")
    cls = getattr(importlib.import_module(module_name), cls_name)
    cls(None, None)


def _spec(bid: str, cls_name: str) -> Mutant:
    return Mutant(
        bid,
        "engine",
        f"tests.position_engine.test_kill_runner.{cls_name}",
        (_CATCHER,),
        "",
        "A",
    )


def test_classify_case_kinds() -> None:
    assert classify("boom", crashed=True) == "CRASH"
    assert classify("fresh child exited 1", crashed=False) == "CRASH"
    assert classify("PRECONDITION: tape", crashed=False) == "PRECONDITION"
    assert classify("NONVACUOUS: no close", crashed=False) == "NONVACUOUS"
    assert classify("M11: proposed 1 != 2", crashed=False) == "PROPERTY"
    old = "m3_deadline grouped cells 199 < 200"
    new = "NONVACUOUS: m3_deadline grouped cells 199 < 200"
    assert classify(old, crashed=False) == "PROPERTY"
    assert classify(new, crashed=False) == "NONVACUOUS"


def test_noop_mutant_survives(capsys: object) -> None:
    code = main(["--timeout", "60"], specs=[_spec("B0", "NoopEngine")])
    assert code != 0
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "B0 SURVIVED" in out


def test_init_raise_is_crash_not_killed(capsys: object) -> None:
    code = main(["--timeout", "60"], specs=[_spec("B0", "CrashEngine")])
    assert code != 0
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "KILLED" not in out
    assert "CRASH" in out


def test_sleep_mutant_times_out(capsys: object) -> None:
    code = main(["--timeout", "5"], specs=[_spec("B0", "SleepEngine")])
    assert code != 0
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "TIMEOUT" in out
    assert "KILLED" not in out


def test_control_reference_has_zero_failures(capsys: object) -> None:
    code = main(["--control", "--timeout", "60"], specs=[_spec("B0", "NoopEngine")])
    assert code == 0
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "CONTROL 0 failures" in out


def test_registry_names_eleven_mutants() -> None:
    assert list(REGISTRY) == [f"B{index}" for index in range(1, 12)]


def test_mutants_import_only_reference_and_stdlib() -> None:
    path = _ROOT / "tests" / "position_engine" / "mutants.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            if name == "__future__" or name.split(".", 1)[0] in sys.stdlib_module_names:
                continue
            if name in _ALLOWED_FEELIES:
                continue
            if name == "tests.position_engine.reference" or name.startswith(
                "tests.position_engine.reference."
            ):
                continue
            offenders.append(name)
    assert not offenders, offenders
