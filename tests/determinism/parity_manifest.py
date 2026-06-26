"""Central registry of locked Inv-5 parity hashes (BT-11 batched re-baseline).

Each entry maps a stable name to ``(hash_hex, event_count)`` pinned in
``tests/determinism/``.  Re-baseline workflow:

1. Run ``uv run python scripts/rebaseline_parity_hashes.py``.
2. Copy printed constants into the owning test module (and this manifest).
3. Commit with rationale referencing the fill-model / layer change.

The manifest is checked by :mod:`tests.determinism.test_parity_manifest`
so drift between modules is caught in CI.

Cross-libm caveat (audit P0-3)
------------------------------
These hashes guarantee bit-identical replay on a **fixed (platform, libm)
pair**, not universally.  Sensors that call ``math.exp`` / ``math.log``
(``hawkes_intensity``, ``realized_vol_30s``, ``snr_drift_diffusion``,
``structural_break_score``, ``liquidity_stress_score``) depend on the C math
library's rounding of those transcendental functions, which is not guaranteed
correctly-rounded across libm versions — so a hash computed on one host may
differ in the last bit on another.  Intra-process reproducibility (the part
that *is* guaranteed) is locked by
:mod:`tests.determinism.test_transcendental_determinism`.  FOLLOW-UP: record
the libm / host fingerprint alongside each parity hash so a cross-host
mismatch is attributable rather than mysterious (provenance plumbing owned by
the data-ingestion / determinism harness).
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
from tests.determinism.test_market_fill_replay import (
    EXPECTED_MARKET_FILL_ACK_COUNT,
    EXPECTED_MARKET_FILL_HASH,
)
from tests.determinism.test_portfolio_order_replay import (
    EXPECTED_LEVEL4_PORTFOLIO_ORDER_COUNT,
    EXPECTED_LEVEL4_PORTFOLIO_ORDER_HASH,
)
from tests.determinism.test_position_pnl_replay import (
    EXPECTED_POSITION_PNL_COUNT,
    EXPECTED_POSITION_PNL_HASH,
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
from tests.determinism.test_state_transition_replay import (
    EXPECTED_STATE_TRANSITION_COUNT,
    EXPECTED_STATE_TRANSITION_HASH,
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
    # Audit P1.5: golden aggressive fill-replay (default market_fill economics).
    "market_fill_acks": (
        EXPECTED_MARKET_FILL_HASH,
        EXPECTED_MARKET_FILL_ACK_COUNT,
    ),
    # Audit P1 #5: PnL — PositionUpdate reconciliation over a deterministic
    # fill/mark scenario (FIFO cost-basis math; closes the Inv-5 "PnL" clause).
    "position_pnl": (
        EXPECTED_POSITION_PNL_HASH,
        EXPECTED_POSITION_PNL_COUNT,
    ),
    # Audit P1 #12: StateTransition stream from a deterministic RiskLevel +
    # OrderState walk (pins SM emission order + sequence allocation).
    "state_transition": (
        EXPECTED_STATE_TRANSITION_HASH,
        EXPECTED_STATE_TRANSITION_COUNT,
    ),
}
