"""T-7 seam and helper tests."""

from __future__ import annotations

import inspect
import json

import pytest

from tests.position_engine import mutants
from tests.position_engine.reference.engine import PositionEngine
from tests.position_engine.scenarios import Record, Records
from tests.position_engine.test_scenarios import ProbeEngine


def test_selectable_engines_accept_session_bounds() -> None:
    classes: list[type] = [PositionEngine, ProbeEngine]
    for cls in vars(mutants).values():
        if (
            isinstance(cls, type)
            and cls.__module__ == mutants.__name__
            and issubclass(cls, PositionEngine)
            and "__init__" in cls.__dict__
        ):
            classes.append(cls)
    assert classes
    for cls in classes:
        parameter = inspect.signature(cls.__init__).parameters["session_bounds"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is None


def test_require_adverse_level() -> None:
    from tests.position_engine.scenarios import require_adverse_level

    def holding(level: int) -> Records:
        body = json.dumps(
            {"drawn_level_ticks": level, "gate": "ADVERSE"},
            separators=(",", ":"),
            sort_keys=True,
        )
        return Records([Record(None, "GateDecision", body)], {}, ())

    with pytest.raises(AssertionError, match=r"^CAP:gate_fire: "):
        require_adverse_level(holding(0))
    require_adverse_level(holding(7))
