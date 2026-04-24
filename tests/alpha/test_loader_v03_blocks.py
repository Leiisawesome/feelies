"""Phase-1.1 (v0.3) loader tests for ``trend_mechanism:`` and ``hazard_exit:``.

Covers the opt-in YAML blocks per §20.5 of
``design_docs/three_layer_architecture.md``:

  - Absent block ⇒ no enforcement, manifest field is ``None``.
  - Present block + valid ``family:`` ⇒ accepted, stored verbatim on
    the loaded ``AlphaManifest``.
  - Present block + unknown ``family:`` ⇒ rejected against the closed
    5-member taxonomy.
  - Malformed (non-mapping) block ⇒ rejected with structured error.

Full v0.3 mechanism enforcement (gate G16, raised as
``TrendMechanismValidationError``) is deferred to Phase 3.1 and
covered by tests at that time.
"""

from __future__ import annotations

import copy

import pytest

from feelies.alpha.loader import AlphaLoadError, AlphaLoader


_BASE_SPEC = {
    "schema_version": "1.1",
    "layer": "LEGACY_SIGNAL",
    "alpha_id": "v03_block_test",
    "version": "1.0.0",
    "description": "v0.3 block parsing test",
    "hypothesis": "Loader-shape fixture for the v0.3 YAML blocks.",
    "falsification_criteria": ["fails by construction"],
    "features": [
        {
            "feature_id": "mid_price",
            "version": "1.0",
            "description": "mid",
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
        "        strategy_id='v03_block_test',\n"
        "        direction=SignalDirection.LONG,\n"
        "        strength=0.5,\n"
        "        edge_estimate_bps=1.0,\n"
        "    )\n"
    ),
}


def _spec(**overrides: object) -> dict[str, object]:
    out = copy.deepcopy(_BASE_SPEC)
    out.update(overrides)
    return out


# ── trend_mechanism: block ──────────────────────────────────────────────


def test_trend_mechanism_absent_yields_none_on_manifest() -> None:
    loaded = AlphaLoader().load_from_dict(_spec(), source="<test>")
    assert loaded.manifest.trend_mechanism is None


@pytest.mark.parametrize(
    "family",
    [
        "KYLE_INFO",
        "INVENTORY",
        "HAWKES_SELF_EXCITE",
        "LIQUIDITY_STRESS",
        "SCHEDULED_FLOW",
    ],
)
def test_trend_mechanism_known_family_accepted(family: str) -> None:
    block = {"family": family, "expected_half_life_seconds": 60}
    loaded = AlphaLoader().load_from_dict(
        _spec(trend_mechanism=block), source="<test>"
    )
    assert loaded.manifest.trend_mechanism is not None
    assert loaded.manifest.trend_mechanism["family"] == family
    assert loaded.manifest.trend_mechanism["expected_half_life_seconds"] == 60


def test_trend_mechanism_unknown_family_rejected() -> None:
    block = {"family": "MOMENTUM_RIDE"}
    with pytest.raises(AlphaLoadError) as excinfo:
        AlphaLoader().load_from_dict(
            _spec(trend_mechanism=block), source="<test>"
        )
    msg = str(excinfo.value)
    assert "MOMENTUM_RIDE" in msg
    assert "closed taxonomy" in msg
    for known in (
        "KYLE_INFO",
        "INVENTORY",
        "HAWKES_SELF_EXCITE",
        "LIQUIDITY_STRESS",
        "SCHEDULED_FLOW",
    ):
        assert known in msg


def test_trend_mechanism_block_without_family_is_accepted_in_phase_1_1() -> None:
    """Phase 1.1 enforces only the family-name closedness.

    Per §20.1 the opt-in is field-presence based, and field-level
    enforcement is deferred to Phase 3.1.  A block missing ``family:``
    is therefore accepted at this slice (a structurally-shaped block
    consumed by later phases will surface its own error).
    """
    block = {"expected_half_life_seconds": 30, "decay": "exponential"}
    loaded = AlphaLoader().load_from_dict(
        _spec(trend_mechanism=block), source="<test>"
    )
    assert loaded.manifest.trend_mechanism == block


def test_trend_mechanism_non_mapping_rejected() -> None:
    with pytest.raises(AlphaLoadError, match="trend_mechanism.*must be a mapping"):
        AlphaLoader().load_from_dict(
            _spec(trend_mechanism="KYLE_INFO"), source="<test>"
        )


def test_trend_mechanism_block_stored_verbatim_as_dict_copy() -> None:
    """Manifest must hold a *copy* — mutating loader inputs after the fact
    must not affect the manifest.
    """
    block = {"family": "INVENTORY", "extra": {"nested": True}}
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
    with pytest.raises(AlphaLoadError, match="hazard_exit.*must be a mapping"):
        AlphaLoader().load_from_dict(
            _spec(hazard_exit=["regime_hazard_spike"]), source="<test>"
        )


# ── Combined block presence ─────────────────────────────────────────────


def test_both_v03_blocks_present_independently_stored() -> None:
    tm = {"family": "HAWKES_SELF_EXCITE"}
    he = {"trigger": "regime_hazard_spike"}
    loaded = AlphaLoader().load_from_dict(
        _spec(trend_mechanism=tm, hazard_exit=he), source="<test>"
    )
    assert loaded.manifest.trend_mechanism == tm
    assert loaded.manifest.hazard_exit == he
