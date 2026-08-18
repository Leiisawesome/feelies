"""C3 — ingress conservation.

Every market-data event fed into a replay is observed on the bus, or a
drop is not silent.  G11, G33.
"""

from __future__ import annotations

from tests.conformance.test_null_alpha_conservation import (
    _replay_under_null_alpha,
    _synth_events,
)

_MARKET_TYPES = frozenset({"NBBOQuote", "Trade"})


def test_ingress_conservation_and_notification() -> None:
    events = _synth_events()
    probe = _replay_under_null_alpha()
    assert probe.samples, "probe recorded no observations — ingress would be vacuous"

    seen_indexes = {
        s.event_index for s in probe.samples if s.event_type in _MARKET_TYPES
    }
    assert seen_indexes, "probe saw no NBBOQuote/Trade — ingress never ran"
    assert len(seen_indexes) == len(events), (
        f"fed {len(events)} market-data events, probe observed "
        f"{len(seen_indexes)} unique NBBOQuote/Trade indexes — a drop "
        "without a notification, or a duplicate publish"
    )
