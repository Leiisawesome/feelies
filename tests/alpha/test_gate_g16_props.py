"""Hypothesis property tests for gate G16 (§20.6.1).

Verifies invariants that no enumerated unit test can claim to cover
exhaustively:

1. **Family closure**: any string outside the closed taxonomy of 5
   names always raises :class:`UnknownTrendMechanismError`.
2. **Half-life envelope**: for each family, the validator accepts
   ``half_life ∈ [floor, ceiling]`` and rejects every value outside
   that envelope with :class:`MechanismHalfLifeOutOfRangeError`.
3. **Horizon-ratio envelope**: for any well-typed half-life and
   horizon, acceptance is iff ``ratio ∈ [0.5, 4.0]``.  Outside that
   range :class:`MechanismHorizonMismatchError` always fires.
4. **Stress-family AST monotonicity**: any AST that returns a
   non-FLAT direction literal/attribute is rejected; flipping just
   that literal to FLAT/None always restores acceptance.

We constrain ``horizon_seconds`` to the 5 registered platform
horizons so G7 never short-circuits the checks under test.  Strategies
encode the half-life floor/ceiling per family to keep the property
focused on the *next* gate in line.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from feelies.alpha.layer_validator import (
    DEFAULT_REGISTERED_HORIZONS,
    LayerValidator,
    MechanismHalfLifeOutOfRangeError,
    MechanismHorizonMismatchError,
    StressFamilyEntryProhibitedError,
    UnknownTrendMechanismError,
)


_SENSORS = frozenset({
    "ofi_ewma",
    "spread_z_30d",
    "kyle_lambda_60s",
    "micro_price",
    "quote_replenish_asymmetry",
    "hawkes_intensity",
    "trade_through_rate",
    "vpin_50bucket",
    "realized_vol_30s",
    "scheduled_flow_window",
})


_REGISTERED_HORIZONS = sorted(DEFAULT_REGISTERED_HORIZONS)  # [30,120,300,900,1800]


_FAMILY_RANGES: dict[str, tuple[int, int]] = {
    "KYLE_INFO": (60, 1800),
    "INVENTORY": (5, 60),
    "HAWKES_SELF_EXCITE": (5, 60),
    "LIQUIDITY_STRESS": (30, 600),
    "SCHEDULED_FLOW": (60, 1800),
}


_FAMILY_FINGERPRINT: dict[str, str] = {
    "KYLE_INFO": "kyle_lambda_60s",
    "INVENTORY": "quote_replenish_asymmetry",
    "HAWKES_SELF_EXCITE": "hawkes_intensity",
    "LIQUIDITY_STRESS": "vpin_50bucket",
    "SCHEDULED_FLOW": "scheduled_flow_window",
}


_NORMATIVE_FAMILIES = frozenset(_FAMILY_RANGES)


def _validator() -> LayerValidator:
    return LayerValidator(
        registered_horizons=DEFAULT_REGISTERED_HORIZONS,
        known_sensor_ids=_SENSORS,
    )


def _spec(
    *,
    family: str,
    half_life: int,
    horizon: int,
    sensors: list[str] | None = None,
    signal_src: str | None = None,
) -> dict:
    if sensors is None:
        sensors = [_FAMILY_FINGERPRINT[family], "ofi_ewma"]
    if signal_src is None:
        signal_src = (
            "def evaluate(snapshot, regime, params):\n"
            "    return None\n"
        )
    return {
        "schema_version": "1.1",
        "layer": "SIGNAL",
        "alpha_id": "alpha_x",
        "version": "1.0.0",
        "description": "test alpha",
        "hypothesis": "test hypothesis",
        "falsification_criteria": ["c"],
        "horizon_seconds": horizon,
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
        "trend_mechanism": {
            "family": family,
            "expected_half_life_seconds": half_life,
            "l1_signature_sensors": sensors,
            "failure_signature": [f"{sensors[0]}_zscore < -1.5"],
        },
        "signal": signal_src,
    }


# ── Strategies ──────────────────────────────────────────────────────────


_alpha_chars = st.text(
    alphabet=st.characters(min_codepoint=65, max_codepoint=90),
    min_size=4,
    max_size=20,
)


@st.composite
def _outside_taxonomy(draw: st.DrawFn) -> str:
    candidate = draw(_alpha_chars)
    assume(candidate not in _NORMATIVE_FAMILIES)
    return candidate


@st.composite
def _family_with_legal_horizon(
    draw: st.DrawFn,
) -> tuple[str, int, int]:
    family = draw(st.sampled_from(sorted(_NORMATIVE_FAMILIES)))
    horizon = draw(st.sampled_from(_REGISTERED_HORIZONS))
    floor, ceiling = _FAMILY_RANGES[family]
    half_min = max(floor, int(horizon / 4) + 1)
    half_max = min(ceiling, int(horizon / 0.5))
    assume(half_min <= half_max)
    half_life = draw(st.integers(min_value=half_min, max_value=half_max))
    return family, half_life, horizon


@st.composite
def _family_with_out_of_range_half_life(
    draw: st.DrawFn,
) -> tuple[str, int, int]:
    family = draw(st.sampled_from(sorted(_NORMATIVE_FAMILIES)))
    horizon = draw(st.sampled_from(_REGISTERED_HORIZONS))
    floor, ceiling = _FAMILY_RANGES[family]
    side = draw(st.sampled_from(["below", "above"]))
    if side == "below":
        half_life = draw(st.integers(min_value=1, max_value=max(1, floor - 1)))
    else:
        half_life = draw(st.integers(min_value=ceiling + 1, max_value=ceiling * 6))
    return family, half_life, horizon


# ── Property 1 — family closure ─────────────────────────────────────────


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(name=_outside_taxonomy())
def test_unknown_family_always_raises(name: str) -> None:
    spec = _spec(
        family="KYLE_INFO",
        half_life=300,
        horizon=300,
    )
    spec["trend_mechanism"]["family"] = name
    with pytest.raises(UnknownTrendMechanismError):
        _validator().validate(spec, source="<prop>")


# ── Property 2 — half-life envelope ────────────────────────────────────


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(triple=_family_with_legal_horizon())
def test_in_range_half_life_accepted(triple: tuple[str, int, int]) -> None:
    family, half_life, horizon = triple
    spec = _spec(family=family, half_life=half_life, horizon=horizon)
    _validator().validate(spec, source="<prop>")


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(triple=_family_with_out_of_range_half_life())
def test_out_of_range_half_life_rejected(triple: tuple[str, int, int]) -> None:
    family, half_life, horizon = triple
    spec = _spec(family=family, half_life=half_life, horizon=horizon)
    with pytest.raises(
        (MechanismHalfLifeOutOfRangeError, MechanismHorizonMismatchError)
    ):
        _validator().validate(spec, source="<prop>")


# ── Property 3 — horizon-ratio envelope ────────────────────────────────


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(
    half_life=st.integers(min_value=60, max_value=1800),
    horizon=st.sampled_from(_REGISTERED_HORIZONS),
)
def test_horizon_ratio_envelope_decides_acceptance(
    half_life: int,
    horizon: int,
) -> None:
    """For KYLE (broadest envelope), the only failure axis varied here
    is the horizon/half-life ratio.  In-range ⇒ accept; out-of-range
    ⇒ reject."""
    family = "KYLE_INFO"
    spec = _spec(family=family, half_life=half_life, horizon=horizon)
    ratio = horizon / half_life
    if 0.5 <= ratio <= 4.0:
        _validator().validate(spec, source="<prop>")
    else:
        with pytest.raises(MechanismHorizonMismatchError):
            _validator().validate(spec, source="<prop>")


# ── Property 4 — stress-family AST monotonicity ────────────────────────


_DIRECTION_LITERALS = ["LONG", "SHORT"]


@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
@given(
    direction=st.sampled_from(_DIRECTION_LITERALS),
    use_attr_form=st.booleans(),
)
def test_stress_family_rejects_any_non_flat_return(
    direction: str,
    use_attr_form: bool,
) -> None:
    if use_attr_form:
        direction_expr = f"SignalDirection.{direction}"
    else:
        direction_expr = repr(direction)
    signal_src = (
        "def evaluate(snapshot, regime, params):\n"
        f"    return Signal(symbol='AAPL', direction={direction_expr}, "
        "strength=1.0)\n"
    )
    spec = _spec(
        family="LIQUIDITY_STRESS",
        half_life=120,
        horizon=300,
        sensors=["vpin_50bucket", "spread_z_30d"],
        signal_src=signal_src,
    )
    with pytest.raises(StressFamilyEntryProhibitedError):
        _validator().validate(spec, source="<prop>")


@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
@given(use_attr_form=st.booleans())
def test_stress_family_accepts_flat_return(use_attr_form: bool) -> None:
    direction_expr = (
        "SignalDirection.FLAT" if use_attr_form else "'FLAT'"
    )
    signal_src = (
        "def evaluate(snapshot, regime, params):\n"
        f"    return Signal(symbol='AAPL', direction={direction_expr}, "
        "strength=0.0)\n"
    )
    spec = _spec(
        family="LIQUIDITY_STRESS",
        half_life=120,
        horizon=300,
        sensors=["vpin_50bucket", "spread_z_30d"],
        signal_src=signal_src,
    )
    _validator().validate(spec, source="<prop>")
