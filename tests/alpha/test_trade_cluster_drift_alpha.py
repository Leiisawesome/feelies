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
    prev_abs_z: float = 0.0,
    trade_flow_imbalance: float = 0.0,
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
            "sde_drift_state_4": prev_abs_z,
            "trade_flow_imbalance": trade_flow_imbalance,
        },
        warm=True,
        stale=False,
        event_count=100,
    )


def test_feature_ids_and_parameters() -> None:
    alpha = AlphaLoader().load(ALPHA_PATH)

    feature_ids = [feature.feature_id for feature in alpha.feature_definitions()]
    assert feature_ids == [
        "sde_drift_state_0",
        "sde_drift_state_1",
        "sde_drift_state_2",
        "sde_drift_state_3",
        "sde_drift_state_4",
        "trade_flow_imbalance",
    ]
    assert list(alpha.manifest.parameters) == [
        "drift_half_life_seconds",
        "vol_drift_ratio",
        "entry_z",
        "exit_fraction",
        "min_net_edge_bps",
        "huber_threshold",
        "regime_suppress_threshold",
    ]


def test_low_z_emits_flat() -> None:
    """z-score below exit band → FLAT."""
    alpha = AlphaLoader().load(ALPHA_PATH)

    signal = alpha.evaluate(
        _feature_vector(
            drift=0.02,
            drift_z=0.4,
            edge_mean_bps=0.6,
            edge_std_bps=0.2,
            prev_abs_z=0.0,
        )
    )
    assert signal is not None
    assert signal.direction == SignalDirection.FLAT


def test_crossing_entry_long() -> None:
    """z-score crosses entry_z upward with positive edge → LONG."""
    alpha = AlphaLoader().load(ALPHA_PATH)
    params = alpha.manifest.parameters

    signal = alpha.evaluate(
        _feature_vector(
            drift=0.02,
            drift_z=2.0,
            edge_mean_bps=1.6,
            edge_std_bps=0.2,
            prev_abs_z=0.4,
        )
    )
    assert signal is not None
    assert signal.direction == SignalDirection.LONG

    expected_edge = abs(1.6) - 0.2 - params["min_net_edge_bps"]
    assert signal.edge_estimate_bps == pytest.approx(expected_edge, abs=1e-12)


def test_no_crossing_above_threshold_holds() -> None:
    """Already above entry_z with positive edge, no crossing → None (hold)."""
    alpha = AlphaLoader().load(ALPHA_PATH)

    signal = alpha.evaluate(
        _feature_vector(
            drift=0.01,
            drift_z=1.8,
            edge_mean_bps=0.8,
            edge_std_bps=0.1,
            prev_abs_z=2.0,
        )
    )
    assert signal is None


def test_z_decay_emits_flat() -> None:
    """z-score decays below exit band → FLAT."""
    alpha = AlphaLoader().load(ALPHA_PATH)

    signal = alpha.evaluate(
        _feature_vector(
            drift=0.001,
            drift_z=0.2,
            edge_mean_bps=0.1,
            edge_std_bps=0.2,
            prev_abs_z=1.8,
        )
    )
    assert signal is not None
    assert signal.direction == SignalDirection.FLAT


def test_crossing_entry_short() -> None:
    """z-score crosses entry_z downward with negative edge → SHORT."""
    alpha = AlphaLoader().load(ALPHA_PATH)

    signal = alpha.evaluate(
        _feature_vector(
            drift=-0.02,
            drift_z=-2.3,
            edge_mean_bps=-1.8,
            edge_std_bps=0.2,
            prev_abs_z=0.2,
        )
    )
    assert signal is not None
    assert signal.direction == SignalDirection.SHORT


def test_trade_flow_opposition_suppresses_entry() -> None:
    """Entry conditions met but trade flow actively opposes → suppressed."""
    alpha = AlphaLoader().load(ALPHA_PATH)

    signal = alpha.evaluate(
        _feature_vector(
            drift=0.02,
            drift_z=2.0,
            edge_mean_bps=1.6,
            edge_std_bps=0.2,
            prev_abs_z=0.4,
            trade_flow_imbalance=-0.5,
        )
    )
    assert signal is None


def test_trade_flow_confirmation_allows_entry() -> None:
    """Entry conditions met with confirming trade flow → entry proceeds."""
    alpha = AlphaLoader().load(ALPHA_PATH)

    signal = alpha.evaluate(
        _feature_vector(
            drift=0.02,
            drift_z=2.0,
            edge_mean_bps=1.6,
            edge_std_bps=0.2,
            prev_abs_z=0.4,
            trade_flow_imbalance=0.3,
        )
    )
    assert signal is not None
    assert signal.direction == SignalDirection.LONG


def test_negative_edge_emits_flat() -> None:
    """Above exit band but edge is negative after deductions → FLAT."""
    alpha = AlphaLoader().load(ALPHA_PATH)

    signal = alpha.evaluate(
        _feature_vector(
            drift=0.01,
            drift_z=1.8,
            edge_mean_bps=0.3,
            edge_std_bps=0.5,
            prev_abs_z=2.0,
        )
    )
    assert signal is not None
    assert signal.direction == SignalDirection.FLAT


def test_cold_features_suppressed() -> None:
    """warm=False → no signal regardless of z-score."""
    alpha = AlphaLoader().load(ALPHA_PATH)

    fv = FeatureVector(
        timestamp_ns=1,
        correlation_id="corr-1",
        sequence=1,
        symbol="AAPL",
        feature_version="test",
        values={
            "sde_drift_state_0": 0.05,
            "sde_drift_state_1": 3.0,
            "sde_drift_state_2": 2.0,
            "sde_drift_state_3": 0.1,
            "sde_drift_state_4": 0.5,
        },
        warm=False,
        stale=False,
        event_count=10,
    )
    assert alpha.evaluate(fv) is None


def test_stale_features_suppressed() -> None:
    """stale=True → no signal regardless of z-score."""
    alpha = AlphaLoader().load(ALPHA_PATH)

    fv = FeatureVector(
        timestamp_ns=1,
        correlation_id="corr-1",
        sequence=1,
        symbol="AAPL",
        feature_version="test",
        values={
            "sde_drift_state_0": 0.05,
            "sde_drift_state_1": 3.0,
            "sde_drift_state_2": 2.0,
            "sde_drift_state_3": 0.1,
            "sde_drift_state_4": 0.5,
        },
        warm=True,
        stale=True,
        event_count=100,
    )
    assert alpha.evaluate(fv) is None
