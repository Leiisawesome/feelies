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
    specs = discover_alpha_specs(_REPO_ROOT / "alphas")
    basenames = sorted(p.name for p in specs)
    assert basenames == sorted(
        [
            "sig_benign_midcap_v1.alpha.yaml",
            "sig_hawkes_burst_v1.alpha.yaml",
            "sig_inventory_revert_v1.alpha.yaml",
            "sig_kyle_drift_v1.alpha.yaml",
            "sig_moc_imbalance_v1.alpha.yaml",
            "pro_burst_revert_v1.alpha.yaml",
            "pro_kyle_benign_v1.alpha.yaml",
        ]
    )


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
