"""Cross-process PYTHONHASHSEED independence (determinism-audit P1 #9).

The same-process ``test_two_replays_produce_identical_*`` tests share one
``PYTHONHASHSEED`` and therefore **cannot** catch a hash that depends on
Python's salted ``hash()`` (dict / set iteration order).  ``§12.5`` of
docs/three_layer_architecture.md claims "CI sets ``PYTHONHASHSEED=0``" but
nothing in the repo actually wires it (no conftest setting, no CI file).

This test re-runs representative replays in *subprocesses* under several
different ``PYTHONHASHSEED`` values and asserts the hashes are identical —
which proves seed-independence directly (a stronger guarantee than pinning
the seed, and one that survives a CI that forgets to).  It also regression-
guards the ``sorted(...)`` canonicalization in the hash functions: drop a
sort and this test goes red even though the in-process two-run tests stay
green.

The probe runs the replays whose hash functions iterate dicts — regime
posteriors, the sorted ``target_positions`` / ``factor_exposures`` /
``mechanism_breakdown`` maps, and the sorted snapshot ``values`` / ``warm`` /
``stale`` maps — i.e. the paths where a salted ``hash()`` could bite.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEEDS = ("0", "1", "424242")


def _probe() -> None:
    """Print ``name=hash`` for the dict-iterating replays (subprocess entry)."""
    sys.path.insert(0, str(_REPO_ROOT))
    os.chdir(_REPO_ROOT)
    from tests.determinism.test_horizon_feature_snapshot_replay import _replay as snapshot_replay
    from tests.determinism.test_regime_state_replay import (
        _drive_regime_states,
        _hash_regime_stream,
    )
    from tests.determinism.test_sized_intent_replay import _replay as intent_replay

    print("regime=" + _hash_regime_stream(_drive_regime_states()))
    print("intent_off=" + intent_replay(decay=False)[0])
    print("intent_on=" + intent_replay(decay=True)[0])
    print("snapshot=" + snapshot_replay()[0])


def _run_under_seed(seed: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--probe"],
        env={**os.environ, "PYTHONHASHSEED": seed},
        cwd=str(_REPO_ROOT),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def test_replay_hashes_are_pythonhashseed_independent() -> None:
    outputs = {seed: _run_under_seed(seed) for seed in _SEEDS}
    distinct = set(outputs.values())
    assert len(distinct) == 1, (
        "replay hashes depend on PYTHONHASHSEED — a hash path iterates a dict "
        "or set without sorting, so replay is not bit-identical across hosts:\n"
        + "\n".join(
            f"  seed={seed}:\n    " + out.replace("\n", "\n    ") for seed, out in outputs.items()
        )
    )


if __name__ == "__main__":  # pragma: no cover - subprocess probe entry point
    if "--probe" in sys.argv:
        _probe()
