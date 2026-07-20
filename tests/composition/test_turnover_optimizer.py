"""Closed-form ``TurnoverOptimizer`` behavior and statuses.

These lock the deterministic closed-form path that runs by default
(``require_solver=False``); the cvxpy/ECOS path parity is covered by
``tests/determinism/test_sized_intent_solver_replay.py``.
"""

from __future__ import annotations

import pytest

from feelies.composition.turnover_optimizer import TurnoverOptimizer, round_cents

_CAPITAL = 100_000.0


def test_round_cents_is_half_up() -> None:
    """Target-dollar rounding is half-up, not banker's rounding."""
    # Half-cent cases where round-half-to-even (float ``round``) diverges from
    # the declared ROUND_HALF_UP mode used at the risk boundary.
    assert round_cents(2.675) == 2.68  # float round(2.675, 2) == 2.67
    assert round_cents(0.125) == 0.13  # float round(0.125, 2) == 0.12
    assert round_cents(-2.675) == -2.68  # half away from zero
    # Plain values are unaffected and the function is deterministic.
    assert round_cents(123.454) == 123.45
    assert round_cents(123.456) == round_cents(123.456)


def test_empty_universe_status() -> None:
    opt = TurnoverOptimizer(capital_usd=_CAPITAL)
    result = opt.optimize({}, ())
    assert result.target_usd == {}
    assert result.solver_status == "EMPTY_UNIVERSE"


def test_zero_gross_status() -> None:
    opt = TurnoverOptimizer(capital_usd=_CAPITAL)
    result = opt.optimize({"AAPL": 0.0, "MSFT": 0.0}, ("AAPL", "MSFT"))
    assert result.target_usd == {}
    assert result.solver_status == "ZERO_GROSS"


def test_small_gross_reaches_target_gross() -> None:
    # gross(weights) = 0.6 < gross_cap (2.0) — the old min(..., capital)
    # clamping would under-lever this to about 60k; rescaling reaches
    # the full target 2.0 × capital = 200k (per-name cap 100% does not bind).
    opt = TurnoverOptimizer(capital_usd=_CAPITAL, gross_cap_pct=2.0, per_name_cap_pct=1.0)
    weights = {"AAPL": 0.2, "MSFT": 0.2, "TSLA": -0.2}
    result = opt.optimize(weights, ("AAPL", "MSFT", "TSLA"))
    assert result.expected_gross_exposure_usd == pytest.approx(2.0 * _CAPITAL, rel=1e-4)
    # No per-name clipping at this scale.
    assert result.target_usd["AAPL"] == pytest.approx(2.0 * _CAPITAL / 3.0, rel=1e-4)
    assert result.solver_status == "CLOSED_FORM"


def test_per_name_cap_binds() -> None:
    opt = TurnoverOptimizer(capital_usd=_CAPITAL, gross_cap_pct=2.0, per_name_cap_pct=0.10)
    # One dominant name: per-name cap = 10% × capital = 10k.
    weights = {"AAPL": 0.9, "MSFT": 0.1}
    result = opt.optimize(weights, ("AAPL", "MSFT"))
    assert abs(result.target_usd.get("AAPL", 0.0)) <= 0.10 * _CAPITAL + 0.01


def test_gross_cap_enforced() -> None:
    opt = TurnoverOptimizer(capital_usd=_CAPITAL, gross_cap_pct=1.0, per_name_cap_pct=1.0)
    weights = {"AAPL": 0.5, "MSFT": -0.5}
    result = opt.optimize(weights, ("AAPL", "MSFT"))
    assert result.expected_gross_exposure_usd <= 1.0 * _CAPITAL + 0.01


def test_closed_form_ignores_lambda_penalties() -> None:
    """The closed-form path ignores lambda penalties.

    Documents that the turnover/risk penalties are inert outside the solver
    path, so an operator tuning them under ``composition_optimizer_mode:
    closed_form`` does not change the desired book.
    """
    weights = {"AAPL": 0.6, "MSFT": -0.3, "TSLA": 0.1}
    universe = ("AAPL", "MSFT", "TSLA")
    current = {"AAPL": 50_000.0, "MSFT": 0.0, "TSLA": 0.0}
    low = TurnoverOptimizer(capital_usd=_CAPITAL, lambda_tc=0.0, lambda_risk=0.0)
    high = TurnoverOptimizer(capital_usd=_CAPITAL, lambda_tc=100.0, lambda_risk=100.0)
    assert (
        low.optimize(weights, universe, current).target_usd
        == high.optimize(weights, universe, current).target_usd
    )


def test_closed_form_is_deterministic() -> None:
    opt = TurnoverOptimizer(capital_usd=_CAPITAL)
    weights = {"AAPL": 0.3, "MSFT": -0.2, "TSLA": 0.1}
    universe = ("AAPL", "MSFT", "TSLA")
    assert opt.optimize(weights, universe).target_usd == opt.optimize(weights, universe).target_usd


def test_small_universe_default_caps_collapse_conviction_to_equal_notional() -> None:
    """Default per-name caps flatten conviction in a small universe.

    Operators can raise ``composition_per_name_cap_pct`` when relative weights
    must survive sizing.
    """
    capital = 150_000.0
    weights = {"AAPL": 0.371, "MSFT": -1.367, "NVDA": 0.997}
    universe = ("AAPL", "MSFT", "NVDA")

    default_caps = TurnoverOptimizer(capital_usd=capital)
    result = default_caps.optimize(weights, universe)
    magnitudes = {abs(v) for v in result.target_usd.values()}
    assert magnitudes == {0.05 * capital}, (
        f"expected every name to collapse to the 5% per-name cap under "
        f"default caps, got {result.target_usd}"
    )

    # Raising the per-name cap lets relative conviction carry through to sizing.
    loose_caps = TurnoverOptimizer(capital_usd=capital, per_name_cap_pct=1.0)
    loose_result = loose_caps.optimize(weights, universe)
    loose_magnitudes = {abs(v) for v in loose_result.target_usd.values()}
    assert len(loose_magnitudes) == 3, (
        "raising per_name_cap_pct should preserve each name's distinct "
        f"conviction, got {loose_result.target_usd}"
    )
