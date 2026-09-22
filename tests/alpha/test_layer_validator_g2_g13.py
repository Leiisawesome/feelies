"""Tests for active gates G2–G12 in :mod:`feelies.alpha.layer_validator`.

Each test uses a minimal valid SIGNAL spec template and mutates exactly
the field under test so failure messages cite the specific gate.

Only SIGNAL and PORTFOLIO specs are loadable:

* G2  — typed event contract  (signal: must be a non-empty string)
* G4  — regime-gate purity     (DSL parse must succeed, whitelist only)
* G5  — signal purity          (no import/exec/eval/__builtins__/etc.)
* G6  — feature/sensor DAG     (named sensors resolve; empty only with reads_no_sensor)
* G7  — horizon registration   (horizon_seconds in registry)
* G8  — no implicit lookahead  (no time/datetime/now refs in signal:)
* G12 — cost arithmetic block  (delegated to CostArithmetic.from_spec)

"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from feelies.alpha.dependency_graph import (
    required_warm_feature_ids_for_signal_alpha,
    warn_unread_sensor_dependencies,
)
from feelies.alpha.loader import AlphaLoader
from feelies.alpha.layer_validator import (
    DEFAULT_REGISTERED_HORIZONS,
    LayerValidationError,
    LayerValidator,
)
from feelies.features.impl.sensor_passthrough import SensorPassthroughFeature


# ── Spec templates ──────────────────────────────────────────────────────


def _signal_spec() -> dict:
    return {
        "schema_version": "1.1",
        "layer": "SIGNAL",
        "alpha_id": "alpha_x",
        "version": "1.0.0",
        "description": "test alpha",
        "hypothesis": "test hypothesis",
        "falsification_criteria": ["criterion 1"],
        "horizon_seconds": 120,
        "depends_on_sensors": ["ofi_ewma", "spread_z_30d"],
        "regime_gate": {
            "regime_engine": "hmm_3state_fractional",
            "on_condition": "P(normal) > 0.7",
            "off_condition": "P(normal) < 0.5",
        },
        "cost_arithmetic": {
            "edge_estimate_bps": 9.0,
            "half_spread_bps": 2.0,
            "impact_bps": 2.0,
            "fee_bps": 1.0,
            "margin_ratio": 1.8,
        },
        "signal": ("def evaluate(snapshot, regime, params):\n    return None\n"),
    }


def _validator(
    *,
    sensors: frozenset[str] | None = None,
    horizons: frozenset[int] | None = None,
) -> LayerValidator:
    return LayerValidator(
        registered_horizons=horizons or DEFAULT_REGISTERED_HORIZONS,
        known_sensor_ids=sensors,
    )


# ── Happy paths ─────────────────────────────────────────────────────────


def test_signal_spec_passes_all_gates() -> None:
    _validator(sensors=frozenset({"ofi_ewma", "spread_z_30d"})).validate(
        _signal_spec(),
        source="<test>",
    )


# ── G2 — event typing ──────────────────────────────────────────────────


def test_g2_rejects_non_string_signal() -> None:
    spec = _signal_spec()
    spec["signal"] = 123
    with pytest.raises(LayerValidationError, match="G2"):
        _validator().validate(spec, source="<test>")


def test_g2_rejects_empty_signal() -> None:
    spec = _signal_spec()
    spec["signal"] = "   "
    with pytest.raises(LayerValidationError, match="G2"):
        _validator().validate(spec, source="<test>")


# ── G4 — regime gate purity ─────────────────────────────────────────────


def test_g4_rejects_missing_regime_gate() -> None:
    spec = _signal_spec()
    spec.pop("regime_gate")
    with pytest.raises(LayerValidationError, match="G4"):
        _validator().validate(spec, source="<test>")


def test_g4_rejects_unsafe_dsl() -> None:
    spec = _signal_spec()
    spec["regime_gate"]["on_condition"] = "open('hack')"
    with pytest.raises(LayerValidationError, match="G4"):
        _validator().validate(spec, source="<test>")


def test_g4_rejects_empty_off_condition() -> None:
    spec = _signal_spec()
    spec["regime_gate"]["off_condition"] = ""
    with pytest.raises(LayerValidationError, match="G4"):
        _validator().validate(spec, source="<test>")


# ── G5 — signal purity ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "snippet",
    [
        "import os\n",
        "from os import path\n",
        "x = exec('1 + 1')\n",
        "x = eval('1 + 1')\n",
        "x = open('hack')\n",
        "global x\n",
        "x = __import__('os')\n",
    ],
)
def test_g5_rejects_banned_constructs(snippet: str) -> None:
    spec = _signal_spec()
    spec["signal"] = f"def evaluate(snapshot, regime, params):\n    {snippet}    return None\n"
    # ``global`` requires being inside a function — wrap accordingly.
    if snippet.startswith("global"):
        spec["signal"] = (
            "x = 0\ndef evaluate(snapshot, regime, params):\n    global x\n    return None\n"
        )
    with pytest.raises(LayerValidationError, match="G5"):
        _validator().validate(spec, source="<test>")


def test_g5_accepts_safe_snippet() -> None:
    spec = _signal_spec()
    spec["signal"] = (
        "def evaluate(snapshot, regime, params):\n"
        "    z = snapshot.values.get('ofi_ewma_zscore', 0.0)\n"
        "    return None\n"
    )
    _validator(sensors=frozenset({"ofi_ewma", "spread_z_30d"})).validate(
        spec,
        source="<test>",
    )


# ── G6 — feature/sensor dependency DAG ──────────────────────────────────


def test_g6_rejects_empty_depends_on_sensors() -> None:
    spec = _signal_spec()
    spec["depends_on_sensors"] = []
    with pytest.raises(LayerValidationError, match="G6"):
        _validator().validate(spec, source="<test>")


def test_g6_rejects_empty_depends_when_reads_no_sensor_is_false() -> None:
    """Absent or false keeps the forgotten-field guard."""
    spec = _signal_spec()
    spec["reads_no_sensor"] = False
    spec["depends_on_sensors"] = []
    with pytest.raises(LayerValidationError, match="G6"):
        _validator().validate(spec, source="<test>")


def test_g6_reads_no_sensor_empty_depends_loads_and_audit_is_silent(caplog) -> None:
    """reads_no_sensor: true with depends_on_sensors: [] loads, and the
    unused-dependency audit logs nothing."""
    spec = _signal_spec()
    spec["reads_no_sensor"] = True
    spec["depends_on_sensors"] = []
    _validator(sensors=frozenset({"ofi_ewma", "spread_z_30d"})).validate(
        spec,
        source="<test>",
    )
    features = [SensorPassthroughFeature("ofi_ewma", spec["horizon_seconds"])]
    with caplog.at_level(logging.WARNING, logger="feelies.alpha.dependency_graph"):
        warn_unread_sensor_dependencies(
            alpha_id=spec["alpha_id"],
            depends_on_sensors=spec["depends_on_sensors"],
            horizon_seconds=spec["horizon_seconds"],
            horizon_features=features,
            warm_ids=frozenset(),
        )
    assert not caplog.records


def test_g6_reads_no_sensor_rejects_evaluate_that_reads_snapshot_values() -> None:
    """reads_no_sensor is not an opt-out: evaluate that reads a feature raises."""
    spec = _signal_spec()
    spec["reads_no_sensor"] = True
    spec["depends_on_sensors"] = []
    spec["signal"] = (
        "def evaluate(snapshot, regime, params):\n    return snapshot.values['ofi_ewma']\n"
    )
    with pytest.raises(LayerValidationError, match="G6"):
        _validator().validate(spec, source="<test>")


def test_g6_reads_no_sensor_rejects_unresolvable_snapshot_values_access() -> None:
    """An unresolved .values access is not an empty read; the warm-set scan
    returns None for it, and reads_no_sensor must not treat that as clean."""
    spec = _signal_spec()
    spec["reads_no_sensor"] = True
    spec["depends_on_sensors"] = []
    spec["signal"] = (
        "def evaluate(snapshot, regime, params):\n    return snapshot.values[params['k']]\n"
    )
    with pytest.raises(LayerValidationError, match="G6"):
        _validator().validate(spec, source="<test>")


def test_g6_reads_no_sensor_rejects_regime_gate_feature_binding() -> None:
    """Regime-gate bindings are part of the warm-set scan."""
    spec = _signal_spec()
    spec["reads_no_sensor"] = True
    spec["depends_on_sensors"] = []
    spec["regime_gate"]["on_condition"] = "ofi_ewma > 0"
    with pytest.raises(LayerValidationError, match="G6"):
        _validator().validate(spec, source="<test>")


def test_g6_reads_no_sensor_rejects_nonempty_depends_on_sensors() -> None:
    """reads_no_sensor: true with a non-empty list contradicts itself."""
    spec = _signal_spec()
    spec["reads_no_sensor"] = True
    spec["depends_on_sensors"] = ["ofi_ewma"]
    with pytest.raises(LayerValidationError, match="G6"):
        _validator(sensors=frozenset({"ofi_ewma", "spread_z_30d"})).validate(
            spec,
            source="<test>",
        )


_CONTROL_FIXTURES = (
    Path("tests/conformance/fixtures/null_alpha/null_alpha.alpha.yaml"),
    Path("tests/conformance/fixtures/portfolio/upstream_signal.alpha.yaml"),
)


@pytest.mark.parametrize("path", _CONTROL_FIXTURES, ids=lambda p: p.parent.name)
def test_control_fixtures_audit_is_silent(path: Path, caplog) -> None:
    """Both control fixtures declare an empty sensor list and the unused-dependency audit is silent."""
    module = AlphaLoader(enforce_trend_mechanism=False).load(path)
    assert module.depends_on_sensors == ()
    features = [SensorPassthroughFeature("ofi_ewma", module.horizon_seconds)]
    warm_ids = required_warm_feature_ids_for_signal_alpha(
        depends_on_sensors=module.depends_on_sensors,
        horizon_seconds=module.horizon_seconds,
        horizon_features=features,
        gate=module.gate,
        signal_source=module.signal_source,
    )
    with caplog.at_level(logging.WARNING, logger="feelies.alpha.dependency_graph"):
        warn_unread_sensor_dependencies(
            alpha_id=module.manifest.alpha_id,
            depends_on_sensors=module.depends_on_sensors,
            horizon_seconds=module.horizon_seconds,
            horizon_features=features,
            warm_ids=warm_ids,
        )
    assert not caplog.records


def test_g6_rejects_non_string_entry() -> None:
    spec = _signal_spec()
    spec["depends_on_sensors"] = ["ofi_ewma", 123]
    with pytest.raises(LayerValidationError, match="G6"):
        _validator().validate(spec, source="<test>")


def test_g6_rejects_duplicate_sensor() -> None:
    spec = _signal_spec()
    spec["depends_on_sensors"] = ["ofi_ewma", "ofi_ewma"]
    with pytest.raises(LayerValidationError, match="duplicate"):
        _validator().validate(spec, source="<test>")


def test_g6_rejects_unknown_sensor_when_registry_known() -> None:
    spec = _signal_spec()
    spec["depends_on_sensors"] = ["ofi_ewma", "missing_sensor"]
    with pytest.raises(LayerValidationError, match="G6"):
        _validator(sensors=frozenset({"ofi_ewma"})).validate(
            spec,
            source="<test>",
        )


def test_g6_skips_registry_check_when_unknown() -> None:
    """When known_sensor_ids is None the resolution check is skipped."""
    spec = _signal_spec()
    spec["depends_on_sensors"] = ["totally_made_up_sensor"]
    _validator(sensors=None).validate(spec, source="<test>")


# ── G7 — horizon registration ───────────────────────────────────────────


def test_g7_rejects_unregistered_horizon() -> None:
    spec = _signal_spec()
    spec["horizon_seconds"] = 999
    with pytest.raises(LayerValidationError, match="G7"):
        _validator().validate(spec, source="<test>")


def test_g7_rejects_non_int_horizon() -> None:
    spec = _signal_spec()
    spec["horizon_seconds"] = 120.5
    with pytest.raises(LayerValidationError, match="G7"):
        _validator().validate(spec, source="<test>")


def test_g7_accepts_custom_registry() -> None:
    spec = _signal_spec()
    spec["horizon_seconds"] = 17
    _validator(horizons=frozenset({17, 120})).validate(spec, source="<test>")


# ── G8 — no implicit lookahead ──────────────────────────────────────────


def test_g8_rejects_time_in_signal() -> None:
    spec = _signal_spec()
    spec["signal"] = "def evaluate(snapshot, regime, params):\n    t = time\n    return None\n"
    with pytest.raises(LayerValidationError, match="G8"):
        _validator().validate(spec, source="<test>")


def test_g8_rejects_now_in_signal() -> None:
    spec = _signal_spec()
    spec["signal"] = "def evaluate(snapshot, regime, params):\n    t = now()\n    return None\n"
    with pytest.raises(LayerValidationError, match="G8"):
        _validator().validate(spec, source="<test>")


# ── G12 — cost arithmetic disclosure ────────────────────────────────────


def test_g12_rejects_missing_cost_block() -> None:
    spec = _signal_spec()
    spec.pop("cost_arithmetic")
    with pytest.raises(LayerValidationError, match="G12"):
        _validator().validate(spec, source="<test>")


def test_g12_rejects_low_margin_ratio() -> None:
    spec = _signal_spec()
    # edge=4.0, costs=2+2+1=5 -> ratio 0.8
    spec["cost_arithmetic"] = {
        "edge_estimate_bps": 4.0,
        "half_spread_bps": 2.0,
        "impact_bps": 2.0,
        "fee_bps": 1.0,
        "margin_ratio": 0.8,
    }
    with pytest.raises(LayerValidationError, match="G12"):
        _validator().validate(spec, source="<test>")


# ── G12 addendum — cost_floor_bps.min pinned to cost_total_bps ──────────
# Overrides cannot lower the floor below disclosed costs.


def test_g12_rejects_cost_floor_min_below_cost_total() -> None:
    spec = _signal_spec()  # cost_arithmetic totals 2.0+2.0+1.0 = 5.0
    spec["parameters"] = {
        "cost_floor_bps": {"type": "float", "default": 5.0, "min": 0.0, "max": 30.0},
    }
    with pytest.raises(LayerValidationError, match="G12"):
        _validator().validate(spec, source="<test>")


def test_g12_accepts_cost_floor_min_at_cost_total() -> None:
    spec = _signal_spec()  # cost_arithmetic totals 2.0+2.0+1.0 = 5.0
    spec["parameters"] = {
        "cost_floor_bps": {"type": "float", "default": 5.0, "min": 5.0, "max": 30.0},
    }
    _validator().validate(spec, source="<test>")  # no raise


def test_g12_accepts_cost_floor_min_above_cost_total() -> None:
    spec = _signal_spec()
    spec["parameters"] = {
        "cost_floor_bps": {"type": "float", "default": 6.0, "min": 6.0, "max": 30.0},
    }
    _validator().validate(spec, source="<test>")  # no raise


def test_g12_ignores_alphas_without_a_cost_floor_bps_parameter() -> None:
    spec = _signal_spec()
    spec["parameters"] = {
        "entry_threshold_z": {"type": "float", "default": 0.8, "min": 0.5, "max": 3.0},
    }
    _validator().validate(spec, source="<test>")  # no raise — no cost_floor_bps declared
