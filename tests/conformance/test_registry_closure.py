"""S1 — gap-to-test registry closure.

Inv-13 requires every remediation to name the gap it closed.  The registry
is that link; this test is the closure assertion over it.

The assertion fails on exactly two gaps and is expected to.  G31 (§F.2 write
authority) and G32 (§F.2 symbol identity) are named by no Phase 6 test, so
they carry empty test lists from wave A onward.  ``xfail(strict=True)`` keeps
that hole visible and named rather than silently absent: S-30 authors their
gates, registers them, and drops this marker.  ``strict`` also means the
marker cannot outlive the hole — once both gaps are covered the XPASS fails
the suite.
"""

from __future__ import annotations

import pytest

from tests.conformance.registry import GAP_REGISTRY

_ENFORCED_SEVERITIES = ("P0", "P1")


@pytest.mark.xfail(strict=True, reason="GAP G31, G32")
def test_every_p0_p1_gap_names_an_enforcing_test() -> None:
    uncovered = sorted(
        gap_id
        for gap_id, entry in GAP_REGISTRY.items()
        if entry.severity in _ENFORCED_SEVERITIES and not entry.tests
    )
    assert not uncovered, (
        f"P0/P1 gaps with no enforcing conformance test: {', '.join(uncovered)}. "
        "Either author a test and register it, or the gap has no guard at all."
    )
