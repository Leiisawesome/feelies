"""Unit tests for :mod:`feelies.research.dsr` (Workstream C-2).

Covers:
- ``standard_normal_cdf`` standard quantile values + symmetry.
- ``standard_normal_quantile`` round-trip + boundary errors.
- ``probabilistic_sharpe_ratio`` Gaussian closed form + variance-
  term boundary checks + skew/kurt sensitivity.
- ``expected_max_sharpe`` closed form + N=1 / variance=0 edge
  cases.
- ``deflated_sharpe`` happy path + edge cases.
- ``standardised_moments`` Gaussian baseline + degenerate inputs.
- ``build_dsr_evidence`` happy path + validator round-trip
  (passes default thresholds for a strong alpha; fails for noise).
- ``build_dsr_evidence_from_returns`` happy path + degenerate
  return series rejection.
"""

from __future__ import annotations

import math
import random
import statistics

import pytest

from feelies.alpha.promotion_evidence import (
    DSREvidence,
    GateThresholds,
    validate_dsr,
)
from feelies.research.dsr import (
    DSRComputation,
    EULER_MASCHERONI,
    build_dsr_evidence,
    build_dsr_evidence_from_returns,
    deflated_sharpe,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
    standard_normal_cdf,
    standard_normal_quantile,
    standardised_moments,
)


# ─────────────────────────────────────────────────────────────────────
#   standard_normal_cdf
# ─────────────────────────────────────────────────────────────────────


class TestStandardNormalCDF:
    def test_zero_is_half(self) -> None:
        assert standard_normal_cdf(0.0) == 0.5

    def test_textbook_quantiles(self) -> None:
        # Φ(1.96) ≈ 0.975 (two-sided 95% CI right edge)
        assert math.isclose(
            standard_normal_cdf(1.96), 0.975002104852, abs_tol=1e-10
        )
        # Φ(2.576) ≈ 0.995 (two-sided 99% CI right edge)
        assert math.isclose(
            standard_normal_cdf(2.5758293035489), 0.995, abs_tol=1e-9
        )

    def test_symmetry_about_zero(self) -> None:
        for x in (0.5, 1.0, 1.5, 2.5, 3.0):
            assert math.isclose(
                standard_normal_cdf(x) + standard_normal_cdf(-x),
                1.0,
                abs_tol=1e-12,
            )

    def test_extremes(self) -> None:
        # Far in either tail saturates.
        assert standard_normal_cdf(-10.0) < 1e-15
        assert standard_normal_cdf(10.0) > 1.0 - 1e-15


# ─────────────────────────────────────────────────────────────────────
#   standard_normal_quantile
# ─────────────────────────────────────────────────────────────────────


class TestStandardNormalQuantile:
    def test_textbook_values(self) -> None:
        assert math.isclose(
            standard_normal_quantile(0.5), 0.0, abs_tol=1e-12
        )
        assert math.isclose(
            standard_normal_quantile(0.975), 1.959963984540054,
            rel_tol=1e-9,
        )

    def test_round_trip_with_cdf(self) -> None:
        for p in (0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99):
            x = standard_normal_quantile(p)
            assert math.isclose(
                standard_normal_cdf(x), p, abs_tol=1e-9
            )

    def test_boundary_p_rejected(self) -> None:
        with pytest.raises(ValueError, match="p in"):
            standard_normal_quantile(0.0)
        with pytest.raises(ValueError, match="p in"):
            standard_normal_quantile(1.0)
        with pytest.raises(ValueError, match="p in"):
            standard_normal_quantile(-0.1)
        with pytest.raises(ValueError, match="p in"):
            standard_normal_quantile(1.5)


# ─────────────────────────────────────────────────────────────────────
#   probabilistic_sharpe_ratio
# ─────────────────────────────────────────────────────────────────────


class TestProbabilisticSharpeRatio:
    def test_observed_equals_threshold_yields_half(self) -> None:
        # SR_hat == SR* → z=0 → PSR = Φ(0) = 0.5
        for sr in (0.0, 0.1, 0.5, 1.0, 2.0):
            psr = probabilistic_sharpe_ratio(
                observed_sharpe=sr,
                threshold_sharpe=sr,
                n_obs=252,
            )
            assert math.isclose(psr, 0.5, abs_tol=1e-12)

    def test_observed_above_threshold_yields_above_half(self) -> None:
        psr = probabilistic_sharpe_ratio(
            observed_sharpe=0.5,
            threshold_sharpe=0.0,
            n_obs=252,
        )
        assert psr > 0.5

    def test_observed_below_threshold_yields_below_half(self) -> None:
        psr = probabilistic_sharpe_ratio(
            observed_sharpe=0.1,
            threshold_sharpe=0.5,
            n_obs=252,
        )
        assert psr < 0.5

    def test_psr_in_unit_interval(self) -> None:
        for sr in (-2.0, -0.5, 0.0, 0.5, 2.0):
            psr = probabilistic_sharpe_ratio(
                observed_sharpe=sr,
                threshold_sharpe=0.0,
                n_obs=100,
            )
            assert 0.0 <= psr <= 1.0

    def test_gaussian_closed_form(self) -> None:
        # For Gaussian (skew=0, kurt=3): variance term = 1 + SR²/2.
        # Closed form: z = (SR_hat - SR*) * sqrt(T-1) / sqrt(1 + SR_hat^2 / 2).
        T = 100
        sr_hat = 1.0
        sr_thresh = 0.5
        var_term = 1.0 + sr_hat * sr_hat / 2.0
        z_expected = (sr_hat - sr_thresh) * math.sqrt(T - 1) / math.sqrt(var_term)
        psr_expected = 0.5 * (1.0 + math.erf(z_expected / math.sqrt(2.0)))
        psr = probabilistic_sharpe_ratio(
            observed_sharpe=sr_hat,
            threshold_sharpe=sr_thresh,
            n_obs=T,
        )
        assert math.isclose(psr, psr_expected, rel_tol=1e-12)

    def test_grows_with_sample_size(self) -> None:
        # Holding sr_hat > sr_thresh fixed, larger T makes PSR larger
        # (more evidence the Sharpe is real).
        kwargs = {
            "observed_sharpe": 0.3,
            "threshold_sharpe": 0.0,
            "skewness": 0.0,
            "kurtosis": 3.0,
        }
        p100 = probabilistic_sharpe_ratio(n_obs=100, **kwargs)
        p1000 = probabilistic_sharpe_ratio(n_obs=1000, **kwargs)
        assert p1000 > p100

    def test_negative_skew_decreases_psr_when_sharpe_positive(self) -> None:
        # Variance term: 1 - skew*SR + ((kurt-1)/4)*SR^2.
        # For positive SR, negative skew INCREASES the variance term,
        # which DECREASES z, which DECREASES PSR.  Use a moderate
        # SR so PSR doesn't saturate at 1.0 in either branch.
        kwargs = {
            "observed_sharpe": 0.1,
            "threshold_sharpe": 0.0,
            "n_obs": 50,
            "kurtosis": 3.0,
        }
        psr_zero_skew = probabilistic_sharpe_ratio(skewness=0.0, **kwargs)
        psr_neg_skew = probabilistic_sharpe_ratio(skewness=-1.0, **kwargs)
        assert psr_neg_skew < psr_zero_skew

    def test_higher_kurtosis_decreases_psr(self) -> None:
        # Higher kurtosis (heavier tails) → larger variance term →
        # smaller z → smaller PSR.  Use a moderate SR so PSR
        # doesn't saturate at 1.0.
        kwargs = {
            "observed_sharpe": 0.1,
            "threshold_sharpe": 0.0,
            "n_obs": 50,
            "skewness": 0.0,
        }
        psr_normal = probabilistic_sharpe_ratio(kurtosis=3.0, **kwargs)
        psr_heavy = probabilistic_sharpe_ratio(kurtosis=9.0, **kwargs)
        assert psr_heavy < psr_normal

    def test_n_obs_below_two_rejected(self) -> None:
        with pytest.raises(ValueError, match="n_obs"):
            probabilistic_sharpe_ratio(
                observed_sharpe=0.5,
                threshold_sharpe=0.0,
                n_obs=1,
            )

    def test_negative_variance_term_rejected(self) -> None:
        # skew=2, kurt=1, sr=2 → var_term = 1 - 2*2 + 0*4 = -3 → reject.
        with pytest.raises(ValueError, match="variance term"):
            probabilistic_sharpe_ratio(
                observed_sharpe=2.0,
                threshold_sharpe=0.0,
                n_obs=100,
                skewness=2.0,
                kurtosis=1.0,
            )


# ─────────────────────────────────────────────────────────────────────
#   expected_max_sharpe
# ─────────────────────────────────────────────────────────────────────


class TestExpectedMaxSharpe:
    def test_n_trials_one_returns_zero(self) -> None:
        # No multiple-testing deflation when only one trial.
        assert expected_max_sharpe(
            n_trials=1, trial_sharpe_variance=0.5
        ) == 0.0

    def test_zero_variance_returns_zero(self) -> None:
        assert expected_max_sharpe(
            n_trials=100, trial_sharpe_variance=0.0
        ) == 0.0

    def test_grows_with_n_trials(self) -> None:
        v = 1.0 / 251
        s10 = expected_max_sharpe(n_trials=10, trial_sharpe_variance=v)
        s100 = expected_max_sharpe(n_trials=100, trial_sharpe_variance=v)
        s1000 = expected_max_sharpe(n_trials=1000, trial_sharpe_variance=v)
        assert s10 < s100 < s1000

    def test_grows_with_variance(self) -> None:
        n = 100
        s_low = expected_max_sharpe(
            n_trials=n, trial_sharpe_variance=0.001
        )
        s_high = expected_max_sharpe(
            n_trials=n, trial_sharpe_variance=0.01
        )
        assert s_low < s_high

    def test_closed_form_n100_v1_over_251(self) -> None:
        # Hand-calculated sanity:
        # Φ⁻¹(0.99) ≈ 2.32635 ; Φ⁻¹(1 - 1/(100e)) ≈ 2.6864
        # γ = 0.5772
        # E[max] = sqrt(1/251) * ((1 - γ) * 2.32635 + γ * 2.6864)
        #        ≈ 0.06309 * (0.4228 * 2.32635 + 0.5772 * 2.6864)
        #        ≈ 0.06309 * (0.9836 + 1.5505)
        #        ≈ 0.06309 * 2.5340 ≈ 0.1599
        s = expected_max_sharpe(
            n_trials=100, trial_sharpe_variance=1.0 / 251
        )
        assert math.isclose(s, 0.1597, abs_tol=1e-3)

    def test_n_trials_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="n_trials"):
            expected_max_sharpe(
                n_trials=0, trial_sharpe_variance=0.1
            )

    def test_negative_n_trials_rejected(self) -> None:
        with pytest.raises(ValueError, match="n_trials"):
            expected_max_sharpe(
                n_trials=-1, trial_sharpe_variance=0.1
            )

    def test_negative_variance_rejected(self) -> None:
        with pytest.raises(ValueError, match="trial_sharpe_variance"):
            expected_max_sharpe(
                n_trials=10, trial_sharpe_variance=-0.1
            )

    def test_euler_mascheroni_constant_value(self) -> None:
        # Documented: γ ≈ 0.5772156649015328606.
        assert math.isclose(EULER_MASCHERONI, 0.5772156649015329, abs_tol=1e-15)


# ─────────────────────────────────────────────────────────────────────
#   deflated_sharpe
# ─────────────────────────────────────────────────────────────────────


class TestDeflatedSharpe:
    def test_returns_dsr_computation(self) -> None:
        comp = deflated_sharpe(
            observed_sharpe=0.5,
            n_obs=252,
            n_trials=100,
        )
        assert isinstance(comp, DSRComputation)
        assert comp.observed_sharpe == 0.5
        assert comp.n_obs == 252
        assert comp.n_trials == 100
        # PSR + dsr_p_value should sum to 1 exactly.
        assert math.isclose(comp.psr + comp.dsr_p_value, 1.0, abs_tol=1e-12)

    def test_dsr_value_equals_observed_minus_threshold(self) -> None:
        comp = deflated_sharpe(
            observed_sharpe=0.5,
            n_obs=252,
            n_trials=50,
        )
        assert math.isclose(
            comp.dsr_value,
            comp.observed_sharpe - comp.threshold_sharpe,
            abs_tol=1e-12,
        )

    def test_n_trials_one_no_deflation(self) -> None:
        comp = deflated_sharpe(
            observed_sharpe=0.5,
            n_obs=252,
            n_trials=1,
        )
        assert comp.threshold_sharpe == 0.0
        assert comp.dsr_value == 0.5

    def test_default_trial_variance_is_one_over_n_minus_one(self) -> None:
        # When trial_sharpe_variance is None, deflated_sharpe uses
        # 1 / (n_obs - 1).  Verify by passing the explicit value.
        comp_default = deflated_sharpe(
            observed_sharpe=0.5,
            n_obs=252,
            n_trials=50,
        )
        comp_explicit = deflated_sharpe(
            observed_sharpe=0.5,
            n_obs=252,
            n_trials=50,
            trial_sharpe_variance=1.0 / 251,
        )
        assert comp_default == comp_explicit

    def test_explicit_variance_changes_threshold(self) -> None:
        comp_low = deflated_sharpe(
            observed_sharpe=0.5,
            n_obs=252,
            n_trials=100,
            trial_sharpe_variance=0.001,
        )
        comp_high = deflated_sharpe(
            observed_sharpe=0.5,
            n_obs=252,
            n_trials=100,
            trial_sharpe_variance=0.01,
        )
        assert comp_low.threshold_sharpe < comp_high.threshold_sharpe
        # Higher threshold -> lower dsr_value -> higher dsr_p_value.
        assert comp_low.dsr_value > comp_high.dsr_value
        assert comp_low.dsr_p_value < comp_high.dsr_p_value

    def test_n_obs_below_two_rejected(self) -> None:
        with pytest.raises(ValueError, match="n_obs"):
            deflated_sharpe(
                observed_sharpe=0.5, n_obs=1, n_trials=10
            )

    def test_n_trials_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="n_trials"):
            deflated_sharpe(
                observed_sharpe=0.5, n_obs=100, n_trials=0
            )


# ─────────────────────────────────────────────────────────────────────
#   standardised_moments
# ─────────────────────────────────────────────────────────────────────


class TestStandardisedMoments:
    def test_gaussian_baseline_for_short_series(self) -> None:
        # Edge case: <2 observations -> Gaussian baseline.
        assert standardised_moments([]) == (0.0, 3.0)
        assert standardised_moments([1.0]) == (0.0, 3.0)

    def test_gaussian_baseline_for_constant_series(self) -> None:
        # σ=0 -> Gaussian baseline (moments undefined).
        assert standardised_moments([1.0, 1.0, 1.0]) == (0.0, 3.0)

    def test_skewness_sign(self) -> None:
        # Right-skewed series.
        right_skew = [-1.0, -1.0, -1.0, -1.0, 4.0]
        s, _ = standardised_moments(right_skew)
        assert s > 0
        # Left-skewed series.
        left_skew = [1.0, 1.0, 1.0, 1.0, -4.0]
        s2, _ = standardised_moments(left_skew)
        assert s2 < 0

    def test_kurtosis_above_three_for_heavy_tails(self) -> None:
        # Synthetic heavy-tailed: most values near 0, occasional large.
        heavy = [0.0] * 95 + [10.0, -10.0, 5.0, -5.0, 8.0]
        _, k = standardised_moments(heavy)
        assert k > 3.0

    def test_kurtosis_below_three_for_uniform(self) -> None:
        # Uniform on [-1, 1]: kurtosis = 1.8 (theory).
        uniform = [(-1.0) + 2.0 * i / 999 for i in range(1000)]
        _, k = standardised_moments(uniform)
        assert math.isclose(k, 1.8, abs_tol=0.01)


# ─────────────────────────────────────────────────────────────────────
#   build_dsr_evidence
# ─────────────────────────────────────────────────────────────────────


class TestBuildDSREvidence:
    def test_returns_a_DSREvidence(self) -> None:
        ev = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=100,
        )
        assert isinstance(ev, DSREvidence)

    def test_fields_propagate(self) -> None:
        ev = build_dsr_evidence(
            observed_sharpe=0.3,
            n_obs=252,
            trials_count=42,
            skewness=-0.5,
            kurtosis=4.0,
        )
        assert ev.observed_sharpe == 0.3
        assert ev.trials_count == 42
        assert ev.skewness == -0.5
        assert ev.kurtosis == 4.0

    def test_annualization_scales_observed_and_dsr(self) -> None:
        ev_per_period = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=100,
            annualization_factor=1.0,
        )
        ev_annualised = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=100,
            annualization_factor=math.sqrt(252),
        )
        scale = math.sqrt(252)
        assert math.isclose(
            ev_annualised.observed_sharpe,
            ev_per_period.observed_sharpe * scale,
            rel_tol=1e-12,
        )
        assert math.isclose(
            ev_annualised.dsr,
            ev_per_period.dsr * scale,
            rel_tol=1e-12,
        )
        # p_value is dimensionless and unchanged.
        assert ev_annualised.dsr_p_value == ev_per_period.dsr_p_value

    def test_zero_trials_yields_no_deflation(self) -> None:
        # Permissive: trials_count=0 still builds the evidence (and
        # the validator rejects it via its own check).
        ev = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=0,
        )
        # No deflation -> dsr == observed_sharpe.
        assert ev.dsr == 0.5
        assert ev.trials_count == 0

    def test_one_trial_yields_no_deflation(self) -> None:
        ev = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=1,
        )
        # threshold = 0 for n_trials=1, so dsr == observed_sharpe.
        assert ev.dsr == 0.5

    def test_strong_alpha_passes_default_validator(self) -> None:
        # Per-period Sharpe = 0.5 over 252 obs, 100 trials, annualised.
        # Annualised observed ~ 0.5 * sqrt(252) ≈ 7.94.
        # E[max SR] per-period ≈ 0.16; annualised ≈ 2.54.
        # DSR annualised ≈ 5.40 — passes dsr_min=1.0.
        ev = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=100,
            annualization_factor=math.sqrt(252),
        )
        errors = validate_dsr(ev, GateThresholds())
        assert errors == [], f"validator rejected: {errors}"

    def test_zero_trials_fails_validator(self) -> None:
        # validator demands trials_count > 0.
        ev = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=0,
            annualization_factor=math.sqrt(252),
        )
        errors = validate_dsr(ev, GateThresholds())
        assert any("trials_count" in e for e in errors)

    def test_marginal_alpha_fails_validator(self) -> None:
        # Sharpe = 0.05 per period (= 0.79 annualised) — below 1.0.
        ev = build_dsr_evidence(
            observed_sharpe=0.05,
            n_obs=252,
            trials_count=100,
            annualization_factor=math.sqrt(252),
        )
        errors = validate_dsr(ev, GateThresholds())
        assert errors  # must reject

    def test_n_obs_below_two_rejected(self) -> None:
        with pytest.raises(ValueError, match="n_obs"):
            build_dsr_evidence(
                observed_sharpe=0.5,
                n_obs=1,
                trials_count=100,
            )

    def test_negative_trials_count_rejected(self) -> None:
        with pytest.raises(ValueError, match="trials_count"):
            build_dsr_evidence(
                observed_sharpe=0.5,
                n_obs=252,
                trials_count=-1,
            )

    def test_zero_annualization_rejected(self) -> None:
        with pytest.raises(ValueError, match="annualization_factor"):
            build_dsr_evidence(
                observed_sharpe=0.5,
                n_obs=252,
                trials_count=100,
                annualization_factor=0.0,
            )

    def test_negative_annualization_rejected(self) -> None:
        with pytest.raises(ValueError, match="annualization_factor"):
            build_dsr_evidence(
                observed_sharpe=0.5,
                n_obs=252,
                trials_count=100,
                annualization_factor=-1.0,
            )

    def test_explicit_trial_variance_used(self) -> None:
        # Pass a wildly large variance and verify the threshold
        # grows accordingly (so dsr_value falls).
        ev_default = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=100,
        )
        ev_high_variance = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=100,
            trial_sharpe_variance=0.1,  # >> default 1/251
        )
        assert ev_high_variance.dsr < ev_default.dsr
        assert ev_high_variance.dsr_p_value > ev_default.dsr_p_value


# ─────────────────────────────────────────────────────────────────────
#   build_dsr_evidence_from_returns
# ─────────────────────────────────────────────────────────────────────


class TestBuildDSREvidenceFromReturns:
    def test_returns_a_DSREvidence(self) -> None:
        rng = random.Random(0)
        returns = [rng.gauss(0.001, 0.01) for _ in range(252)]
        ev = build_dsr_evidence_from_returns(
            returns=returns,
            trials_count=100,
        )
        assert isinstance(ev, DSREvidence)

    def test_observed_sharpe_matches_sharpe_ratio(self) -> None:
        rng = random.Random(7)
        returns = [rng.gauss(0.002, 0.01) for _ in range(252)]
        ev = build_dsr_evidence_from_returns(
            returns=returns,
            trials_count=50,
        )
        # observed_sharpe should equal mean/pstdev (the cpcv.sharpe_ratio convention).
        expected = statistics.fmean(returns) / statistics.pstdev(returns)
        assert math.isclose(ev.observed_sharpe, expected, rel_tol=1e-12)

    def test_strong_signal_passes_default_validator(self) -> None:
        # Strong signal: mean=0.005, stddev=0.005 → per-day Sharpe ~ 1.
        # Over 252 obs that's an annualised Sharpe of ~16, well above
        # 1.0 even after deflation.
        rng = random.Random(0)
        returns = [rng.gauss(0.005, 0.005) for _ in range(252)]
        ev = build_dsr_evidence_from_returns(
            returns=returns,
            trials_count=100,
            annualization_factor=math.sqrt(252),
        )
        errors = validate_dsr(ev, GateThresholds())
        assert errors == [], f"validator rejected: {errors}"

    def test_short_returns_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            build_dsr_evidence_from_returns(
                returns=[0.5], trials_count=10
            )

    def test_empty_returns_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            build_dsr_evidence_from_returns(
                returns=[], trials_count=10
            )

    def test_moments_propagate(self) -> None:
        rng = random.Random(0)
        returns = [rng.gauss(0.001, 0.01) for _ in range(252)]
        ev = build_dsr_evidence_from_returns(
            returns=returns,
            trials_count=100,
        )
        skew, kurt = standardised_moments(returns)
        assert ev.skewness == skew
        assert ev.kurtosis == kurt
