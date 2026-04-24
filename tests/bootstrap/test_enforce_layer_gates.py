"""``enforce_layer_gates`` flag — strict (default) vs research-mode.

When ``True`` (default, production posture) G1 / G3 violations raise
:class:`LayerValidationError`.  When ``False`` they downgrade to a
WARNING so researchers can iterate on cross-layer prototypes — but
G9 / G10 / G11 (data-integrity gates) **always** block, regardless of
the flag.
"""

from __future__ import annotations

import logging

import pytest

from feelies.alpha.layer_validator import LayerValidationError, LayerValidator


def _signal_with_universe_field() -> dict:
    """Schema-1.1 SIGNAL spec that violates G1 by declaring ``universe:``."""
    return {
        "schema_version": "1.1",
        "layer": "SIGNAL",
        "alpha_id": "alpha_a",
        "version": "1.0.0",
        "description": "x",
        "hypothesis": "h",
        "falsification_criteria": ["c"],
        "horizon_seconds": 300,
        "depends_on_sensors": ["s1"],
        "universe": ["AAPL"],  # G1 violation — PORTFOLIO-only field on SIGNAL
        "regime_gate": {
            "on_condition": "True",
            "off_condition": "False",
        },
        "cost_arithmetic": {
            "edge_estimate_bps": 5.0,
            "half_spread_bps": 1.0,
            "impact_bps": 0.5,
            "fee_bps": 0.5,
            "margin_ratio": 2.5,
        },
        "signal": "def evaluate(snapshot, regime, params):\n    return None\n",
    }


def _portfolio_missing_universe() -> dict:
    """Schema-1.1 PORTFOLIO spec that violates G10 (empty universe)."""
    return {
        "schema_version": "1.1",
        "layer": "PORTFOLIO",
        "alpha_id": "pofi_xsect_v1",
        "version": "1.0.0",
        "description": "x",
        "hypothesis": "h",
        "falsification_criteria": ["c"],
        "horizon_seconds": 300,
        "universe": [],  # G10 violation
        "depends_on_signals": ["alpha_a"],
        "factor_neutralization": True,
        "cost_arithmetic": {
            "edge_estimate_bps": 10.0,
            "half_spread_bps": 1.0,
            "impact_bps": 0.5,
            "fee_bps": 0.5,
            "margin_ratio": 5.0,
        },
    }


class TestEnforceLayerGates:

    def test_g1_blocks_when_strict(self) -> None:
        """Default ``enforce_layer_gates=True`` raises on G1 violation."""
        with pytest.raises(LayerValidationError, match="G1"):
            LayerValidator().validate(
                _signal_with_universe_field(), source="<test>",
            )

    def test_g1_warns_when_relaxed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``enforce_layer_gates=False`` downgrades G1 to a WARNING."""
        caplog.set_level(logging.WARNING, logger="feelies.alpha.layer_validator")
        LayerValidator(enforce_layer_gates=False).validate(
            _signal_with_universe_field(), source="<test>",
        )
        # The downgrade message must mention the gate id so operators
        # can grep for residual violations.
        warnings = [
            rec for rec in caplog.records
            if rec.levelno == logging.WARNING and "G1" in rec.message
        ]
        assert warnings, "expected G1 warning when enforce_layer_gates=False"

    def test_g10_always_blocks_regardless_of_flag(self) -> None:
        """G10 / G11 are data-integrity gates: never downgraded."""
        with pytest.raises(LayerValidationError, match="G10"):
            LayerValidator(enforce_layer_gates=False).validate(
                _portfolio_missing_universe(), source="<test>",
            )

    def test_g11_always_blocks_regardless_of_flag(self) -> None:
        """Missing factor_neutralization disclosure cannot be silenced."""
        spec = _portfolio_missing_universe()
        spec["universe"] = ["AAPL", "MSFT"]
        spec.pop("factor_neutralization")
        with pytest.raises(LayerValidationError, match="G11"):
            LayerValidator(enforce_layer_gates=False).validate(
                spec, source="<test>",
            )
