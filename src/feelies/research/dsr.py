"""Deflated Sharpe Ratio (DSR) — Workstream **C-2**.

DSR is the multiple-testing-corrected Sharpe-significance procedure
the platform uses to populate
:class:`feelies.alpha.promotion_evidence.DSREvidence` for the
``RESEARCH → PAPER`` and ``PAPER → LIVE`` promotion gates.  This
module implements Bailey & López de Prado's procedure in pure
Python (stdlib only, no numpy / scipy) so the resulting evidence is
bit-identical across hosts and replays deterministically (Inv-5).

References
==========

- Bailey & López de Prado (2014), "The Deflated Sharpe Ratio:
  Correcting for Selection Bias, Backtest Overfitting, and
  Non-Normality", *Journal of Portfolio Management*, vol. 40, no.
  5, pp. 94-107.  Equations referenced inline as **eq. K** below
  refer to that paper.
- Bailey & López de Prado (2012), "The Sharpe Ratio Efficient
  Frontier", *Journal of Risk*, vol. 15, no. 2 — for the
  underlying probabilistic Sharpe ratio (PSR) derivation.
- López de Prado (2018), *Advances in Financial Machine Learning*
  §8 — for the textbook treatment.

Public API
==========

- :func:`standard_normal_cdf`         — Φ(x) via :func:`math.erf`.
- :func:`standard_normal_quantile`    — Φ⁻¹(p) via
  :class:`statistics.NormalDist`.
- :func:`probabilistic_sharpe_ratio`  — PSR (eq. 1) — probability
  that the true Sharpe exceeds the supplied threshold.
- :func:`expected_max_sharpe`         — E[max Sharpe] across
  ``n_trials`` iid-Gaussian trials (eq. 7).
- :func:`deflated_sharpe`             — return the
  ``(dsr_value, dsr_p_value)`` pair.
- :func:`standardised_moments`        — non-excess (skewness,
  kurtosis) of a sample.
- :func:`sharpe_ratio`                — population-style Sharpe;
  re-exported here from :mod:`feelies.research.cpcv` for
  symmetry with C-1.
- :func:`build_dsr_evidence`          — emit
  :class:`feelies.alpha.promotion_evidence.DSREvidence` from
  caller-supplied summary stats.
- :func:`build_dsr_evidence_from_returns` — convenience wrapper
  that extracts Sharpe + skew + kurtosis from a return series
  and forwards to :func:`build_dsr_evidence`.

Schema interpretation
=====================

The F-2 :class:`DSREvidence` schema reports two fields:

- ``dsr``: the **net** deflated Sharpe ratio,
  ``observed_sharpe − E[max Sharpe under null]``, in the same
  units as ``observed_sharpe``.  This is the *economic* component
  of the gate: the alpha must clear the deflated null bar by at
  least ``GateThresholds.dsr_min`` (default 1.0, anchored to
  schema-1.1's "OOS DSR < 1.0 across any single calendar quarter
  after LIVE" falsification rule for **annualised** Sharpe).
- ``dsr_p_value``: ``1 − PSR(observed; threshold = E[max])``.
  This is the *statistical* component: even if the alpha clears
  the economic bar, the deflation-adjusted significance must be
  below ``GateThresholds.dsr_max_p_value`` (default 0.05).

Both checks are wired through :func:`validate_dsr` in F-2.  The
two-of-two design intentionally blocks alphas that are
statistically-significant-but-economically-marginal as well as
economically-large-but-noisy.

Annualisation
=============

The Bailey-LdP test statistic is derived assuming the input
Sharpe is computed at the **same frequency** as the sample-size
``T`` (e.g. daily Sharpe + ``T`` in days; per-bar Sharpe + ``T``
in bars).  The ``dsr_min`` threshold defaults are in **annualised**
units, so :func:`build_dsr_evidence` accepts an
``annualization_factor`` (default 1.0) that scales both
``observed_sharpe`` and ``dsr`` on the emitted evidence:

- Pass ``annualization_factor = sqrt(252)`` to convert
  per-trading-day Sharpes to annualised.
- Pass ``annualization_factor = sqrt(periods_per_year)`` for any
  other bar frequency.

The dimensionless PSR p-value is unaffected by annualisation —
it's a probability under the same per-period null regardless of
the unit choice.

Determinism
===========

Every public function in this module is a pure function of its
arguments.  No PRNG, no clock reads, no I/O, no global state.
:func:`statistics.NormalDist.inv_cdf` is documented as a
deterministic Newton-Raphson refinement (Acklam 2003), bit-stable
across CPython versions at the same minor release.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from feelies.alpha.promotion_evidence import DSREvidence
from feelies.research.cpcv import sharpe_ratio

__all__ = [
    "DSRComputation",
    "build_dsr_evidence",
    "build_dsr_evidence_from_returns",
    "deflated_sharpe",
    "expected_max_sharpe",
    "probabilistic_sharpe_ratio",
    "sharpe_ratio",
    "standard_normal_cdf",
    "standard_normal_quantile",
    "standardised_moments",
]


# ─────────────────────────────────────────────────────────────────────
#   Constants
# ─────────────────────────────────────────────────────────────────────


# Euler-Mascheroni constant γ.  Bailey & López de Prado (2014, eq. 7)
# uses γ ≈ 0.5772 in the closed-form expected-max-Sharpe expression;
# we keep ~16 significant digits here so the result is bit-identical
# across CPython releases.
EULER_MASCHERONI: float = 0.5772156649015328606


# ─────────────────────────────────────────────────────────────────────
#   Standard normal CDF / quantile
# ─────────────────────────────────────────────────────────────────────


def standard_normal_cdf(x: float) -> float:
    """Standard-normal cumulative distribution function Φ(x).

    Implemented via the stdlib :func:`math.erf` so the result is
    bit-identical across hosts: Φ(x) = ½·(1 + erf(x/√2)).
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def standard_normal_quantile(p: float) -> float:
    """Standard-normal inverse CDF Φ⁻¹(p).

    Delegates to :meth:`statistics.NormalDist.inv_cdf`, which uses a
    Newton-Raphson refinement of the Acklam (2003) approximation
    documented as deterministic at the CPython minor-version level.

    Raises ``ValueError`` for ``p`` outside the open interval
    ``(0, 1)`` — Bailey-LdP's eq. 7 only applies in the open
    interval, so an explicit boundary error here saves a confusing
    ``inf`` / ``nan`` propagating through downstream arithmetic.
    """
    if not (0.0 < p < 1.0):
        raise ValueError(
            f"standard_normal_quantile requires p in (0, 1), got {p}"
        )
    return statistics.NormalDist().inv_cdf(p)


# ─────────────────────────────────────────────────────────────────────
#   Probabilistic Sharpe Ratio
# ─────────────────────────────────────────────────────────────────────


def probabilistic_sharpe_ratio(
    *,
    observed_sharpe: float,
    threshold_sharpe: float,
    n_obs: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Bailey & López de Prado (2012/2014) Probabilistic Sharpe Ratio.

    Returns ``P(true Sharpe > threshold_sharpe | observed_sharpe,
    n_obs, skewness, kurtosis)`` under the asymptotic normal
    sampling distribution of the Sharpe estimator.

    Closed form (Bailey-LdP 2014, eq. 1)::

        z = (SR_hat - SR*) * sqrt(T - 1)
            / sqrt(1 - γ₃·SR_hat + ((γ₄ - 1)/4)·SR_hat²)
        PSR(SR*) = Φ(z)

    where ``γ₃`` is the skewness (3rd standardised moment) and
    ``γ₄`` is the **non-excess** kurtosis (4th standardised moment;
    Gaussian = 3, default).

    Inputs / outputs are dimensionless.  The Sharpe arguments must
    be in the **same frequency** as ``n_obs`` — i.e. per-bar Sharpe
    with ``n_obs`` in bars, or per-day Sharpe with ``n_obs`` in
    days.  The caller is responsible for unit consistency; this
    function does not annualise.

    Raises ``ValueError`` if:

    - ``n_obs < 2`` (the variance term divides by ``T - 1``).
    - the variance-correction factor goes non-positive (only
      possible for highly-skewed, low-kurtosis distributions
      paired with extreme Sharpes — Bailey-LdP §3 flags this as
      a sign of misspecified inputs).
    """
    if n_obs < 2:
        raise ValueError(
            f"probabilistic_sharpe_ratio requires n_obs >= 2, got {n_obs}"
        )
    var_term = (
        1.0
        - skewness * observed_sharpe
        + ((kurtosis - 1.0) / 4.0) * observed_sharpe * observed_sharpe
    )
    if var_term <= 0.0:
        raise ValueError(
            "PSR variance term non-positive — inputs imply a "
            f"misspecified return distribution (skew={skewness}, "
            f"kurt={kurtosis}, observed_sharpe={observed_sharpe}, "
            f"variance_factor={var_term})"
        )
    z = (
        (observed_sharpe - threshold_sharpe)
        * math.sqrt(n_obs - 1)
        / math.sqrt(var_term)
    )
    return standard_normal_cdf(z)


# ─────────────────────────────────────────────────────────────────────
#   Expected max Sharpe across N trials
# ─────────────────────────────────────────────────────────────────────


def expected_max_sharpe(
    *,
    n_trials: int,
    trial_sharpe_variance: float,
) -> float:
    """E[max Sharpe] under iid-Gaussian-trials null (Bailey-LdP eq. 7).

    Closed form::

        E[max SR] = sqrt(V[SR])
                  · ((1 - γ)·Φ⁻¹(1 - 1/N)
                     + γ·Φ⁻¹(1 - 1/(N·e)))

    where ``γ ≈ 0.5772`` is the Euler-Mascheroni constant, ``N`` is
    the number of trials explored, ``V[SR]`` is the variance of the
    trial-Sharpe estimates under the null, and ``Φ⁻¹`` is the
    standard-normal quantile.

    Edge cases
    ----------
    - ``n_trials < 1``: ``ValueError`` (degenerate).
    - ``n_trials == 1``: returns ``0.0`` — with a single trial the
      "max" is just the observation itself, no multiple-testing
      deflation applies.
    - ``trial_sharpe_variance < 0``: ``ValueError``.
    - ``trial_sharpe_variance == 0``: returns ``0.0`` — without
      trial-to-trial variability, the max under the null is zero
      by construction.

    Inputs / outputs are in Sharpe units consistent with whatever
    the caller passed for ``trial_sharpe_variance``.  See the
    module docstring for the per-period vs. annualised convention.
    """
    if n_trials < 1:
        raise ValueError(
            f"expected_max_sharpe requires n_trials >= 1, got {n_trials}"
        )
    if trial_sharpe_variance < 0.0:
        raise ValueError(
            "expected_max_sharpe requires trial_sharpe_variance >= 0, "
            f"got {trial_sharpe_variance}"
        )
    if n_trials == 1 or trial_sharpe_variance == 0.0:
        return 0.0
    inv1 = standard_normal_quantile(1.0 - 1.0 / n_trials)
    inv2 = standard_normal_quantile(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(trial_sharpe_variance) * (
        (1.0 - EULER_MASCHERONI) * inv1 + EULER_MASCHERONI * inv2
    )


# ─────────────────────────────────────────────────────────────────────
#   DSR composition
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class DSRComputation:
    """Intermediate result of a DSR calculation.

    Exposed as a dataclass so callers (notebooks, CLI tools) can
    inspect the deflation step without having to re-derive the
    pieces from a :class:`DSREvidence`.

    Attributes
    ----------
    observed_sharpe
        The input Sharpe (per-period; not annualised).
    threshold_sharpe
        ``E[max Sharpe under null]`` for ``n_trials`` iid trials.
    n_obs
        Sample size used for the PSR variance term.
    n_trials
        Number of variants explored before the candidate.
    skewness, kurtosis
        Higher moments used by the PSR variance correction.
    psr
        ``PSR(observed; threshold = threshold_sharpe)`` —
        probability that the true Sharpe exceeds the deflated null.
    dsr_value
        ``observed_sharpe - threshold_sharpe`` — the net deflated
        Sharpe in the same units as the input.
    dsr_p_value
        ``1 - psr`` — probability of observing the candidate
        Sharpe under the deflated null.
    """

    observed_sharpe: float
    threshold_sharpe: float
    n_obs: int
    n_trials: int
    skewness: float
    kurtosis: float
    psr: float
    dsr_value: float
    dsr_p_value: float


def deflated_sharpe(
    *,
    observed_sharpe: float,
    n_obs: int,
    n_trials: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    trial_sharpe_variance: float | None = None,
) -> DSRComputation:
    """Compute the deflated Sharpe ratio for a single candidate.

    Workflow:

    1. ``threshold_sharpe = expected_max_sharpe(n_trials,
       trial_sharpe_variance)``.  When ``trial_sharpe_variance`` is
       ``None`` we substitute ``1 / (n_obs - 1)`` — the variance
       under an iid-Gaussian null with zero true Sharpe and ``n_obs``
       observations per trial (Bailey-LdP eq. 4).  Callers with
       non-iid trial structure (CPCV, walk-forward, etc.) should
       pass an empirically-measured variance.
    2. ``psr = probabilistic_sharpe_ratio(observed; threshold,
       n_obs, skew, kurt)``.
    3. Return both the net Sharpe ``dsr_value = observed - threshold``
       and the right-tail p-value ``dsr_p_value = 1 - psr``,
       together with the intermediate values for inspection.

    Edge cases
    ----------
    - ``n_trials < 1``: ``ValueError``.
    - ``n_trials in {1}``: no deflation, ``threshold_sharpe = 0``,
      ``dsr_value = observed_sharpe``.
    - ``n_obs < 2``: ``ValueError`` (PSR variance term divides by
      ``n_obs - 1``).
    """
    if n_obs < 2:
        raise ValueError(
            f"deflated_sharpe requires n_obs >= 2, got {n_obs}"
        )
    if n_trials < 1:
        raise ValueError(
            f"deflated_sharpe requires n_trials >= 1, got {n_trials}"
        )

    if trial_sharpe_variance is None:
        trial_sharpe_variance = 1.0 / (n_obs - 1)

    threshold_sharpe = expected_max_sharpe(
        n_trials=n_trials,
        trial_sharpe_variance=trial_sharpe_variance,
    )
    psr = probabilistic_sharpe_ratio(
        observed_sharpe=observed_sharpe,
        threshold_sharpe=threshold_sharpe,
        n_obs=n_obs,
        skewness=skewness,
        kurtosis=kurtosis,
    )
    return DSRComputation(
        observed_sharpe=observed_sharpe,
        threshold_sharpe=threshold_sharpe,
        n_obs=n_obs,
        n_trials=n_trials,
        skewness=skewness,
        kurtosis=kurtosis,
        psr=psr,
        dsr_value=observed_sharpe - threshold_sharpe,
        dsr_p_value=1.0 - psr,
    )


# ─────────────────────────────────────────────────────────────────────
#   Standardised moments (skewness + kurtosis)
# ─────────────────────────────────────────────────────────────────────


def standardised_moments(returns: Sequence[float]) -> tuple[float, float]:
    """Return ``(skewness, kurtosis)`` — the 3rd and 4th
    *non-central, standardised, non-excess* moments of the sample.

    Definitions::

        skew = (1/n) Σ ((r - μ)/σ)^3
        kurt = (1/n) Σ ((r - μ)/σ)^4

    where ``σ = pstdev(returns)`` (population standard deviation,
    matching :func:`feelies.research.cpcv.sharpe_ratio`'s
    convention).  The Gaussian baseline is ``(0.0, 3.0)`` — in
    particular, this function returns *non-excess* kurtosis to
    align with the F-2 :class:`DSREvidence` schema (whose
    ``kurtosis`` field defaults to ``3.0`` for the Gaussian case).

    Degenerate inputs (``len < 2`` or ``σ = 0``) return the
    Gaussian baseline ``(0.0, 3.0)``, since the higher moments
    are undefined and the PSR formula then collapses safely to
    its Gaussian form.
    """
    n = len(returns)
    if n < 2:
        return (0.0, 3.0)
    mean = statistics.fmean(returns)
    sd = statistics.pstdev(returns)
    if sd == 0.0:
        return (0.0, 3.0)
    sd3 = sd * sd * sd
    sd4 = sd3 * sd
    # Defend against subnormal-stddev underflow: if sd is so small
    # that its cube/fourth-power saturates to 0.0, the higher
    # moments are numerically meaningless — fall back to Gaussian.
    if sd3 == 0.0 or sd4 == 0.0:
        return (0.0, 3.0)
    m3 = sum((r - mean) ** 3 for r in returns) / n
    m4 = sum((r - mean) ** 4 for r in returns) / n
    return (m3 / sd3, m4 / sd4)


# ─────────────────────────────────────────────────────────────────────
#   Top-level DSREvidence builders
# ─────────────────────────────────────────────────────────────────────


def build_dsr_evidence(
    *,
    observed_sharpe: float,
    n_obs: int,
    trials_count: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    trial_sharpe_variance: float | None = None,
    annualization_factor: float = 1.0,
) -> DSREvidence:
    """Build :class:`DSREvidence` from caller-supplied summary stats.

    Inputs are in **per-period** Sharpe units (i.e. computed at the
    same bar frequency as ``n_obs``).  The ``annualization_factor``
    parameter scales the emitted ``observed_sharpe`` and ``dsr``
    fields onto whatever target unit the caller wants — e.g.
    ``annualization_factor = math.sqrt(252)`` for the standard
    daily-to-annual convention.

    The ``dsr_p_value`` field is dimensionless and unaffected by
    ``annualization_factor``; the deflation null is evaluated at
    the same per-period frequency as the inputs.

    The function is permissive about ``trials_count`` — it accepts
    ``trials_count = 0`` and produces a valid (but inevitably
    failing-validator) :class:`DSREvidence` so a researcher can
    inspect the no-deflation baseline without the function raising
    in the middle of an exploration notebook.  ``trials_count <
    0`` is rejected as nonsensical.

    Raises ``ValueError`` for ``n_obs < 2``, ``trials_count < 0``,
    ``annualization_factor <= 0``, or any inputs the underlying
    :func:`probabilistic_sharpe_ratio` rejects.
    """
    if n_obs < 2:
        raise ValueError(
            f"build_dsr_evidence requires n_obs >= 2, got {n_obs}"
        )
    if trials_count < 0:
        raise ValueError(
            f"build_dsr_evidence requires trials_count >= 0, "
            f"got {trials_count}"
        )
    if annualization_factor <= 0.0:
        raise ValueError(
            "build_dsr_evidence requires annualization_factor > 0, "
            f"got {annualization_factor}"
        )

    if trials_count == 0:
        # No deflation possible.  Build a degenerate evidence package
        # so the validator can flag the missing trial count.  We
        # still compute a meaningful PSR against threshold = 0 so
        # the dsr_p_value is informative.
        psr = probabilistic_sharpe_ratio(
            observed_sharpe=observed_sharpe,
            threshold_sharpe=0.0,
            n_obs=n_obs,
            skewness=skewness,
            kurtosis=kurtosis,
        )
        dsr_value = observed_sharpe
        dsr_p_value = 1.0 - psr
    else:
        comp = deflated_sharpe(
            observed_sharpe=observed_sharpe,
            n_obs=n_obs,
            n_trials=trials_count,
            skewness=skewness,
            kurtosis=kurtosis,
            trial_sharpe_variance=trial_sharpe_variance,
        )
        dsr_value = comp.dsr_value
        dsr_p_value = comp.dsr_p_value

    return DSREvidence(
        observed_sharpe=observed_sharpe * annualization_factor,
        trials_count=trials_count,
        skewness=skewness,
        kurtosis=kurtosis,
        dsr=dsr_value * annualization_factor,
        dsr_p_value=dsr_p_value,
    )


def build_dsr_evidence_from_returns(
    *,
    returns: Sequence[float],
    trials_count: int,
    trial_sharpe_variance: float | None = None,
    annualization_factor: float = 1.0,
) -> DSREvidence:
    """Convenience wrapper that derives Sharpe + skew + kurtosis
    from a return series and forwards to :func:`build_dsr_evidence`.

    The returned evidence's ``observed_sharpe`` and ``dsr`` are
    scaled by ``annualization_factor`` (default 1.0); the inputs
    (``returns``, ``trial_sharpe_variance``) remain in the input's
    native frequency.  Rejects sequences shorter than 2 elements
    (the PSR formula divides by ``n_obs - 1``).
    """
    if len(returns) < 2:
        raise ValueError(
            "build_dsr_evidence_from_returns requires at least 2 returns, "
            f"got {len(returns)}"
        )
    skew, kurt = standardised_moments(returns)
    return build_dsr_evidence(
        observed_sharpe=sharpe_ratio(returns),
        n_obs=len(returns),
        trials_count=trials_count,
        skewness=skew,
        kurtosis=kurt,
        trial_sharpe_variance=trial_sharpe_variance,
        annualization_factor=annualization_factor,
    )
