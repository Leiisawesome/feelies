"""Engine events stay frozen, slotted, and free of list/dict/set fields (D-103)."""

from __future__ import annotations

import re
from dataclasses import fields

from feelies.core.events import (
    DeRiskRequirement,
    ExitTriggeredPath,
    GateDecision,
    MarkRailUpdate,
    PositionClosed,
    PositionExtreme,
    PositionFillLeg,
    PositionSnapshot,
    RailOrientation,
    SlicePositionUpdate,
)

_ENGINE_TYPES = (
    MarkRailUpdate,
    RailOrientation,
    SlicePositionUpdate,
    PositionSnapshot,
    GateDecision,
    PositionClosed,
    DeRiskRequirement,
    PositionExtreme,
    PositionFillLeg,
    ExitTriggeredPath,
)
_MUTABLE = re.compile(r"\b(list|dict|set)\b")
_RAIL_CENTS = (
    "paying_mark_cents",
    "valuation_mark_cents",
    "worst_side_mark_cents",
    "forced_exit_mark_cents",
    "dwelled_exit_mark_cents",
)


def _annotation(field_type: object) -> str:
    if isinstance(field_type, str):
        return field_type
    return getattr(field_type, "__name__", str(field_type))


def test_engine_events_are_frozen_slotted_and_tuple_only() -> None:
    mutable: list[str] = []
    for cls in _ENGINE_TYPES:
        params = cls.__dataclass_params__
        assert params.frozen, cls.__name__
        assert params.slots, cls.__name__
        for item in fields(cls):
            text = _annotation(item.type)
            if _MUTABLE.search(text):
                mutable.append(f"{cls.__name__}.{item.name}:{text}")
    assert not mutable, "mutable container fields: " + ", ".join(mutable)


def test_optional_marks_and_suppressions() -> None:
    """C1 widening. Fails while annotations lack None or suppressions is missing."""
    assert "suppressions" in GateDecision.__dataclass_fields__
    suppression = GateDecision.__dataclass_fields__["suppressions"]
    assert "tuple" in _annotation(suppression.type)
    assert suppression.default == ()
    for name in _RAIL_CENTS:
        assert "None" in _annotation(RailOrientation.__dataclass_fields__[name].type), name
    for name in (
        "move_now_cents",
        "move_worst_cents",
        "move_forced_cents",
        "best",
        "worst",
        "best_clean",
    ):
        assert "None" in _annotation(PositionSnapshot.__dataclass_fields__[name].type), name
    for name in ("best", "worst", "best_clean", "proposed_price_cents"):
        assert "None" in _annotation(PositionClosed.__dataclass_fields__[name].type), name
