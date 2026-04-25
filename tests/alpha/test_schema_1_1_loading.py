"""Loader tests for schema_version 1.1 dispatch (§6.6 + §8.7).

After workstreams D.1 + D.2, the matrix collapses to:

  - (no schema_version)           ⇒ rejected (D.1 hard-removal).
  - ("1.0", any layer)            ⇒ rejected (D.1 hard-removal).
  - ("2.0+", any layer)           ⇒ rejected (unsupported version).
  - (1.1, no layer)               ⇒ rejected (§8.7 mandatory layer).
  - (1.1, LEGACY_SIGNAL)          ⇒ rejected (D.2 hard-removal).
  - (1.1, SIGNAL/PORTFOLIO)       ⇒ accepted via dedicated layer paths.
  - (1.1, SENSOR)                 ⇒ rejected with phase-not-implemented.
  - (1.1, unknown layer)          ⇒ rejected with allowed-layers list.

Also covers:
  - Loaded ``AlphaManifest`` carries ``layer`` when set.
  - The LayerValidator's G14 (data scope) and G15 (fill-model) gates
    fire for malformed declarations on schema-1.1 specs.

Workstream D.2: the base spec is now a ``layer: SIGNAL`` minimal alpha.
LEGACY_SIGNAL acceptance tests have been replaced with a single
rejection-path test pinning the post-D.2 contract.
"""

from __future__ import annotations

import copy

import pytest

from feelies.alpha.layer_validator import LayerValidationError
from feelies.alpha.loader import AlphaLoadError, AlphaLoader


# ── Minimal valid SIGNAL spec (post-D.2 canonical fixture) ──────────────


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
    "signal": (
        "def evaluate(snapshot, regime, params):\n"
        "    return None\n"
    ),
}


def _spec(**overrides: object) -> dict[str, object]:
    """Return a deep-copied base spec with field overrides applied."""
    out = copy.deepcopy(_BASE_SPEC)
    out.update(overrides)
    return out


# ── Schema-1.0 hard-removal (workstream D.1) ────────────────────────────


def test_schema_1_0_is_rejected_post_d1() -> None:
    """``schema_version: "1.0"`` was removed in workstream D.1.

    The loader must reject the legacy version with a message pointing
    at the migration cookbook.  Authors must migrate to
    ``schema_version: "1.1"`` and pick one of the still-loadable layer
    values (``SIGNAL`` or ``PORTFOLIO``).
    """
    spec = _spec(schema_version="1.0")
    with pytest.raises(AlphaLoadError, match="unsupported schema_version"):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_schema_1_0_with_layer_field_is_also_rejected() -> None:
    """Even a 1.0 spec carrying a ``layer:`` field is rejected.

    The version-level rejection fires before any layer-specific check;
    this guards against authors who half-migrate their schema and
    leave the version pin behind.
    """
    spec = _spec(schema_version="1.0", layer="SIGNAL")
    with pytest.raises(AlphaLoadError, match="unsupported schema_version"):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_missing_schema_version_is_rejected() -> None:
    """Omitting ``schema_version:`` no longer defaults to 1.0.

    Pre-D.1 the loader emitted a warning and silently fell back to
    schema 1.0; post-D.1 the field is mandatory.
    """
    spec = _spec()
    spec.pop("schema_version", None)
    with pytest.raises(AlphaLoadError, match="missing required 'schema_version'"):
        AlphaLoader().load_from_dict(spec, source="<test>")


# ── (1.1, no layer): rejected (§8.7) ────────────────────────────────────


def test_schema_1_1_without_layer_is_rejected() -> None:
    spec = _spec(schema_version="1.1")
    spec.pop("layer", None)
    with pytest.raises(
        AlphaLoadError, match="schema_version '1.1' requires the 'layer' field"
    ):
        AlphaLoader().load_from_dict(spec, source="<test>")


# ── (1.1, LEGACY_SIGNAL): rejected (workstream D.2) ─────────────────────


def test_schema_1_1_legacy_signal_layer_is_rejected_post_d2() -> None:
    """``layer: LEGACY_SIGNAL`` was retired by workstream D.2.

    The loader must hard-reject the legacy layer with a migration
    pointer.  There is no longer a sunset banner, no fallback dispatch
    — every alpha author must declare ``SIGNAL`` or ``PORTFOLIO``.
    """
    spec = _spec(schema_version="1.1", layer="LEGACY_SIGNAL")
    with pytest.raises(AlphaLoadError) as excinfo:
        AlphaLoader().load_from_dict(spec, source="<test>")
    msg = str(excinfo.value)
    assert "LEGACY_SIGNAL" in msg
    # Every rejection must direct authors to the migration cookbook so
    # they have a known, stable destination URL to follow.
    assert "schema_1_0_to_1_1.md" in msg


# ── (1.1, SIGNAL): accepted ─────────────────────────────────────────────


def test_schema_1_1_signal_loads_ok() -> None:
    spec = _spec(schema_version="1.1", layer="SIGNAL")
    loaded = AlphaLoader().load_from_dict(spec, source="<test>")
    assert loaded.manifest.layer == "SIGNAL"


# ── (1.1, future layers): rejected with phase-not-implemented msg ───────


@pytest.mark.parametrize(
    "layer,expected_phase",
    [
        # Phase 3-α activates SIGNAL — its acceptance test lives in
        # tests/alpha/test_signal_layer_loader.py.
        # Phase 4 activates PORTFOLIO — its acceptance test lives in
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
    # Post-D.2 the only loadable layer values are SIGNAL and PORTFOLIO,
    # so the loader's not-yet-implemented message must direct authors
    # to one of them rather than to the retired LEGACY_SIGNAL fallback.
    assert "SIGNAL" in msg


# ── (1.1, unknown layer): rejected ──────────────────────────────────────


def test_schema_1_1_unknown_layer_rejected_with_taxonomy() -> None:
    spec = _spec(schema_version="1.1", layer="MAGIC")
    with pytest.raises(AlphaLoadError) as excinfo:
        AlphaLoader().load_from_dict(spec, source="<test>")
    msg = str(excinfo.value)
    assert "MAGIC" in msg
    # Post-D.2 the recognised set is SIGNAL / PORTFOLIO / SENSOR.
    # LEGACY_SIGNAL is no longer enumerated as a recognised value.
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


@pytest.mark.parametrize(
    "router", ["PassiveLimitOrderRouter", "BacktestOrderRouter"]
)
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
    """LayerValidator now runs unconditionally on every accepted spec.

    Pre-D.1 schema 1.0 bypassed the LayerValidator; post-D.1 schema 1.0
    is rejected outright, so every spec the loader accepts has been
    through the LayerValidator's gates.  This test pins that property
    by feeding a malformed ``data_sources`` block on a SIGNAL spec and
    asserting G14 fires.
    """
    spec = _spec(
        schema_version="1.1",
        layer="SIGNAL",
        data_sources=["alternative_data"],
    )
    with pytest.raises(LayerValidationError, match="G14"):
        AlphaLoader().load_from_dict(spec, source="<test>")
