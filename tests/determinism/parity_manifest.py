"""Central registry of locked Inv-5 parity hashes (BT-11 batched re-baseline).

Each entry maps a stable name to ``(hash_hex, event_count)`` pinned in
``tests/determinism/``.  Re-baseline workflow:

1. Run ``uv run python scripts/rebaseline_parity_hashes.py``.
2. Copy printed constants into the owning test module (and this manifest).
3. Commit with rationale referencing the fill-model / layer change.

The manifest is checked by :mod:`tests.determinism.test_parity_manifest`
so drift between modules is caught in CI.
"""

from __future__ import annotations

from typing import Final

from tests.determinism.test_hazard_exit_replay import (
    EXPECTED_LEVEL4_HAZARD_EXIT_ORDER_COUNT,
    EXPECTED_LEVEL4_HAZARD_EXIT_ORDER_HASH,
)
from tests.determinism.test_horizon_feature_snapshot_replay import (
    EXPECTED_LEVEL3_SNAPSHOT_COUNT,
    EXPECTED_LEVEL3_SNAPSHOT_HASH,
)
from tests.determinism.test_horizon_tick_replay import (
    EXPECTED_LEVEL2_TICK_COUNT,
    EXPECTED_LEVEL2_TICK_HASH,
)
from tests.determinism.test_portfolio_order_replay import (
    EXPECTED_LEVEL4_PORTFOLIO_ORDER_COUNT,
    EXPECTED_LEVEL4_PORTFOLIO_ORDER_HASH,
)
from tests.determinism.test_regime_hazard_replay import (
    EXPECTED_LEVEL5_HAZARD_COUNT,
    EXPECTED_LEVEL5_HAZARD_HASH,
)
from tests.determinism.test_regime_state_replay import (
    EXPECTED_LEVEL6_REGIME_STATE_COUNT,
    EXPECTED_LEVEL6_REGIME_STATE_HASH,
)
from tests.determinism.test_sensor_reading_replay import (
    EXPECTED_LEVEL4_READING_COUNT,
    EXPECTED_LEVEL4_READING_HASH,
)
from tests.determinism.test_signal_replay import (
    EXPECTED_LEVEL2_SIGNAL_COUNT,
    EXPECTED_LEVEL2_SIGNAL_HASH,
)
from tests.determinism.test_sized_intent_replay import (
    EXPECTED_LEVEL3_INTENT_DECAY_OFF_COUNT,
    EXPECTED_LEVEL3_INTENT_DECAY_OFF_HASH,
)
from tests.determinism.test_sized_intent_with_decay_replay import (
    EXPECTED_LEVEL3_INTENT_DECAY_ON_COUNT,
    EXPECTED_LEVEL3_INTENT_DECAY_ON_HASH,
)
from tests.determinism.test_v03_sensor_replay import (
    EXPECTED_V03_READING_COUNT,
    EXPECTED_V03_READING_HASH,
)

ParityEntry = tuple[str, int]

LOCKED_PARITY_BASELINES: Final[dict[str, ParityEntry]] = {
    "level1_sensor_reading": (EXPECTED_LEVEL4_READING_HASH, EXPECTED_LEVEL4_READING_COUNT),
    "level1_v03_sensor_reading": (EXPECTED_V03_READING_HASH, EXPECTED_V03_READING_COUNT),
    "level2_horizon_tick": (EXPECTED_LEVEL2_TICK_HASH, EXPECTED_LEVEL2_TICK_COUNT),
    "level2_signal": (EXPECTED_LEVEL2_SIGNAL_HASH, EXPECTED_LEVEL2_SIGNAL_COUNT),
    "level3_horizon_feature_snapshot": (
        EXPECTED_LEVEL3_SNAPSHOT_HASH,
        EXPECTED_LEVEL3_SNAPSHOT_COUNT,
    ),
    "level3_sized_intent_decay_off": (
        EXPECTED_LEVEL3_INTENT_DECAY_OFF_HASH,
        EXPECTED_LEVEL3_INTENT_DECAY_OFF_COUNT,
    ),
    "level3_sized_intent_decay_on": (
        EXPECTED_LEVEL3_INTENT_DECAY_ON_HASH,
        EXPECTED_LEVEL3_INTENT_DECAY_ON_COUNT,
    ),
    "level4_portfolio_order": (
        EXPECTED_LEVEL4_PORTFOLIO_ORDER_HASH,
        EXPECTED_LEVEL4_PORTFOLIO_ORDER_COUNT,
    ),
    "level4_hazard_exit_order": (
        EXPECTED_LEVEL4_HAZARD_EXIT_ORDER_HASH,
        EXPECTED_LEVEL4_HAZARD_EXIT_ORDER_COUNT,
    ),
    "level5_regime_hazard_spike": (
        EXPECTED_LEVEL5_HAZARD_HASH,
        EXPECTED_LEVEL5_HAZARD_COUNT,
    ),
    "level6_regime_state": (
        EXPECTED_LEVEL6_REGIME_STATE_HASH,
        EXPECTED_LEVEL6_REGIME_STATE_COUNT,
    ),
}
