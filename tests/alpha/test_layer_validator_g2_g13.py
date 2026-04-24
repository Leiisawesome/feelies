"""Tests for the Phase-3-α active gates G2-G13 in :mod:`feelies.alpha.layer_validator`.

Each test uses a minimal valid SIGNAL spec template and mutates exactly
the field under test so failure messages cite the specific gate.

Gate matrix:

* G2  — typed event contract  (signal: must be a non-empty string)
* G4  — regime-gate purity     (DSL parse must succeed, whitelist only)
* G5  — signal purity          (no import/exec/eval/__builtins__/etc.)
* G6  — feature/sensor DAG     (depends_on_sensors non-empty + unique)
* G7  — horizon registration   (horizon_seconds in registry)
* G8  — no implicit lookahead  (no time/datetime/now refs)
* G12 — cost arithmetic block  (delegated to CostArithmetic.from_spec)
* G13 — warm-up documentation  (LEGACY_SIGNAL only)
"""

from __future__ import annotations

import copy

import pytest

from feelies.alpha.layer_validator import (
    DEFAULT_REGISTERED_HORIZONS,
    LayerValidationError,
    LayerValidator,
)


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
        "signal": (
            "def evaluate(snapshot, regime, params):\n"
            "    return None\n"
        ),
    }


def _legacy_spec() -> dict:
    return {
        "schema_version": "1.1",
        "layer": "LEGACY_SIGNAL",
        "alpha_id": "alpha_x",
        "version": "1.0.0",
        "description": "test alpha",
        "hypothesis": "test hypothesis",
        "falsification_criteria": ["criterion 1"],
        "features": {
            "f1": {
                "version": "1.0.0",
                "description": "x",
                "computation": (
                    "def initial_state():\n"
                    "    return {}\n"
                    "def update(quote, state, params):\n"
                    "    return 0.0\n"
                ),
                "warm_up": {"min_events": 5},
            },
        },
        "signal": (
            "def evaluate(features, params):\n"
            "    return None\n"
        ),
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
        _signal_spec(), source="<test>",
    )


def test_legacy_spec_passes_all_gates() -> None:
    _validator().validate(_legacy_spec(), source="<test>")


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


@pytest.mark.parametrize("snippet", [
    "import os\n",
    "from os import path\n",
    "x = exec('1 + 1')\n",
    "x = eval('1 + 1')\n",
    "x = open('hack')\n",
    "global x\n",
    "x = __import__('os')\n",
])
def test_g5_rejects_banned_constructs(snippet: str) -> None:
    spec = _signal_spec()
    spec["signal"] = (
        "def evaluate(snapshot, regime, params):\n"
        f"    {snippet}"
        "    return None\n"
    )
    # ``global`` requires being inside a function — wrap accordingly.
    if snippet.startswith("global"):
        spec["signal"] = (
            "x = 0\n"
            "def evaluate(snapshot, regime, params):\n"
            "    global x\n"
            "    return None\n"
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
        spec, source="<test>",
    )


# ── G6 — feature/sensor dependency DAG ──────────────────────────────────


def test_g6_rejects_empty_depends_on_sensors() -> None:
    spec = _signal_spec()
    spec["depends_on_sensors"] = []
    with pytest.raises(LayerValidationError, match="G6"):
        _validator().validate(spec, source="<test>")


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
            spec, source="<test>",
        )


def test_g6_skips_registry_check_when_unknown() -> None:
    """When known_sensor_ids is None the resolution check is skipped."""
    spec = _signal_spec()
    spec["depends_on_sensors"] = ["totally_made_up_sensor"]
    _validator(sensors=None).validate(spec, source="<test>")


def test_g6_legacy_feature_self_loop() -> None:
    spec = _legacy_spec()
    spec["features"]["f1"]["depends_on"] = ["f1"]
    with pytest.raises(LayerValidationError, match="G6"):
        _validator().validate(spec, source="<test>")


def test_g6_legacy_feature_cycle() -> None:
    spec = _legacy_spec()
    spec["features"]["f1"]["depends_on"] = ["f2"]
    spec["features"]["f2"] = copy.deepcopy(spec["features"]["f1"])
    spec["features"]["f2"]["depends_on"] = ["f1"]
    with pytest.raises(LayerValidationError, match="G6"):
        _validator().validate(spec, source="<test>")


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
    spec["signal"] = (
        "def evaluate(snapshot, regime, params):\n"
        "    t = time\n"
        "    return None\n"
    )
    with pytest.raises(LayerValidationError, match="G8"):
        _validator().validate(spec, source="<test>")


def test_g8_rejects_now_in_signal() -> None:
    spec = _signal_spec()
    spec["signal"] = (
        "def evaluate(snapshot, regime, params):\n"
        "    t = now()\n"
        "    return None\n"
    )
    with pytest.raises(LayerValidationError, match="G8"):
        _validator().validate(spec, source="<test>")


def test_g8_rejects_datetime_in_legacy_feature() -> None:
    spec = _legacy_spec()
    spec["features"]["f1"]["computation"] = (
        "def initial_state():\n"
        "    return {}\n"
        "def update(quote, state, params):\n"
        "    return datetime\n"
    )
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


# ── G13 — warm-up documentation (LEGACY_SIGNAL only) ────────────────────


def test_g13_rejects_legacy_feature_missing_warmup() -> None:
    spec = _legacy_spec()
    spec["features"]["f1"].pop("warm_up")
    with pytest.raises(LayerValidationError, match="G13"):
        _validator().validate(spec, source="<test>")


def test_g13_rejects_legacy_warmup_without_required_keys() -> None:
    spec = _legacy_spec()
    spec["features"]["f1"]["warm_up"] = {"unrelated": 0}
    with pytest.raises(LayerValidationError, match="G13"):
        _validator().validate(spec, source="<test>")


def test_g13_signal_layer_no_op() -> None:
    """SIGNAL alphas don't have inline features — G13 is skipped."""
    _validator(sensors=frozenset({"ofi_ewma", "spread_z_30d"})).validate(
        _signal_spec(), source="<test>",
    )
