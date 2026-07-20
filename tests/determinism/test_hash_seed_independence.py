"""Verify replay hashes are independent of ``PYTHONHASHSEED``.

Representative dict-heavy replays run in subprocesses under several seeds.
Identical output proves that canonical sorting, rather than salted mapping or
set order, determines parity hashes.
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
    from tests.determinism.test_cross_sectional_context_replay import (
        _replay as xsect_context_replay,
    )
    from tests.determinism.test_horizon_feature_snapshot_replay import _replay as snapshot_replay
    from tests.determinism.test_multi_symbol_sensor_replay import (
        _replay as multi_symbol_sensor_replay,
    )
    from tests.determinism.test_regime_state_replay import (
        _drive_regime_states,
        _hash_regime_stream,
    )
    from tests.determinism.test_signal_fires_replay import _replay as signal_fires_replay
    from tests.determinism.test_sized_intent_replay import _replay as intent_replay
    from tests.determinism.test_state_transition_replay import _replay as transition_replay

    print("regime=" + _hash_regime_stream(_drive_regime_states()))
    print("intent_off=" + intent_replay(decay=False)[0])
    print("intent_on=" + intent_replay(decay=True)[0])
    print("snapshot=" + snapshot_replay()[0])
    print("transition=" + transition_replay()[0])
    print("cross_sectional_context=" + xsect_context_replay()[0])
    print("signal_fires=" + signal_fires_replay()[0])
    print("multi_symbol_sensor_reading=" + multi_symbol_sensor_replay()[0])


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
