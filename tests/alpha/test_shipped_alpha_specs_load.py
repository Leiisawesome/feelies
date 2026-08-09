"""Regression: every discoverable spec under ``alphas/`` must load cleanly.

Templates and underscore-prefixed paths are excluded by
:func:`feelies.alpha.discovery.discover_alpha_specs` (same rule as production).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.alpha.discovery import discover_alpha_specs
from feelies.alpha.loader import AlphaLoader

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_all_shipped_alpha_specs_discovered() -> None:
    """Shipping an alpha must be a deliberate act, not a side effect of a file.

    ``discover_alpha_specs`` walks the directory, so anything dropped under
    ``alphas/`` is loaded by every config that globs. Pinning the list means a new
    spec has to be added here on purpose.
    """
    specs = discover_alpha_specs(_REPO_ROOT / "alphas")
    basenames = sorted(p.name for p in specs)
    assert basenames == sorted(
        [
            "sig_benign_midcap_v1.alpha.yaml",
            # RESEARCH fixture, not a strategy: mirrors sig_benign_midcap_v1 and
            # inverts the direction so the portfolio netter has a two-sided
            # contest to observe. lifecycle_state RESEARCH blocks PAPER/LIVE
            # promotion at load; see the spec header and
            # configs/bt_netting_contest.yaml.
            "sig_contra_fixture_v1.alpha.yaml",
            "sig_hawkes_burst_v1.alpha.yaml",
            "sig_inventory_revert_v1.alpha.yaml",
            "sig_kyle_drift_v1.alpha.yaml",
            "sig_moc_imbalance_v1.alpha.yaml",
        ]
    )


def test_research_fixture_alpha_cannot_be_promoted() -> None:
    """The fixture's whole safety story is one field; assert it rather than trust it.

    It exists to be traded against in research and has no edge claim, so a path
    that let it reach PAPER or LIVE would put capital behind a deliberate
    counter-position.
    """
    loader = AlphaLoader(enforce_trend_mechanism=True)
    spec = _REPO_ROOT / "alphas/sig_contra_fixture_v1/sig_contra_fixture_v1.alpha.yaml"
    module = loader.load(spec)
    assert module.manifest.alpha_id == "sig_contra_fixture_v1"
    assert module.manifest.lifecycle_cap == "RESEARCH"


@pytest.mark.parametrize(
    "enforce_tm",
    [False, True],
    ids=["enforce_trend_mechanism_off", "enforce_trend_mechanism_on"],
)
def test_all_shipped_alpha_specs_load(enforce_tm: bool) -> None:
    loader = AlphaLoader(enforce_trend_mechanism=enforce_tm)
    specs = discover_alpha_specs(_REPO_ROOT / "alphas")
    assert specs, "Expected at least one shipped alpha spec under alphas/"
    for path in specs:
        module = loader.load(path)
        assert module.manifest.alpha_id
