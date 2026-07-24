"""Phase-4 load-time invariants for the Stage-0 ``safety_exit_policy:`` block.

Covers the design rev-5 dual-permission actuation load guards:

  - loader structural parse + manifest round-trip (mode enum, both ceilings
    mandatory + positive under ``decouple_caps_only``);
  - gate G17 cross-block invariants: SIGNAL-only, ``story_permission ⇒
    decouple``, ``decouple ⇒ trend_mechanism`` family + half-life, and the
    per-family ``max_hold_after_safe_off`` ceiling;
  - the cross-alpha scope invariant ``validate_decouple_symbol_scope`` (a
    symbol-net backstop on a shared symbol is rejected; single-strategy-per-
    symbol otherwise; a strategy-slice-scoped backstop makes sharing safe).

The base fixture is a G16-compliant SIGNAL spec so the safety block is the only
thing under test.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from feelies.alpha.layer_validator import (
    LayerValidationError,
    validate_decouple_symbol_scope,
)
from feelies.alpha.loader import AlphaLoadError, AlphaLoader

# Either a loader structural rejection (``AlphaLoadError``) or a G17 gate
# rejection (``LayerValidationError``) is an acceptable "block was rejected".
_LOAD_REJECTED = (AlphaLoadError, LayerValidationError)


_BASE_SPEC: dict[str, Any] = {
    "schema_version": "1.1",
    "layer": "SIGNAL",
    "alpha_id": "sep_test",
    "version": "1.0.0",
    "description": "safety_exit_policy load-guard fixture",
    "hypothesis": "Loader-shape fixture for the Stage-0 dual-permission block.",
    "falsification_criteria": ["fails by construction"],
    "horizon_seconds": 120,
    "depends_on_sensors": ["kyle_lambda_60s", "micro_price"],
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
    # KYLE_INFO: half-life 120s ⇒ ceiling = 3 × 120 = 360s.
    "trend_mechanism": {
        "family": "KYLE_INFO",
        "expected_half_life_seconds": 120,
        "l1_signature_sensors": ["kyle_lambda_60s", "micro_price"],
        "failure_signature": ["kyle_lambda_60s deviation falls below 1σ for 30s"],
    },
    "signal": "def evaluate(snapshot, regime, params):\n    return None\n",
}


def _spec(**overrides: object) -> dict[str, Any]:
    out = copy.deepcopy(_BASE_SPEC)
    out.update(overrides)
    return out


def _decouple(
    *, max_hold: int = 300, hard_age: int = 600, **extra: object
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "mode": "decouple_caps_only",
        "max_hold_after_safe_off": max_hold,
        "hard_exit_age_seconds": hard_age,
    }
    block.update(extra)
    return block


# ── Absence / default (bit-identical) ───────────────────────────────────────


def test_absent_block_yields_none_and_not_decoupled() -> None:
    loaded = AlphaLoader().load_from_dict(_spec(), source="<t>")
    assert loaded.manifest.safety_exit_policy is None
    assert loaded.decouple_gate_close is False


def test_gate_close_flat_explicit_is_not_decoupled() -> None:
    loaded = AlphaLoader().load_from_dict(
        _spec(safety_exit_policy={"mode": "gate_close_flat"}), source="<t>"
    )
    assert loaded.manifest.safety_exit_policy == {"mode": "gate_close_flat"}
    assert loaded.decouple_gate_close is False


# ── Happy path + manifest round-trip ────────────────────────────────────────


def test_decouple_round_trips_onto_manifest_and_sets_flag() -> None:
    loaded = AlphaLoader().load_from_dict(
        _spec(safety_exit_policy=_decouple(max_hold=300, hard_age=600)), source="<t>"
    )
    assert loaded.manifest.safety_exit_policy == {
        "mode": "decouple_caps_only",
        "max_hold_after_safe_off": 300,
        "hard_exit_age_seconds": 600,
    }
    assert loaded.decouple_gate_close is True


def test_block_stored_as_copy_not_alias() -> None:
    block = _decouple()
    loaded = AlphaLoader().load_from_dict(_spec(safety_exit_policy=block), source="<t>")
    block["mode"] = "gate_close_flat"  # mutate the loader input after the fact
    assert loaded.manifest.safety_exit_policy is not None
    assert loaded.manifest.safety_exit_policy["mode"] == "decouple_caps_only"


# ── Structural loader rejections ────────────────────────────────────────────


def test_non_mapping_block_rejected() -> None:
    with pytest.raises(_LOAD_REJECTED, match="safety_exit_policy.*must be a mapping"):
        AlphaLoader().load_from_dict(
            _spec(safety_exit_policy="decouple_caps_only"), source="<t>"
        )


def test_unknown_key_rejected() -> None:
    with pytest.raises(_LOAD_REJECTED, match="unknown key"):
        AlphaLoader().load_from_dict(
            _spec(safety_exit_policy=_decouple(surprise=1)), source="<t>"
        )


def test_unknown_mode_rejected() -> None:
    with pytest.raises(_LOAD_REJECTED, match="mode.*not supported"):
        AlphaLoader().load_from_dict(
            _spec(safety_exit_policy={"mode": "hold_forever"}), source="<t>"
        )


@pytest.mark.parametrize("missing", ["max_hold_after_safe_off", "hard_exit_age_seconds"])
def test_decouple_missing_either_ceiling_rejected(missing: str) -> None:
    block = _decouple()
    del block[missing]
    with pytest.raises(_LOAD_REJECTED, match=missing):
        AlphaLoader().load_from_dict(_spec(safety_exit_policy=block), source="<t>")


@pytest.mark.parametrize("field", ["max_hold_after_safe_off", "hard_exit_age_seconds"])
@pytest.mark.parametrize("bad", [0, -5])
def test_non_positive_ceiling_rejected(field: str, bad: int) -> None:
    block = _decouple()
    block[field] = bad
    with pytest.raises(_LOAD_REJECTED, match=f"{field} must be > 0"):
        AlphaLoader().load_from_dict(_spec(safety_exit_policy=block), source="<t>")


# ── G17: story ⇒ decouple ───────────────────────────────────────────────────


def test_story_permission_requires_decouple_mode() -> None:
    with pytest.raises(_LOAD_REJECTED, match="story_permission"):
        AlphaLoader().load_from_dict(
            _spec(
                story_permission={"map_id": "story_v1"},
                safety_exit_policy={"mode": "gate_close_flat"},
            ),
            source="<t>",
        )


def test_story_permission_without_any_policy_requires_decouple() -> None:
    # No safety_exit_policy ⇒ effective mode is gate_close_flat ⇒ still rejected.
    with pytest.raises(_LOAD_REJECTED, match="story_permission"):
        AlphaLoader().load_from_dict(
            _spec(story_permission={"map_id": "story_v1"}), source="<t>"
        )


def test_story_permission_with_decouple_accepted() -> None:
    loaded = AlphaLoader().load_from_dict(
        _spec(story_permission={"map_id": "story_v1"}, safety_exit_policy=_decouple()),
        source="<t>",
    )
    assert loaded.decouple_gate_close is True


# ── G17: decouple requires a family + half-life envelope ─────────────────────


def test_decouple_without_trend_mechanism_rejected() -> None:
    spec = _spec(safety_exit_policy=_decouple())
    del spec["trend_mechanism"]
    with pytest.raises(_LOAD_REJECTED, match="trend_mechanism.family"):
        AlphaLoader().load_from_dict(spec, source="<t>")


# ── G17: per-family max_hold ceiling ────────────────────────────────────────


def test_max_hold_at_family_ceiling_accepted() -> None:
    # KYLE_INFO: 3 × 120 = 360s exactly.
    loaded = AlphaLoader().load_from_dict(
        _spec(safety_exit_policy=_decouple(max_hold=360)), source="<t>"
    )
    assert loaded.manifest.safety_exit_policy is not None
    assert loaded.manifest.safety_exit_policy["max_hold_after_safe_off"] == 360


def test_max_hold_over_family_ceiling_rejected() -> None:
    with pytest.raises(_LOAD_REJECTED, match="ceiling"):
        AlphaLoader().load_from_dict(
            _spec(safety_exit_policy=_decouple(max_hold=361)), source="<t>"
        )


@pytest.mark.parametrize(
    ("family", "half_life", "horizon", "sensors", "multiple"),
    [
        # ``horizon`` is a registered platform horizon (G7) whose ratio to the
        # half-life stays inside the G16 rule-3 [0.5, 4.0] band.
        ("KYLE_INFO", 120, 120, ["kyle_lambda_60s", "micro_price"], 3),
        ("INVENTORY", 30, 30, ["quote_replenish_asymmetry"], 1),
        ("HAWKES_SELF_EXCITE", 30, 30, ["hawkes_intensity"], 1),
        ("SCHEDULED_FLOW", 60, 120, ["scheduled_flow_window"], 2),
    ],
)
def test_per_family_ceiling_boundary(
    family: str, half_life: int, horizon: int, sensors: list[str], multiple: int
) -> None:
    ceiling = multiple * half_life
    tm = {
        "family": family,
        "expected_half_life_seconds": half_life,
        "l1_signature_sensors": sensors,
        "failure_signature": ["mechanism-specific invalidator"],
    }
    ok = _spec(
        horizon_seconds=horizon,
        depends_on_sensors=sensors,
        trend_mechanism=tm,
        safety_exit_policy=_decouple(max_hold=ceiling, hard_age=ceiling + 10),
    )
    AlphaLoader().load_from_dict(ok, source="<t>")  # boundary accepted

    with pytest.raises(_LOAD_REJECTED, match="ceiling"):
        AlphaLoader().load_from_dict(
            _spec(
                horizon_seconds=horizon,
                depends_on_sensors=sensors,
                trend_mechanism=tm,
                safety_exit_policy=_decouple(
                    max_hold=ceiling + 1, hard_age=ceiling + 10
                ),
            ),
            source="<t>",
        )


# ── G17: SIGNAL-only ────────────────────────────────────────────────────────


def test_safety_exit_policy_rejected_on_portfolio_layer() -> None:
    portfolio_spec: dict[str, Any] = {
        "schema_version": "1.1",
        "layer": "PORTFOLIO",
        "alpha_id": "sep_portfolio",
        "version": "1.0.0",
        "description": "portfolio must not declare safety_exit_policy",
        "hypothesis": "h",
        "falsification_criteria": ["f"],
        "horizon_seconds": 120,
        "universe": ["AAPL", "MSFT"],
        "depends_on_signals": ["sig_upstream"],
        "factor_neutralization": False,
        "cost_arithmetic": {
            "edge_estimate_bps": 9.0,
            "half_spread_bps": 2.0,
            "impact_bps": 2.0,
            "fee_bps": 1.0,
            "margin_ratio": 1.8,
        },
        "safety_exit_policy": _decouple(),
    }
    with pytest.raises(_LOAD_REJECTED, match="SIGNAL-layer block"):
        AlphaLoader().load_from_dict(portfolio_spec, source="<t>")


# ── Cross-alpha scope invariant ─────────────────────────────────────────────


def test_scope_slice_scoped_backstop_allows_shared_symbol() -> None:
    # A strategy-slice-scoped backstop flattens one strategy's slice ⇒ sharing OK.
    validate_decouple_symbol_scope(
        [
            ("a_decoupled", frozenset({"AAPL"}), True),
            ("b_other", frozenset({"AAPL"}), False),
        ],
        backstop_slice_scoped=True,
    )


def test_scope_symbol_net_backstop_rejects_shared_symbol() -> None:
    with pytest.raises(LayerValidationError, match="shares symbol"):
        validate_decouple_symbol_scope(
            [
                ("a_decoupled", frozenset({"AAPL"}), True),
                ("b_other", frozenset({"AAPL"}), False),
            ],
            backstop_slice_scoped=False,
        )


def test_scope_symbol_net_backstop_allows_single_strategy_per_symbol() -> None:
    validate_decouple_symbol_scope(
        [
            ("a_decoupled", frozenset({"AAPL"}), True),
            ("b_other", frozenset({"MSFT"}), False),
        ],
        backstop_slice_scoped=False,
    )


def test_scope_symbol_net_two_decoupled_sharing_rejected() -> None:
    with pytest.raises(LayerValidationError, match="AAPL"):
        validate_decouple_symbol_scope(
            [
                ("a_decoupled", frozenset({"AAPL", "MSFT"}), True),
                ("b_decoupled", frozenset({"AAPL"}), True),
            ],
            backstop_slice_scoped=False,
        )


def test_scope_non_decoupled_sharing_is_ignored() -> None:
    # Two non-decoupled strategies sharing a symbol is not this gate's concern.
    validate_decouple_symbol_scope(
        [
            ("a_other", frozenset({"AAPL"}), False),
            ("b_other", frozenset({"AAPL"}), False),
        ],
        backstop_slice_scoped=False,
    )
