"""S3 — no alpha-id literal outside alphas/ and config that declares it.

Inv-6: core does not branch on alpha identity.  The scanner is
``tools.arch.gapscan.alpha_literal_leaks``; this test is the assertion
over its output.
"""

from __future__ import annotations

from tools.arch.gapscan import alpha_literal_leaks


def test_no_alpha_shape_literal_outside_alphas_and_config() -> None:
    report = alpha_literal_leaks()
    ids = report["known_alpha_ids"]
    assert ids, "scanner declared no alpha ids — the leak check would be vacuous"
    leaks = report["leak_sites"]
    assert not leaks, (
        f"{len(leaks)} alpha-id literal(s) in src/feelies; core must not name "
        f"an alpha. First: {leaks[0]}"
    )
