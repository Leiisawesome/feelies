"""Consume-driven ``required_warm`` derivation.

The platform must gate a SIGNAL alpha's entry only on the features it actually
reads (``snapshot.values.get("…")``), not on every feature of every declared
sensor.  These tests lock the static extractor and its conservative fallback.
"""

from __future__ import annotations

from pathlib import Path

from feelies.alpha.loader import AlphaLoader
from feelies.bootstrap import _horizon_features_for
from feelies.alpha.dependency_graph import (
    consumed_features_for_signal_registration,
    consumed_value_keys_from_signal_source,
    required_warm_feature_ids_for_signal_alpha,
    warn_unread_sensor_dependencies,
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
    assert consumed_value_keys_from_signal_source(src) == frozenset(
        {"ofi_ewma_zscore", "book_imbalance", "spread_z_30d"}
    )


def test_dynamic_key_forces_conservative_none() -> None:
    src = (
        "def evaluate(snapshot, regime, params):\n"
        "    key = 'ofi_ewma_zscore'\n"
        "    return snapshot.values.get(key)\n"
    )
    assert consumed_value_keys_from_signal_source(src) is None


def test_aliased_values_forces_conservative_none() -> None:
    src = (
        "def evaluate(snapshot, regime, params):\n"
        "    v = snapshot.values\n"
        "    return v.get('ofi_ewma_zscore')\n"
    )
    # ``v = snapshot.values`` is an unresolved .values access → conservative.
    assert consumed_value_keys_from_signal_source(src) is None


def test_values_iteration_forces_conservative_none() -> None:
    src = "def evaluate(snapshot, regime, params):\n    return sum(snapshot.values.values())\n"
    assert consumed_value_keys_from_signal_source(src) is None


def test_missing_or_unparseable_source_is_none() -> None:
    assert consumed_value_keys_from_signal_source(None) is None
    assert consumed_value_keys_from_signal_source("def evaluate(:") is None


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
    req = required_warm_feature_ids_for_signal_alpha(
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
    req = required_warm_feature_ids_for_signal_alpha(
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
    req = required_warm_feature_ids_for_signal_alpha(
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

    req = required_warm_feature_ids_for_signal_alpha(
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
    req = required_warm_feature_ids_for_signal_alpha(
        depends_on_sensors=module.depends_on_sensors,
        horizon_seconds=module.horizon_seconds,
        horizon_features=features,
        gate=module.gate,
        signal_source=module.signal_source,
    )

    consumed = consumed_features_for_signal_registration(
        declared_consumed_features=module.consumed_features,
        required_warm_feature_ids=req,
    )

    assert consumed == (
        "quote_hazard_rate",
        "quote_replenish_asymmetry_zscore",
        "realized_vol_30s_zscore",
        "spread_z_30d",
    )


# Unread sensor dependency warning.


def test_warns_on_declared_sensor_whose_features_are_never_read(caplog) -> None:
    """A sensor whose full horizon feature set is disjoint from warm_ids —
    i.e. neither evaluate() nor the regime gate reads any feature it
    produces — must be flagged.  This is the shape of the ``micro_price``
    failure mode covered by ``sig_benign_midcap_v1``."""
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
    warm_ids = required_warm_feature_ids_for_signal_alpha(
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
        warn_unread_sensor_dependencies(
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
        warn_unread_sensor_dependencies(
            alpha_id="alpha_x",
            depends_on_sensors=("inventory_pressure",),
            horizon_seconds=120,
            horizon_features=[],  # nothing registered for this sensor at h=120
            warm_ids=frozenset(),
        )
    assert not caplog.records


def test_sig_benign_midcap_v1_has_no_unread_sensor_dependency(caplog) -> None:
    """Every declared sensor dependency must be read by evaluation or a gate."""
    import logging

    module = AlphaLoader(enforce_trend_mechanism=True).load(
        Path("alphas/sig_benign_midcap_v1/sig_benign_midcap_v1.alpha.yaml")
    )
    features = []
    for sensor_id in module.depends_on_sensors:
        features.extend(_horizon_features_for(sensor_id, module.horizon_seconds))
    warm_ids = required_warm_feature_ids_for_signal_alpha(
        depends_on_sensors=module.depends_on_sensors,
        horizon_seconds=module.horizon_seconds,
        horizon_features=features,
        gate=module.gate,
        signal_source=module.signal_source,
    )

    with caplog.at_level(logging.WARNING, logger="feelies.bootstrap"):
        warn_unread_sensor_dependencies(
            alpha_id=module.manifest.alpha_id,
            depends_on_sensors=module.depends_on_sensors,
            horizon_seconds=module.horizon_seconds,
            horizon_features=features,
            warm_ids=warm_ids,
        )
    assert not caplog.records


# ── Fail-safe direction of the static analysis ──────────────────────────
# Every unresolvable form must widen to "require everything warm". A narrower
# answer would let an alpha trade on a cold feature (Inv-11), so these pin the
# direction rather than just the happy path.


def test_unresolvable_value_access_forms_all_fall_back_to_none() -> None:
    unresolvable = {
        "aliased binding": "def evaluate(s, r, p):\n    v = s.values\n    return v.get('a')\n",
        "iteration": "def evaluate(s, r, p):\n    return list(s.values.items())\n",
        "dynamic get key": "def evaluate(s, r, p):\n    return s.values.get(p['k'])\n",
        "dynamic subscript": "def evaluate(s, r, p):\n    return s.values[p['k']]\n",
        "f-string key": "def evaluate(s, r, p):\n    return s.values[f'{p['k']}_z']\n",
        "keys()": "def evaluate(s, r, p):\n    return sorted(s.values.keys())\n",
    }
    for label, src in unresolvable.items():
        assert consumed_value_keys_from_signal_source(src) is None, (
            f"{label}: unresolvable access must widen to the conservative set, not a subset"
        )


def test_absent_or_unparseable_source_falls_back_to_none() -> None:
    assert consumed_value_keys_from_signal_source(None) is None
    assert consumed_value_keys_from_signal_source("") is None
    # A body that does not compile cannot be analysed; it must not read as
    # "consumes nothing".
    assert consumed_value_keys_from_signal_source("def evaluate(:\n") is None


def test_literal_forms_resolve_exactly() -> None:
    src = (
        "def evaluate(s, r, p):\n"
        "    a = s.values.get('ofi_ewma')\n"
        "    b = s.values['spread_z_30d']\n"
        "    c = s.values.get('vpin_50bucket', 0.0)\n"
        "    return a + b + c\n"
    )
    assert consumed_value_keys_from_signal_source(src) == frozenset(
        {"ofi_ewma", "spread_z_30d", "vpin_50bucket"}
    )


def test_one_dynamic_access_poisons_the_whole_result() -> None:
    """A body that reads two literals and one dynamic key is not partially known.

    Returning just the literals would under-declare the warm set.
    """
    src = (
        "def evaluate(s, r, p):\n"
        "    a = s.values.get('ofi_ewma')\n"
        "    b = s.values[p['dynamic']]\n"
        "    return a + b\n"
    )
    assert consumed_value_keys_from_signal_source(src) is None
