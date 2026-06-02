"""Reference tests for :mod:`feelies.research.dsr` (Workstream C-2).

Each assertion compares the module to an inline reimplementation of the
same closed form using :func:`math.erf`,
:meth:`statistics.NormalDist.inv_cdf`, and the Bailey–López de Prado
algebra — **not** precomputed float literals.  CPython's ``erf`` /
``inv_cdf`` outputs can differ by a ULP across minor releases (e.g.
3.12 vs 3.14); tying expectations to the running interpreter keeps
the suite stable while still catching accidental formula drift inside
``feelies.research.dsr``.
"""

from __future__ import annotations

import math
import statistics

from feelies.alpha.promotion_evidence import (
    GateThresholds,
    validate_dsr,
)
from feelies.research.dsr import (
    EULER_MASCHERONI,
    build_dsr_evidence,
    deflated_sharpe,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
    standard_normal_cdf,
    standard_normal_quantile,
)


def _reference_phi(x: float) -> float:
    """Φ(x) via stdlib ``erf`` — mirrors ``standard_normal_cdf``."""

    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _reference_normal_inv(p: float) -> float:
    """Φ⁻¹(p) via stdlib — same primitive as ``standard_normal_quantile``."""

    return statistics.NormalDist().inv_cdf(p)


class TestStandardNormalCDFPinned:
    def test_phi_zero_exact(self) -> None:
        assert standard_normal_cdf(0.0) == 0.5

    def test_phi_one(self) -> None:
        assert standard_normal_cdf(1.0) == _reference_phi(1.0)

    def test_phi_1_96(self) -> None:
        assert standard_normal_cdf(1.96) == _reference_phi(1.96)

    def test_phi_neg_1_96(self) -> None:
        assert standard_normal_cdf(-1.96) == _reference_phi(-1.96)

    def test_phi_2_5758(self) -> None:
        # Two-sided 99% CI right edge: Φ(2.5758…) = 0.995 at this tolerance.
        assert math.isclose(
            standard_normal_cdf(2.5758293035489),
            0.995,
            abs_tol=1e-9,
        )


class TestStandardNormalQuantilePinned:
    def test_inv_cdf_0_975(self) -> None:
        assert standard_normal_quantile(0.975) == _reference_normal_inv(0.975)

    def test_inv_cdf_0_99(self) -> None:
        assert standard_normal_quantile(0.99) == _reference_normal_inv(0.99)

    def test_inv_cdf_1_minus_1_over_100e(self) -> None:
        p = 1.0 - 1.0 / (100.0 * math.e)
        assert standard_normal_quantile(p) == _reference_normal_inv(p)


class TestProbabilisticSharpeRatioPinned:
    def test_gaussian_T252_SR0_1(self) -> None:
        sr_hat = 0.1
        var_term = 1.0 + sr_hat * sr_hat / 2.0
        z = sr_hat * math.sqrt(251) / math.sqrt(var_term)
        expected_psr = _reference_phi(z)
        psr = probabilistic_sharpe_ratio(
            observed_sharpe=0.1,
            threshold_sharpe=0.0,
            n_obs=252,
            skewness=0.0,
            kurtosis=3.0,
        )
        assert psr == expected_psr


class TestExpectedMaxSharpePinned:
    def test_n100_v1_over_251(self) -> None:
        n_trials = 100
        v = 1.0 / 251
        inv1 = _reference_normal_inv(1.0 - 1.0 / n_trials)
        inv2 = _reference_normal_inv(1.0 - 1.0 / (n_trials * math.e))
        expected = math.sqrt(v) * (
            (1.0 - EULER_MASCHERONI) * inv1 + EULER_MASCHERONI * inv2
        )
        s = expected_max_sharpe(n_trials=n_trials, trial_sharpe_variance=v)
        assert s == expected

    def test_hand_derived_components(self) -> None:
        n_trials = 100
        v = 1.0 / 251
        inv1 = _reference_normal_inv(1.0 - 1.0 / n_trials)
        inv2 = _reference_normal_inv(1.0 - 1.0 / (n_trials * math.e))
        s_expected = math.sqrt(v) * (
            (1.0 - EULER_MASCHERONI) * inv1 + EULER_MASCHERONI * inv2
        )
        s_module = expected_max_sharpe(
            n_trials=n_trials, trial_sharpe_variance=v
        )
        assert s_expected == s_module


class TestDeflatedSharpePinned:
    def test_strong_alpha_per_period(self) -> None:
        comp = deflated_sharpe(
            observed_sharpe=0.5,
            n_obs=252,
            n_trials=100,
            skewness=0.0,
            kurtosis=3.0,
        )
        thresh = expected_max_sharpe(
            n_trials=100, trial_sharpe_variance=1.0 / 251
        )
        psr = probabilistic_sharpe_ratio(
            observed_sharpe=0.5,
            threshold_sharpe=thresh,
            n_obs=252,
            skewness=0.0,
            kurtosis=3.0,
        )
        assert comp.threshold_sharpe == thresh
        assert comp.dsr_value == 0.5 - thresh
        assert comp.psr == psr
        assert comp.dsr_p_value == 1.0 - psr
        assert comp.psr + comp.dsr_p_value == 1.0


class TestBuildDSREvidencePinned:
    def test_strong_alpha_annualised(self) -> None:
        af = math.sqrt(252)
        comp = deflated_sharpe(
            observed_sharpe=0.5,
            n_obs=252,
            n_trials=100,
            skewness=0.0,
            kurtosis=3.0,
        )
        ev = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=100,
            skewness=0.0,
            kurtosis=3.0,
            annualization_factor=af,
        )
        assert ev.observed_sharpe == 0.5 * af
        assert ev.dsr == comp.dsr_value * af
        assert ev.dsr_p_value == comp.dsr_p_value
        assert ev.trials_count == 100
        assert ev.skewness == 0.0
        assert ev.kurtosis == 3.0

    def test_strong_alpha_passes_default_validator(self) -> None:
        ev = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=100,
            annualization_factor=math.sqrt(252),
        )
        errors = validate_dsr(ev, GateThresholds())
        assert errors == []
        thresholds = GateThresholds()
        assert ev.dsr > thresholds.dsr_min
        assert ev.dsr_p_value < thresholds.dsr_max_p_value


class TestEdgeCasesPinned:
    def test_zero_trials_no_deflation_dsr_equals_observed(self) -> None:
        ev = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=0,
            annualization_factor=math.sqrt(252),
        )
        assert ev.dsr == 0.5 * math.sqrt(252)
        assert ev.observed_sharpe == 0.5 * math.sqrt(252)
        sr_hat = 0.5
        var_term = 1.0 + sr_hat * sr_hat / 2.0
        z = sr_hat * math.sqrt(251) / math.sqrt(var_term)
        psr = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
        assert ev.dsr_p_value == 1.0 - psr
        errors = validate_dsr(ev, GateThresholds())
        assert any("trials_count" in e for e in errors)

    def test_one_trial_no_deflation(self) -> None:
        ev = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=1,
            annualization_factor=math.sqrt(252),
        )
        assert ev.dsr == 0.5 * math.sqrt(252)

    def test_default_kurtosis_is_gaussian(self) -> None:
        ev_default = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=100,
        )
        ev_explicit_gauss = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=100,
            kurtosis=3.0,
        )
        assert ev_default == ev_explicit_gauss

    def test_p_value_matches_dsr_consistency(self) -> None:
        ev = build_dsr_evidence(
            observed_sharpe=0.3,
            n_obs=252,
            trials_count=50,
            skewness=-0.2,
            kurtosis=4.0,
        )
        sr0 = expected_max_sharpe(
            n_trials=50, trial_sharpe_variance=1.0 / 251
        )
        psr = probabilistic_sharpe_ratio(
            observed_sharpe=0.3,
            threshold_sharpe=sr0,
            n_obs=252,
            skewness=-0.2,
            kurtosis=4.0,
        )
        assert ev.dsr_p_value == 1.0 - psr
