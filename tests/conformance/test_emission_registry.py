"""S11 — every published event type has a subscriber.

Promotes ``tools.arch.contracts.bus_sites``.  A type published onto the
domain bus with zero static subscribers is a docstring promise with no
consumer (G10); ``KillSwitchActivation`` is the named case (G28).
"""

from __future__ import annotations

from collections import defaultdict

import pytest

from tools.arch.contracts import bus_sites, collect_classes, event_closure, global_returns


@pytest.mark.xfail(strict=True, reason="GAP G10 G28")
def test_every_published_type_has_a_subscriber() -> None:
    events = event_closure(collect_classes())
    assert events, "contracts scanner found no Event subclasses"
    names = set(events)
    pubs, subs, _unresolved = bus_sites(names, global_returns(names))
    assert pubs, "scanner found no publish sites — the subscriber check is vacuous"

    pub_by: dict[str, set[str]] = defaultdict(set)
    sub_by: dict[str, set[str]] = defaultdict(set)
    for rec in pubs:
        if rec["event_type"] in names:
            pub_by[rec["event_type"]].add(f"{rec['path']}:{rec['line']}")
    for rec in subs:
        if rec["call"] == "subscribe" and rec["event_type"] in names:
            sub_by[rec["event_type"]].add(f"{rec['path']}:{rec['line']}")

    published_never_subscribed = sorted(set(pub_by) - set(sub_by))
    assert not published_never_subscribed, (
        "event types published to zero static subscribers: "
        + ", ".join(published_never_subscribed)
    )


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
