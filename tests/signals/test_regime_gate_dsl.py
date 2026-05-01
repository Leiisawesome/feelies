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


def _bindings(
    *,
    regime: _FakeRegime | None = None,
    sensor_values: dict[str, float] | None = None,
    percentiles: dict[str, float] | None = None,
    zscores: dict[str, float] | None = None,
) -> Bindings:
    return Bindings(
        regime=regime,
        sensor_values=sensor_values or {},
        percentiles=percentiles or {},
        zscores=zscores or {},
    )


# ── Parse-time validation ───────────────────────────────────────────────


@pytest.mark.parametrize("expr", [
    "P(normal) > 0.7",
    "P(normal) > 0.7 AND ofi_ewma_zscore > 2.0",
    "P(normal) > 0.7 OR P(toxic) < 0.2",
    "abs(spread_z_30d) < 0.5",
    "min(P(normal), P(toxic)) > 0.1",
    "max(ofi_ewma, 0.0) > 1.0",
    "spread_z_30d_percentile < p40",
    "dominant == \"normal\"",
    "not (spread_z_30d > 2.0)",
])
def test_compile_accepts_whitelisted(expr: str) -> None:
    compile_expression(expr)


@pytest.mark.parametrize("expr", [
    "regime.posteriors[0] > 0.5",          # subscript
    "obj.method()",                         # attribute access
    "[x for x in [1, 2]]",                 # listcomp
    "lambda x: x > 0",                      # lambda
    "open('hack')",                          # call to non-whitelisted
    "exec('import os')",                    # call to forbidden
    "f'{P(normal)} > 0.5'",                  # joined-str
    "x := 1",                                # walrus / NamedExpr
    "P(normal) if True else 0",             # IfExp
    "{1: 2}",                                # dict literal
    "{1, 2}",                                # set literal
])
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
    tree = compile_expression("dominant == \"normal\"")
    regime = _FakeRegime(
        state_names=("normal", "toxic"),
        posteriors=(0.9, 0.1),
        dominant_name="normal",
    )
    assert evaluate(tree, _bindings(regime=regime)) is True


def test_evaluate_dominant_without_regime_raises() -> None:
    tree = compile_expression("dominant == \"normal\"")
    with pytest.raises(UnknownIdentifierError, match="dominant"):
        evaluate(tree, _bindings())


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
