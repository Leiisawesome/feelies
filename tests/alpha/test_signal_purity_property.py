"""Purity property tests for the shipped SIGNAL alphas (audit P2 2026-07-02).

``HorizonSignal.evaluate`` is documented as a pure function (no per-instance
state, deterministic on identical inputs) and the loader's compiled-code
sandbox + AST purity scan (G5) enforce this structurally. This module adds
the missing executable check: for each production alpha, calling
``evaluate()`` twice with the *same* ``(snapshot, regime, params)`` triple
must produce equal ``Signal`` outputs and must not mutate ``params`` or
``snapshot.values`` — the two containers a buggy alpha body could plausibly
write through despite the sandbox (Inv-5).

Each fixture is hand-tuned to clear every gate in the corresponding alpha's
``evaluate()`` body so the comparison is meaningful (a ``None`` output can't
demonstrate output equality). See
``docs/audits/signal_alpha_audit_2026-07-02.md`` §4 for the per-alpha gating
logic each fixture exercises.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.core.events import HorizonFeatureSnapshot, Signal, SignalDirection


def _snapshot(values: dict[str, float]) -> HorizonFeatureSnapshot:
    return HorizonFeatureSnapshot(
        timestamp_ns=1_700_000_000_000_000_000,
        correlation_id="corr",
        sequence=1,
        symbol="AAPL",
        horizon_seconds=0,  # unused by evaluate() — only snapshot.values matters
        boundary_index=1,
        values=values,
        warm={k: True for k in values},
        stale={k: False for k in values},
    )


# One "fires" fixture per shipped SIGNAL alpha, tuned to clear every
# threshold in its evaluate() body (percentile floors, z-score floors,
# hazard/window gates, cost floors) and to produce a non-FLAT direction.
_FIRING_SNAPSHOTS: dict[str, dict[str, float]] = {
    "sig_kyle_drift_v1": {
        "kyle_lambda_60s_percentile": 0.85,
        "kyle_lambda_60s_zscore": 3.0,
        "ofi_ewma": 0.8,
    },
    "sig_hawkes_burst_v1": {
        "hawkes_intensity_zscore": 3.0,
        "trade_through_rate": 0.7,
        "ofi_ewma": 0.5,
    },
    "sig_inventory_revert_v1": {
        "quote_replenish_asymmetry_zscore": 6.0,
        "quote_hazard_rate": 10.0,
    },
    "sig_moc_imbalance_v1": {
        "scheduled_flow_window_active": 1.0,
        "seconds_to_window_close": 300.0,
        "scheduled_flow_window_direction_prior": 1.0,
        "ofi_ewma": 0.5,
    },
    "sig_benign_midcap_v1": {
        "ofi_ewma_zscore": 2.0,
        "book_imbalance_mean": 0.3,
    },
}

_ALPHA_IDS = tuple(_FIRING_SNAPSHOTS)


@pytest.mark.parametrize("alpha_id", _ALPHA_IDS)
def test_evaluate_is_pure_and_does_not_mutate_inputs(alpha_id: str) -> None:
    path = Path("alphas") / alpha_id / f"{alpha_id}.alpha.yaml"
    loaded = AlphaLoader(enforce_trend_mechanism=True).load(str(path))
    assert isinstance(loaded, LoadedSignalLayerModule)

    snapshot = _snapshot(_FIRING_SNAPSHOTS[alpha_id])
    params = loaded.params  # one Mapping instance, reused across both calls
    # exactly as the engine reuses ``registered.params`` across dispatches.
    params_before = dict(params)
    values_before = dict(snapshot.values)

    first = loaded.signal.evaluate(snapshot, None, params)
    second = loaded.signal.evaluate(snapshot, None, params)

    assert isinstance(first, Signal), f"{alpha_id}: fixture must trigger a real emission"
    assert first.direction is not SignalDirection.FLAT
    assert first == second, f"{alpha_id}: evaluate() is not deterministic across identical calls"
    assert dict(params) == params_before, f"{alpha_id}: evaluate() mutated params"
    assert dict(snapshot.values) == values_before, (
        f"{alpha_id}: evaluate() mutated snapshot.values"
    )
