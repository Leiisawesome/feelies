"""Consume-driven required_warm derivation (audit 2P-1).

The platform must gate a SIGNAL alpha's entry only on the features it actually
reads (``snapshot.values.get("…")``), not on every feature of every declared
sensor.  These tests lock the static extractor and its conservative fallback.
"""

from __future__ import annotations

from pathlib import Path

from feelies.alpha.loader import AlphaLoader
from feelies.bootstrap import (
    _consumed_features_for_signal_registration,
    _consumed_value_keys_from_signal_source,
    _horizon_features_for,
    _required_warm_feature_ids_for_signal_alpha,
    _warn_unread_sensor_dependencies,
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
    src = "def evaluate(snapshot, regime, params):\n    return sum(snapshot.values.values())\n"
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


def test_gate_bare_identifier_prefers_exact_feature_over_derivatives() -> None:
    h = 30
    features = [
        SensorPassthroughFeature("quote_hazard_rate", h),
        HorizonWindowedFeature(
            "quote_hazard_rate",
            h,
            reducer="zscore",
            feature_id="quote_hazard_rate_zscore",
        ),
    ]
    gate = RegimeGate.from_spec(
        alpha_id="t",
        spec={
            "regime_engine": "hmm_3state_fractional",
            "on_condition": "quote_hazard_rate > 4.0",
            "off_condition": "quote_hazard_rate < 4.0",
        },
    )
    req = _required_warm_feature_ids_for_signal_alpha(
        depends_on_sensors=("quote_hazard_rate",),
        horizon_seconds=h,
        horizon_features=features,
        gate=gate,
        signal_source=(
            "def evaluate(snapshot, regime, params):\n"
            "    return snapshot.values.get('quote_hazard_rate')\n"
        ),
    )
    assert req == frozenset({"quote_hazard_rate"})


def test_inventory_revert_required_warm_excludes_unused_hazard_zscore() -> None:
    module = AlphaLoader(enforce_trend_mechanism=True).load(
        Path("alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml")
    )
    features = []
    for sensor_id in module.depends_on_sensors:
        features.extend(_horizon_features_for(sensor_id, module.horizon_seconds))

    req = _required_warm_feature_ids_for_signal_alpha(
        depends_on_sensors=module.depends_on_sensors,
        horizon_seconds=module.horizon_seconds,
        horizon_features=features,
        gate=module.gate,
        signal_source=module.signal_source,
    )

    assert req == frozenset(
        {
            "quote_hazard_rate",
            "quote_replenish_asymmetry_zscore",
            "realized_vol_30s_zscore",
            "spread_z_30d",
        }
    )


def test_inventory_revert_bootstrap_consumed_features_are_feature_ids() -> None:
    module = AlphaLoader(enforce_trend_mechanism=True).load(
        Path("alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml")
    )
    features = []
    for sensor_id in module.depends_on_sensors:
        features.extend(_horizon_features_for(sensor_id, module.horizon_seconds))
    req = _required_warm_feature_ids_for_signal_alpha(
        depends_on_sensors=module.depends_on_sensors,
        horizon_seconds=module.horizon_seconds,
        horizon_features=features,
        gate=module.gate,
        signal_source=module.signal_source,
    )

    consumed = _consumed_features_for_signal_registration(
        declared_consumed_features=module.consumed_features,
        required_warm_feature_ids=req,
    )

    assert consumed == (
        "quote_hazard_rate",
        "quote_replenish_asymmetry_zscore",
        "realized_vol_30s_zscore",
        "spread_z_30d",
    )


# ── Unread sensor dependency warning (sensor_audit_2026-07-02 P1) ───────────


def test_warns_on_declared_sensor_whose_features_are_never_read(caplog) -> None:
    """A sensor whose full horizon feature set is disjoint from warm_ids —
    i.e. neither evaluate() nor the regime gate reads any feature it
    produces — must be flagged.  This is the shape of the ``micro_price``
    defect this audit pass found (and fixed) in ``sig_benign_midcap_v1``."""
    import logging

    h = 120
    features = [
        SensorPassthroughFeature("ofi_ewma", h),
        HorizonWindowedFeature("ofi_ewma", h, reducer="zscore", feature_id="ofi_ewma_zscore"),
        SensorPassthroughFeature("micro_price", h),
        HorizonWindowedFeature(
            "micro_price", h, reducer="zscore", feature_id="micro_price_zscore"
        ),
    ]
    warm_ids = _required_warm_feature_ids_for_signal_alpha(
        depends_on_sensors=("ofi_ewma", "micro_price"),
        horizon_seconds=h,
        horizon_features=features,
        gate=_gate(),
        signal_source=(
            "def evaluate(snapshot, regime, params):\n"
            "    return snapshot.values.get('ofi_ewma_zscore')\n"
        ),
    )
    assert "micro_price" not in warm_ids
    assert "micro_price_zscore" not in warm_ids

    with caplog.at_level(logging.WARNING, logger="feelies.bootstrap"):
        _warn_unread_sensor_dependencies(
            alpha_id="alpha_x",
            depends_on_sensors=("ofi_ewma", "micro_price"),
            horizon_seconds=h,
            horizon_features=features,
            warm_ids=warm_ids,
        )

    messages = [r.message for r in caplog.records]
    assert any("micro_price" in m and "alpha_x" in m for m in messages)
    assert not any("'ofi_ewma'" in m for m in messages)  # the read sensor stays silent


def test_no_warning_when_sensor_produces_no_features_at_this_horizon(caplog) -> None:
    """A sensor with zero features at this horizon (e.g. inventory_pressure
    outside h=30) has nothing to compare against and must not be flagged —
    that gap belongs to the H3/M2 'uncovered dependency' check, not this
    one."""
    import logging

    with caplog.at_level(logging.WARNING, logger="feelies.bootstrap"):
        _warn_unread_sensor_dependencies(
            alpha_id="alpha_x",
            depends_on_sensors=("inventory_pressure",),
            horizon_seconds=120,
            horizon_features=[],  # nothing registered for this sensor at h=120
            warm_ids=frozenset(),
        )
    assert not caplog.records


def test_sig_benign_midcap_v1_has_no_unread_sensor_dependency(caplog) -> None:
    """Regression guard: the reference alpha's depends_on_sensors must stay
    fully backed by evaluate()/gate usage after the P1 micro_price fix."""
    import logging

    module = AlphaLoader(enforce_trend_mechanism=True).load(
        Path("alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml")
    )
    features = []
    for sensor_id in module.depends_on_sensors:
        features.extend(_horizon_features_for(sensor_id, module.horizon_seconds))
    warm_ids = _required_warm_feature_ids_for_signal_alpha(
        depends_on_sensors=module.depends_on_sensors,
        horizon_seconds=module.horizon_seconds,
        horizon_features=features,
        gate=module.gate,
        signal_source=module.signal_source,
    )

    with caplog.at_level(logging.WARNING, logger="feelies.bootstrap"):
        _warn_unread_sensor_dependencies(
            alpha_id=module.manifest.alpha_id,
            depends_on_sensors=module.depends_on_sensors,
            horizon_seconds=module.horizon_seconds,
            horizon_features=features,
            warm_ids=warm_ids,
        )
    assert not caplog.records
