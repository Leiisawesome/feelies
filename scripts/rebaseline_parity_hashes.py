#!/usr/bin/env python3
"""Print current SHA-256 parity fingerprints for BT-11 re-baselining.

Run from the repo root::

    uv run python scripts/rebaseline_parity_hashes.py

Copy the printed ``EXPECTED_*`` constants into the owning module under
``tests/determinism/`` and update ``tests/determinism/parity_manifest.py``
in the same commit.  Then run::

    uv run pytest tests/determinism/test_parity_manifest.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.determinism.test_hazard_exit_replay import _replay as hazard_exit_replay
from tests.determinism.test_horizon_feature_snapshot_replay import _replay as snapshot_replay
from tests.determinism.test_portfolio_order_replay import _replay as portfolio_order_replay
from tests.determinism.test_regime_hazard_replay import _replay as regime_hazard_replay
from tests.determinism.test_regime_state_replay import (
    _drive_regime_states,
    _hash_regime_stream,
)
from tests.determinism.test_sensor_reading_replay import _replay as sensor_replay
from tests.determinism.test_signal_replay import _replay as signal_replay
from tests.determinism.test_sized_intent_replay import _replay as intent_replay
from tests.determinism.test_sized_intent_with_decay_replay import _replay as intent_decay_on
from tests.determinism.test_v03_sensor_replay import _replay as v03_sensor_replay
from tests.fixtures.replay import (
    hash_horizon_tick_stream,
    replay_quotes_through_scheduler,
)


def _section(title: str) -> None:
    print(f"\n# {title}")
    print("#" * (len(title) + 2))


def main() -> None:
    rows: list[tuple[str, str, int]] = []

    h, c = sensor_replay()
    rows.append(("EXPECTED_LEVEL4_READING", h, c))

    h, c = v03_sensor_replay()
    rows.append(("EXPECTED_V03_READING", h, c))

    ticks, _ = replay_quotes_through_scheduler()
    rows.append(("EXPECTED_LEVEL2_TICK", hash_horizon_tick_stream(ticks), len(ticks)))

    h, c = signal_replay()
    rows.append(("EXPECTED_LEVEL2_SIGNAL", h, c))

    h, c = snapshot_replay()
    rows.append(("EXPECTED_LEVEL3_SNAPSHOT", h, c))

    h, c = intent_replay(decay=False)
    rows.append(("EXPECTED_LEVEL3_INTENT_DECAY_OFF", h, c))

    h, c = intent_decay_on(decay=True)
    rows.append(("EXPECTED_LEVEL3_INTENT_DECAY_ON", h, c))

    h, c = portfolio_order_replay()
    rows.append(("EXPECTED_LEVEL4_PORTFOLIO_ORDER", h, c))

    h, c = hazard_exit_replay()
    rows.append(("EXPECTED_LEVEL4_HAZARD_EXIT_ORDER", h, c))

    h, c = regime_hazard_replay()
    rows.append(("EXPECTED_LEVEL5_HAZARD", h, c))

    states = _drive_regime_states()
    rows.append(("EXPECTED_LEVEL6_REGIME_STATE", _hash_regime_stream(states), len(states)))

    _section("Locked parity hashes (copy into tests/determinism/)")
    for prefix, hash_hex, count in rows:
        print(f"{prefix}_HASH = (\n    \"{hash_hex}\"\n)")
        print(f"{prefix}_COUNT = {count}")
        print()

    print("Done. Update parity_manifest.py imports if names changed.")


if __name__ == "__main__":
    main()
