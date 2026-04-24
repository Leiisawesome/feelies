"""Smoke tests for the Phase-4 PORTFOLIO layer load path."""

from __future__ import annotations

import pytest

from feelies.alpha.loader import AlphaLoader, AlphaLoadError
from feelies.alpha.portfolio_layer_module import LoadedPortfolioLayerModule


def _portfolio_spec(**overrides) -> dict:
    spec: dict = {
        "schema_version": "1.1",
        "layer": "PORTFOLIO",
        "alpha_id": "pofi_xsect_v1",
        "version": "1.0.0",
        "description": "test cross-sectional",
        "hypothesis": "h",
        "falsification_criteria": ["c1"],
        "horizon_seconds": 300,
        "universe": ["AAPL", "MSFT", "GOOG"],
        "depends_on_signals": ["alpha_a"],
        "factor_neutralization": True,
        "cost_arithmetic": {
            "edge_estimate_bps": 10.0,
            "half_spread_bps": 1.0,
            "impact_bps": 0.5,
            "fee_bps": 0.5,
            "margin_ratio": 5.0,
        },
        "trend_mechanism": {
            "consumes": [
                {"family": "KYLE_INFO", "max_share_of_gross": 0.6},
                {"family": "INVENTORY", "max_share_of_gross": 0.4},
            ],
            "max_share_of_gross": 0.6,
        },
    }
    spec.update(overrides)
    return spec


def test_loader_dispatches_portfolio_layer():
    spec = _portfolio_spec()
    module = AlphaLoader().load_from_dict(spec, source="<test>")
    assert isinstance(module, LoadedPortfolioLayerModule)
    assert module.alpha_id == "pofi_xsect_v1"
    assert module.universe == ("AAPL", "GOOG", "MSFT")
    assert module.horizon_seconds == 300
    assert len(module.consumes_mechanisms) == 2
    assert module.max_share_of_gross == 0.6
    assert module.factor_neutralization_disclosed


def test_loader_rejects_signal_with_universe_field():
    """G1 — SIGNAL specs may not declare PORTFOLIO-only fields."""
    spec = {
        "schema_version": "1.1",
        "layer": "SIGNAL",
        "alpha_id": "alpha_a",
        "version": "1.0.0",
        "description": "x",
        "hypothesis": "h",
        "falsification_criteria": ["c"],
        "horizon_seconds": 300,
        "depends_on_sensors": ["s1"],
        "universe": ["AAPL"],
        "regime_gate": {"on_condition": "True", "off_condition": "False"},
        "cost_arithmetic": {
            "edge_estimate_bps": 5.0,
            "half_spread_bps": 1.0,
            "impact_bps": 0.5,
            "fee_bps": 0.5,
            "margin_ratio": 1.5,
        },
        "signal": "def evaluate(snapshot, regime, params):\n    return None\n",
    }
    with pytest.raises(Exception, match="G1"):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_loader_rejects_portfolio_with_depends_on_sensors():
    spec = _portfolio_spec(depends_on_sensors=["sensor_x"])
    with pytest.raises(Exception, match="G1"):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_g11_requires_factor_neutralization_disclosure():
    spec = _portfolio_spec()
    spec.pop("factor_neutralization")
    with pytest.raises(Exception, match="G11"):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_g10_requires_universe_list():
    spec = _portfolio_spec(universe=[])
    with pytest.raises(Exception, match="G10"):
        AlphaLoader().load_from_dict(spec, source="<test>")
