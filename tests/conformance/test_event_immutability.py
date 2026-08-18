"""S10 — frozen events carry no mutable container.

Promotes ``tools.arch.contracts``.  The decorator half (every Event
subclass is ``frozen=True``) and the payload half (no ``dict``/``list``/
``set`` field) are both asserted.  G12 is the payload half.
"""

from __future__ import annotations

import pytest

from tools.arch.contracts import collect_classes, event_closure


@pytest.mark.xfail(strict=True, reason="GAP G12")
def test_frozen_events_carry_no_mutable_container() -> None:
    events = event_closure(collect_classes())
    assert events, "contracts scanner found no Event subclasses"

    non_frozen = sorted(
        name for name, cls in events.items() if cls["is_dataclass"] and not cls["frozen"]
    )
    assert not non_frozen, f"Event subclasses missing frozen=True: {non_frozen}"

    mutable = {
        name: [field["name"] for field in cls["fields"] if field["mutable_container"]]
        for name, cls in events.items()
    }
    mutable = {name: fields for name, fields in mutable.items() if fields}
    assert not mutable, (
        "frozen events with mutable container fields (G12): " + ", ".join(
            f"{name}={fields}" for name, fields in sorted(mutable.items())
        )
    )
