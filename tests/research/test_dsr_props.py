"""Hypothesis property tests for :mod:`feelies.research.dsr` (Workstream C-2).

Property invariants asserted here:

- ``standard_normal_cdf`` ∈ [0, 1] for every input.
- ``standard_normal_cdf`` is monotone non-decreasing.
- CDF/quantile are inverses on the open interval ``(0, 1)``.
- ``probabilistic_sharpe_ratio`` ∈ [0, 1] for every valid input.
- ``probabilistic_sharpe_ratio`` is monotone non-decreasing in
  ``observed_sharpe`` (holding everything else fixed).
- ``probabilistic_sharpe_ratio`` is monotone non-increasing in
  ``threshold_sharpe`` (higher null bar → smaller probability of
  beating it).
- ``probabilistic_sharpe_ratio`` saturates at 0.5 when observed ==
  threshold (already covered in unit tests; re-asserted here as a
  fuzzed sanity check).
- ``expected_max_sharpe`` is non-decreasing in ``n_trials``.
- ``expected_max_sharpe`` is ``√v``-scaled in ``trial_sharpe_variance``.
- ``deflated_sharpe`` is deterministic (replay produces identical
  results for identical inputs) — Inv-5.
- ``build_dsr_evidence`` is deterministic and produces ``dsr_p_value
  ∈ [0, 1]`` for every well-formed input.
- ``build_dsr_evidence`` annualisation is linear in
  ``annualization_factor``.
- ``build_dsr_evidence_from_returns`` matches the explicit-stats
  path when invoked with the same data.
"""

from __future__ import annotations

import math
import statistics
from typing import Any

import pytest
from hypothesis import HealthCheck, assume, given, settings, strategies as st

from feelies.research.dsr import (
    build_dsr_evidence,
    build_dsr_evidence_from_returns,
    deflated_sharpe,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
    standard_normal_cdf,
    standard_normal_quantile,
    standardised_moments,
)


SETTINGS = settings(
    max_examples=80,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ─────────────────────────────────────────────────────────────────────
#   Strategies
# ─────────────────────────────────────────────────────────────────────


# A "well-formed" Sharpe input that keeps the PSR variance term
# safely positive: skewness in [-1, 1], kurtosis in [3, 8] (always
# above the (skew² + 1) lower bound for moderate skews); Sharpe in
# [-2, 2] (avoiding the pathological saturation at very large |SR|).
WELL_FORMED_SHARPE_KWARGS = st.fixed_dictionaries(
    {
        "observed_sharpe": st.floats(min_value=-2.0, max_value=2.0),
        "threshold_sharpe": st.floats(min_value=-2.0, max_value=2.0),
        "n_obs": st.integers(min_value=10, max_value=2000),
        "skewness": st.floats(min_value=-1.0, max_value=1.0),
        "kurtosis": st.floats(min_value=3.0, max_value=8.0),
    }
)


# Variance is non-negative; bound it to a reasonable empirical range.
TRIAL_SHARPE_VARIANCE = st.floats(min_value=0.0, max_value=1.0)


# ─────────────────────────────────────────────────────────────────────
#   standard_normal_cdf
# ─────────────────────────────────────────────────────────────────────


@SETTINGS
@given(x=st.floats(min_value=-10.0, max_value=10.0))
def test_standard_normal_cdf_in_unit_interval(x: float) -> None:
    p = standard_normal_cdf(x)
    assert 0.0 <= p <= 1.0


@SETTINGS
@given(
    x=st.floats(min_value=-5.0, max_value=5.0),
    delta=st.floats(min_value=1e-6, max_value=1.0),
)
def test_standard_normal_cdf_monotone_non_decreasing(
    x: float, delta: float
) -> None:
    assert standard_normal_cdf(x) <= standard_normal_cdf(x + delta)


@SETTINGS
@given(p=st.floats(min_value=1e-9, max_value=1.0 - 1e-9))
def test_cdf_quantile_round_trip(p: float) -> None:
    x = standard_normal_quantile(p)
    p_round = standard_normal_cdf(x)
    assert math.isclose(p, p_round, abs_tol=1e-9)


# ─────────────────────────────────────────────────────────────────────
#   probabilistic_sharpe_ratio
# ─────────────────────────────────────────────────────────────────────


@SETTINGS
@given(kwargs=WELL_FORMED_SHARPE_KWARGS)
def test_psr_in_unit_interval(kwargs: dict[str, Any]) -> None:
    psr = probabilistic_sharpe_ratio(**kwargs)
    assert 0.0 <= psr <= 1.0


@SETTINGS
@given(
    base=WELL_FORMED_SHARPE_KWARGS,
    delta=st.floats(min_value=1e-3, max_value=0.5),
)
def test_psr_monotone_in_observed_sharpe(
    base: dict[str, Any], delta: float
) -> None:
    # Increasing observed_sharpe → at least non-decreasing PSR.
    kwargs_low = dict(base)
    kwargs_high = dict(base)
    kwargs_high["observed_sharpe"] = base["observed_sharpe"] + delta
    # Skip cases that push the variance term non-positive.
    for k in (kwargs_low, kwargs_high):
        sr = k["observed_sharpe"]
        var_term = (
            1.0 - k["skewness"] * sr + ((k["kurtosis"] - 1.0) / 4.0) * sr * sr
        )
        assume(var_term > 0.0)
    psr_low = probabilistic_sharpe_ratio(**kwargs_low)
    psr_high = probabilistic_sharpe_ratio(**kwargs_high)
    # Allow tiny floating-point regressions when both saturate.
    # Tolerance is 1e-9: the CDF loses ~1e-10 precision near saturation
    # (PSR ≈ 1), which is ~70× larger than the old 1e-12 guard.
    assert psr_high >= psr_low - 1e-9


@SETTINGS
@given(
    base=WELL_FORMED_SHARPE_KWARGS,
    delta=st.floats(min_value=1e-3, max_value=0.5),
)
def test_psr_monotone_non_increasing_in_threshold(
    base: dict[str, Any], delta: float
) -> None:
    # Increasing threshold_sharpe → non-increasing PSR.
    kwargs_low = dict(base)
    kwargs_high = dict(base)
    kwargs_high["threshold_sharpe"] = base["threshold_sharpe"] + delta
    psr_low_threshold = probabilistic_sharpe_ratio(**kwargs_low)
    psr_high_threshold = probabilistic_sharpe_ratio(**kwargs_high)
    assert psr_high_threshold <= psr_low_threshold + 1e-12


@SETTINGS
@given(
    sr=st.floats(min_value=-2.0, max_value=2.0),
    n_obs=st.integers(min_value=10, max_value=2000),
    skewness=st.floats(min_value=-1.0, max_value=1.0),
    kurtosis=st.floats(min_value=3.0, max_value=8.0),
)
def test_psr_at_threshold_equals_observed_is_half(
    sr: float, n_obs: int, skewness: float, kurtosis: float
) -> None:
    psr = probabilistic_sharpe_ratio(
        observed_sharpe=sr,
        threshold_sharpe=sr,
        n_obs=n_obs,
        skewness=skewness,
        kurtosis=kurtosis,
    )
    assert math.isclose(psr, 0.5, abs_tol=1e-12)


@SETTINGS
@given(kwargs=WELL_FORMED_SHARPE_KWARGS)
def test_psr_deterministic(kwargs: dict[str, Any]) -> None:
    p1 = probabilistic_sharpe_ratio(**kwargs)
    p2 = probabilistic_sharpe_ratio(**kwargs)
    assert p1 == p2


# ─────────────────────────────────────────────────────────────────────
#   expected_max_sharpe
# ─────────────────────────────────────────────────────────────────────


@SETTINGS
@given(
    n=st.integers(min_value=2, max_value=1000),
    delta=st.integers(min_value=1, max_value=100),
    v=st.floats(min_value=1e-6, max_value=1.0),
)
def test_expected_max_sharpe_monotone_in_n_trials(
    n: int, delta: int, v: float
) -> None:
    s_low = expected_max_sharpe(n_trials=n, trial_sharpe_variance=v)
    s_high = expected_max_sharpe(n_trials=n + delta, trial_sharpe_variance=v)
    # Strictly increasing for v > 0 and n >= 2; allow tiny FP slop.
    assert s_high >= s_low - 1e-12


@SETTINGS
@given(
    n=st.integers(min_value=2, max_value=1000),
    v=st.floats(min_value=1e-6, max_value=1.0),
    scale=st.floats(min_value=1.0, max_value=1000.0),
)
def test_expected_max_sharpe_sqrt_variance_scaling(
    n: int, v: float, scale: float
) -> None:
    # E[max] is sqrt(v)-linear: scaling v by k scales E[max] by sqrt(k).
    s_base = expected_max_sharpe(n_trials=n, trial_sharpe_variance=v)
    s_scaled = expected_max_sharpe(
        n_trials=n, trial_sharpe_variance=v * scale
    )
    assume(s_base > 1e-15)
    ratio = s_scaled / s_base
    assert math.isclose(ratio, math.sqrt(scale), rel_tol=1e-9)


@SETTINGS
@given(
    n=st.integers(min_value=1, max_value=5000),
    v=TRIAL_SHARPE_VARIANCE,
)
def test_expected_max_sharpe_non_negative(n: int, v: float) -> None:
    s = expected_max_sharpe(n_trials=n, trial_sharpe_variance=v)
    assert s >= 0.0


# ─────────────────────────────────────────────────────────────────────
#   deflated_sharpe (the composition)
# ─────────────────────────────────────────────────────────────────────


@SETTINGS
@given(
    sr=st.floats(min_value=-2.0, max_value=2.0),
    n_obs=st.integers(min_value=10, max_value=2000),
    n_trials=st.integers(min_value=1, max_value=2000),
    skewness=st.floats(min_value=-1.0, max_value=1.0),
    kurtosis=st.floats(min_value=3.0, max_value=8.0),
)
def test_deflated_sharpe_deterministic(
    sr: float,
    n_obs: int,
    n_trials: int,
    skewness: float,
    kurtosis: float,
) -> None:
    kwargs = {
        "observed_sharpe": sr,
        "n_obs": n_obs,
        "n_trials": n_trials,
        "skewness": skewness,
        "kurtosis": kurtosis,
    }
    c1 = deflated_sharpe(**kwargs)
    c2 = deflated_sharpe(**kwargs)
    assert c1 == c2


@SETTINGS
@given(
    sr=st.floats(min_value=-2.0, max_value=2.0),
    n_obs=st.integers(min_value=10, max_value=2000),
    n_trials=st.integers(min_value=1, max_value=2000),
    skewness=st.floats(min_value=-1.0, max_value=1.0),
    kurtosis=st.floats(min_value=3.0, max_value=8.0),
)
def test_deflated_sharpe_psr_plus_p_value_is_one(
    sr: float,
    n_obs: int,
    n_trials: int,
    skewness: float,
    kurtosis: float,
) -> None:
    comp = deflated_sharpe(
        observed_sharpe=sr,
        n_obs=n_obs,
        n_trials=n_trials,
        skewness=skewness,
        kurtosis=kurtosis,
    )
    assert math.isclose(comp.psr + comp.dsr_p_value, 1.0, abs_tol=1e-12)


@SETTINGS
@given(
    base_sr=st.floats(min_value=-1.0, max_value=2.0),
    n_obs=st.integers(min_value=10, max_value=500),
    n_trials_low=st.integers(min_value=2, max_value=100),
    delta=st.integers(min_value=1, max_value=900),
)
def test_deflation_grows_with_more_trials(
    base_sr: float,
    n_obs: int,
    n_trials_low: int,
    delta: int,
) -> None:
    # More trials → larger E[max] → smaller dsr_value → larger
    # dsr_p_value (under iid-Gaussian default variance).
    n_trials_high = n_trials_low + delta
    kw = {
        "observed_sharpe": base_sr,
        "n_obs": n_obs,
        "skewness": 0.0,
        "kurtosis": 3.0,
    }
    c_low = deflated_sharpe(n_trials=n_trials_low, **kw)
    c_high = deflated_sharpe(n_trials=n_trials_high, **kw)
    assert c_high.threshold_sharpe >= c_low.threshold_sharpe - 1e-12
    assert c_high.dsr_value <= c_low.dsr_value + 1e-12
    assert c_high.dsr_p_value >= c_low.dsr_p_value - 1e-12


# ─────────────────────────────────────────────────────────────────────
#   build_dsr_evidence
# ─────────────────────────────────────────────────────────────────────


@SETTINGS
@given(
    sr=st.floats(min_value=-2.0, max_value=2.0),
    n_obs=st.integers(min_value=10, max_value=2000),
    trials_count=st.integers(min_value=0, max_value=2000),
    skewness=st.floats(min_value=-1.0, max_value=1.0),
    kurtosis=st.floats(min_value=3.0, max_value=8.0),
    annualization_factor=st.floats(min_value=0.1, max_value=20.0),
)
def test_build_dsr_evidence_deterministic(
    sr: float,
    n_obs: int,
    trials_count: int,
    skewness: float,
    kurtosis: float,
    annualization_factor: float,
) -> None:
    kwargs = {
        "observed_sharpe": sr,
        "n_obs": n_obs,
        "trials_count": trials_count,
        "skewness": skewness,
        "kurtosis": kurtosis,
        "annualization_factor": annualization_factor,
    }
    e1 = build_dsr_evidence(**kwargs)
    e2 = build_dsr_evidence(**kwargs)
    assert e1 == e2


@SETTINGS
@given(
    sr=st.floats(min_value=-2.0, max_value=2.0),
    n_obs=st.integers(min_value=10, max_value=2000),
    trials_count=st.integers(min_value=0, max_value=2000),
    skewness=st.floats(min_value=-1.0, max_value=1.0),
    kurtosis=st.floats(min_value=3.0, max_value=8.0),
    annualization_factor=st.floats(min_value=0.1, max_value=20.0),
)
def test_build_dsr_evidence_p_value_in_unit_interval(
    sr: float,
    n_obs: int,
    trials_count: int,
    skewness: float,
    kurtosis: float,
    annualization_factor: float,
) -> None:
    ev = build_dsr_evidence(
        observed_sharpe=sr,
        n_obs=n_obs,
        trials_count=trials_count,
        skewness=skewness,
        kurtosis=kurtosis,
        annualization_factor=annualization_factor,
    )
    assert 0.0 <= ev.dsr_p_value <= 1.0


@SETTINGS
@given(
    sr=st.floats(min_value=-1.0, max_value=2.0),
    n_obs=st.integers(min_value=10, max_value=500),
    trials_count=st.integers(min_value=1, max_value=1000),
    annualization_factor=st.floats(min_value=0.5, max_value=20.0),
)
def test_build_dsr_evidence_annualisation_is_linear(
    sr: float,
    n_obs: int,
    trials_count: int,
    annualization_factor: float,
) -> None:
    kwargs = {
        "observed_sharpe": sr,
        "n_obs": n_obs,
        "trials_count": trials_count,
        "skewness": 0.0,
        "kurtosis": 3.0,
    }
    ev_per_period = build_dsr_evidence(annualization_factor=1.0, **kwargs)
    ev_annualised = build_dsr_evidence(
        annualization_factor=annualization_factor, **kwargs
    )
    assert math.isclose(
        ev_annualised.observed_sharpe,
        ev_per_period.observed_sharpe * annualization_factor,
        rel_tol=1e-12,
        abs_tol=1e-12,
    )
    assert math.isclose(
        ev_annualised.dsr,
        ev_per_period.dsr * annualization_factor,
        rel_tol=1e-12,
        abs_tol=1e-12,
    )
    # p-value is dimensionless and unaffected.
    assert ev_annualised.dsr_p_value == ev_per_period.dsr_p_value


# ─────────────────────────────────────────────────────────────────────
#   build_dsr_evidence_from_returns
# ─────────────────────────────────────────────────────────────────────


# A non-degenerate return series strategy: at least 5 elements,
# moderate range; we exclude the all-zero / all-equal case via assume.
RETURN_SERIES = st.lists(
    st.floats(min_value=-0.1, max_value=0.1, allow_nan=False, allow_infinity=False),
    min_size=5,
    max_size=200,
)


@SETTINGS
@given(
    returns=RETURN_SERIES,
    trials_count=st.integers(min_value=1, max_value=500),
)
def test_from_returns_matches_explicit_stats(
    returns: list[float], trials_count: int
) -> None:
    # Exclude the constant-series degenerate case (skewness/kurt
    # default branch) so the parity test below stays meaningful.
    sd = statistics.pstdev(returns)
    assume(sd > 1e-10)
    skew, kurt = standardised_moments(returns)
    ev_from_returns = build_dsr_evidence_from_returns(
        returns=returns, trials_count=trials_count
    )
    ev_explicit = build_dsr_evidence(
        observed_sharpe=sharpe_ratio(returns),
        n_obs=len(returns),
        trials_count=trials_count,
        skewness=skew,
        kurtosis=kurt,
    )
    assert ev_from_returns == ev_explicit


@SETTINGS
@given(returns=RETURN_SERIES)
def test_from_returns_deterministic(returns: list[float]) -> None:
    sd = statistics.pstdev(returns)
    assume(sd > 1e-10)
    e1 = build_dsr_evidence_from_returns(returns=returns, trials_count=10)
    e2 = build_dsr_evidence_from_returns(returns=returns, trials_count=10)
    assert e1 == e2


@SETTINGS
@given(returns=RETURN_SERIES)
def test_from_returns_p_value_in_unit_interval(
    returns: list[float],
) -> None:
    ev = build_dsr_evidence_from_returns(
        returns=returns, trials_count=50
    )
    assert 0.0 <= ev.dsr_p_value <= 1.0


# ─────────────────────────────────────────────────────────────────────
#   standardised_moments
# ─────────────────────────────────────────────────────────────────────


@SETTINGS
@given(returns=RETURN_SERIES)
def test_standardised_moments_kurtosis_non_negative(
    returns: list[float],
) -> None:
    _, kurt = standardised_moments(returns)
    # Kurtosis (non-excess, 4th standardised moment) is always >= 1
    # by the Cauchy-Schwarz inequality.
    assert kurt >= 1.0 - 1e-12


@SETTINGS
@given(returns=RETURN_SERIES)
def test_standardised_moments_deterministic(
    returns: list[float],
) -> None:
    a = standardised_moments(returns)
    b = standardised_moments(returns)
    assert a == b


# ─────────────────────────────────────────────────────────────────────
#   Boundary error propagation
# ─────────────────────────────────────────────────────────────────────


@SETTINGS
@given(n_obs=st.integers(min_value=-100, max_value=1))
def test_psr_rejects_n_obs_below_two(n_obs: int) -> None:
    with pytest.raises(ValueError):
        probabilistic_sharpe_ratio(
            observed_sharpe=0.5,
            threshold_sharpe=0.0,
            n_obs=n_obs,
        )


@SETTINGS
@given(n_trials=st.integers(min_value=-100, max_value=0))
def test_expected_max_sharpe_rejects_invalid_n_trials(n_trials: int) -> None:
    with pytest.raises(ValueError):
        expected_max_sharpe(
            n_trials=n_trials, trial_sharpe_variance=0.1
        )
