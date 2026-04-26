"""Workstream F-5 loader tests for the optional ``promotion:`` block.

Pins the loader-side contract for per-alpha gate-threshold overrides
declared inline in ``.alpha.yaml``:

  * **Absent block** — manifest's ``gate_thresholds_overrides`` field
    is ``None`` (backwards-compat with every alpha that pre-dates F-5).
  * **Empty / missing ``gate_thresholds:`` sub-block** — same
    semantics as absent.  The platform-level defaults (and skill
    defaults beneath them) flow through unchanged.
  * **Non-mapping ``promotion:``** — :class:`AlphaLoadError`.
  * **Unknown top-level keys under ``promotion:``** —
    :class:`AlphaLoadError` (only ``gate_thresholds`` is recognised
    today; future blocks like ``capital_tier`` will live here).
  * **Unknown override keys under ``promotion.gate_thresholds:``** —
    :class:`AlphaLoadError` listing the offending keys.
  * **Bad value types** (string for a numeric field, bool for an int
    field, etc.) — :class:`AlphaLoadError`.
  * **Well-formed partial overrides** — survive the round-trip onto
    :attr:`AlphaManifest.gate_thresholds_overrides` as a dict whose
    values have been coerced into the dataclass's declared scalar
    types.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from feelies.alpha.layer_validator import LayerValidationError
from feelies.alpha.loader import AlphaLoadError, AlphaLoader

_LOAD_REJECTED = (AlphaLoadError, LayerValidationError)


_SIGNAL_BASE_SPEC: dict[str, Any] = {
    "schema_version": "1.1",
    "layer": "SIGNAL",
    "alpha_id": "f5_promotion_block_test",
    "version": "1.0.0",
    "description": "F-5 promotion-block parsing test fixture",
    "hypothesis": "Loader-shape fixture for the F-5 promotion block.",
    "falsification_criteria": ["fails by construction"],
    "horizon_seconds": 120,
    "depends_on_sensors": ["ofi_ewma"],
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
    out = copy.deepcopy(_SIGNAL_BASE_SPEC)
    out.update(overrides)
    return out


# ── Absent / empty block ────────────────────────────────────────────


def test_promotion_absent_yields_none_on_manifest() -> None:
    loaded = AlphaLoader().load_from_dict(_spec(), source="<test>")
    assert loaded.manifest.gate_thresholds_overrides is None


def test_promotion_block_with_no_gate_thresholds_yields_none() -> None:
    loaded = AlphaLoader().load_from_dict(
        _spec(promotion={}), source="<test>"
    )
    assert loaded.manifest.gate_thresholds_overrides is None


def test_promotion_block_with_empty_gate_thresholds_yields_none() -> None:
    loaded = AlphaLoader().load_from_dict(
        _spec(promotion={"gate_thresholds": {}}), source="<test>"
    )
    assert loaded.manifest.gate_thresholds_overrides is None


# ── Structural rejection ────────────────────────────────────────────


def test_promotion_block_non_mapping_rejected() -> None:
    with pytest.raises(_LOAD_REJECTED, match="promotion.*must be a mapping"):
        AlphaLoader().load_from_dict(
            _spec(promotion=["nope"]), source="<test>"
        )


def test_promotion_block_unknown_top_level_key_rejected() -> None:
    with pytest.raises(_LOAD_REJECTED, match="unknown key"):
        AlphaLoader().load_from_dict(
            _spec(promotion={"capital_tier": "SCALED"}),
            source="<test>",
        )


def test_promotion_gate_thresholds_non_mapping_rejected() -> None:
    with pytest.raises(_LOAD_REJECTED, match="gate_thresholds.*must be a mapping"):
        AlphaLoader().load_from_dict(
            _spec(promotion={"gate_thresholds": [1, 2, 3]}),
            source="<test>",
        )


# ── Per-key override validation ─────────────────────────────────────


def test_promotion_unknown_override_key_rejected() -> None:
    with pytest.raises(_LOAD_REJECTED, match="unknown field"):
        AlphaLoader().load_from_dict(
            _spec(promotion={"gate_thresholds": {"not_a_threshold": 1}}),
            source="<test>",
        )


def test_promotion_string_value_for_numeric_field_rejected() -> None:
    with pytest.raises(_LOAD_REJECTED, match="expects float"):
        AlphaLoader().load_from_dict(
            _spec(promotion={"gate_thresholds": {"dsr_min": "1.0"}}),
            source="<test>",
        )


def test_promotion_bool_value_for_int_field_rejected() -> None:
    with pytest.raises(_LOAD_REJECTED, match="expects int"):
        AlphaLoader().load_from_dict(
            _spec(
                promotion={
                    "gate_thresholds": {"paper_min_trading_days": True}
                }
            ),
            source="<test>",
        )


def test_promotion_float_value_for_int_field_rejected() -> None:
    with pytest.raises(_LOAD_REJECTED, match="expects int"):
        AlphaLoader().load_from_dict(
            _spec(
                promotion={
                    "gate_thresholds": {"paper_min_trading_days": 7.5}
                }
            ),
            source="<test>",
        )


# ── Round-trip onto the manifest ────────────────────────────────────


def test_promotion_partial_overrides_round_trip_onto_manifest() -> None:
    loaded = AlphaLoader().load_from_dict(
        _spec(
            promotion={
                "gate_thresholds": {
                    "dsr_min": 1.5,
                    "paper_min_trading_days": 7,
                }
            }
        ),
        source="<test>",
    )
    overrides = loaded.manifest.gate_thresholds_overrides
    assert overrides is not None
    assert overrides == {"dsr_min": 1.5, "paper_min_trading_days": 7}
    # Type coercion happened at parse time so the registry merge step
    # never has to second-guess a YAML int-vs-float.
    assert isinstance(overrides["dsr_min"], float)
    assert isinstance(overrides["paper_min_trading_days"], int)


def test_promotion_int_value_for_float_field_coerced() -> None:
    loaded = AlphaLoader().load_from_dict(
        _spec(promotion={"gate_thresholds": {"dsr_min": 2}}),
        source="<test>",
    )
    overrides = loaded.manifest.gate_thresholds_overrides
    assert overrides is not None
    assert overrides["dsr_min"] == 2.0
    assert isinstance(overrides["dsr_min"], float)


# ── PORTFOLIO layer also accepts the block ─────────────────────────


_PORTFOLIO_BASE_SPEC: dict[str, Any] = {
    "schema_version": "1.1",
    "layer": "PORTFOLIO",
    "alpha_id": "f5_portfolio_promotion_block_test",
    "version": "1.0.0",
    "description": "F-5 portfolio promotion-block parsing test",
    "hypothesis": "Loader-shape fixture for the F-5 promotion block.",
    "falsification_criteria": ["fails by construction"],
    "horizon_seconds": 300,
    "universe": ["AAPL", "MSFT"],
    "depends_on_signals": ["upstream_signal_v1"],
    "factor_neutralization": False,
    "cost_arithmetic": {
        "edge_estimate_bps": 9.0,
        "half_spread_bps": 2.0,
        "impact_bps": 2.0,
        "fee_bps": 1.0,
        "margin_ratio": 1.8,
    },
}


def _portfolio_spec(**overrides: object) -> dict[str, Any]:
    out = copy.deepcopy(_PORTFOLIO_BASE_SPEC)
    out.update(overrides)
    return out


def test_portfolio_promotion_absent_yields_none_on_manifest() -> None:
    loaded = AlphaLoader().load_from_dict(
        _portfolio_spec(), source="<test>"
    )
    assert loaded.manifest.gate_thresholds_overrides is None


def test_portfolio_promotion_partial_overrides_round_trip() -> None:
    loaded = AlphaLoader().load_from_dict(
        _portfolio_spec(
            promotion={"gate_thresholds": {"dsr_min": 1.8}},
        ),
        source="<test>",
    )
    overrides = loaded.manifest.gate_thresholds_overrides
    assert overrides == {"dsr_min": 1.8}


def test_portfolio_promotion_unknown_key_rejected() -> None:
    with pytest.raises(_LOAD_REJECTED, match="unknown field"):
        AlphaLoader().load_from_dict(
            _portfolio_spec(
                promotion={"gate_thresholds": {"bogus_key": 1}}
            ),
            source="<test>",
        )
