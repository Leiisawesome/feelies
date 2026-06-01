"""BT-11 acceptance: locked parity baselines hold after fill-model work (Inv-5).

Verifies the batched parity manifest still matches live replays on the
current tree (including BT-14 tick-size rounding).  The synthetic
Level-1–6 fixtures in ``tests/determinism/`` do not route through
``market_fill``; composition and hazard-exit hashes are therefore
expected to be stable across fill-price grid changes unless a future
change touches those layers.

The authoritative per-module pins live in ``tests/determinism/*_replay.py``;
this file is the remediation-plan handoff gate that runs the manifest in one
CI pass alongside other acceptance rows.
"""

from __future__ import annotations

import pytest

from tests.determinism import parity_manifest
from tests.determinism.test_parity_manifest import _REPLAY_BY_NAME


@pytest.mark.parametrize(
    "name",
    list(parity_manifest.LOCKED_PARITY_BASELINES.keys()),
    ids=list(parity_manifest.LOCKED_PARITY_BASELINES.keys()),
)
def test_locked_parity_baseline_matches_replay_after_fill_model_changes(
    name: str,
) -> None:
    expected = parity_manifest.LOCKED_PARITY_BASELINES[name]
    actual = _REPLAY_BY_NAME[name]()
    assert actual == expected, (
        f"parity manifest drift for {name!r} after fill-model changes: "
        f"locked {expected}, replay produced {actual}.  Run "
        "`uv run python scripts/rebaseline_parity_hashes.py` and update "
        "the owning test module plus parity_manifest.py in one commit."
    )
