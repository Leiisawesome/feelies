"""S1 — gap-to-test registry closure.

Inv-13 requires every remediation to name the gap it closed.  The registry
is that link; this test is the closure assertion over it.

The assertion pins the uncovered set to exactly two gaps.  G31 (§F.2 write
authority) and G32 (§F.2 symbol identity) are named by no Phase 6 test, so
they carry empty test lists from wave A onward.  Asserting equality against
that known set keeps the hole visible and named rather than silently absent:
S-30 authors their gates, registers them, and shrinks ``_KNOWN_UNCOVERED``.
Equality — rather than ``not uncovered`` under a blanket ``xfail`` — means the
expectation cannot outlive the hole (closing G31/G32 without updating this set
fails) and cannot mask a new one (any other P0/P1 gap losing coverage fails).
"""

from __future__ import annotations

from tests.conformance.registry import GAP_REGISTRY

_ENFORCED_SEVERITIES = ("P0", "P1")

#: P0/P1 gaps knowingly without an enforcing test — closed by S-30 (§G.0.4).
_KNOWN_UNCOVERED = ("G31", "G32")


def test_every_p0_p1_gap_names_an_enforcing_test() -> None:
    uncovered = sorted(
        gap_id
        for gap_id, entry in GAP_REGISTRY.items()
        if entry.severity in _ENFORCED_SEVERITIES and not entry.tests
    )
    assert uncovered == sorted(_KNOWN_UNCOVERED), (
        "P0/P1 gaps without an enforcing conformance test must be exactly "
        f"{sorted(_KNOWN_UNCOVERED)}, found {uncovered}. "
        "Author a test and register it, or update _KNOWN_UNCOVERED when S-30 "
        "closes G31/G32 — do not let a new gap open unnamed."
    )
