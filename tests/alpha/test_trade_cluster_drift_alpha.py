from __future__ import annotations

from pathlib import Path

import pytest

from feelies.alpha.loader import AlphaLoader
from feelies.core.events import FeatureVector, SignalDirection


ALPHA_PATH = (
    Path(__file__).resolve().parents[2]
    / "alphas"
    / "trade_cluster_drift"
    / "trade_cluster_drift.alpha.yaml"
)


def _feature_vector(
    drift: float,
    drift_z: float,
    edge_mean_bps: float,
    edge_std_bps: float,
) -> FeatureVector:
    return FeatureVector(
        timestamp_ns=1,
        correlation_id="corr-1",
        sequence=1,
        symbol="AAPL",
        feature_version="test",
        values={
            "sde_drift_state_0": drift,
            "sde_drift_state_1": drift_z,
            "sde_drift_state_2": edge_mean_bps,
            "sde_drift_state_3": edge_std_bps,
        },
        warm=True,
        stale=False,
        event_count=100,
    )


def test_trade_cluster_drift_rewrite_is_single_sde_feature() -> None:
    alpha = AlphaLoader().load(ALPHA_PATH)

    feature_ids = [feature.feature_id for feature in alpha.feature_definitions()]
    assert feature_ids == [
        "sde_drift_state_0",
        "sde_drift_state_1",
        "sde_drift_state_2",
        "sde_drift_state_3",
    ]
    assert list(alpha.manifest.parameters) == [
        "drift_half_life_seconds",
        "vol_half_life_seconds",
        "entry_z",
        "edge_confidence_z",
        "exit_threshold",
        "cost_floor_bps",
    ]


def test_trade_cluster_drift_signal_policy_uses_only_sde_state() -> None:
    alpha = AlphaLoader().load(ALPHA_PATH)

    long_signal = alpha.evaluate(
        _feature_vector(
            drift=0.02,
            drift_z=0.4,
            edge_mean_bps=0.6,
            edge_std_bps=0.2,
        )
    )
    assert long_signal is not None
    assert long_signal.direction == SignalDirection.FLAT

    long_signal = alpha.evaluate(
        _feature_vector(
            drift=0.02,
            drift_z=2.0,
            edge_mean_bps=1.6,
            edge_std_bps=0.2,
        )
    )
    assert long_signal is not None
    assert long_signal.direction == SignalDirection.LONG
    expected_edge = (
        abs(1.6)
        - alpha.manifest.parameters["edge_confidence_z"] * 0.2
        - alpha.manifest.parameters["cost_floor_bps"]
    )
    assert long_signal.edge_estimate_bps == pytest.approx(expected_edge, abs=1e-12)

    hold_signal = alpha.evaluate(
        _feature_vector(
            drift=0.01,
            drift_z=1.8,
            edge_mean_bps=0.8,
            edge_std_bps=0.6,
        )
    )
    assert hold_signal is None

    flat_signal = alpha.evaluate(
        _feature_vector(
            drift=0.001,
            drift_z=0.2,
            edge_mean_bps=0.1,
            edge_std_bps=0.2,
        )
    )
    assert flat_signal is not None
    assert flat_signal.direction == SignalDirection.FLAT

    short_signal = alpha.evaluate(
        _feature_vector(
            drift=-0.02,
            drift_z=-2.3,
            edge_mean_bps=-1.8,
            edge_std_bps=0.2,
        )
    )
    assert short_signal is not None
    assert short_signal.direction == SignalDirection.SHORT