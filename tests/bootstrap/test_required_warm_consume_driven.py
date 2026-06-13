"""Consume-driven required_warm derivation (audit 2P-1).

The platform must gate a SIGNAL alpha's entry only on the features it actually
reads (``snapshot.values.get("…")``), not on every feature of every declared
sensor.  These tests lock the static extractor and its conservative fallback.
"""

from __future__ import annotations

from feelies.bootstrap import (
    _consumed_value_keys_from_signal_source,
    _required_warm_feature_ids_for_signal_alpha,
)
from feelies.features.impl.horizon_windowed import HorizonWindowedFeature
from feelies.features.impl.sensor_passthrough import SensorPassthroughFeature
from feelies.signals.regime_gate import RegimeGate


# ── Static key extraction ───────────────────────────────────────────────────


def test_extracts_literal_get_and_subscript_keys() -> None:
    src = (
        "def evaluate(snapshot, regime, params):\n"
        "    a = snapshot.values.get('ofi_ewma_zscore')\n"
        "    b = snapshot.values.get('book_imbalance', 0.0)\n"
        "    c = snapshot.values['spread_z_30d']\n"
        "    return None\n"
    )
    assert _consumed_value_keys_from_signal_source(src) == frozenset(
        {"ofi_ewma_zscore", "book_imbalance", "spread_z_30d"}
    )


def test_dynamic_key_forces_conservative_none() -> None:
    src = (
        "def evaluate(snapshot, regime, params):\n"
        "    key = 'ofi_ewma_zscore'\n"
        "    return snapshot.values.get(key)\n"
    )
    assert _consumed_value_keys_from_signal_source(src) is None


def test_aliased_values_forces_conservative_none() -> None:
    src = (
        "def evaluate(snapshot, regime, params):\n"
        "    v = snapshot.values\n"
        "    return v.get('ofi_ewma_zscore')\n"
    )
    # ``v = snapshot.values`` is an unresolved .values access → conservative.
    assert _consumed_value_keys_from_signal_source(src) is None


def test_values_iteration_forces_conservative_none() -> None:
    src = (
        "def evaluate(snapshot, regime, params):\n"
        "    return sum(snapshot.values.values())\n"
    )
    assert _consumed_value_keys_from_signal_source(src) is None


def test_missing_or_unparseable_source_is_none() -> None:
    assert _consumed_value_keys_from_signal_source(None) is None
    assert _consumed_value_keys_from_signal_source("def evaluate(:") is None


# ── End-to-end required_warm ────────────────────────────────────────────────


def _gate() -> RegimeGate:
    return RegimeGate.from_spec(
        alpha_id="t",
        spec={
            "regime_engine": "hmm_3state_fractional",
            "on_condition": "P(normal) > 0.5 and spread_z_30d < 1.5",
            "off_condition": "P(normal) < 0.35",
        },
    )


def test_consume_driven_excludes_unread_features() -> None:
    """An alpha reading only ofi_ewma_zscore must not be gated on the
    auxiliary ofi_ewma_integrated / passthrough features of the same sensor."""
    h = 120
    features = [
        SensorPassthroughFeature("ofi_ewma", h),
        HorizonWindowedFeature("ofi_ewma", h, reducer="zscore", feature_id="ofi_ewma_zscore"),
        HorizonWindowedFeature("ofi_ewma", h, reducer="sum", feature_id="ofi_ewma_integrated"),
        SensorPassthroughFeature("spread_z_30d", h),
    ]
    src = (
        "def evaluate(snapshot, regime, params):\n"
        "    return snapshot.values.get('ofi_ewma_zscore')\n"
    )
    req = _required_warm_feature_ids_for_signal_alpha(
        depends_on_sensors=("ofi_ewma", "spread_z_30d"),
        horizon_seconds=h,
        horizon_features=features,
        gate=_gate(),
        signal_source=src,
    )
    # Body reads ofi_ewma_zscore; gate reads spread_z_30d.
    assert "ofi_ewma_zscore" in req
    assert "spread_z_30d" in req  # gate identifier
    # The unread auxiliary + passthrough views are NOT required.
    assert "ofi_ewma_integrated" not in req
    assert "ofi_ewma" not in req


def test_conservative_fallback_requires_all_depended_features() -> None:
    """When the consumed keys cannot be resolved, fall back to every feature
    of every depended sensor (pre-2P-1 safe behaviour)."""
    h = 120
    features = [
        SensorPassthroughFeature("ofi_ewma", h),
        HorizonWindowedFeature("ofi_ewma", h, reducer="zscore", feature_id="ofi_ewma_zscore"),
        HorizonWindowedFeature("ofi_ewma", h, reducer="sum", feature_id="ofi_ewma_integrated"),
    ]
    dynamic_src = (
        "def evaluate(snapshot, regime, params):\n"
        "    k = 'ofi_ewma_zscore'\n"
        "    return snapshot.values.get(k)\n"
    )
    req = _required_warm_feature_ids_for_signal_alpha(
        depends_on_sensors=("ofi_ewma",),
        horizon_seconds=h,
        horizon_features=features,
        gate=_gate(),
        signal_source=dynamic_src,
    )
    assert {"ofi_ewma", "ofi_ewma_zscore", "ofi_ewma_integrated"} <= req
