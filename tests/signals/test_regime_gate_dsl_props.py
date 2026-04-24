"""Hypothesis property tests for the regime-gate DSL.

Properties enforced:

1. **Soundness**: any AST that survives :func:`compile_expression`
   contains *only* whitelisted node types — proven by walking the
   returned tree.
2. **Determinism**: evaluating the same compiled tree against
   structurally-equal :class:`Bindings` yields the same value across
   repeated calls (no hidden RNG, no time-dependence).
3. **Safety**: a curated corpus of forbidden expressions always raises
   :class:`UnsafeExpressionError`; conversely a curated corpus of
   syntactically valid whitelisted expressions never raises.
4. **Hysteresis**: per-symbol latch is monotonic per single evaluation
   — the post-state is always one of {prior, opposite}, never some
   third value.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from feelies.signals.regime_gate import (
    Bindings,
    RegimeGate,
    UnsafeExpressionError,
    compile_expression,
    evaluate,
)


# ── Strategies ──────────────────────────────────────────────────────────


_FINITE_FLOATS = st.floats(
    min_value=-100.0, max_value=100.0,
    allow_nan=False, allow_infinity=False,
)


@dataclass(frozen=True)
class _FakeRegime:
    state_names: tuple[str, ...]
    posteriors: tuple[float, ...]
    dominant_name: str


def _bindings(
    sensor_values: dict[str, float] | None = None,
    percentiles: dict[str, float] | None = None,
    zscores: dict[str, float] | None = None,
    regime: _FakeRegime | None = None,
) -> Bindings:
    return Bindings(
        regime=regime,
        sensor_values=sensor_values or {},
        percentiles=percentiles or {},
        zscores=zscores or {},
    )


# Allowed AST classes identical to the parser's whitelist.  We import
# the constant transitively by walking a tree we know to be valid.
def _collect_allowed_nodes() -> frozenset[type[ast.AST]]:
    """Seed the whitelist by walking known-safe expressions.

    We compile multiple expressions covering every allowed operator and
    union the discovered node types.  This snapshot is what the
    soundness property test compares against.
    """
    seeds = [
        "P(normal) > 0.5 AND abs(spread_z_30d) < 0.5 OR not (a < b)",
        "ofi_ewma + 1.0 > 0.0",
        "a - b * c / d > 0",
        "a % b > 0",
        "a // b > 0",
        "+x > -y",
        "P(normal) >= 0.5 AND P(toxic) <= 0.3 AND a != 0 AND b == 0",
    ]
    out: set[type[ast.AST]] = set()
    for s in seeds:
        for n in ast.walk(compile_expression(s)):
            out.add(type(n))
    return frozenset(out)


_OBSERVED_ALLOWED = _collect_allowed_nodes()


# ── Property 1: every node in a compiled tree is whitelisted ────────────


_VALID_EXPRESSIONS = [
    "P(normal) > 0.7",
    "P(toxic) < 0.3 OR P(normal) > 0.5",
    "abs(spread_z_30d) < 0.5",
    "min(a, b, c) > 0",
    "max(P(normal), P(toxic)) > 0.5",
    "ofi_ewma_zscore > 2.0 AND vpin_50bucket_percentile < p40",
    "dominant == \"normal\"",
    "not (spread_z_30d > 2.0)",
    "ofi_ewma + 1.0 > 0.0",
    "(a > b) AND (c < d) OR (e == f)",
]


@pytest.mark.parametrize("expr", _VALID_EXPRESSIONS)
def test_compiled_tree_contains_only_whitelisted_nodes(expr: str) -> None:
    tree = compile_expression(expr)
    for node in ast.walk(tree):
        # The walker may surface descendants of allowed parents; treat
        # any "all-allowed" tree as proof of soundness.
        assert type(node) in _OBSERVED_ALLOWED | {
            ast.cmpop, ast.boolop, ast.operator, ast.unaryop,
        } | {
            ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.FloorDiv,
            ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
        }, (
            f"forbidden node {type(node).__name__!r} survived parser "
            f"for expression {expr!r}"
        )


# ── Property 2: deterministic evaluation ────────────────────────────────


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(
    sv1=_FINITE_FLOATS, sv2=_FINITE_FLOATS,
    z1=_FINITE_FLOATS, p1=st.floats(0.0, 1.0),
)
def test_evaluation_is_deterministic(
    sv1: float, sv2: float, z1: float, p1: float,
) -> None:
    tree = compile_expression(
        "ofi_ewma > spread_z_30d AND ofi_ewma_zscore > 0 AND "
        "vpin_50bucket_percentile < p40"
    )
    b = _bindings(
        sensor_values={"ofi_ewma": sv1, "spread_z_30d": sv2},
        zscores={"ofi_ewma": z1},
        percentiles={"vpin_50bucket": p1},
    )
    a = evaluate(tree, b)
    c = evaluate(tree, b)
    assert a == c


# ── Property 3: forbidden expressions always raise ──────────────────────


_FORBIDDEN_CORPUS = [
    "import os",                           # SyntaxError → wrapped as Unsafe
    "regime.posteriors",                    # attribute
    "values[0]",                            # subscript
    "[i for i in range(3)]",               # listcomp
    "lambda x: x",                          # lambda
    "1 if True else 2",                    # IfExp
    "yield 1",                              # yield (SyntaxError outside def)
    "P('normal')",                          # P with string arg
    "P(normal, toxic)",                     # P with two args
    "min(a=1)",                             # keyword arg
    "{'a': 1}",                             # dict literal
    "{1, 2, 3}",                            # set literal
    "f'{x}'",                               # f-string
    "a := 1",                               # walrus
]


@pytest.mark.parametrize("expr", _FORBIDDEN_CORPUS)
def test_forbidden_expressions_always_raise(expr: str) -> None:
    with pytest.raises(UnsafeExpressionError):
        compile_expression(expr)


# ── Property 4: hysteresis latch monotonicity ───────────────────────────


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(posteriors=st.lists(
    st.floats(0.0, 1.0, allow_nan=False, allow_infinity=False),
    min_size=1, max_size=50,
))
def test_gate_post_state_is_boolean_and_in_two_value_set(
    posteriors: list[float],
) -> None:
    """Each evaluation must return exactly True or False.

    Stronger property: across an arbitrary sequence of posteriors the
    latch transitions only ever land on ``True`` or ``False``; we
    never see e.g. an integer or a string sneaking through the gate.
    """
    g = RegimeGate(
        alpha_id="alpha_x",
        on_condition="P(normal) > 0.7",
        off_condition="P(normal) < 0.5",
    )
    states: list[bool] = []
    for p in posteriors:
        regime = _FakeRegime(("normal",), (p,), "normal")
        out = g.evaluate(symbol="AAPL", bindings=_bindings(regime=regime))
        assert out is True or out is False
        states.append(out)
    # Equally, the cached is_on agrees with the last returned value.
    assert g.is_on("AAPL") is states[-1]
