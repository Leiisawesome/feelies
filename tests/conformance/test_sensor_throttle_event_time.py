"""R7 — sensor throttle is in event time.

A throttle comparison against wall-clock time would make replay
host-speed-dependent.  The comparison must use ``event.timestamp_ns``.
G42 is a guard, not a gap that fails today.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REGISTRY = (
    Path(__file__).resolve().parents[2] / "src" / "feelies" / "sensors" / "registry.py"
)
_WALL_LEAVES = frozenset(
    {
        "time",
        "time_ns",
        "monotonic",
        "monotonic_ns",
        "perf_counter",
        "perf_counter_ns",
        "now",
        "utcnow",
    }
)


def test_sensor_throttle_uses_event_time() -> None:
    source = _REGISTRY.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_REGISTRY))
    throttle_compares: list[str] = []
    duration_compares: list[str] = []
    wall_in_throttle: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        text = ast.unparse(node)
        if "throttle_ns" not in text:
            continue
        throttle_compares.append(text)
        if re.search(r"throttle_ns\s*[<>]=?\s*0\b", text):
            continue
        duration_compares.append(text)
        if "timestamp_ns" not in text:
            wall_in_throttle.append(text)
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and child.attr in _WALL_LEAVES:
                wall_in_throttle.append(text)
    assert throttle_compares, (
        "no throttle_ns comparison in sensors/registry.py — the event-time "
        "guard never ran"
    )
    assert duration_compares, (
        "throttle_ns is only compared to zero — the duration compare never ran"
    )
    assert not wall_in_throttle, (
        "throttle comparison is not in event time: " + "; ".join(wall_in_throttle)
    )
    assert all("timestamp_ns" in text for text in duration_compares), (
        "duration compare does not use event.timestamp_ns: "
        + "; ".join(duration_compares)
    )
