"""S5 — hot-path allow list.

Promotes ``tools.arch.hotpath.scan`` / ``dead_compute``.  A prohibited
construct that cProfile observed on the tick path, or a public method
with zero call sites in src, fails here.  G41, G42, G44, G45.
"""

from __future__ import annotations

import pytest

from tools.arch.hotpath import ALLOWED_NOT_PROHIBITED, dead_compute, scan


@pytest.mark.xfail(strict=True, reason="GAP G41 G42 G44 G45")
def test_hot_path_allow_list() -> None:
    report = scan()
    prohibitions = report["prohibitions"]
    assert prohibitions, "hotpath scanner returned no prohibition rows"

    proven: list[str] = []
    for kind, row in prohibitions.items():
        if kind in ALLOWED_NOT_PROHIBITED:
            continue
        n = int(row["proven_per_event_sites"])
        if n:
            sites = ", ".join(s["site"] for s in row["proven_sites"][:5])
            proven.append(f"{kind}: {n} proven per-event ({sites})")
    assert not proven, "hot-path prohibitions with proven per-event sites:\n  " + "\n  ".join(
        proven
    )

    dead = dead_compute()
    methods = dead["public_methods_zero_call_sites_in_src"]
    n_anywhere = int(methods["n_zero_call_anywhere"])
    assert methods["n_public_methods"] > 0, "dead-compute scanned no public methods"
    assert n_anywhere == 0, (
        f"{n_anywhere} public methods have zero call sites in src/ and tests/; "
        "G44 residue"
    )
