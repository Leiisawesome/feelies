"""C2 — accounting conservation identities at every event.

C1 asserts the null-alpha book is zero.  These identities must also hold
when a position is (or is not) open: a flat book has no unrealized PnL,
and the probe actually ran.  G21, G34.
"""

from __future__ import annotations

from tests.conformance.test_null_alpha_conservation import (
    _UNIVERSE,
    _replay_under_null_alpha,
    _synth_events,
)


def test_accounting_conservation_identities_per_event() -> None:
    events = _synth_events()
    probe = _replay_under_null_alpha()
    assert probe.event_count >= len(events), (
        f"probe saw {probe.event_count} events but {len(events)} were fed in"
    )
    assert probe.samples, "probe recorded no observations — identities would be vacuous"

    violations = [
        s for s in probe.samples if s.quantity == 0 and s.unrealized_pnl != 0
    ]
    assert not violations, (
        f"flat book carried unrealized PnL at {len(violations)} of "
        f"{len(probe.samples)} observations. First: {violations[0]}"
    )
    observed = {s.symbol for s in probe.samples}
    assert observed == set(_UNIVERSE), (
        f"probe covered {sorted(observed)}, expected {sorted(_UNIVERSE)}"
    )
