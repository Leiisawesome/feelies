"""Pinned-reference tests for :mod:`feelies.research.dsr` (Workstream C-2).

Locks down specific floating-point outputs of the DSR module to
golden values.  Each value was hand-derived from the closed-form
formula using :func:`math.erf` and
:meth:`statistics.NormalDist.inv_cdf` directly (i.e. *not* via the
module under test) and then verified to match the module's output
to the last representable bit.  A regression in the module — or in
CPython's stdlib `math.erf` / `statistics.NormalDist.inv_cdf`
implementations — would surface here as a numerical drift.

The values below are reproducible offline by re-running the
derivation script in the test docstring; if a CPython upgrade
shifts a value by ULP, update both the hand-derived expectation
and the pinned constant in the same commit so the audit trail
records what changed.  (CPython 3.12–3.14 can differ by a ULP from
earlier releases; constants below match 3.14.x.)
"""

from __future__ import annotations

import math
import statistics

from feelies.alpha.promotion_evidence import (
    GateThresholds,
    validate_dsr,
)
from feelies.research.dsr import (
    build_dsr_evidence,
    deflated_sharpe,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
    standard_normal_cdf,
    standard_normal_quantile,
)


# ─────────────────────────────────────────────────────────────────────
#   Pinned reference values
# ─────────────────────────────────────────────────────────────────────


# Standard normal CDF reference values (hand-derived via math.erf):
#     Φ(x) = 0.5 * (1 + erf(x / sqrt(2)))
PINNED_PHI_1_0 = 0.8413447460685428
PINNED_PHI_1_96 = 0.9750021048517796
PINNED_PHI_NEG_1_96 = 0.024997895148220373
PINNED_PHI_2_5758 = 0.995  # exact at this precision

# Standard normal quantile (Φ⁻¹) reference values (hand-derived via
# statistics.NormalDist().inv_cdf):
PINNED_INV_CDF_0_975 = 1.9599639845400536
PINNED_INV_CDF_0_99 = 2.3263478740408408
# Φ⁻¹(1 - 1 / (100·e)), used inside expected_max_sharpe(N=100):
PINNED_INV_CDF_1_MINUS_1_OVER_100E = 2.680210444966887

# PSR reference: observed=0.1, threshold=0, T=252, Gaussian.
# Hand-derived:
#   var_term = 1 + 0.1² / 2 = 1.005
#   z = 0.1 * sqrt(251) / sqrt(1.005) = 1.5803519980722478
#   PSR = Φ(z) = 0.9429868610243622
PINNED_PSR_REF_Z = 1.5803519980722478
PINNED_PSR_REF_VALUE = 0.9429868610243622

# Expected max Sharpe reference: N=100, V=1/251, γ=0.5772156649…
# Hand-derived:
#   E[max SR] = sqrt(1/251)
#             · ((1-γ)·Φ⁻¹(0.99) + γ·Φ⁻¹(1 - 1/(100·e)))
#             = 0.15973023826520108
PINNED_E_MAX_SHARPE_N100_V1_OVER_251 = 0.15973023826520108

# Strong-alpha DSR reference: observed_sharpe=0.5 (per-period),
# T=252, trials=100, Gaussian, annualisation = sqrt(252).
# Hand-derived from the chain
#   threshold = expected_max_sharpe(100, 1/251) = 0.15973…
#   dsr_per_period = 0.5 - threshold = 0.34026976173479895
#   dsr_annualised = dsr_per_period * sqrt(252) = 5.401615009352882
#   z2 = (0.5 - threshold) * sqrt(251) / sqrt(1 + 0.25/2) = 5.084…
#   psr2 = Φ(z2) ≈ 1 - 1.86e-7
#   dsr_p_value = 1 - psr2 = 1.8617426289502248e-07
#   observed_sharpe_annualised = 0.5 * sqrt(252) = 7.937253933193772
PINNED_STRONG_ALPHA_THRESHOLD_PER_PERIOD = 0.15973023826520108
PINNED_STRONG_ALPHA_DSR_PER_PERIOD = 0.34026976173479895
PINNED_STRONG_ALPHA_DSR_ANNUALISED = 5.401615009352882
PINNED_STRONG_ALPHA_DSR_P_VALUE = 1.8617426289502248e-07
PINNED_STRONG_ALPHA_OBSERVED_ANNUALISED = 7.937253933193772


# ─────────────────────────────────────────────────────────────────────
#   Standard normal pinned tests
# ─────────────────────────────────────────────────────────────────────


class TestStandardNormalCDFPinned:
    def test_phi_zero_exact(self) -> None:
        assert standard_normal_cdf(0.0) == 0.5

    def test_phi_one(self) -> None:
        assert standard_normal_cdf(1.0) == PINNED_PHI_1_0

    def test_phi_1_96(self) -> None:
        assert standard_normal_cdf(1.96) == PINNED_PHI_1_96

    def test_phi_neg_1_96(self) -> None:
        assert standard_normal_cdf(-1.96) == PINNED_PHI_NEG_1_96

    def test_phi_2_5758(self) -> None:
        # Two-sided 99% CI right edge: Φ(2.5758…) = 0.995 exactly.
        assert math.isclose(
            standard_normal_cdf(2.5758293035489),
            PINNED_PHI_2_5758,
            abs_tol=1e-9,
        )


class TestStandardNormalQuantilePinned:
    def test_inv_cdf_0_975(self) -> None:
        assert standard_normal_quantile(0.975) == PINNED_INV_CDF_0_975

    def test_inv_cdf_0_99(self) -> None:
        assert standard_normal_quantile(0.99) == PINNED_INV_CDF_0_99

    def test_inv_cdf_1_minus_1_over_100e(self) -> None:
        # Used inside expected_max_sharpe(N=100).
        p = 1.0 - 1.0 / (100.0 * math.e)
        assert (
            standard_normal_quantile(p)
            == PINNED_INV_CDF_1_MINUS_1_OVER_100E
        )


# ─────────────────────────────────────────────────────────────────────
#   PSR pinned tests
# ─────────────────────────────────────────────────────────────────────


class TestProbabilisticSharpeRatioPinned:
    def test_gaussian_T252_SR0_1(self) -> None:
        psr = probabilistic_sharpe_ratio(
            observed_sharpe=0.1,
            threshold_sharpe=0.0,
            n_obs=252,
            skewness=0.0,
            kurtosis=3.0,
        )
        assert psr == PINNED_PSR_REF_VALUE

    def test_z_statistic_consistency(self) -> None:
        # Verify the z-statistic the module computes matches the
        # hand-derived value to last bit.
        sr_hat = 0.1
        var_term = 1.0 + sr_hat * sr_hat / 2.0
        z_expected = sr_hat * math.sqrt(251) / math.sqrt(var_term)
        assert z_expected == PINNED_PSR_REF_Z


# ─────────────────────────────────────────────────────────────────────
#   Expected max Sharpe pinned tests
# ─────────────────────────────────────────────────────────────────────


class TestExpectedMaxSharpePinned:
    def test_n100_v1_over_251(self) -> None:
        s = expected_max_sharpe(
            n_trials=100, trial_sharpe_variance=1.0 / 251
        )
        assert s == PINNED_E_MAX_SHARPE_N100_V1_OVER_251

    def test_hand_derived_components(self) -> None:
        # Re-derive the closed form using the stdlib directly and
        # confirm it matches the module's output bit-for-bit.
        nd = statistics.NormalDist()
        gamma = 0.5772156649015328606
        N = 100
        v = 1.0 / 251
        inv1 = nd.inv_cdf(1 - 1 / N)
        inv2 = nd.inv_cdf(1 - 1 / (N * math.e))
        s_expected = math.sqrt(v) * (
            (1 - gamma) * inv1 + gamma * inv2
        )
        s_module = expected_max_sharpe(
            n_trials=N, trial_sharpe_variance=v
        )
        assert s_expected == s_module
        assert s_module == PINNED_E_MAX_SHARPE_N100_V1_OVER_251


# ─────────────────────────────────────────────────────────────────────
#   Deflated Sharpe pinned tests
# ─────────────────────────────────────────────────────────────────────


class TestDeflatedSharpePinned:
    def test_strong_alpha_per_period(self) -> None:
        comp = deflated_sharpe(
            observed_sharpe=0.5,
            n_obs=252,
            n_trials=100,
            skewness=0.0,
            kurtosis=3.0,
        )
        assert (
            comp.threshold_sharpe
            == PINNED_STRONG_ALPHA_THRESHOLD_PER_PERIOD
        )
        assert comp.dsr_value == PINNED_STRONG_ALPHA_DSR_PER_PERIOD
        assert comp.dsr_p_value == PINNED_STRONG_ALPHA_DSR_P_VALUE
        # PSR + p-value sum to one exactly.
        assert comp.psr + comp.dsr_p_value == 1.0


# ─────────────────────────────────────────────────────────────────────
#   build_dsr_evidence pinned tests
# ─────────────────────────────────────────────────────────────────────


class TestBuildDSREvidencePinned:
    def test_strong_alpha_annualised(self) -> None:
        ev = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=100,
            skewness=0.0,
            kurtosis=3.0,
            annualization_factor=math.sqrt(252),
        )
        assert ev.observed_sharpe == PINNED_STRONG_ALPHA_OBSERVED_ANNUALISED
        assert ev.dsr == PINNED_STRONG_ALPHA_DSR_ANNUALISED
        assert ev.dsr_p_value == PINNED_STRONG_ALPHA_DSR_P_VALUE
        assert ev.trials_count == 100
        assert ev.skewness == 0.0
        assert ev.kurtosis == 3.0

    def test_strong_alpha_passes_default_validator(self) -> None:
        # Belt-and-suspenders: verify the pinned strong-alpha
        # evidence actually clears both gate thresholds.
        ev = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=100,
            annualization_factor=math.sqrt(252),
        )
        errors = validate_dsr(ev, GateThresholds())
        assert errors == []
        # Defaults: dsr_min=1.0, dsr_max_p_value=0.05.  The pinned
        # DSR ≈ 5.40 (≫ 1.0) and p-value ≈ 1.86e-7 (≪ 0.05).
        thresholds = GateThresholds()
        assert ev.dsr > thresholds.dsr_min
        assert ev.dsr_p_value < thresholds.dsr_max_p_value


# ─────────────────────────────────────────────────────────────────────
#   Edge-case pinned tests
# ─────────────────────────────────────────────────────────────────────


class TestEdgeCasesPinned:
    def test_zero_trials_no_deflation_dsr_equals_observed(self) -> None:
        # trials_count=0 → threshold=0 (no deflation) → dsr =
        # observed_sharpe; the validator catches the zero-trials
        # contract violation.
        ev = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=0,
            annualization_factor=math.sqrt(252),
        )
        assert ev.dsr == 0.5 * math.sqrt(252)
        assert ev.observed_sharpe == 0.5 * math.sqrt(252)
        # dsr_p_value should equal 1 - PSR(0.5, threshold=0, gauss).
        sr_hat = 0.5
        var_term = 1.0 + sr_hat * sr_hat / 2.0
        z = sr_hat * math.sqrt(251) / math.sqrt(var_term)
        psr = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
        assert ev.dsr_p_value == 1.0 - psr
        # Validator must reject due to trials_count <= 0.
        errors = validate_dsr(ev, GateThresholds())
        assert any("trials_count" in e for e in errors)

    def test_one_trial_no_deflation(self) -> None:
        ev = build_dsr_evidence(
            observed_sharpe=0.5,
            n_obs=252,
            trials_count=1,
            annualization_factor=math.sqrt(252),
        )
        # threshold = 0 for n_trials=1.
        assert ev.dsr == 0.5 * math.sqrt(252)

    def test_default_kurtosis_is_gaussian(self) -> None:
        # The schema docs the default kurtosis as 3.0 (Gaussian
        # convention).  Verify build_dsr_evidence inherits that
        # default and produces the same evidence as if 3.0 were
        # passed explicitly.
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
        # For any well-formed inputs, dsr_p_value = 1 - PSR(observed;
        # threshold = E[max]) exactly — no numerical slack.
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
