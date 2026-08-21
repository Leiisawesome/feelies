"""X8 — re-entrant bus publish is depth-bounded.

G02: 16 subscribe sites publish from inside their own dispatch, with no
depth bound. A cascade that would exceed the bound is refused (fail-closed:
the nested publish is not delivered).
"""

from __future__ import annotations

from feelies.bus.event_bus import EventBus
from feelies.core.events import Alert, AlertSeverity


def _alert(sequence: int = 1) -> Alert:
    return Alert(
        timestamp_ns=1,
        correlation_id="x8",
        sequence=sequence,
        severity=AlertSeverity.INFO,
        layer="conformance",
        alert_name="cascade",
        message="x8",
    )


def test_x8_cascade_depth_is_bounded() -> None:
    bound = getattr(EventBus, "MAX_CASCADE_DEPTH", None)
    assert bound is not None and int(bound) > 0, (
        "event bus has no cascade depth bound"
    )


def test_x8_exceeding_cascade_depth_is_fail_closed() -> None:
    bound = getattr(EventBus, "MAX_CASCADE_DEPTH", 0)
    assert bound, "event bus has no cascade depth bound"
    bus = EventBus()
    delivered = {"n": 0}

    def boom(event: Alert) -> None:
        delivered["n"] += 1
        bus.publish(event)

    bus.subscribe(Alert, boom)
    raised: BaseException | None = None
    try:
        bus.publish(_alert())
    except BaseException as exc:  # noqa: BLE001 — X8 names the refusal
        raised = exc
    assert raised is not None, (
        "unbounded re-entrant publish: cascade was delivered without a bound"
    )
    assert not isinstance(raised, RecursionError), (
        "cascade hit the interpreter recursion limit rather than a declared bound"
    )
    assert delivered["n"] == int(bound), (
        f"fail-closed bound must refuse the publish that would exceed it: "
        f"delivered={delivered['n']} bound={bound}"
    )
    assert "cascade depth" in str(raised).lower()
