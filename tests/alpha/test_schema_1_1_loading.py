"""Loader tests for schema 1.1 layer dispatch and validation."""

from __future__ import annotations

import copy

import pytest

from feelies.alpha.layer_validator import LayerValidationError
from feelies.alpha.loader import AlphaLoadError, AlphaLoader


# Minimal valid signal spec.


_BASE_SPEC = {
    "alpha_id": "schema_test_alpha",
    "version": "1.0.0",
    "description": "schema dispatch test",
    "hypothesis": "No real hypothesis; this is a loader-shape fixture.",
    "falsification_criteria": ["fails by construction"],
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


def _spec(**overrides: object) -> dict[str, object]:
    """Return a deep-copied base spec with field overrides applied."""
    out = copy.deepcopy(_BASE_SPEC)
    out.update(overrides)
    return out


# ── Schema 1.0 rejection ────────────────────────────────────────────────


def test_schema_1_0_is_rejected_post_d1() -> None:
    """Reject schema 1.0 with migration guidance."""
    spec = _spec(schema_version="1.0")
    with pytest.raises(AlphaLoadError, match="unsupported schema_version"):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_schema_1_0_with_layer_field_is_also_rejected() -> None:
    """Version rejection takes precedence over layer validation."""
    spec = _spec(schema_version="1.0", layer="SIGNAL")
    with pytest.raises(AlphaLoadError, match="unsupported schema_version"):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_missing_schema_version_is_rejected() -> None:
    """Require an explicit schema version."""
    spec = _spec()
    spec.pop("schema_version", None)
    with pytest.raises(AlphaLoadError, match="missing required 'schema_version'"):
        AlphaLoader().load_from_dict(spec, source="<test>")


# ── (1.1, no layer): rejected (§8.7) ────────────────────────────────────


def test_schema_1_1_without_layer_is_rejected() -> None:
    spec = _spec(schema_version="1.1")
    spec.pop("layer", None)
    with pytest.raises(AlphaLoadError, match="schema_version '1.1' requires the 'layer' field"):
        AlphaLoader().load_from_dict(spec, source="<test>")


# ── (1.1, LEGACY_SIGNAL): rejected ─────────────────────────────────────


def test_schema_1_1_legacy_signal_layer_is_rejected_post_d2() -> None:
    """Reject ``LEGACY_SIGNAL`` with a migration pointer."""
    spec = _spec(schema_version="1.1", layer="LEGACY_SIGNAL")
    with pytest.raises(AlphaLoadError) as excinfo:
        AlphaLoader().load_from_dict(spec, source="<test>")
    msg = str(excinfo.value)
    assert "LEGACY_SIGNAL" in msg
    # Point authors to the stable migration guide.
    assert "schema_1_0_to_1_1.md" in msg


# ── (1.1, SIGNAL): accepted ─────────────────────────────────────────────


def test_schema_1_1_signal_loads_ok() -> None:
    spec = _spec(schema_version="1.1", layer="SIGNAL")
    loaded = AlphaLoader().load_from_dict(spec, source="<test>")
    assert loaded.manifest.layer == "SIGNAL"


# Unsupported schema-1.1 layers are rejected clearly.


@pytest.mark.parametrize(
    "layer,expected_phase",
    [
        # SIGNAL acceptance lives in
        # tests/alpha/test_signal_layer_loader.py.
        # PORTFOLIO acceptance lives in
        # tests/composition/test_portfolio_loader.py.
        ("SENSOR", "Phase 2"),
    ],
)
def test_schema_1_1_future_layers_rejected_with_phase_message(
    layer: str, expected_phase: str
) -> None:
    spec = _spec(schema_version="1.1", layer=layer)
    with pytest.raises(AlphaLoadError) as excinfo:
        AlphaLoader().load_from_dict(spec, source="<test>")
    msg = str(excinfo.value)
    assert layer in msg
    assert expected_phase in msg
    # Direct authors to a supported loadable layer.
    assert "SIGNAL" in msg


# ── (1.1, unknown layer): rejected ──────────────────────────────────────


def test_schema_1_1_unknown_layer_rejected_with_taxonomy() -> None:
    spec = _spec(schema_version="1.1", layer="MAGIC")
    with pytest.raises(AlphaLoadError) as excinfo:
        AlphaLoader().load_from_dict(spec, source="<test>")
    msg = str(excinfo.value)
    assert "MAGIC" in msg
    # LEGACY_SIGNAL is not a recognized layer.
    for valid in ("SIGNAL", "PORTFOLIO", "SENSOR"):
        assert valid in msg
    assert "LEGACY_SIGNAL" not in msg


# ── (1.1, unknown schema_version): rejected ─────────────────────────────


def test_unsupported_schema_version_rejected() -> None:
    spec = _spec(schema_version="2.0", layer="SIGNAL")
    with pytest.raises(AlphaLoadError, match="unsupported schema_version"):
        AlphaLoader().load_from_dict(spec, source="<test>")


# ── LayerValidator gates (G14 / G15) wired into 1.1 path ────────────────


def test_g14_data_scope_violation_rejected() -> None:
    spec = _spec(
        schema_version="1.1",
        layer="SIGNAL",
        data_sources=["l1_nbbo", "options_chain"],
    )
    with pytest.raises(LayerValidationError, match="G14"):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_g14_allowed_data_sources_pass() -> None:
    spec = _spec(
        schema_version="1.1",
        layer="SIGNAL",
        data_sources=["l1_nbbo", "trades"],
    )
    AlphaLoader().load_from_dict(spec, source="<test>")


def test_g14_data_sources_must_be_list() -> None:
    spec = _spec(
        schema_version="1.1",
        layer="SIGNAL",
        data_sources={"x": 1},
    )
    with pytest.raises(LayerValidationError, match="G14"):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_g15_unknown_router_rejected() -> None:
    spec = _spec(
        schema_version="1.1",
        layer="SIGNAL",
        fill_model={"router": "MagicRouter"},
    )
    with pytest.raises(LayerValidationError, match="G15"):
        AlphaLoader().load_from_dict(spec, source="<test>")


@pytest.mark.parametrize("router", ["PassiveLimitOrderRouter", "BacktestOrderRouter"])
def test_g15_known_routers_pass(router: str) -> None:
    spec = _spec(
        schema_version="1.1",
        layer="SIGNAL",
        fill_model={"router": router},
    )
    AlphaLoader().load_from_dict(spec, source="<test>")


def test_g15_inactive_when_fill_model_absent() -> None:
    """No fill_model declaration ⇒ G15 trivially satisfied."""
    spec = _spec(schema_version="1.1", layer="SIGNAL")
    AlphaLoader().load_from_dict(spec, source="<test>")


def test_layer_validator_fires_on_every_schema_1_1_spec() -> None:
    """Every accepted spec passes through ``LayerValidator``."""
    spec = _spec(
        schema_version="1.1",
        layer="SIGNAL",
        data_sources=["alternative_data"],
    )
    with pytest.raises(LayerValidationError, match="G14"):
        AlphaLoader().load_from_dict(spec, source="<test>")
