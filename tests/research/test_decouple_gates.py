"""Stage-0 ``decouple_caps_only`` research harness (dual-permission Phase 6).

Covers :mod:`feelies.research.decouple_gates`:

  * :func:`conditional_cvar` — expected-shortfall arithmetic.
  * :func:`apply_inv12_cost_stress` — the 1.5× cost leg.
  * :func:`build_conditional_cvar_evidence` — pass / tail-worse / under-powered
    cells, Inv-12 provenance, and determinism (Inv-5).
  * :func:`build_turnover_bound_evidence` — pass and churn-beyond-bound.

The gate arithmetic is exercised through the *builders*, then validated with the
real :func:`feelies.promotion.evidence.validate_conditional_cvar` /
``validate_turnover_bound`` so the harness and gate stay in lock-step.
"""

from __future__ import annotations

import math

import pytest

from feelies.promotion.evidence import (
    GateThresholds,
    validate_conditional_cvar,
    validate_turnover_bound,
)
from feelies.core.inv12_stress import (
    INV12_COST_STRESS_MULTIPLIER,
    INV12_LATENCY_STRESS_MULTIPLIER,
)
from feelies.research.cpcv import CPCVConfig
from feelies.research.decouple_gates import (
    apply_inv12_cost_stress,
    build_conditional_cvar_evidence,
    build_turnover_bound_evidence,
    conditional_cvar,
)

# A CPCV config clearing the default decouple gate floors: C(9, 1) = 9 paths
# (>= decouple_cvar_min_folds = 8) and embargo 5 (>= 1).
_CFG = CPCVConfig(n_groups=10, k_test_groups=2, embargo_bars=5)


# ─────────────────────────────────────────────────────────────────────
#   conditional_cvar
# ─────────────────────────────────────────────────────────────────────


class TestConditionalCVaR:
    def test_expected_shortfall_of_worst_fraction(self) -> None:
        # 20 returns, worst 5% = the single worst observation.
        returns = [float(x) for x in range(20)]  # 0 .. 19
        # level 0.05 -> tail_count = int(0.05*20) = 1 -> the worst is 0.0.
        assert conditional_cvar(returns, 0.05) == 0.0

    def test_tail_is_the_mean_of_the_worst_block(self) -> None:
        returns = [-10.0, -8.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        # level 0.2 -> tail_count = 2 -> mean(-10, -8) = -9.
        assert conditional_cvar(returns, 0.2) == pytest.approx(-9.0)

    def test_tail_count_floors_to_at_least_one(self) -> None:
        # level so small the floor would be 0 -> statistic still defined on the
        # single worst observation (power is judged separately by the gate).
        returns = [-5.0, 1.0, 2.0]
        assert conditional_cvar(returns, 0.001) == -5.0

    def test_rejects_empty_series(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            conditional_cvar([], 0.05)

    def test_rejects_out_of_range_level(self) -> None:
        with pytest.raises(ValueError, match="level"):
            conditional_cvar([1.0, 2.0], 0.0)


# ─────────────────────────────────────────────────────────────────────
#   apply_inv12_cost_stress
# ─────────────────────────────────────────────────────────────────────


class TestInv12CostStress:
    def test_applies_one_and_a_half_times_cost(self) -> None:
        net = apply_inv12_cost_stress([0.010, 0.020], [0.002, 0.004])
        assert net == pytest.approx((0.010 - 1.5 * 0.002, 0.020 - 1.5 * 0.004))

    def test_rejects_length_mismatch(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            apply_inv12_cost_stress([0.01], [0.001, 0.002])

    def test_rejects_negative_cost(self) -> None:
        with pytest.raises(ValueError, match=">= 0"):
            apply_inv12_cost_stress([0.01], [-0.001])


# ─────────────────────────────────────────────────────────────────────
#   build_conditional_cvar_evidence
# ─────────────────────────────────────────────────────────────────────


def _flat_returns(n: int, value: float) -> list[float]:
    return [value] * n


class TestBuildConditionalCVaR:
    def test_passes_when_hold_tail_not_worse_than_flatten(self) -> None:
        # Hold uniformly a touch better than flatten -> tail not worse.
        n = 400
        flatten = _flat_returns(n, 0.001)
        hold = [f + 0.0002 for f in flatten]
        costs = _flat_returns(n, 0.0002)
        ev = build_conditional_cvar_evidence(
            config=_CFG,
            hold_returns=hold,
            flatten_returns=flatten,
            round_trip_costs=costs,
            level=0.05,
            horizon_bars=10,
        )
        assert ev.cvar_delta >= 0.0
        assert ev.effective_tail_sample == 20  # int(0.05 * 400)
        assert ev.cpcv_fold_count == 9
        assert validate_conditional_cvar(ev) == []

    def test_records_inv12_stress_provenance(self) -> None:
        n = 400
        ev = build_conditional_cvar_evidence(
            config=_CFG,
            hold_returns=_flat_returns(n, 0.001),
            flatten_returns=_flat_returns(n, 0.001),
            round_trip_costs=_flat_returns(n, 0.0002),
            level=0.05,
            horizon_bars=10,
        )
        assert ev.modeled_fills is True
        assert ev.inv12_cost_multiplier == INV12_COST_STRESS_MULTIPLIER
        assert ev.inv12_latency_multiplier == float(INV12_LATENCY_STRESS_MULTIPLIER)

    def test_fails_when_hold_tail_worse_than_flatten(self) -> None:
        # Holding through the flagged regime deepens the left tail: the worst
        # episodes realise a big loss under hold that flatten avoided.
        n = 400
        flatten = _flat_returns(n, 0.001)
        hold = list(flatten)
        for i in range(40):  # worst 10% of episodes crater under hold
            hold[i] = -0.05
        costs = _flat_returns(n, 0.0002)
        ev = build_conditional_cvar_evidence(
            config=_CFG,
            hold_returns=hold,
            flatten_returns=flatten,
            round_trip_costs=costs,
            level=0.05,
            horizon_bars=10,
        )
        assert ev.cvar_delta < 0.0
        errors = validate_conditional_cvar(ev)
        assert any("worse than flatten" in e for e in errors)

    def test_under_powered_cell_fails_rather_than_passes(self) -> None:
        # ACCEPTANCE (design §3.5): a tail that cannot be powered on the
        # available subpopulation blocks promotion — it does not default-accept.
        n = 200  # int(0.05 * 200) = 10 < decouple_cvar_min_tail_sample (20)
        ev = build_conditional_cvar_evidence(
            config=_CFG,
            hold_returns=_flat_returns(n, 0.001),
            flatten_returns=_flat_returns(n, 0.001),
            round_trip_costs=_flat_returns(n, 0.0002),
            level=0.05,
            horizon_bars=10,
        )
        assert ev.effective_tail_sample == 10
        assert ev.cvar_delta >= 0.0  # tail itself is not "worse"...
        errors = validate_conditional_cvar(ev)
        # ...yet the cell still FAILs, purely on power.
        assert errors
        assert any("under-powered" in e for e in errors)

    def test_is_deterministic(self) -> None:
        n = 400
        kwargs = dict(
            config=_CFG,
            hold_returns=_flat_returns(n, 0.0012),
            flatten_returns=_flat_returns(n, 0.001),
            round_trip_costs=_flat_returns(n, 0.0002),
            level=0.05,
            horizon_bars=10,
        )
        assert build_conditional_cvar_evidence(**kwargs) == build_conditional_cvar_evidence(
            **kwargs
        )

    def test_path_deltas_mean_matches_summary(self) -> None:
        n = 400
        ev = build_conditional_cvar_evidence(
            config=_CFG,
            hold_returns=_flat_returns(n, 0.0012),
            flatten_returns=_flat_returns(n, 0.001),
            round_trip_costs=_flat_returns(n, 0.0002),
            level=0.05,
            horizon_bars=10,
        )
        assert len(ev.path_cvar_deltas) == ev.cpcv_fold_count
        assert math.isclose(
            ev.cvar_delta,
            sum(ev.path_cvar_deltas) / len(ev.path_cvar_deltas),
            rel_tol=1e-9,
        )

    def test_rejects_length_mismatch(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            build_conditional_cvar_evidence(
                config=_CFG,
                hold_returns=[0.01] * 100,
                flatten_returns=[0.01] * 99,
                round_trip_costs=[0.001] * 100,
                level=0.05,
                horizon_bars=10,
            )

    def test_rejects_nonpositive_horizon(self) -> None:
        with pytest.raises(ValueError, match="horizon_bars"):
            build_conditional_cvar_evidence(
                config=_CFG,
                hold_returns=[0.01] * 100,
                flatten_returns=[0.01] * 100,
                round_trip_costs=[0.001] * 100,
                level=0.05,
                horizon_bars=0,
            )


# ─────────────────────────────────────────────────────────────────────
#   build_turnover_bound_evidence
# ─────────────────────────────────────────────────────────────────────


class TestBuildTurnoverBound:
    def test_pass_within_declared_bound(self) -> None:
        ev = build_turnover_bound_evidence(
            baseline_round_trips=100,
            deferral_round_trips=110,
            declared_max_ratio=1.2,
            subpopulation_size=400,
        )
        assert ev.observed_ratio == pytest.approx(1.1)
        assert validate_turnover_bound(ev) == []

    def test_churn_beyond_bound_is_rejected(self) -> None:
        # ACCEPTANCE (design §3.5): reject an alpha that churns beyond its
        # declared round-trip bound.
        ev = build_turnover_bound_evidence(
            baseline_round_trips=100,
            deferral_round_trips=180,
            declared_max_ratio=1.2,
            subpopulation_size=400,
        )
        assert ev.observed_ratio == pytest.approx(1.8)
        errors = validate_turnover_bound(ev)
        assert any("churns beyond" in e for e in errors)

    def test_declared_bound_beyond_platform_ceiling_is_rejected(self) -> None:
        t = GateThresholds()
        ev = build_turnover_bound_evidence(
            baseline_round_trips=100,
            deferral_round_trips=120,
            declared_max_ratio=t.decouple_turnover_ceiling_ratio + 0.5,
            subpopulation_size=400,
        )
        errors = validate_turnover_bound(ev)
        assert any("platform" in e and "ceiling" in e for e in errors)

    def test_rejects_nonpositive_baseline(self) -> None:
        with pytest.raises(ValueError, match="> 0 to form a ratio"):
            build_turnover_bound_evidence(
                baseline_round_trips=0,
                deferral_round_trips=10,
                declared_max_ratio=1.2,
                subpopulation_size=400,
            )
