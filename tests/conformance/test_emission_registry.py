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
