"""S9 — every numeric field on the Event contract declares a unit.

G46: CORE §C.8 — a field whose unit is not declared does not exist.
No event type declared a unit for any field (Phase 6 §8.1).

S9 asserts closure: a numeric field with no declared unit fails.
``UNIT_UNDETERMINED`` is not a missing unit and is not a resolved one.
A sibling assertion stays xfailed while any field still carries that token.
Units live in dataclass ``Field.metadata['unit']`` so they do not add a
field to ``__dataclass_fields__`` (``event_schema_hash`` walks name and type).
"""

from __future__ import annotations

import pytest

import feelies.core.events as events_mod
from feelies.core.events import UNIT_UNDETERMINED, Event, declared_unit

_NUMERIC_LEAVES = frozenset({"int", "float", "Decimal"})


def _concrete_event_classes() -> dict[str, type[Event]]:
    found: dict[str, type[Event]] = {}
    for name, obj in vars(events_mod).items():
        if isinstance(obj, type) and issubclass(obj, Event) and obj is not Event:
            found[name] = obj
    return found


def _annotation_str(field_type: object) -> str:
    if isinstance(field_type, str):
        return field_type
    return getattr(field_type, "__name__", str(field_type))


def _dict_value_annotation(ann: str) -> str:
    s = ann.strip()
    if not s.startswith("dict["):
        return s
    inner = s[5:]
    if inner.endswith("]"):
        inner = inner[:-1]
    depth = 0
    for i, ch in enumerate(inner):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "," and depth == 0:
            return inner[i + 1 :].strip()
    return s


def _union_parts(ann: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in ann:
        if ch == "[":
            depth += 1
            buf.append(ch)
        elif ch == "]":
            depth -= 1
            buf.append(ch)
        elif ch == "|" and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return parts


def _tuple_inner(ann: str) -> str | None:
    s = ann.strip()
    if not s.startswith("tuple["):
        return None
    inner = s[6:]
    if inner.endswith("]"):
        inner = inner[:-1]
    if ", ..." in inner:
        return inner.split(", ...", 1)[0].strip()
    return inner.strip()


def _is_numeric_annotation(ann: str) -> bool:
    ann = _dict_value_annotation(ann)
    leaves: list[str] = []
    for part in _union_parts(ann):
        if part == "None":
            continue
        inner = _tuple_inner(part)
        leaf = inner if inner is not None else part
        if leaf.startswith("dict["):
            return False
        leaves.append(leaf)
    if not leaves:
        return False
    return all(leaf in _NUMERIC_LEAVES for leaf in leaves)


def test_s9_numeric_fields_declare_a_unit() -> None:
    """Closure: every numeric field on Event and the 21 subclasses has a unit."""
    concrete = _concrete_event_classes()
    assert concrete, "no Event subclasses found"

    undeclared: list[str] = []
    envelope = set(Event.__dataclass_fields__)
    for name, field_obj in Event.__dataclass_fields__.items():
        if not _is_numeric_annotation(_annotation_str(field_obj.type)):
            continue
        unit = declared_unit(Event, name)
        if not isinstance(unit, str) or not unit:
            undeclared.append(f"Event.{name}")

    for cls_name, cls in sorted(concrete.items()):
        for name, field_obj in cls.__dataclass_fields__.items():
            if name in envelope:
                continue
            if not _is_numeric_annotation(_annotation_str(field_obj.type)):
                continue
            unit = declared_unit(cls, name)
            if not isinstance(unit, str) or not unit:
                undeclared.append(f"{cls_name}.{name}")

    assert not undeclared, "numeric fields with no declared unit: " + ", ".join(undeclared)


def _undetermined_fields() -> list[str]:
    remaining: list[str] = []
    envelope = set(Event.__dataclass_fields__)
    for name in Event.__dataclass_fields__:
        if declared_unit(Event, name) == UNIT_UNDETERMINED:
            remaining.append(f"Event.{name}")
    for cls_name, cls in sorted(_concrete_event_classes().items()):
        for name in cls.__dataclass_fields__:
            if name in envelope:
                continue
            if declared_unit(cls, name) == UNIT_UNDETERMINED:
                remaining.append(f"{cls_name}.{name}")
    return remaining


@pytest.mark.xfail(
    strict=True,
    reason=(
        "G46 undetermined units: HorizonFeatureSnapshot.values, "
        "MetricEvent.value, NBBOQuote.ask_size, NBBOQuote.bid_size, "
        "RegimeHazardSpike.hazard_score, RegimeState.discriminability, "
        "RiskVerdict.constraints, SensorReading.value, "
        "SizedPositionIntent.disclosed_cost_total_bps_by_symbol, "
        "SizedPositionIntent.factor_exposures, "
        "SizedPositionIntent.target_positions"
    ),
)
def test_s9_undetermined_units_remain_unresolved() -> None:
    """Disputed units stay open. Fails while any UNIT_UNDETERMINED remains."""
    remaining = _undetermined_fields()
    assert not remaining, "undetermined units remain: " + ", ".join(remaining)
