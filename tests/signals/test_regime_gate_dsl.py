"""Tests for the regime-gate DSL evaluator (``feelies.signals.regime_gate``).

Covers:

* Whitelist enforcement at parse time (P, abs/min/max, identifier
  resolution, percentile / zscore / ``dominant`` / ``p<NN>`` literals).
* Forbidden constructs raise :class:`UnsafeExpressionError`.
* Runtime resolution against a typed :class:`Bindings` object,
  including unknown-identifier and unknown-state errors.
* :class:`RegimeGate` hysteresis state machine (per-symbol latch,
  ON↔OFF transitions, reset).
* :py:meth:`RegimeGate.from_spec` validates the YAML block shape.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from feelies.signals.regime_gate import (
    Bindings,
    RegimeGate,
    RegimeGateError,
    UnknownIdentifierError,
    UnknownRegimeStateError,
    UnsafeExpressionError,
    compile_expression,
    evaluate,
)


# ── Helpers ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _FakeRegime:
    state_names: tuple[str, ...]
    posteriors: tuple[float, ...]
    dominant_name: str
    posterior_entropy_nats: float = 0.0
    calibrated: bool = True
    discriminability: float = float("inf")


def _bindings(
    *,
    regime: _FakeRegime | None = None,
    sensor_values: dict[str, float] | None = None,
    percentiles: dict[str, float] | None = None,
    zscores: dict[str, float] | None = None,
    min_discriminability: float = 0.0,
) -> Bindings:
    return Bindings(
        regime=regime,
        sensor_values=sensor_values or {},
        percentiles=percentiles or {},
        zscores=zscores or {},
        min_discriminability=min_discriminability,
    )


# ── Parse-time validation ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "expr",
    [
        "P(normal) > 0.7",
        "P(normal) > 0.7 AND ofi_ewma_zscore > 2.0",
        "P(normal) > 0.7 OR P(toxic) < 0.2",
        "abs(spread_z_30d) < 0.5",
        "min(P(normal), P(toxic)) > 0.1",
        "max(ofi_ewma, 0.0) > 1.0",
        "spread_z_30d_percentile < p40",
        'dominant == "normal"',
        "not (spread_z_30d > 2.0)",
    ],
)
def test_compile_accepts_whitelisted(expr: str) -> None:
    compile_expression(expr)


@pytest.mark.parametrize(
    "expr",
    [
        "regime.posteriors[0] > 0.5",  # subscript
        "obj.method()",  # attribute access
        "[x for x in [1, 2]]",  # listcomp
        "lambda x: x > 0",  # lambda
        "open('hack')",  # call to non-whitelisted
        "exec('import os')",  # call to forbidden
        "f'{P(normal)} > 0.5'",  # joined-str
        "x := 1",  # walrus / NamedExpr
        "P(normal) if True else 0",  # IfExp
        "{1: 2}",  # dict literal
        "{1, 2}",  # set literal
    ],
)
def test_compile_rejects_forbidden(expr: str) -> None:
    with pytest.raises(UnsafeExpressionError):
        compile_expression(expr)


def test_compile_rejects_empty_expression() -> None:
    with pytest.raises(UnsafeExpressionError, match="non-empty"):
        compile_expression("")


def test_compile_rejects_keyword_args() -> None:
    with pytest.raises(UnsafeExpressionError, match="keyword arguments"):
        compile_expression("min(a=1, b=2)")


def test_compile_rejects_p_with_non_identifier() -> None:
    with pytest.raises(UnsafeExpressionError, match="bare identifier"):
        compile_expression("P('normal') > 0.5")


# ── Runtime resolution ──────────────────────────────────────────────────


def test_evaluate_posterior_lookup() -> None:
    tree = compile_expression("P(normal) > 0.5")
    regime = _FakeRegime(
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.10, 0.80, 0.10),
        dominant_name="normal",
    )
    assert evaluate(tree, _bindings(regime=regime)) is True


def test_evaluate_unknown_state_raises() -> None:
    tree = compile_expression("P(benign) > 0.5")
    regime = _FakeRegime(
        state_names=("normal",),
        posteriors=(1.0,),
        dominant_name="normal",
    )
    with pytest.raises(UnknownRegimeStateError, match="benign"):
        evaluate(tree, _bindings(regime=regime))


def test_evaluate_dominant_resolution() -> None:
    tree = compile_expression('dominant == "normal"')
    regime = _FakeRegime(
        state_names=("normal", "toxic"),
        posteriors=(0.9, 0.1),
        dominant_name="normal",
    )
    assert evaluate(tree, _bindings(regime=regime)) is True


def test_evaluate_dominant_without_regime_raises() -> None:
    tree = compile_expression('dominant == "normal"')
    with pytest.raises(UnknownIdentifierError, match="dominant"):
        evaluate(tree, _bindings())


def test_evaluate_entropy_binding() -> None:
    tree = compile_expression("entropy < 0.5")
    regime = _FakeRegime(
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.10, 0.80, 0.10),
        dominant_name="normal",
        posterior_entropy_nats=0.3,
    )
    assert evaluate(tree, _bindings(regime=regime)) is True


def test_evaluate_entropy_without_regime_raises() -> None:
    tree = compile_expression("entropy < 1.0")
    with pytest.raises(UnknownIdentifierError, match="entropy"):
        evaluate(tree, _bindings())


def test_compile_accepts_entropy_in_condition() -> None:
    compile_expression("P(normal) > 0.7 AND entropy < 1.0")


def test_evaluate_sensor_value() -> None:
    tree = compile_expression("ofi_ewma > 1.0")
    b = _bindings(sensor_values={"ofi_ewma": 2.5})
    assert evaluate(tree, b) is True


def test_evaluate_zscore_suffix() -> None:
    tree = compile_expression("ofi_ewma_zscore > 2.0")
    b = _bindings(zscores={"ofi_ewma": 3.0})
    assert evaluate(tree, b) is True


def test_evaluate_percentile_suffix_and_literal() -> None:
    tree = compile_expression("vpin_50bucket_percentile < p40")
    b = _bindings(percentiles={"vpin_50bucket": 0.30})
    assert evaluate(tree, b) is True


def test_evaluate_unknown_sensor_raises() -> None:
    tree = compile_expression("ofi_ewma > 0")
    with pytest.raises(UnknownIdentifierError, match="ofi_ewma"):
        evaluate(tree, _bindings())


def test_evaluate_abs_min_max() -> None:
    tree = compile_expression("abs(spread_z_30d) < 0.5")
    b = _bindings(sensor_values={"spread_z_30d": -0.2})
    assert evaluate(tree, b) is True

    tree = compile_expression("min(a, b) > 1")
    b = _bindings(sensor_values={"a": 2.0, "b": 3.0})
    assert evaluate(tree, b) is True

    tree = compile_expression("max(a, b, c) > 5")
    b = _bindings(sensor_values={"a": 1.0, "b": 2.0, "c": 6.0})
    assert evaluate(tree, b) is True


def test_evaluate_compound_and_or() -> None:
    expr = "P(normal) > 0.7 AND abs(spread_z_30d) < 0.5"
    tree = compile_expression(expr)
    regime = _FakeRegime(
        state_names=("normal",),
        posteriors=(0.9,),
        dominant_name="normal",
    )
    b = _bindings(regime=regime, sensor_values={"spread_z_30d": 0.2})
    assert evaluate(tree, b) is True

    b = _bindings(regime=regime, sensor_values={"spread_z_30d": 1.0})
    assert evaluate(tree, b) is False


# ── RegimeGate hysteresis ───────────────────────────────────────────────


def _make_gate() -> RegimeGate:
    return RegimeGate(
        alpha_id="alpha_x",
        on_condition="P(normal) > 0.7",
        off_condition="P(normal) < 0.5",
    )


def test_gate_starts_off() -> None:
    g = _make_gate()
    assert g.is_on("AAPL") is False


def test_gate_transitions_off_to_on_to_off() -> None:
    g = _make_gate()
    regime_high = _FakeRegime(("normal",), (0.9,), "normal")
    regime_low = _FakeRegime(("normal",), (0.4,), "normal")
    regime_mid = _FakeRegime(("normal",), (0.6,), "normal")

    assert g.evaluate(symbol="AAPL", bindings=_bindings(regime=regime_high)) is True
    assert g.is_on("AAPL") is True

    # Mid-band: neither on nor off → stays ON (hysteresis).
    assert g.evaluate(symbol="AAPL", bindings=_bindings(regime=regime_mid)) is True

    # Drop below off threshold → OFF.
    assert g.evaluate(symbol="AAPL", bindings=_bindings(regime=regime_low)) is False
    assert g.is_on("AAPL") is False


def test_gate_per_symbol_independence() -> None:
    g = _make_gate()
    high = _FakeRegime(("normal",), (0.9,), "normal")
    low = _FakeRegime(("normal",), (0.3,), "normal")

    g.evaluate(symbol="AAPL", bindings=_bindings(regime=high))
    g.evaluate(symbol="MSFT", bindings=_bindings(regime=low))

    assert g.is_on("AAPL") is True
    assert g.is_on("MSFT") is False


def test_gate_reset_single_and_all() -> None:
    g = _make_gate()
    high = _FakeRegime(("normal",), (0.9,), "normal")

    g.evaluate(symbol="AAPL", bindings=_bindings(regime=high))
    g.evaluate(symbol="MSFT", bindings=_bindings(regime=high))
    assert g.is_on("AAPL") is True
    assert g.is_on("MSFT") is True

    g.reset("AAPL")
    assert g.is_on("AAPL") is False
    assert g.is_on("MSFT") is True

    g.reset()
    assert g.is_on("MSFT") is False


# ── from_spec validation ────────────────────────────────────────────────


def test_from_spec_rejects_non_mapping() -> None:
    with pytest.raises(RegimeGateError, match="must be a mapping"):
        RegimeGate.from_spec(alpha_id="alpha_x", spec=[])  # type: ignore[arg-type]


def test_from_spec_rejects_missing_on_condition() -> None:
    with pytest.raises(RegimeGateError, match="on_condition"):
        RegimeGate.from_spec(
            alpha_id="alpha_x",
            spec={"off_condition": "P(normal) < 0.5"},
        )


def test_from_spec_rejects_empty_off_condition() -> None:
    with pytest.raises(RegimeGateError, match="off_condition"):
        RegimeGate.from_spec(
            alpha_id="alpha_x",
            spec={"on_condition": "P(normal) > 0.7", "off_condition": "  "},
        )


def test_from_spec_propagates_unsafe_expression() -> None:
    with pytest.raises(UnsafeExpressionError):
        RegimeGate.from_spec(
            alpha_id="alpha_x",
            spec={
                "on_condition": "open('hack')",
                "off_condition": "P(normal) < 0.5",
            },
        )


def test_from_spec_records_engine_name_and_hysteresis() -> None:
    g = RegimeGate.from_spec(
        alpha_id="alpha_x",
        spec={
            "regime_engine": "hmm_3state_fractional",
            "on_condition": "P(normal) > 0.7",
            "off_condition": "P(normal) < 0.5",
            "hysteresis": {"posterior_margin": 0.20, "percentile_margin": 0.30},
        },
    )
    assert g.engine_name == "hmm_3state_fractional"
    h = g.hysteresis
    assert h["posterior_margin"] == pytest.approx(0.20)
    assert h["percentile_margin"] == pytest.approx(0.30)


def test_binding_identifier_names_strips_regime_and_hysteresis_noise() -> None:
    g = RegimeGate(
        alpha_id="a",
        on_condition="P(normal) > 0.6 and spread_z_30d <= 1.0",
        off_condition="P(normal) < 0.4 or spread_z_30d > 2.0",
        hysteresis={"posterior_margin": 0.2, "percentile_margin": 0.3},
        engine_name="hmm",
    )
    assert g.binding_identifier_names() == frozenset({"spread_z_30d"})


def test_binding_identifier_names_keeps_zscore_identifiers() -> None:
    g = RegimeGate(
        alpha_id="a",
        on_condition="P(normal) > 0.7 and ofi_ewma_zscore > 2.0",
        off_condition="P(normal) < 0.5",
        engine_name="hmm",
    )
    assert g.binding_identifier_names() == frozenset({"ofi_ewma_zscore"})


# ── Warn on unreferenced hysteresis margins ─────────────────────────


def test_from_spec_warns_when_hysteresis_unreferenced(caplog):
    """A declared hysteresis block whose keys are not referenced by
    either condition is dead config — surface a load-time warning."""
    import logging

    spec = {
        "regime_engine": "hmm_3state_fractional",
        "on_condition": "P(normal) > 0.6",
        "off_condition": "P(normal) < 0.4",
        "hysteresis": {
            "posterior_margin": 0.20,
            "percentile_margin": 0.30,
        },
    }
    with caplog.at_level(logging.WARNING, logger="feelies.signals.regime_gate"):
        from feelies.signals.regime_gate import RegimeGate

        RegimeGate.from_spec(alpha_id="alpha_unref", spec=spec)
    assert any(
        "hysteresis declares" in r.message and "dead config" in r.message for r in caplog.records
    ), [r.message for r in caplog.records]


def test_from_spec_no_warning_when_hysteresis_referenced(caplog):
    """When the expressions reference the declared margins the warning
    must not fire (e.g. sig_inventory_revert_v1's pattern)."""
    import logging

    spec = {
        "regime_engine": "hmm_3state_fractional",
        "on_condition": "P(normal) > 0.6 + posterior_margin",
        "off_condition": "P(normal) < 0.5 - posterior_margin",
        "hysteresis": {
            "posterior_margin": 0.10,
        },
    }
    with caplog.at_level(logging.WARNING, logger="feelies.signals.regime_gate"):
        from feelies.signals.regime_gate import RegimeGate

        RegimeGate.from_spec(alpha_id="alpha_ref", spec=spec)
    assert not any("dead config" in r.message for r in caplog.records)


# ── Uncalibrated regimes fail gate bindings safely ──────────────────────


def test_uncalibrated_regime_makes_posterior_unavailable() -> None:
    """Treat uncalibrated posteriors as unavailable to trading gates."""
    regime = _FakeRegime(
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.0, 0.0, 1.0),
        dominant_name="vol_breakout",
        calibrated=False,
    )
    tree = compile_expression("P(normal) > 0.5")
    with pytest.raises(UnknownIdentifierError):
        evaluate(tree, _bindings(regime=regime))


def test_uncalibrated_regime_makes_dominant_and_entropy_unavailable() -> None:
    regime = _FakeRegime(
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.2, 0.3, 0.5),
        dominant_name="vol_breakout",
        posterior_entropy_nats=1.0,
        calibrated=False,
    )
    for expr in ('dominant == "normal"', "entropy < 0.9"):
        with pytest.raises(UnknownIdentifierError):
            evaluate(compile_expression(expr), _bindings(regime=regime))


def test_uncalibrated_regime_still_surfaces_typo_as_unknown_state() -> None:
    """A misspelled P(<name>) is an UnknownRegimeStateError even uncalibrated.

    The calibration fail-safe must not mask authoring typos: an undeclared
    state name takes precedence over the uncalibrated-unavailable signal.
    """
    regime = _FakeRegime(
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.0, 0.0, 1.0),
        dominant_name="vol_breakout",
        calibrated=False,
    )
    with pytest.raises(UnknownRegimeStateError):
        evaluate(compile_expression("P(noraml) > 0.5"), _bindings(regime=regime))


def test_calibrated_regime_resolves_normally() -> None:
    """The default (calibrated=True) path is unchanged."""
    regime = _FakeRegime(
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.1, 0.7, 0.2),
        dominant_name="normal",
        posterior_entropy_nats=0.8,
    )
    assert evaluate(compile_expression("P(normal) > 0.5"), _bindings(regime=regime)) is True
    assert evaluate(compile_expression('dominant == "normal"'), _bindings(regime=regime)) is True


def test_uncalibrated_gate_latches_off() -> None:
    """End-to-end through the latch: an uncalibrated regime keeps the gate OFF."""
    gate = RegimeGate(
        alpha_id="a",
        on_condition="P(normal) > 0.5",
        off_condition="P(normal) < 0.3",
    )
    regime = _FakeRegime(
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.0, 0.9, 0.1),  # would be ON if trusted
        dominant_name="normal",
        calibrated=False,
    )
    # evaluate() does not swallow the error; the HorizonSignalEngine does.
    with pytest.raises(UnknownIdentifierError):
        gate.evaluate(symbol="AAPL", bindings=_bindings(regime=regime))
    assert gate.is_on("AAPL") is False


# ── Percentile literal boundaries ───────────────────────────────────────


def test_percentile_literal_p100_resolves() -> None:
    assert evaluate(compile_expression("p100 == 1.0"), _bindings()) is True
    assert evaluate(compile_expression("p0 == 0.0"), _bindings()) is True


def test_percentile_literal_out_of_range_rejected() -> None:
    with pytest.raises(UnsafeExpressionError):
        evaluate(compile_expression("p101 > 0.5"), _bindings())


# ── Indiscriminate regimes fail gate bindings safely ────────────────────


def _discr_regime(d: float) -> _FakeRegime:
    return _FakeRegime(
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.34, 0.33, 0.33),
        dominant_name="compression_clustering",
        posterior_entropy_nats=1.09,
        calibrated=True,
        discriminability=d,
    )


def test_indiscriminate_regime_below_floor_unavailable() -> None:
    """P(), dominant, and entropy fail below the discriminability floor."""
    regime = _discr_regime(0.05)  # degenerate calibration
    b = _bindings(regime=regime, min_discriminability=0.5)
    for expr in ("P(normal) > 0.5", 'dominant == "normal"', "entropy < 1.0"):
        with pytest.raises(UnknownIdentifierError, match="indiscriminate"):
            evaluate(compile_expression(expr), b)


def test_discriminative_regime_above_floor_resolves() -> None:
    """A well-separated regime resolves normally even with the floor set."""
    regime = _discr_regime(1.48)  # APP-like
    b = _bindings(regime=regime, min_discriminability=0.5)
    assert evaluate(compile_expression("P(compression_clustering) > 0.3"), b) is True
    assert evaluate(compile_expression('dominant == "compression_clustering"'), b) is True


def test_default_floor_zero_is_noop() -> None:
    """Floor 0.0 (the default) never disables, even for d==0.0."""
    regime = _discr_regime(0.0)
    b = _bindings(regime=regime, min_discriminability=0.0)
    assert evaluate(compile_expression("P(normal) >= 0.0"), b) is True


def test_indiscriminate_still_surfaces_typo_as_unknown_state() -> None:
    """A misspelled P(<name>) is UnknownRegimeStateError even below the floor."""
    regime = _discr_regime(0.05)
    b = _bindings(regime=regime, min_discriminability=0.5)
    with pytest.raises(UnknownRegimeStateError):
        evaluate(compile_expression("P(noraml) > 0.5"), b)


def test_regime_free_gate_unaffected_by_floor() -> None:
    """A gate that references no regime binding is never disabled by the floor
    (the unusable-reason check is only reached via P()/dominant/entropy)."""
    regime = _discr_regime(0.01)
    b = _bindings(regime=regime, sensor_values={"spread_z_30d": 0.2}, min_discriminability=0.9)
    # Pure sensor gate (cf. sig_moc_imbalance_v1) resolves regardless.
    assert evaluate(compile_expression("spread_z_30d < 1.5"), b) is True


# Parameter injection as gate constants.


def test_param_injected_as_gate_constant() -> None:
    gate = RegimeGate(
        alpha_id="a",
        on_condition="ofi_ewma > entry_z",
        off_condition="ofi_ewma < 0",
        params={"entry_z": 2.0},
    )
    assert gate.evaluate(symbol="X", bindings=_bindings(sensor_values={"ofi_ewma": 3.0})) is True
    gate2 = RegimeGate(
        alpha_id="a",
        on_condition="ofi_ewma > entry_z",
        off_condition="ofi_ewma < 0",
        params={"entry_z": 2.0},
    )
    assert gate2.evaluate(symbol="X", bindings=_bindings(sensor_values={"ofi_ewma": 1.0})) is False


def test_param_names_excluded_from_binding_identifiers() -> None:
    gate = RegimeGate(
        alpha_id="a",
        on_condition="ofi_ewma > entry_z",
        off_condition="ofi_ewma < 0",
        params={"entry_z": 2.0},
    )
    names = gate.binding_identifier_names()
    assert "entry_z" not in names  # injected constant, not a warm-sensor binding
    assert "ofi_ewma" in names


def test_real_sensor_overrides_param_constant() -> None:
    # A live sensor of the same name wins; the param is only the fallback.
    gate = RegimeGate(
        alpha_id="a",
        on_condition="threshold > 5",
        off_condition="threshold < 0",
        params={"threshold": 1.0},  # would be 1 > 5 -> False on its own
    )
    assert gate.evaluate(symbol="X", bindings=_bindings(sensor_values={"threshold": 10.0})) is True


def test_hysteresis_overrides_param_on_collision() -> None:
    gate = RegimeGate(
        alpha_id="a",
        on_condition="P(normal) > margin",
        off_condition="P(normal) < 0",
        params={"margin": 0.9},
        hysteresis={"margin": 0.2},  # hysteresis wins -> 0.5 > 0.2 True
    )
    regime = _FakeRegime(
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.25, 0.5, 0.25),
        dominant_name="normal",
    )
    assert gate.evaluate(symbol="X", bindings=_bindings(regime=regime)) is True


# Strict dead-hysteresis load error.


def _dead_hyst_spec() -> dict:
    return {
        "regime_engine": "hmm_3state_fractional",
        "on_condition": "P(normal) > 0.6",
        "off_condition": "P(normal) < 0.4",
        "hysteresis": {"posterior_margin": 0.2},
    }


def test_from_spec_strict_rejects_dead_hysteresis() -> None:
    with pytest.raises(RegimeGateError, match="dead config"):
        RegimeGate.from_spec(alpha_id="a", spec=_dead_hyst_spec(), strict=True)


def test_from_spec_non_strict_accepts_dead_hysteresis(caplog) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger="feelies.signals.regime_gate"):
        gate = RegimeGate.from_spec(alpha_id="a", spec=_dead_hyst_spec(), strict=False)
    assert gate is not None
    assert any("dead config" in r.message for r in caplog.records)


def test_from_spec_strict_accepts_referenced_hysteresis() -> None:
    spec = {
        "regime_engine": "hmm_3state_fractional",
        "on_condition": "P(normal) > 0.6 + posterior_margin",
        "off_condition": "P(normal) < 0.4 - posterior_margin",
        "hysteresis": {"posterior_margin": 0.1},
    }
    gate = RegimeGate.from_spec(alpha_id="a", spec=spec, strict=True)
    assert gate is not None
