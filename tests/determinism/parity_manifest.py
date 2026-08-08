"""Central registry of locked replay hashes.

Each entry maps a stable name to ``(hash_hex, event_count)`` pinned in
``tests/determinism/``.  Re-baseline workflow:

1. Run ``uv run python scripts/rebaseline_parity_hashes.py``.
2. Copy printed constants into the owning test module (and this manifest).
3. Commit with rationale referencing the fill-model / layer change.

The manifest is checked by :mod:`tests.determinism.test_parity_manifest`
so drift between modules is caught in CI.

Hashes involving transcendental math are stable only for a fixed platform and
libm. In-process reproducibility is covered separately by
``test_transcendental_determinism``.

That caveat is about the general case, not about the entries below.  Every
baseline registered here was verified identical on macOS and on glibc
(GitHub Actions run 31262226139, 2026-08-08): both hosts produced
4600 passed / 5 skipped / 43 deselected with no re-baseline, so the registered
corpus is portable and CI runs a single host on that basis.  The caveat still
governs the *unregistered* hashes — the orchestrator streams and the phase-4 E2E
pins — which is why they carry a host-sensitivity exemption in
``test_parity_manifest._UNREGISTERED_HASH_EXEMPTIONS`` rather than a manifest
entry.  If a future entry does prove host-dependent, exempt it there; do not
re-baseline it onto whichever host CI happens to run.
"""

from __future__ import annotations

import hashlib
from typing import Final

from tests.determinism.test_cross_sectional_context_replay import (
    EXPECTED_XSECT_CONTEXT_COUNT,
    EXPECTED_XSECT_CONTEXT_HASH,
)
from tests.determinism.test_decoupled_safety_replay import (
    EXPECTED_DECOUPLED_RISK_FLATTEN_ORDER_COUNT,
    EXPECTED_DECOUPLED_RISK_FLATTEN_ORDER_HASH,
    EXPECTED_DECOUPLED_SAFETY_STATE_CHANGE_COUNT,
    EXPECTED_DECOUPLED_SAFETY_STATE_CHANGE_HASH,
)
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
from tests.determinism.test_forced_exit_attribution_replay import (
    EXPECTED_FORCED_EXIT_ATTRIBUTION_COUNT,
    EXPECTED_FORCED_EXIT_ATTRIBUTION_HASH,
)
from tests.determinism.test_market_fill_replay import (
    EXPECTED_MARKET_FILL_ACK_COUNT,
    EXPECTED_MARKET_FILL_HASH,
)
from tests.determinism.test_multi_symbol_sensor_replay import (
    EXPECTED_MULTI_SYMBOL_READING_COUNT,
    EXPECTED_MULTI_SYMBOL_READING_HASH,
)
from tests.determinism.test_portfolio_order_replay import (
    EXPECTED_LEVEL4_PORTFOLIO_ORDER_COUNT,
    EXPECTED_LEVEL4_PORTFOLIO_ORDER_HASH,
)
from tests.determinism.test_position_pnl_replay import (
    EXPECTED_POSITION_PNL_COUNT,
    EXPECTED_POSITION_PNL_HASH,
)
from tests.determinism.test_reference_alpha_signal_fires_replay import (
    EXPECTED_REFERENCE_ALPHA_SIGNAL_FIRES_COUNT,
    EXPECTED_REFERENCE_ALPHA_SIGNAL_FIRES_HASH,
)
from tests.determinism.test_regime_hazard_replay import (
    EXPECTED_LEVEL5_HAZARD_COUNT,
    EXPECTED_LEVEL5_HAZARD_HASH,
)
from tests.determinism.test_risk_verdict_replay import (
    EXPECTED_RISK_VERDICT_COUNT,
    EXPECTED_RISK_VERDICT_HASH,
)
from tests.determinism.test_regime_state_replay import (
    EXPECTED_LEVEL6_REGIME_STATE_COUNT,
    EXPECTED_LEVEL6_REGIME_STATE_HASH,
)
from tests.determinism.test_sensor_reading_replay import (
    EXPECTED_LEVEL4_READING_COUNT,
    EXPECTED_LEVEL4_READING_HASH,
)
from tests.determinism.test_signal_fires_replay import (
    EXPECTED_SIGNAL_FIRES_COUNT,
    EXPECTED_SIGNAL_FIRES_HASH,
)
from tests.determinism.test_signal_replay import (
    EXPECTED_LEVEL2_SIGNAL_COUNT,
    EXPECTED_LEVEL2_SIGNAL_HASH,
)
from tests.determinism.test_state_transition_replay import (
    EXPECTED_STATE_TRANSITION_COUNT,
    EXPECTED_STATE_TRANSITION_HASH,
)
from tests.determinism.test_symbol_halted_replay import (
    EXPECTED_HALT_ACK_COUNT,
    EXPECTED_HALT_ACK_HASH,
    EXPECTED_HALT_ORDER_COUNT,
    EXPECTED_HALT_ORDER_HASH,
    EXPECTED_HALT_POSITION_UPDATE_COUNT,
    EXPECTED_HALT_POSITION_UPDATE_HASH,
    EXPECTED_SYMBOL_HALTED_COUNT,
    EXPECTED_SYMBOL_HALTED_HASH,
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
    # Aggressive-fill replay with default market-fill economics.
    "market_fill_acks": (
        EXPECTED_MARKET_FILL_HASH,
        EXPECTED_MARKET_FILL_ACK_COUNT,
    ),
    # FIFO PnL reconciliation over deterministic fills and marks.
    "position_pnl": (
        EXPECTED_POSITION_PNL_HASH,
        EXPECTED_POSITION_PNL_COUNT,
    ),
    # Per-strategy attribution of a symbol-net forced exit across two slices.
    # The only fixture that observes *which alpha* a fill is booked to.
    "forced_exit_attribution": (
        EXPECTED_FORCED_EXIT_ATTRIBUTION_HASH,
        EXPECTED_FORCED_EXIT_ATTRIBUTION_COUNT,
    ),
    # State-machine emission order and sequence allocation.
    "state_transition": (
        EXPECTED_STATE_TRANSITION_HASH,
        EXPECTED_STATE_TRANSITION_COUNT,
    ),
    # UniverseSynchronizer fan-in, completeness, and context sequencing.
    "cross_sectional_context": (
        EXPECTED_XSECT_CONTEXT_HASH,
        EXPECTED_XSECT_CONTEXT_COUNT,
    ),
    # Non-empty signal emission from the real HorizonSignalEngine.
    "signal_fires": (
        EXPECTED_SIGNAL_FIRES_HASH,
        EXPECTED_SIGNAL_FIRES_COUNT,
    ),
    # Cross-symbol sensor emission order and sequence allocation.
    "multi_symbol_sensor_reading": (
        EXPECTED_MULTI_SYMBOL_READING_HASH,
        EXPECTED_MULTI_SYMBOL_READING_COUNT,
    ),
    # Non-empty signal emission from the reference alpha.
    "reference_alpha_signal_fires": (
        EXPECTED_REFERENCE_ALPHA_SIGNAL_FIRES_HASH,
        EXPECTED_REFERENCE_ALPHA_SIGNAL_FIRES_COUNT,
    ),
    # Halt events and fill suppression through the resume blackout.
    "symbol_halted": (EXPECTED_SYMBOL_HALTED_HASH, EXPECTED_SYMBOL_HALTED_COUNT),
    "halt_order": (EXPECTED_HALT_ORDER_HASH, EXPECTED_HALT_ORDER_COUNT),
    "halt_ack": (EXPECTED_HALT_ACK_HASH, EXPECTED_HALT_ACK_COUNT),
    "halt_position_update": (
        EXPECTED_HALT_POSITION_UPDATE_HASH,
        EXPECTED_HALT_POSITION_UPDATE_COUNT,
    ),
    # Risk verdict action, reason, and scale.
    "risk_verdict": (EXPECTED_RISK_VERDICT_HASH, EXPECTED_RISK_VERDICT_COUNT),
    # Stage-0 dual-permission decoupling (design rev 5).  Promotion migrates a
    # gate-close FLAT off the SIGNAL Signal stream onto a typed SafetyStateChange
    # that a RISK-layer author converts to a flatten OrderRequest at a new
    # sequence.  These two baselines lock the shape of those new cross-layer
    # streams; the FLAT-migration itself is guarded in
    # test_decoupled_safety_replay.py.
    "decoupled_safety_state_change": (
        EXPECTED_DECOUPLED_SAFETY_STATE_CHANGE_HASH,
        EXPECTED_DECOUPLED_SAFETY_STATE_CHANGE_COUNT,
    ),
    "decoupled_risk_flatten_order": (
        EXPECTED_DECOUPLED_RISK_FLATTEN_ORDER_HASH,
        EXPECTED_DECOUPLED_RISK_FLATTEN_ORDER_COUNT,
    ),
}


def manifest_fingerprint() -> str:
    """Hash the sorted manifest so coordinated re-pins remain visible."""
    canonical = "\n".join(
        f"{name}|{hash_hex}|{count}"
        for name, (hash_hex, count) in sorted(LOCKED_PARITY_BASELINES.items())
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
