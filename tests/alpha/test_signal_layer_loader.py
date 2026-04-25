"""Tests for the SIGNAL-layer load path of :class:`AlphaLoader` (Phase 3-α).

Covers :py:meth:`AlphaLoader.load_from_dict` dispatch on
``layer: SIGNAL`` and the helper methods
:py:meth:`_load_signal_layer`, :py:meth:`_parse_horizon_seconds`,
:py:meth:`_parse_depends_on_sensors`, :py:meth:`_extract_trend_metadata`,
and :py:meth:`_compile_signal_layer_evaluate`.

The reference YAML at ``alphas/pofi_benign_midcap_v1`` is used as the
canonical happy-path fixture.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from feelies.alpha.cost_arithmetic import CostArithmetic
from feelies.alpha.layer_validator import LayerValidationError
from feelies.alpha.loader import AlphaLoader, AlphaLoadError
from feelies.alpha.signal_layer_module import (
    LoadedSignalLayerModule,
    _CompiledHorizonSignal,
)
from feelies.signals.regime_gate import RegimeGate


# ``LayerValidator`` runs before the loader's own per-field checks, so
# many spec violations surface as ``LayerValidationError`` rather than
# ``AlphaLoadError``.  Both are fatal to the load and either is
# acceptable for a "spec rejected" assertion.
_LOAD_REJECTED = (AlphaLoadError, LayerValidationError)


REFERENCE_PATH = Path("alphas/pofi_benign_midcap_v1/pofi_benign_midcap_v1.alpha.yaml")


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


# ── Reference alpha (file-based) ───────────────────────────────────────


def test_reference_alpha_loads_from_file() -> None:
    m = AlphaLoader().load(str(REFERENCE_PATH))
    assert isinstance(m, LoadedSignalLayerModule)
    assert m.manifest.alpha_id == "pofi_benign_midcap_v1"
    assert m.manifest.layer == "SIGNAL"
    assert m.horizon_seconds == 120
    assert m.depends_on_sensors == ("ofi_ewma", "micro_price", "spread_z_30d")
    assert isinstance(m.gate, RegimeGate)
    assert isinstance(m.cost, CostArithmetic)
    assert m.cost.margin_ratio == pytest.approx(1.8)


# ── Dispatch ───────────────────────────────────────────────────────────


def test_dispatch_returns_signal_layer_module() -> None:
    m = AlphaLoader().load_from_dict(_signal_spec(), source="<test>")
    assert isinstance(m, LoadedSignalLayerModule)


def test_evaluate_returns_none_for_signal_layer_module() -> None:
    """Loaded SIGNAL alphas never participate in CompositeSignalEngine."""
    m = AlphaLoader().load_from_dict(_signal_spec(), source="<test>")
    assert m.evaluate(features=object()) is None  # type: ignore[arg-type]


def test_feature_definitions_empty_for_signal_layer() -> None:
    m = AlphaLoader().load_from_dict(_signal_spec(), source="<test>")
    assert tuple(m.feature_definitions()) == ()


def test_signal_attribute_is_compiled_callable() -> None:
    m = AlphaLoader().load_from_dict(_signal_spec(), source="<test>")
    assert isinstance(m.signal, _CompiledHorizonSignal)
    assert m.signal.signal_id == "alpha_x"


def test_consumed_features_default_to_depends_on_sensors() -> None:
    m = AlphaLoader().load_from_dict(_signal_spec(), source="<test>")
    assert m.consumed_features == ("ofi_ewma", "spread_z_30d")


# ── horizon_seconds parsing ─────────────────────────────────────────────


def test_horizon_seconds_must_be_int() -> None:
    spec = _signal_spec()
    spec["horizon_seconds"] = "120"
    with pytest.raises(_LOAD_REJECTED, match="horizon_seconds"):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_horizon_seconds_must_meet_minimum_floor() -> None:
    spec = _signal_spec()
    spec["horizon_seconds"] = 10
    with pytest.raises(_LOAD_REJECTED, match="horizon_seconds"):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_horizon_seconds_rejects_bool_subtype() -> None:
    spec = _signal_spec()
    spec["horizon_seconds"] = True
    with pytest.raises(_LOAD_REJECTED, match="horizon_seconds"):
        AlphaLoader().load_from_dict(spec, source="<test>")


# ── depends_on_sensors parsing ──────────────────────────────────────────


def test_depends_on_sensors_must_be_list() -> None:
    spec = _signal_spec()
    spec["depends_on_sensors"] = "ofi_ewma"
    with pytest.raises(_LOAD_REJECTED, match="depends_on_sensors"):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_depends_on_sensors_rejects_duplicates() -> None:
    spec = _signal_spec()
    spec["depends_on_sensors"] = ["ofi_ewma", "ofi_ewma"]
    with pytest.raises(_LOAD_REJECTED):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_depends_on_sensors_rejects_empty_string() -> None:
    spec = _signal_spec()
    spec["depends_on_sensors"] = ["ofi_ewma", "   "]
    with pytest.raises(_LOAD_REJECTED):
        AlphaLoader().load_from_dict(spec, source="<test>")


# ── cost_arithmetic + regime_gate are required ──────────────────────────


def test_missing_cost_arithmetic_rejected() -> None:
    spec = _signal_spec()
    spec.pop("cost_arithmetic")
    with pytest.raises(_LOAD_REJECTED):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_missing_regime_gate_rejected() -> None:
    spec = _signal_spec()
    spec.pop("regime_gate")
    with pytest.raises(_LOAD_REJECTED):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_invalid_regime_gate_dsl_rejected() -> None:
    spec = _signal_spec()
    spec["regime_gate"]["on_condition"] = "open('hack')"
    with pytest.raises(_LOAD_REJECTED):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_low_margin_cost_rejected() -> None:
    spec = _signal_spec()
    spec["cost_arithmetic"] = {
        "edge_estimate_bps": 4.0,
        "half_spread_bps": 2.0,
        "impact_bps": 2.0,
        "fee_bps": 1.0,
        "margin_ratio": 0.8,
    }
    with pytest.raises(_LOAD_REJECTED):
        AlphaLoader().load_from_dict(spec, source="<test>")


# ── inline signal: code compilation ─────────────────────────────────────


def test_signal_code_must_define_evaluate() -> None:
    spec = _signal_spec()
    spec["signal"] = "x = 1\n"
    with pytest.raises(_LOAD_REJECTED):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_signal_code_evaluate_must_be_3_arg() -> None:
    spec = _signal_spec()
    spec["signal"] = (
        "def evaluate(features, params):\n"
        "    return None\n"
    )
    with pytest.raises(_LOAD_REJECTED):
        AlphaLoader().load_from_dict(spec, source="<test>")


# ── trend_mechanism extraction (Phase 3.1 metadata) ─────────────────────


def test_trend_mechanism_default_none() -> None:
    m = AlphaLoader().load_from_dict(_signal_spec(), source="<test>")
    assert m.trend_mechanism_enum is None
    assert m.expected_half_life_seconds == 0


def test_trend_mechanism_extracts_enum_and_half_life() -> None:
    spec = _signal_spec()
    spec["horizon_seconds"] = 300
    spec["trend_mechanism"] = {
        "family": "KYLE_INFO",
        "expected_half_life_seconds": 600,
        "l1_signature_sensors": ["kyle_lambda_60s", "ofi_ewma"],
        "failure_signature": ["spread_z_30d > 2.5"],
    }
    m = AlphaLoader().load_from_dict(spec, source="<test>")
    assert m.trend_mechanism_enum is not None
    assert m.trend_mechanism_enum.name == "KYLE_INFO"
    assert m.expected_half_life_seconds == 600


def test_trend_mechanism_unknown_family_rejected() -> None:
    spec = _signal_spec()
    spec["trend_mechanism"] = {"family": "MADE_UP_FAMILY"}
    with pytest.raises(_LOAD_REJECTED):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_trend_mechanism_negative_half_life_rejected() -> None:
    spec = _signal_spec()
    spec["trend_mechanism"] = {
        "family": "KYLE_INFO",
        "expected_half_life_seconds": -1,
    }
    with pytest.raises(_LOAD_REJECTED):
        AlphaLoader().load_from_dict(spec, source="<test>")


# ── Schema 1.1 acceptance / LEGACY_SIGNAL retirement (workstream D.2) ──


def test_layer_legacy_signal_is_rejected_post_d2() -> None:
    """``layer: LEGACY_SIGNAL`` is hard-rejected by the loader.

    Workstream D.2 retired the per-tick legacy path entirely.  Any
    spec carrying the legacy layer must surface an :class:`AlphaLoadError`
    with a migration pointer; there is no longer a fallback constructor.
    """
    spec = _signal_spec()
    spec["layer"] = "LEGACY_SIGNAL"
    with pytest.raises(_LOAD_REJECTED, match="LEGACY_SIGNAL"):
        AlphaLoader().load_from_dict(spec, source="<test>")


# ── Manifest fields preserved end-to-end ───────────────────────────────


def test_manifest_layer_and_falsification_criteria_propagate() -> None:
    spec = copy.deepcopy(_signal_spec())
    spec["falsification_criteria"] = ["a", "b", "c"]
    m = AlphaLoader().load_from_dict(spec, source="<test>")
    assert m.manifest.layer == "SIGNAL"
    assert m.manifest.falsification_criteria == ("a", "b", "c")
