"""S5 — hot-path allow list.

Promotes ``tools.arch.hotpath.scan`` / ``dead_compute``.  A prohibited
construct that cProfile observed on the tick path, or a public method
with zero call sites in src, fails here.  G41, G42, G44, G45.
"""

from __future__ import annotations

import os

import pytest

from tools.arch.hotpath import ALLOWED_NOT_PROHIBITED, dead_compute, scan

# Inv-13 unique per-event stamp; built from a timestamp and a sequence;
# cannot be interned. Every replacement still allocates. The six other
# proven sites are not in this keep.
_G45_KEEP: frozenset[tuple[str, str, str]] = frozenset(
    {
        (
            "src/feelies/core/identifiers.py",
            "make_correlation_id",
            "string_formatting",
        ),
    }
)

# Six S-31c dead-compute keeps. Key is (path, class, method); no line number.
# A new zero-call-anywhere method is a STOP, not an implicit keep.
_G44_KEEP: frozenset[tuple[str, str, str]] = frozenset(
    {
        # Inv-12 declaration-time disclosure, distinct from runtime B4
        (
            "src/feelies/core/cost_arithmetic.py",
            "CostArithmetic",
            "declared_round_trip_cost_bps",
        ),
        # persist per-alpha HWM across restarts
        (
            "src/feelies/risk/risk_wrapper.py",
            "AlphaBudgetRiskWrapper",
            "checkpoint_risk_state",
        ),
        # restore pair of checkpoint
        (
            "src/feelies/risk/risk_wrapper.py",
            "AlphaBudgetRiskWrapper",
            "restore_risk_state",
        ),
        # named-engine lookup (tick path uses latest())
        (
            "src/feelies/services/regime_state_cache.py",
            "RegimeStateCache",
            "for_engine",
        ),
        # S7 delisting of cached regime state
        (
            "src/feelies/services/regime_state_cache.py",
            "RegimeStateCache",
            "forget",
        ),
        # S7 symbol lifecycle on the signal engine
        (
            "src/feelies/signals/horizon_engine.py",
            "HorizonSignalEngine",
            "forget",
        ),
    }
)


@pytest.mark.xfail(strict=True, reason="GAP G41 G42")
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
        f"{n_anywhere} public methods have zero call sites in src/ and tests/; G44 residue"
    )


@pytest.mark.skipif(
    os.environ.get("FEELIES_HOTPATH_FORK_SKIP") == "1",
    reason="fork PR: hot-path profile not generated",
)
def test_g45_keep() -> None:
    report = scan()
    keep_hits: set[tuple[str, str, str]] = set()
    for kind, row in report["prohibitions"].items():
        for site_row in row["proven_sites"]:
            site = str(site_row["site"]).replace("\\", "/")
            key = (site.rsplit(":", 1)[0], str(site_row["func"]), str(kind))
            if key == (
                "src/feelies/core/identifiers.py",
                "make_correlation_id",
                "string_formatting",
            ):
                keep_hits.add(key)
    assert keep_hits == _G45_KEEP, (
        f"unexpected {sorted(keep_hits - _G45_KEEP)}; missing {sorted(_G45_KEEP - keep_hits)}"
    )


def test_g44_dead_compute() -> None:
    dead = dead_compute()
    methods = dead["public_methods_zero_call_sites_in_src"]
    keep_hits: set[tuple[str, str, str]] = set()
    for row in methods["methods"]:
        if row["called_by_tests"] or row["called_by_scripts"]:
            continue
        site = str(row["site"]).replace("\\", "/")
        key = (site.rsplit(":", 1)[0], str(row["cls"]), str(row["method"]))
        keep_hits.add(key)
    assert keep_hits == _G44_KEEP, (
        f"unexpected {sorted(keep_hits - _G44_KEEP)}; missing {sorted(_G44_KEEP - keep_hits)}"
    )
