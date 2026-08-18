"""S17 — no post-construction mutation or private reach.

Promotes ``tools.arch.coupling``.  External attribute assignment and
cross-object private access are allowed at the composition root
(bootstrap) and nowhere else.  G39.
"""

from __future__ import annotations

import pytest

from tools.arch.coupling import cross_object_private, external_attribute_assignment

_COMPOSITION_ROOT = "src/feelies/bootstrap.py"


@pytest.mark.xfail(strict=True, reason="GAP G39")
def test_no_post_construction_mutation_or_private_reach() -> None:
    patched = external_attribute_assignment()
    private = cross_object_private()
    assert patched or private, (
        "scanner found no external assignment and no private reach — the "
        "allowlist check is vacuous"
    )
    patched_out = [h for h in patched if h["path"] != _COMPOSITION_ROOT]
    private_out = [h for h in private if h["path"] != _COMPOSITION_ROOT]
    assert not patched_out, (
        f"{len(patched_out)} external attribute assignment(s) outside the "
        f"composition root. First: {patched_out[0]['path']}:{patched_out[0]['line']} "
        f"{patched_out[0]['target']}"
    )
    assert not private_out, (
        f"{len(private_out)} cross-object private access site(s) outside the "
        f"composition root. First: {private_out[0]['path']}:{private_out[0]['line']} "
        f"{private_out[0]['expr']}"
    )
