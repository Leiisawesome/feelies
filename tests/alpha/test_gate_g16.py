"""Tests for gate G16 — mechanism-horizon binding (§20.6.1).

Phase 3.1 status: G16 is **ACTIVE** for any schema-1.1 SIGNAL or
PORTFOLIO spec that declares a ``trend_mechanism:`` block.  Strict mode
(``enforce_trend_mechanism=True``) additionally refuses to load any
schema-1.1 SIGNAL/PORTFOLIO spec missing the block.

Each of the 9 binding rules from §20.6.1 raises a *distinct subclass*
of :class:`TrendMechanismValidationError` so callers can attribute
failures cleanly without parsing message strings.  This module covers
both pass-paths and fail-paths for every rule, including the
AST-driven rule 7 stress-family-entry check.

The fingerprint-sensor table inside the validator MUST stay aligned
with the production sensor universe.  Each test passes the relevant
sensor IDs in via ``known_sensor_ids`` so we are testing the gate
logic, not coupling to the global sensor registry.
"""

from __future__ import annotations

import pytest

from feelies.alpha.layer_validator import (
    DEFAULT_REGISTERED_HORIZONS,
    LayerValidator,
    LayerValidationError,
    MechanismHalfLifeOutOfRangeError,
    MechanismHorizonMismatchError,
    MechanismShareUnreachableError,
    MissingFailureSignatureError,
    MissingFingerprintSensorError,
    MissingMechanismSensorError,
    MissingTrendMechanismError,
    StressFamilyEntryProhibitedError,
    TrendMechanismValidationError,
    UnauthorizedMechanismDependencyError,
    UnknownTrendMechanismError,
)


# ── Sensor universe used across this module ─────────────────────────────


_SENSORS = frozenset({
    "ofi_ewma",
    "spread_z_30d",
    "kyle_lambda_60s",
    "micro_price",
    "quote_replenish_asymmetry",
    "quote_hazard_rate",
    "hawkes_intensity",
    "trade_through_rate",
    "vpin_50bucket",
    "realized_vol_30s",
    "scheduled_flow_window",
    "seconds_to_window_close",
})


# ── Spec templates ──────────────────────────────────────────────────────


def _signal_spec_with_mechanism(
    *,
    family: str = "KYLE_INFO",
    half_life: int = 600,
    horizon: int = 300,
    sensors: list | None = None,
    failure_signature: list | None = None,
    signal_src: str | None = None,
) -> dict:
    """Build a minimal SIGNAL spec that satisfies G2-G13 + G16.

    Override individual fields to flip exactly one rule under test.
    """
    if sensors is None:
        sensors = ["kyle_lambda_60s", "ofi_ewma", "micro_price"]
    if failure_signature is None:
        failure_signature = [
            "spread_z_30d > 2.5",
            "kyle_lambda_60s_zscore < -1.5",
        ]
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
        "falsification_criteria": ["criterion 1"],
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
            "failure_signature": failure_signature,
        },
        "signal": signal_src,
    }


def _portfolio_spec_with_consumes(
    *,
    consumes: list | None = None,
    depends: list | None = None,
) -> dict:
    if consumes is None:
        consumes = [
            {"family": "KYLE_INFO", "max_share_of_gross": 0.5},
            {"family": "INVENTORY", "max_share_of_gross": 0.5},
        ]
    spec: dict = {
        "schema_version": "1.1",
        "layer": "PORTFOLIO",
        "alpha_id": "portfolio_x",
        "version": "1.0.0",
        "description": "test portfolio",
        "hypothesis": "test hypothesis",
        "falsification_criteria": ["criterion 1"],
        "universe": ["AAPL", "MSFT"],
        "factor_neutralization": False,
        "trend_mechanism": {"consumes": consumes},
    }
    if depends is not None:
        spec["depends_on_signals"] = depends
    return spec


def _validator(*, strict: bool = False) -> LayerValidator:
    return LayerValidator(
        registered_horizons=DEFAULT_REGISTERED_HORIZONS,
        known_sensor_ids=_SENSORS,
        enforce_trend_mechanism=strict,
    )


# ── Happy paths ─────────────────────────────────────────────────────────


def test_signal_spec_with_full_mechanism_block_passes() -> None:
    _validator().validate(
        _signal_spec_with_mechanism(), source="<test>",
    )


def test_signal_spec_without_mechanism_passes_when_strict_off() -> None:
    spec = _signal_spec_with_mechanism()
    spec.pop("trend_mechanism")
    _validator(strict=False).validate(spec, source="<test>")


# ── Strict mode (§20.6.2) ───────────────────────────────────────────────


class TestStrictMode:
    def test_v11_signal_missing_block_refused_under_strict(self) -> None:
        spec = _signal_spec_with_mechanism()
        spec.pop("trend_mechanism")
        with pytest.raises(MissingTrendMechanismError, match="strict-mode"):
            _validator(strict=True).validate(spec, source="<test>")

    def test_v11_portfolio_missing_block_refused_under_strict(self) -> None:
        spec = _portfolio_spec_with_consumes()
        spec.pop("trend_mechanism")
        with pytest.raises(MissingTrendMechanismError):
            _validator(strict=True).validate(spec, source="<test>")

# ── Rule 1 — closed family taxonomy ─────────────────────────────────────


class TestRule1Family:
    def test_unknown_family_rejected(self) -> None:
        spec = _signal_spec_with_mechanism()
        spec["trend_mechanism"]["family"] = "QUANTUM_TUNNEL"
        with pytest.raises(UnknownTrendMechanismError, match="rule 1"):
            _validator().validate(spec, source="<test>")

    def test_missing_family_rejected(self) -> None:
        spec = _signal_spec_with_mechanism()
        del spec["trend_mechanism"]["family"]
        with pytest.raises(UnknownTrendMechanismError, match="rule 1"):
            _validator().validate(spec, source="<test>")

    @pytest.mark.parametrize("family,sensors,half_life,horizon", [
        ("KYLE_INFO", ["kyle_lambda_60s", "ofi_ewma"], 600, 300),
        ("INVENTORY", ["quote_replenish_asymmetry", "spread_z_30d"], 20, 30),
        ("HAWKES_SELF_EXCITE", ["hawkes_intensity", "ofi_ewma"], 30, 30),
        ("LIQUIDITY_STRESS", ["vpin_50bucket", "spread_z_30d"], 120, 300),
        ("SCHEDULED_FLOW", ["scheduled_flow_window", "ofi_ewma"], 240, 120),
    ])
    def test_each_family_can_be_constructed(
        self,
        family: str,
        sensors: list,
        half_life: int,
        horizon: int,
    ) -> None:
        spec = _signal_spec_with_mechanism(
            family=family,
            half_life=half_life,
            horizon=horizon,
            sensors=sensors,
        )
        _validator().validate(spec, source="<test>")


# ── Rule 2 — half-life envelope ─────────────────────────────────────────


class TestRule2HalfLifeRange:
    def test_kyle_below_floor_rejected(self) -> None:
        spec = _signal_spec_with_mechanism(half_life=30, horizon=120)
        with pytest.raises(MechanismHalfLifeOutOfRangeError, match="rule 2"):
            _validator().validate(spec, source="<test>")

    def test_kyle_above_ceiling_rejected(self) -> None:
        spec = _signal_spec_with_mechanism(half_life=2000, horizon=1800)
        with pytest.raises(MechanismHalfLifeOutOfRangeError, match="rule 2"):
            _validator().validate(spec, source="<test>")

    def test_kyle_at_floor_accepted(self) -> None:
        spec = _signal_spec_with_mechanism(half_life=60, horizon=120)
        _validator().validate(spec, source="<test>")

    def test_kyle_at_ceiling_accepted(self) -> None:
        spec = _signal_spec_with_mechanism(half_life=1800, horizon=1800)
        _validator().validate(spec, source="<test>")

    def test_missing_half_life_rejected(self) -> None:
        spec = _signal_spec_with_mechanism()
        del spec["trend_mechanism"]["expected_half_life_seconds"]
        with pytest.raises(MechanismHalfLifeOutOfRangeError, match="rule 2"):
            _validator().validate(spec, source="<test>")

    def test_non_int_half_life_rejected(self) -> None:
        spec = _signal_spec_with_mechanism()
        spec["trend_mechanism"]["expected_half_life_seconds"] = "soonish"
        with pytest.raises(MechanismHalfLifeOutOfRangeError, match="rule 2"):
            _validator().validate(spec, source="<test>")


# ── Rule 3 — horizon ↔ half-life ratio ──────────────────────────────────


class TestRule3HorizonRatio:
    def test_horizon_far_below_half_life_rejected(self) -> None:
        spec = _signal_spec_with_mechanism(half_life=600, horizon=120)
        with pytest.raises(MechanismHorizonMismatchError, match="rule 3"):
            _validator().validate(spec, source="<test>")

    def test_horizon_far_above_half_life_rejected(self) -> None:
        spec = _signal_spec_with_mechanism(half_life=60, horizon=900)
        with pytest.raises(MechanismHorizonMismatchError, match="rule 3"):
            _validator().validate(spec, source="<test>")

    def test_horizon_at_floor_accepted(self) -> None:
        spec = _signal_spec_with_mechanism(half_life=600, horizon=300)
        _validator().validate(spec, source="<test>")

    def test_horizon_at_ceiling_accepted(self) -> None:
        spec = _signal_spec_with_mechanism(half_life=75, horizon=300)
        _validator().validate(spec, source="<test>")

    def test_missing_horizon_rejected(self) -> None:
        spec = _signal_spec_with_mechanism()
        spec.pop("horizon_seconds", None)
        with pytest.raises(LayerValidationError):
            _validator().validate(spec, source="<test>")


# ── Rule 4 — l1_signature_sensors registered ────────────────────────────


class TestRule4SensorRegistration:
    def test_unknown_sensor_rejected(self) -> None:
        spec = _signal_spec_with_mechanism()
        spec["trend_mechanism"]["l1_signature_sensors"] = [
            "kyle_lambda_60s",
            "imaginary_sensor_42",
        ]
        with pytest.raises(MissingMechanismSensorError, match="rule 4"):
            _validator().validate(spec, source="<test>")

    def test_unknown_sensor_skipped_when_registry_unset(self) -> None:
        """When ``known_sensor_ids`` is None, rule 4 abstains by design
        (mirrors the behaviour documented for G6).  Other rules still
        run."""
        validator = LayerValidator(
            registered_horizons=DEFAULT_REGISTERED_HORIZONS,
            known_sensor_ids=None,
        )
        spec = _signal_spec_with_mechanism()
        spec["trend_mechanism"]["l1_signature_sensors"] = [
            "kyle_lambda_60s",
            "imaginary_sensor_42",
        ]
        validator.validate(spec, source="<test>")

    def test_dict_form_with_id_accepted(self) -> None:
        spec = _signal_spec_with_mechanism()
        spec["trend_mechanism"]["l1_signature_sensors"] = [
            {"id": "kyle_lambda_60s", "version": 1},
            {"id": "ofi_ewma", "version": 1},
        ]
        _validator().validate(spec, source="<test>")


# ── Rule 5 — primary fingerprint sensor present ─────────────────────────


class TestRule5FingerprintSensor:
    def test_kyle_missing_lambda_or_micro_rejected(self) -> None:
        spec = _signal_spec_with_mechanism(
            family="KYLE_INFO",
            half_life=600,
            horizon=300,
            sensors=["ofi_ewma", "spread_z_30d"],
        )
        with pytest.raises(MissingFingerprintSensorError, match="rule 5"):
            _validator().validate(spec, source="<test>")

    def test_kyle_with_micro_price_only_accepted(self) -> None:
        spec = _signal_spec_with_mechanism(
            family="KYLE_INFO",
            half_life=600,
            horizon=300,
            sensors=["micro_price", "ofi_ewma"],
        )
        _validator().validate(spec, source="<test>")

    def test_inventory_without_replenish_asymmetry_rejected(self) -> None:
        spec = _signal_spec_with_mechanism(
            family="INVENTORY",
            half_life=20,
            horizon=30,
            sensors=["spread_z_30d"],
        )
        with pytest.raises(MissingFingerprintSensorError, match="rule 5"):
            _validator().validate(spec, source="<test>")

    def test_hawkes_without_intensity_rejected(self) -> None:
        spec = _signal_spec_with_mechanism(
            family="HAWKES_SELF_EXCITE",
            half_life=30,
            horizon=30,
            sensors=["ofi_ewma", "trade_through_rate"],
        )
        with pytest.raises(MissingFingerprintSensorError, match="rule 5"):
            _validator().validate(spec, source="<test>")

    def test_stress_with_vpin_accepted(self) -> None:
        spec = _signal_spec_with_mechanism(
            family="LIQUIDITY_STRESS",
            half_life=120,
            horizon=300,
            sensors=["vpin_50bucket", "spread_z_30d"],
        )
        _validator().validate(spec, source="<test>")

    def test_stress_with_realized_vol_accepted(self) -> None:
        spec = _signal_spec_with_mechanism(
            family="LIQUIDITY_STRESS",
            half_life=120,
            horizon=300,
            sensors=["realized_vol_30s", "spread_z_30d"],
        )
        _validator().validate(spec, source="<test>")

    def test_scheduled_flow_without_window_sensor_rejected(self) -> None:
        spec = _signal_spec_with_mechanism(
            family="SCHEDULED_FLOW",
            half_life=240,
            horizon=120,
            sensors=["ofi_ewma", "spread_z_30d"],
        )
        with pytest.raises(MissingFingerprintSensorError, match="rule 5"):
            _validator().validate(spec, source="<test>")


# ── Rule 6 — non-empty failure_signature ────────────────────────────────


class TestRule6FailureSignature:
    def test_missing_failure_signature_rejected(self) -> None:
        spec = _signal_spec_with_mechanism()
        del spec["trend_mechanism"]["failure_signature"]
        with pytest.raises(MissingFailureSignatureError, match="rule 6"):
            _validator().validate(spec, source="<test>")

    def test_empty_list_failure_signature_rejected(self) -> None:
        spec = _signal_spec_with_mechanism(failure_signature=[])
        with pytest.raises(MissingFailureSignatureError, match="rule 6"):
            _validator().validate(spec, source="<test>")

    def test_string_failure_signature_rejected(self) -> None:
        spec = _signal_spec_with_mechanism()
        spec["trend_mechanism"]["failure_signature"] = "spread_z_30d > 2.5"
        with pytest.raises(MissingFailureSignatureError, match="rule 6"):
            _validator().validate(spec, source="<test>")

    def test_non_empty_list_failure_signature_accepted(self) -> None:
        """Rule 6 positive case — a non-empty list of strings passes.

        Anchors the matrix invariant that Rule 6 has at least one
        explicit pass-case test; ``TestRule1Family`` exercises this
        rule transitively for every family but the matrix audit
        (``tests/acceptance/test_g16_rule_completeness.py``) wants a
        per-rule positive case so a future regression cannot silently
        slip through.
        """
        spec = _signal_spec_with_mechanism(
            failure_signature=["spread_z_30d > 2.5", "vpin_50bucket > 0.6"],
        )
        # No exception = rule 6 accepted.
        _validator().validate(spec, source="<test>")


# ── Rule 7 — LIQUIDITY_STRESS exit-only (AST) ───────────────────────────


_STRESS_KW = dict(
    family="LIQUIDITY_STRESS",
    half_life=120,
    horizon=300,
    sensors=["vpin_50bucket", "spread_z_30d"],
)


class TestRule7StressEntryProhibited:
    def test_stress_returning_long_string_literal_rejected(self) -> None:
        signal_src = (
            "def evaluate(snapshot, regime, params):\n"
            "    return Signal(symbol='AAPL', direction='LONG', strength=1.0)\n"
        )
        spec = _signal_spec_with_mechanism(signal_src=signal_src, **_STRESS_KW)
        with pytest.raises(StressFamilyEntryProhibitedError, match="rule 7"):
            _validator().validate(spec, source="<test>")

    def test_stress_returning_short_string_literal_rejected(self) -> None:
        signal_src = (
            "def evaluate(snapshot, regime, params):\n"
            "    if snapshot.x:\n"
            "        return Signal(symbol='AAPL', direction='SHORT', strength=1.0)\n"
            "    return None\n"
        )
        spec = _signal_spec_with_mechanism(signal_src=signal_src, **_STRESS_KW)
        with pytest.raises(StressFamilyEntryProhibitedError, match="rule 7"):
            _validator().validate(spec, source="<test>")

    def test_stress_returning_signal_direction_long_attr_rejected(self) -> None:
        signal_src = (
            "def evaluate(snapshot, regime, params):\n"
            "    return Signal(\n"
            "        symbol='AAPL',\n"
            "        direction=SignalDirection.LONG,\n"
            "        strength=1.0,\n"
            "    )\n"
        )
        spec = _signal_spec_with_mechanism(signal_src=signal_src, **_STRESS_KW)
        with pytest.raises(StressFamilyEntryProhibitedError, match="rule 7"):
            _validator().validate(spec, source="<test>")

    def test_stress_returning_flat_accepted(self) -> None:
        signal_src = (
            "def evaluate(snapshot, regime, params):\n"
            "    return Signal(symbol='AAPL', direction='FLAT', strength=1.0)\n"
        )
        spec = _signal_spec_with_mechanism(signal_src=signal_src, **_STRESS_KW)
        _validator().validate(spec, source="<test>")

    def test_stress_returning_none_accepted(self) -> None:
        signal_src = (
            "def evaluate(snapshot, regime, params):\n"
            "    return None\n"
        )
        spec = _signal_spec_with_mechanism(signal_src=signal_src, **_STRESS_KW)
        _validator().validate(spec, source="<test>")

    def test_stress_returning_signal_direction_flat_accepted(self) -> None:
        signal_src = (
            "def evaluate(snapshot, regime, params):\n"
            "    return Signal(\n"
            "        symbol='AAPL',\n"
            "        direction=SignalDirection.FLAT,\n"
            "        strength=1.0,\n"
            "    )\n"
        )
        spec = _signal_spec_with_mechanism(signal_src=signal_src, **_STRESS_KW)
        _validator().validate(spec, source="<test>")

    def test_stress_returning_dynamic_direction_abstains(self) -> None:
        """When ``direction`` cannot be statically resolved, rule 7
        abstains rather than raising — the safer default for a
        structural gate.  Runtime validation belongs to G2/loader.
        """
        signal_src = (
            "def evaluate(snapshot, regime, params):\n"
            "    d = compute_direction(snapshot)\n"
            "    return Signal(symbol='AAPL', direction=d, strength=1.0)\n"
        )
        spec = _signal_spec_with_mechanism(signal_src=signal_src, **_STRESS_KW)
        _validator().validate(spec, source="<test>")

    def test_non_stress_family_returning_long_unaffected(self) -> None:
        """Rule 7 only fires for LIQUIDITY_STRESS.  A KYLE_INFO alpha
        returning LONG is legitimate."""
        signal_src = (
            "def evaluate(snapshot, regime, params):\n"
            "    return Signal(symbol='AAPL', direction='LONG', strength=1.0)\n"
        )
        spec = _signal_spec_with_mechanism(
            family="KYLE_INFO",
            half_life=600,
            horizon=300,
            sensors=["kyle_lambda_60s", "ofi_ewma"],
            signal_src=signal_src,
        )
        _validator().validate(spec, source="<test>")


# ── Rule 8 — PORTFOLIO max_share_of_gross sums to ≥ 1.0 ────────────────


class TestRule8ShareReachable:
    def test_consumes_summing_below_one_rejected(self) -> None:
        spec = _portfolio_spec_with_consumes(
            consumes=[
                {"family": "KYLE_INFO", "max_share_of_gross": 0.4},
                {"family": "INVENTORY", "max_share_of_gross": 0.4},
            ],
        )
        with pytest.raises(MechanismShareUnreachableError, match="rule 8"):
            _validator().validate(spec, source="<test>")

    def test_consumes_summing_to_exactly_one_accepted(self) -> None:
        spec = _portfolio_spec_with_consumes(
            consumes=[
                {"family": "KYLE_INFO", "max_share_of_gross": 0.5},
                {"family": "INVENTORY", "max_share_of_gross": 0.5},
            ],
        )
        _validator().validate(spec, source="<test>")

    def test_consumes_summing_above_one_accepted(self) -> None:
        """Per §20.6.1 rule 8 the *floor* is 1.0; portfolios are free
        to over-allocate (e.g. 2.0 = 200% gross) and let the live
        risk engine apply the actual cap."""
        spec = _portfolio_spec_with_consumes(
            consumes=[
                {"family": "KYLE_INFO", "max_share_of_gross": 0.7},
                {"family": "INVENTORY", "max_share_of_gross": 0.7},
                {"family": "HAWKES_SELF_EXCITE", "max_share_of_gross": 0.6},
            ],
        )
        _validator().validate(spec, source="<test>")

    def test_negative_share_rejected(self) -> None:
        spec = _portfolio_spec_with_consumes(
            consumes=[
                {"family": "KYLE_INFO", "max_share_of_gross": -0.1},
                {"family": "INVENTORY", "max_share_of_gross": 1.2},
            ],
        )
        with pytest.raises(MechanismShareUnreachableError, match="rule 8"):
            _validator().validate(spec, source="<test>")

    def test_share_above_one_per_family_rejected(self) -> None:
        spec = _portfolio_spec_with_consumes(
            consumes=[
                {"family": "KYLE_INFO", "max_share_of_gross": 1.5},
            ],
        )
        with pytest.raises(MechanismShareUnreachableError, match="rule 8"):
            _validator().validate(spec, source="<test>")


# ── Rule 9 — depends_on_signals authorised by consumes ──────────────────


class TestRule9DependencyAuthorised:
    def test_dependency_outside_consumes_whitelist_rejected(self) -> None:
        spec = _portfolio_spec_with_consumes(
            consumes=[
                {"family": "KYLE_INFO", "max_share_of_gross": 1.0},
            ],
            depends=[
                {
                    "alpha_id": "pofi_hawkes_burst_v1",
                    "trend_mechanism_family": "HAWKES_SELF_EXCITE",
                },
            ],
        )
        with pytest.raises(UnauthorizedMechanismDependencyError, match="rule 9"):
            _validator().validate(spec, source="<test>")

    def test_dependency_in_consumes_whitelist_accepted(self) -> None:
        spec = _portfolio_spec_with_consumes(
            consumes=[
                {"family": "KYLE_INFO", "max_share_of_gross": 0.5},
                {"family": "HAWKES_SELF_EXCITE", "max_share_of_gross": 0.5},
            ],
            depends=[
                {
                    "alpha_id": "pofi_hawkes_burst_v1",
                    "trend_mechanism_family": "HAWKES_SELF_EXCITE",
                },
                {
                    "alpha_id": "pofi_kyle_drift_v1",
                    "trend_mechanism_family": "KYLE_INFO",
                },
            ],
        )
        _validator().validate(spec, source="<test>")

    def test_dependency_without_family_marker_skipped(self) -> None:
        """Backwards compatible: a dependency entry that doesn't yet
        carry ``trend_mechanism_family`` is simply not policed by
        rule 9 — the alpha registry's deeper checks (G3) catch
        unresolved references."""
        spec = _portfolio_spec_with_consumes(
            consumes=[
                {"family": "KYLE_INFO", "max_share_of_gross": 1.0},
            ],
            depends=[{"alpha_id": "some_other_alpha"}],
        )
        _validator().validate(spec, source="<test>")


# ── Structural / shape errors ───────────────────────────────────────────


class TestBlockShape:
    def test_non_dict_block_rejected(self) -> None:
        spec = _signal_spec_with_mechanism()
        spec["trend_mechanism"] = ["KYLE_INFO"]
        with pytest.raises(TrendMechanismValidationError, match="must be a mapping"):
            _validator().validate(spec, source="<test>")

    def test_non_list_l1_signature_sensors_rejected(self) -> None:
        spec = _signal_spec_with_mechanism()
        spec["trend_mechanism"]["l1_signature_sensors"] = "kyle_lambda_60s"
        with pytest.raises(TrendMechanismValidationError, match="must be a list"):
            _validator().validate(spec, source="<test>")

    def test_non_string_sensor_entry_rejected(self) -> None:
        spec = _signal_spec_with_mechanism()
        spec["trend_mechanism"]["l1_signature_sensors"] = [42, "ofi_ewma"]
        with pytest.raises(TrendMechanismValidationError, match="entry must be"):
            _validator().validate(spec, source="<test>")

    def test_portfolio_consumes_non_list_rejected(self) -> None:
        spec = _portfolio_spec_with_consumes()
        spec["trend_mechanism"]["consumes"] = "KYLE_INFO"
        with pytest.raises(TrendMechanismValidationError, match="must be a list"):
            _validator().validate(spec, source="<test>")
