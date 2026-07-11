"""Horizon-feature factory wiring for ``inventory_pressure`` (Task 7 §14.3).

The sig_inventory_fade_v1 formal spec (docs/research/
sig_inventory_fade_v1_formal_spec.md §1.2) requires the last-of-horizon
passthrough at h=120 in addition to the original h=30 (G16 ratio
120/40 = 3.0 ∈ [0.5, 4.0] is legal for INVENTORY).  Longer horizons stay
deliberately unwired — a 300–1800 s window smears a 5–60 s half-life
reversion.
"""

from __future__ import annotations

from feelies.bootstrap import _horizon_features_for
from feelies.features.impl.sensor_passthrough import SensorPassthroughFeature


def test_inventory_pressure_passthrough_wired_at_30_and_120() -> None:
    for h in (30, 120):
        features = _horizon_features_for("inventory_pressure", h)
        assert len(features) == 1
        feature = features[0]
        assert isinstance(feature, SensorPassthroughFeature)
        assert feature.feature_id == "inventory_pressure"
        assert feature.horizon_seconds == h


def test_inventory_pressure_unwired_at_longer_horizons() -> None:
    for h in (300, 900, 1800):
        assert _horizon_features_for("inventory_pressure", h) == []
