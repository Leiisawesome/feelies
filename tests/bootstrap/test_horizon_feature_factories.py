"""Horizon-feature factory wiring (inventory_pressure + ofi_raw percentile).

The sig_inventory_fade_v1 formal spec (docs/research/
sig_inventory_fade_v1_formal_spec.md §1.2) requires the last-of-horizon
passthrough at h=120 in addition to the original h=30 (G16 ratio
120/40 = 3.0 ∈ [0.5, 4.0] is legal for INVENTORY).  Longer horizons stay
deliberately unwired — a 300–1800 s window smears a 5–60 s half-life
reversion.

H12 Phase A (sig_halfhour_clock_drift_h900_v1 formal-spec §1.2) adds
``ofi_integrated_percentile`` alongside ``ofi_integrated`` on the ofi_raw
factory line (kyle_lambda_60s percentile wiring precedent). H13 Phase A
consumes the same factory at h=1800 — no silent h=900 substitution.
"""

from __future__ import annotations

from feelies.bootstrap import _horizon_features_for
from feelies.features.impl.horizon_windowed import HorizonWindowedFeature
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


def test_ofi_raw_factory_emits_integrated_and_percentile_at_900() -> None:
    """H12 P0-1: ofi_integrated_percentile present at h=900 (canonical set)."""
    features = _horizon_features_for("ofi_raw", 900)
    by_id = {f.feature_id: f for f in features}
    assert set(by_id) == {"ofi_integrated", "ofi_integrated_percentile"}
    integ = by_id["ofi_integrated"]
    pctl = by_id["ofi_integrated_percentile"]
    assert isinstance(integ, HorizonWindowedFeature)
    assert isinstance(pctl, HorizonWindowedFeature)
    assert integ.horizon_seconds == 900
    assert pctl.horizon_seconds == 900
    assert integ._reducer == "sum"
    assert pctl._reducer == "percentile"


def test_ofi_raw_percentile_wired_across_canonical_horizons() -> None:
    """Factory is horizon-generic; H12 consumes h=900; H13 consumes h=1800."""
    for h in (30, 120, 300, 900, 1800):
        ids = {f.feature_id for f in _horizon_features_for("ofi_raw", h)}
        assert "ofi_integrated" in ids
        assert "ofi_integrated_percentile" in ids


def test_ofi_raw_factory_emits_integrated_and_percentile_at_1800() -> None:
    """H13 P0-1: ofi_integrated_percentile present at h=1800 (no silent h=900 sub)."""
    features = _horizon_features_for("ofi_raw", 1800)
    by_id = {f.feature_id: f for f in features}
    assert set(by_id) == {"ofi_integrated", "ofi_integrated_percentile"}
    integ = by_id["ofi_integrated"]
    pctl = by_id["ofi_integrated_percentile"]
    assert isinstance(integ, HorizonWindowedFeature)
    assert isinstance(pctl, HorizonWindowedFeature)
    assert integ.horizon_seconds == 1800
    assert pctl.horizon_seconds == 1800
    assert integ._reducer == "sum"
    assert pctl._reducer == "percentile"
