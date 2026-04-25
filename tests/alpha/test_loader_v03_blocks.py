"""Phase-1.1 (v0.3) loader tests for ``trend_mechanism:`` and ``hazard_exit:``.

Covers the opt-in YAML blocks per §20.5 of
``design_docs/three_layer_architecture.md``:

  - Absent block ⇒ no enforcement, manifest field is ``None``.
  - Present, well-formed block on a SIGNAL alpha ⇒ accepted and
    stored verbatim on the loaded ``AlphaManifest``.
  - Malformed (non-mapping) block ⇒ rejected with a structured error.

**Workstream D.2.** Pre-D.2 these tests used a ``layer: LEGACY_SIGNAL``
base spec to bypass G16 and exercise only the schema-shape contract.
Post-D.2 the loader rejects ``LEGACY_SIGNAL`` outright, so the base
spec is now ``layer: SIGNAL`` and every accepted ``trend_mechanism:``
block has to be G16-compliant. Family-name *rejection* paths and
field-level enforcement live in
``tests/alpha/test_signal_layer_loader.py`` and
``tests/alpha/test_gate_g16{,_props}.py``; this file pins the loader
contract that an opt-in v0.3 block survives the round-trip onto
``AlphaManifest``.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from feelies.alpha.layer_validator import LayerValidationError
from feelies.alpha.loader import AlphaLoadError, AlphaLoader

# Loader-side schema rejections raise ``AlphaLoadError`` while
# G2-G16 violations raise ``LayerValidationError`` subclasses; both
# kill the load so either is acceptable for "block was rejected".
_LOAD_REJECTED = (AlphaLoadError, LayerValidationError)


_BASE_SPEC: dict[str, Any] = {
    "schema_version": "1.1",
    "layer": "SIGNAL",
    "alpha_id": "v03_block_test",
    "version": "1.0.0",
    "description": "v0.3 block parsing test",
    "hypothesis": "Loader-shape fixture for the v0.3 YAML blocks.",
    "falsification_criteria": ["fails by construction"],
    "horizon_seconds": 120,
    "depends_on_sensors": [
        "ofi_ewma",
        "spread_z_30d",
        "kyle_lambda_60s",
        "micro_price",
        "quote_replenish_asymmetry",
        "hawkes_intensity",
        "vpin_50bucket",
        "realized_vol_30s",
        "scheduled_flow_window",
    ],
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


def _spec(**overrides: object) -> dict[str, Any]:
    out = copy.deepcopy(_BASE_SPEC)
    out.update(overrides)
    return out


# ── G16-compliant trend_mechanism fixtures (one per family) ─────────────
#
# The half-life is chosen inside the per-family envelope AND so that
# ``horizon_seconds(120) / expected_half_life_seconds`` lands inside
# the [0.5, 4.0] gate-G16 ratio band.

_TREND_MECHANISM_FIXTURES: dict[str, dict[str, Any]] = {
    "KYLE_INFO": {
        "family": "KYLE_INFO",
        "expected_half_life_seconds": 120,
        "l1_signature_sensors": ["kyle_lambda_60s", "micro_price"],
        "failure_signature": [
            "kyle_lambda_60s deviation falls below 1σ for 30s",
        ],
    },
    "INVENTORY": {
        "family": "INVENTORY",
        "expected_half_life_seconds": 30,
        "l1_signature_sensors": ["quote_replenish_asymmetry"],
        "failure_signature": [
            "asymmetric replenishment dissipates within one horizon",
        ],
    },
    "HAWKES_SELF_EXCITE": {
        "family": "HAWKES_SELF_EXCITE",
        "expected_half_life_seconds": 30,
        "l1_signature_sensors": ["hawkes_intensity"],
        "failure_signature": ["intensity ratio reverts below 1.5 within 60s"],
    },
    "LIQUIDITY_STRESS": {
        "family": "LIQUIDITY_STRESS",
        "expected_half_life_seconds": 60,
        "l1_signature_sensors": ["vpin_50bucket", "realized_vol_30s"],
        "failure_signature": ["vpin recovery within one horizon"],
    },
    "SCHEDULED_FLOW": {
        "family": "SCHEDULED_FLOW",
        "expected_half_life_seconds": 60,
        "l1_signature_sensors": ["scheduled_flow_window"],
        "failure_signature": ["window passes without measurable flow"],
    },
}


# ── trend_mechanism: block ──────────────────────────────────────────────


def test_trend_mechanism_absent_yields_none_on_manifest() -> None:
    loaded = AlphaLoader().load_from_dict(_spec(), source="<test>")
    assert loaded.manifest.trend_mechanism is None


@pytest.mark.parametrize(
    "family",
    sorted(_TREND_MECHANISM_FIXTURES.keys()),
)
def test_trend_mechanism_known_family_accepted(family: str) -> None:
    block = copy.deepcopy(_TREND_MECHANISM_FIXTURES[family])
    loaded = AlphaLoader().load_from_dict(
        _spec(trend_mechanism=block), source="<test>"
    )
    assert loaded.manifest.trend_mechanism is not None
    assert loaded.manifest.trend_mechanism["family"] == family
    assert loaded.manifest.trend_mechanism[
        "expected_half_life_seconds"
    ] == block["expected_half_life_seconds"]


def test_trend_mechanism_non_mapping_rejected() -> None:
    with pytest.raises(_LOAD_REJECTED, match="trend_mechanism.*must be a mapping"):
        AlphaLoader().load_from_dict(
            _spec(trend_mechanism="KYLE_INFO"), source="<test>"
        )


def test_trend_mechanism_block_stored_verbatim_as_dict_copy() -> None:
    """Manifest must hold a *copy* — mutating loader inputs after the fact
    must not affect the manifest.
    """
    block = copy.deepcopy(_TREND_MECHANISM_FIXTURES["INVENTORY"])
    block["extra"] = {"nested": True}
    loaded = AlphaLoader().load_from_dict(
        _spec(trend_mechanism=block), source="<test>"
    )
    block["family"] = "KYLE_INFO"
    assert loaded.manifest.trend_mechanism is not None
    assert loaded.manifest.trend_mechanism["family"] == "INVENTORY"


# ── hazard_exit: block ──────────────────────────────────────────────────


def test_hazard_exit_absent_yields_none_on_manifest() -> None:
    loaded = AlphaLoader().load_from_dict(_spec(), source="<test>")
    assert loaded.manifest.hazard_exit is None


def test_hazard_exit_block_accepted_verbatim() -> None:
    block = {
        "trigger": "regime_hazard_spike",
        "min_hazard_score": 0.7,
        "exit_urgency": 0.9,
    }
    loaded = AlphaLoader().load_from_dict(
        _spec(hazard_exit=block), source="<test>"
    )
    assert loaded.manifest.hazard_exit == block


def test_hazard_exit_non_mapping_rejected() -> None:
    with pytest.raises(_LOAD_REJECTED, match="hazard_exit.*must be a mapping"):
        AlphaLoader().load_from_dict(
            _spec(hazard_exit=["regime_hazard_spike"]), source="<test>"
        )


# ── Combined block presence ─────────────────────────────────────────────


def test_both_v03_blocks_present_independently_stored() -> None:
    tm = copy.deepcopy(_TREND_MECHANISM_FIXTURES["HAWKES_SELF_EXCITE"])
    he = {"trigger": "regime_hazard_spike"}
    loaded = AlphaLoader().load_from_dict(
        _spec(trend_mechanism=tm, hazard_exit=he), source="<test>"
    )
    assert loaded.manifest.trend_mechanism == tm
    assert loaded.manifest.hazard_exit == he
