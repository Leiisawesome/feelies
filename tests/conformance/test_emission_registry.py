"""S11 — zero-subscriber types match ZERO_SUBSCRIBER_RESOLUTIONS.

A published type with no subscribe site fails unless it is a counted
resolution row. ``StateTransition`` is the notification-record keep (G10).
``KillSwitchActivation`` is a subscriber (G28), not a resolution.
"""

from __future__ import annotations

from collections import Counter

from feelies.core.wiring_manifest import ZERO_SUBSCRIBER_RESOLUTIONS
from tools.arch.contracts import bus_sites, collect_classes, event_closure, global_returns


def _live_zero_subscribers() -> Counter[str]:
    events = event_closure(collect_classes())
    names = set(events)
    pubs, subs, _unresolved = bus_sites(names, global_returns(names))
    published: set[str] = set()
    subscribed: set[str] = set()
    for rec in pubs:
        event_type = rec["event_type"]
        if event_type in names:
            published.add(event_type)
    for rec in subs:
        if rec["call"] == "subscribe" and rec["event_type"] in names:
            subscribed.add(rec["event_type"])
    return Counter(published - subscribed)


def test_zero_subscriber_resolutions_match_live_set() -> None:
    found = _live_zero_subscribers()
    allowed: Counter[str] = Counter(
        event_type for event_type, _resolution in ZERO_SUBSCRIBER_RESOLUTIONS
    )
    extra = found - allowed
    missing = allowed - found
    assert extra == Counter(), (
        "published types with no subscriber and no resolution row: " + ", ".join(sorted(extra))
    )
    assert missing == Counter(), (
        "ZERO_SUBSCRIBER_RESOLUTIONS rows absent from the live zero-subscriber set: "
        + ", ".join(sorted(missing))
    )
    assert all(resolution.strip() for _event_type, resolution in ZERO_SUBSCRIBER_RESOLUTIONS)
    assert ZERO_SUBSCRIBER_RESOLUTIONS == (("StateTransition", "notification_record"),)


def test_discarded_forecasts_are_named_on_the_selection_result() -> None:
    """A discarded forecast that appears in no contract cannot be attributed.

    Path (5): losers used to exist only in the tick trace. The declared
    construction policy emits them as ``SelectionResult.exclusions``.
    """
    from feelies.composition.selection_policy import Top1SelectionPolicy
    from feelies.core.events import Signal, SignalDirection

    def _sig(strategy_id: str, strength: float, edge_bps: float) -> Signal:
        return Signal(
            timestamp_ns=1,
            correlation_id="emit",
            sequence=1,
            symbol="AAPL",
            strategy_id=strategy_id,
            direction=SignalDirection.LONG,
            strength=strength,
            edge_estimate_bps=edge_bps,
        )

    winner = _sig("alpha_a", 1.0, 20.0)
    loser = _sig("alpha_b", 0.2, 5.0)
    result = Top1SelectionPolicy(dead_zone_bps=0.0).select([loser, winner])
    assert result.winner is winner
    named = [e.signal for e in result.exclusions]
    assert loser in named, "losing forecast is absent from the selection contract"
    assert all(e.reason for e in result.exclusions)
