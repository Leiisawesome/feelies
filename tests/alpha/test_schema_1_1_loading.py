"""Loader tests for schema_version 1.1 dispatch (§6.6 + §8.7).

After workstream D.1, schema 1.0 has been removed from the supported
set.  The matrix collapses to:

  - (no schema_version)           ⇒ rejected (D.1 hard-removal).
  - ("1.0", any layer)            ⇒ rejected (D.1 hard-removal).
  - ("2.0+", any layer)           ⇒ rejected (unsupported version).
  - (1.1, no layer)               ⇒ rejected (§8.7 mandatory layer).
  - (1.1, LEGACY_SIGNAL)          ⇒ accepted (D.2 will retire this).
  - (1.1, SIGNAL/PORTFOLIO)       ⇒ accepted via dedicated layer paths.
  - (1.1, SENSOR)                 ⇒ rejected with phase-not-implemented.
  - (1.1, unknown layer)          ⇒ rejected with allowed-layers list.

Also covers:
  - Loaded ``AlphaManifest`` carries ``layer`` when set.
  - The LayerValidator's G14 (data scope) and G15 (fill-model) gates
    fire for malformed declarations on schema-1.1 specs.
"""

from __future__ import annotations

import copy
import logging

import pytest

from feelies.alpha.layer_validator import LayerValidationError
from feelies.alpha.loader import AlphaLoadError, AlphaLoader, _LEGACY_SUNSET_WARNED


@pytest.fixture(autouse=True)
def _reset_sunset_warned() -> None:
    """Clear the once-per-process LEGACY/1.0 banner dedupe between tests.

    The loader deliberately deduplicates the deprecation banner by
    ``alpha_id`` across a process to avoid spamming operators (Phase 5
    docs).  This file's tests all reuse the same fixture
    ``alpha_id="schema_test_alpha"`` and assert on the WARNING record,
    so we have to flush the dedupe set at the boundary or only the
    first test in the file would observe the message.
    """
    _LEGACY_SUNSET_WARNED.clear()
    yield
    _LEGACY_SUNSET_WARNED.clear()


# ── Minimal valid 1.0 spec (copied shape from tests/alpha/test_loader.py) ──


_BASE_SPEC = {
    "alpha_id": "schema_test_alpha",
    "version": "1.0.0",
    "description": "schema dispatch test",
    "hypothesis": "No real hypothesis; this is a loader-shape fixture.",
    "falsification_criteria": ["fails by construction"],
    "features": [
        {
            "feature_id": "mid_price",
            "version": "1.0",
            "description": "Mid price",
            "depends_on": [],
            "warm_up": {"min_events": 0},
            "computation": (
                "def initial_state():\n"
                "    return {}\n"
                "def update(quote, state, params):\n"
                "    return (float(quote.bid) + float(quote.ask)) / 2.0\n"
            ),
        }
    ],
    "signal": (
        "def evaluate(features, params):\n"
        "    if not features.warm:\n"
        "        return None\n"
        "    return Signal(\n"
        "        timestamp_ns=features.timestamp_ns,\n"
        "        correlation_id=features.correlation_id,\n"
        "        sequence=features.sequence,\n"
        "        symbol=features.symbol,\n"
        "        strategy_id='schema_test_alpha',\n"
        "        direction=SignalDirection.LONG,\n"
        "        strength=0.5,\n"
        "        edge_estimate_bps=1.0,\n"
        "    )\n"
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
    ``schema_version: "1.1"`` and add ``layer: LEGACY_SIGNAL`` (zero
    behaviour change) or one of the higher-layer values.
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
    spec = _spec(schema_version="1.0", layer="LEGACY_SIGNAL")
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
    with pytest.raises(
        AlphaLoadError, match="schema_version '1.1' requires the 'layer' field"
    ):
        AlphaLoader().load_from_dict(spec, source="<test>")


# ── (1.1, LEGACY_SIGNAL): accepted ──────────────────────────────────────


def test_schema_1_1_legacy_signal_loads_ok() -> None:
    spec = _spec(schema_version="1.1", layer="LEGACY_SIGNAL")
    loaded = AlphaLoader().load_from_dict(spec, source="<test>")
    assert loaded.manifest.layer == "LEGACY_SIGNAL"


def test_schema_1_1_legacy_signal_emits_layer_sunset_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``layer: LEGACY_SIGNAL`` itself is on a sunset path.

    D.1 removed the schema-1.0 banner; the LEGACY_SIGNAL layer-axis
    banner remains until D.2 hard-removes the layer entirely.  The
    test pins the (case-insensitive) substring so D.2 can flip this
    assertion to ``raises(AlphaLoadError)`` without revisiting the
    string-matching contract.
    """
    spec = _spec(schema_version="1.1", layer="LEGACY_SIGNAL")
    with caplog.at_level(logging.WARNING):
        AlphaLoader().load_from_dict(spec, source="<test>")
    assert any(
        "deprecated" in r.getMessage().lower() for r in caplog.records
    ), "expected layer: LEGACY_SIGNAL sunset banner"


# ── (1.1, future layers): rejected with phase-not-implemented msg ───────


@pytest.mark.parametrize(
    "layer,expected_phase",
    [
        # Phase 3-α activates SIGNAL — it is no longer rejected here;
        # the SIGNAL acceptance test lives below in
        # tests/alpha/test_signal_layer_loader.py.
        # Phase 4 activates PORTFOLIO — its acceptance test lives in
        # tests/alpha/test_portfolio_layer_loader.py.
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
    assert "LEGACY_SIGNAL" in msg, "error must direct authors to the workaround"


# ── (1.1, unknown layer): rejected ──────────────────────────────────────


def test_schema_1_1_unknown_layer_rejected_with_taxonomy() -> None:
    spec = _spec(schema_version="1.1", layer="MAGIC")
    with pytest.raises(AlphaLoadError) as excinfo:
        AlphaLoader().load_from_dict(spec, source="<test>")
    msg = str(excinfo.value)
    assert "MAGIC" in msg
    for valid in ("LEGACY_SIGNAL", "SIGNAL", "PORTFOLIO", "SENSOR"):
        assert valid in msg


# ── (1.1, unknown schema_version): rejected ─────────────────────────────


def test_unsupported_schema_version_rejected() -> None:
    spec = _spec(schema_version="2.0", layer="LEGACY_SIGNAL")
    with pytest.raises(AlphaLoadError, match="unsupported schema_version"):
        AlphaLoader().load_from_dict(spec, source="<test>")


# ── LayerValidator gates (G14 / G15) wired into 1.1 path ────────────────


def test_g14_data_scope_violation_rejected() -> None:
    spec = _spec(
        schema_version="1.1",
        layer="LEGACY_SIGNAL",
        data_sources=["l1_nbbo", "options_chain"],
    )
    with pytest.raises(LayerValidationError, match="G14"):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_g14_allowed_data_sources_pass() -> None:
    spec = _spec(
        schema_version="1.1",
        layer="LEGACY_SIGNAL",
        data_sources=["l1_nbbo", "trades"],
    )
    AlphaLoader().load_from_dict(spec, source="<test>")


def test_g14_data_sources_must_be_list() -> None:
    spec = _spec(
        schema_version="1.1",
        layer="LEGACY_SIGNAL",
        data_sources={"x": 1},
    )
    with pytest.raises(LayerValidationError, match="G14"):
        AlphaLoader().load_from_dict(spec, source="<test>")


def test_g15_unknown_router_rejected() -> None:
    spec = _spec(
        schema_version="1.1",
        layer="LEGACY_SIGNAL",
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
        layer="LEGACY_SIGNAL",
        fill_model={"router": router},
    )
    AlphaLoader().load_from_dict(spec, source="<test>")


def test_g15_inactive_when_fill_model_absent() -> None:
    """No fill_model declaration ⇒ G15 trivially satisfied."""
    spec = _spec(schema_version="1.1", layer="LEGACY_SIGNAL")
    AlphaLoader().load_from_dict(spec, source="<test>")


def test_layer_validator_fires_on_every_schema_1_1_spec() -> None:
    """LayerValidator now runs unconditionally on every accepted spec.

    Pre-D.1 schema 1.0 bypassed the LayerValidator; post-D.1 schema 1.0
    is rejected outright, so every spec the loader accepts has been
    through the LayerValidator's gates.  This test pins that property
    by feeding a malformed ``data_sources`` block on a LEGACY_SIGNAL
    spec and asserting G14 fires.
    """
    spec = _spec(
        schema_version="1.1",
        layer="LEGACY_SIGNAL",
        data_sources=["alternative_data"],
    )
    with pytest.raises(LayerValidationError, match="G14"):
        AlphaLoader().load_from_dict(spec, source="<test>")
