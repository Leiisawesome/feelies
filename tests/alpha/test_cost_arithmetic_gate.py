"""Tests for the cost-arithmetic disclosure gate (G12 / Phase 3-α).

Covers ``feelies.alpha.cost_arithmetic.CostArithmetic``:

* :py:meth:`CostArithmetic.from_spec` — happy path, missing fields,
  type coercion, sign / magnitude rules, declared-vs-computed
  reconciliation, MIN_MARGIN_RATIO floor.
* :py:func:`compute_margin_ratio` — pure arithmetic helper, including
  the zero-cost edge case.

The gate is purely structural: it never inspects platform state, so
all tests are fast unit-tests.
"""

from __future__ import annotations

import math

import pytest

from feelies.alpha.cost_arithmetic import (
    MARGIN_RATIO_TOLERANCE,
    MIN_MARGIN_RATIO,
    CostArithmetic,
    CostArithmeticError,
    compute_margin_ratio,
)


def _spec(**overrides: float) -> dict[str, float]:
    base = {
        "edge_estimate_bps": 9.0,
        "half_spread_bps": 2.0,
        "impact_bps": 2.0,
        "fee_bps": 1.0,
        "margin_ratio": 1.8,
    }
    base.update(overrides)
    return base


# ── Happy path ──────────────────────────────────────────────────────────


def test_from_spec_happy_path() -> None:
    block = CostArithmetic.from_spec(alpha_id="alpha_x", spec=_spec())
    assert block.edge_estimate_bps == 9.0
    assert block.cost_total_bps == pytest.approx(5.0)
    assert block.margin_ratio == 1.8
    assert block.computed_margin_ratio == pytest.approx(1.8, abs=1e-6)


def test_from_spec_within_tolerance() -> None:
    """A small declared/computed mismatch within tolerance is accepted."""
    block = CostArithmetic.from_spec(
        alpha_id="alpha_x",
        spec=_spec(margin_ratio=1.83),
    )
    assert block.margin_ratio == 1.83


# ── Validation: structural ──────────────────────────────────────────────


def test_from_spec_rejects_missing_block() -> None:
    with pytest.raises(CostArithmeticError, match="cost_arithmetic block"):
        CostArithmetic.from_spec(alpha_id="alpha_x", spec=None)


def test_from_spec_rejects_non_mapping() -> None:
    with pytest.raises(CostArithmeticError, match="must be a mapping"):
        CostArithmetic.from_spec(alpha_id="alpha_x", spec=[1, 2, 3])  # type: ignore[arg-type]


def test_from_spec_rejects_missing_fields() -> None:
    spec = _spec()
    spec.pop("impact_bps")
    with pytest.raises(CostArithmeticError, match="missing required field"):
        CostArithmetic.from_spec(alpha_id="alpha_x", spec=spec)


@pytest.mark.parametrize("field", [
    "edge_estimate_bps", "half_spread_bps", "impact_bps", "fee_bps",
    "margin_ratio",
])
def test_from_spec_rejects_non_numeric(field: str) -> None:
    spec = _spec()
    spec[field] = "not a number"  # type: ignore[assignment]
    with pytest.raises(CostArithmeticError, match=f"{field}"):
        CostArithmetic.from_spec(alpha_id="alpha_x", spec=spec)


def test_from_spec_rejects_bool_as_number() -> None:
    """``bool`` is technically ``int`` — gate must reject it explicitly."""
    spec = _spec()
    spec["edge_estimate_bps"] = True  # type: ignore[assignment]
    with pytest.raises(CostArithmeticError, match="edge_estimate_bps"):
        CostArithmetic.from_spec(alpha_id="alpha_x", spec=spec)


def test_from_spec_rejects_non_finite() -> None:
    spec = _spec(edge_estimate_bps=float("inf"))
    with pytest.raises(CostArithmeticError, match="finite"):
        CostArithmetic.from_spec(alpha_id="alpha_x", spec=spec)


# ── Validation: signs / magnitudes ──────────────────────────────────────


def test_from_spec_rejects_zero_edge() -> None:
    spec = _spec(edge_estimate_bps=0.0)
    with pytest.raises(CostArithmeticError, match="edge_estimate_bps"):
        CostArithmetic.from_spec(alpha_id="alpha_x", spec=spec)


def test_from_spec_rejects_negative_edge() -> None:
    spec = _spec(edge_estimate_bps=-1.0)
    with pytest.raises(CostArithmeticError, match="edge_estimate_bps"):
        CostArithmetic.from_spec(alpha_id="alpha_x", spec=spec)


@pytest.mark.parametrize("field", ["half_spread_bps", "impact_bps", "fee_bps"])
def test_from_spec_rejects_negative_cost_components(field: str) -> None:
    spec = _spec()
    spec[field] = -0.1
    with pytest.raises(CostArithmeticError, match=field):
        CostArithmetic.from_spec(alpha_id="alpha_x", spec=spec)


# ── Validation: margin ratio floor + reconciliation ─────────────────────


def test_from_spec_rejects_below_min_margin_ratio() -> None:
    spec = _spec(margin_ratio=MIN_MARGIN_RATIO - 0.01)
    with pytest.raises(CostArithmeticError, match="margin_ratio"):
        CostArithmetic.from_spec(alpha_id="alpha_x", spec=spec)


def test_from_spec_accepts_floor_exactly() -> None:
    # edge=7.5, cost=5.0  → ratio 1.5 exactly
    spec = _spec(edge_estimate_bps=7.5, margin_ratio=1.5)
    block = CostArithmetic.from_spec(alpha_id="alpha_x", spec=spec)
    assert block.margin_ratio == pytest.approx(1.5)


def test_from_spec_rejects_disclosed_disagrees_with_computed() -> None:
    # cost=5, edge=9 → computed=1.8; declare 2.5 (well outside tol)
    spec = _spec(margin_ratio=2.5)
    with pytest.raises(CostArithmeticError, match="disagrees with computed"):
        CostArithmetic.from_spec(alpha_id="alpha_x", spec=spec)


# ── compute_margin_ratio helper ─────────────────────────────────────────


def test_compute_margin_ratio_basic() -> None:
    assert compute_margin_ratio(
        edge_bps=10.0, half_spread_bps=2.0, impact_bps=2.0, fee_bps=1.0,
    ) == pytest.approx(2.0)


def test_compute_margin_ratio_zero_cost_returns_inf() -> None:
    val = compute_margin_ratio(
        edge_bps=10.0, half_spread_bps=0.0, impact_bps=0.0, fee_bps=0.0,
    )
    assert math.isinf(val)


def test_constants_exported() -> None:
    assert MIN_MARGIN_RATIO == 1.5
    assert 0.0 < MARGIN_RATIO_TOLERANCE < 1.0
