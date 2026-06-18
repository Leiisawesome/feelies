"""``TurnoverOptimizer`` — translate target weights into target USD positions.

Given the cross-sectionally ranked, factor-neutralized,
sector-matched weight vector ``w_target`` and the current notional
positions ``p_current`` (USD), the optimizer solves a small convex
problem:

    minimize    -wᵀ μ + λ_risk * wᵀ Σ w + λ_tc * ||w - p_current||₁
    subject to  ||w||₁ ≤ gross_cap
                |w_i| ≤ per_name_cap

CVXPY (with the ECOS solver per design Q7) is used when available.
For deterministic / no-extras builds the optimizer falls back to a
**closed-form rescale**: weights are L1-normalized to ``gross_cap``
and clipped to ``per_name_cap`` per name.  In both modes the output
dollar quantities are rounded to whole-cent precision so two
back-to-back invocations produce bit-identical
:class:`feelies.core.events.SizedPositionIntent` events.

The optimizer never raises on infeasibility — instead it returns the
*null* allocation (``{}``) and logs a warning.  Upstream callers
treat the empty dict as "hold existing positions" per
:class:`SizedPositionIntent` semantics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Mapping

# Optional [portfolio] extras — typed as ``Any`` so strict mypy accepts
# the ImportError branch without pretending ``numpy`` / ``cvxpy`` exist.
cp: Any = None
_np: Any = None
try:  # pragma: no cover - optional extra
    import cvxpy as _cp
    import numpy as _numpy

    cp = _cp
    _np = _numpy
    _HAS_CVXPY = True
except ImportError:  # pragma: no cover
    _HAS_CVXPY = False


_logger = logging.getLogger(__name__)


# Pinned ECOS interior-point tolerances and iteration cap (audit P0-2).
# ECOS is invoked with *explicit* convergence criteria so the returned
# solution does not drift across ECOS / BLAS builds or CPU architectures.
# Re-baseline the Level-3 solver-parity hash in the same commit if these
# values ever change.
_ECOS_ABSTOL: float = 1e-8
_ECOS_RELTOL: float = 1e-8
_ECOS_FEASTOL: float = 1e-8
_ECOS_MAX_ITERS: int = 100


class MissingOptionalDependencyError(RuntimeError):
    """Raised when a feature requires the [portfolio] extras."""


@dataclass(frozen=True)
class OptimizerResult:
    target_usd: dict[str, float]
    expected_turnover_usd: float
    expected_gross_exposure_usd: float
    solver_status: str


class TurnoverOptimizer:
    """Translate target weights to target dollar positions.

    Parameters
    ----------
    capital_usd :
        Strategy notional budget; weights are scaled to span at most
        ``gross_cap_pct * capital_usd`` of gross exposure.
    gross_cap_pct :
        Maximum gross-leverage as a fraction of ``capital_usd``
        (default ``2.0`` = 200% gross).
    per_name_cap_pct :
        Maximum *per-symbol* exposure as a fraction of
        ``capital_usd`` (default ``0.05`` = 5%).
    lambda_tc :
        L1 turnover penalty (default ``1.0``).  Higher → less change
        from current positions.
    lambda_risk :
        Quadratic-risk penalty (default ``0.1``).  Used only by the
        CVXPY path; the closed-form fallback ignores it.
    require_solver :
        Selects the optimization path **deterministically** (audit P0-1).
        When ``True`` the cvxpy/ECOS path is used (and
        :class:`MissingOptionalDependencyError` is raised at construction
        if cvxpy is absent).  When ``False`` (default) the deterministic
        closed-form rescale is always used — *regardless of whether cvxpy
        happens to be installed* — so the emitted intent stream does not
        depend on the environment's optional extras (Inv-5 / Inv-9).

    Caps vs. the alpha ``risk_budget`` (audit P2-3)
    -----------------------------------------------
    ``gross_cap_pct`` / ``per_name_cap_pct`` are *composition-shaping*
    parameters: they bound the **desired** book the optimizer constructs,
    in USD / fraction-of-capital units.  They are intentionally **not**
    sourced from the alpha's ``risk_budget`` (``max_position_per_symbol``
    in *shares*, ``max_gross_exposure_pct``) — that budget is enforced
    authoritatively *downstream* and per-leg by the risk engine
    (``RiskEngine.check_sized_intent`` → ``check_order`` / the per-alpha
    ``AlphaBudgetRiskWrapper``), which owns the shares↔USD conversion and
    the regime-scaled, account-level veto (Inv-11).  Feeding the
    shares-domain risk budget into this USD-domain optimizer would
    double-count the constraint and leak the risk layer into the
    composition layer (Inv-8).  Making these shaping caps operator-tunable
    (a ``composition_gross_cap_pct`` config, parallel to ``lambda_tc``) is
    the natural extension if per-deployment shaping is needed.
    """

    __slots__ = (
        "_capital",
        "_gross_cap",
        "_per_name_cap",
        "_lambda_tc",
        "_lambda_risk",
        "_require_solver",
    )

    def __init__(
        self,
        *,
        capital_usd: float,
        gross_cap_pct: float = 2.0,
        per_name_cap_pct: float = 0.05,
        lambda_tc: float = 1.0,
        lambda_risk: float = 0.1,
        require_solver: bool = False,
    ) -> None:
        if capital_usd <= 0:
            raise ValueError("capital_usd must be positive")
        if gross_cap_pct <= 0:
            raise ValueError("gross_cap_pct must be positive")
        if not 0 < per_name_cap_pct <= 1:
            raise ValueError("per_name_cap_pct must be in (0, 1]")
        if lambda_tc < 0 or lambda_risk < 0:
            raise ValueError("penalty weights must be non-negative")
        if require_solver and not _HAS_CVXPY:
            raise MissingOptionalDependencyError(
                "TurnoverOptimizer: require_solver=True but cvxpy is not "
                "installed.  pip install 'feelies[portfolio]'"
            )
        self._capital = float(capital_usd)
        self._gross_cap = float(gross_cap_pct)
        self._per_name_cap = float(per_name_cap_pct)
        self._lambda_tc = float(lambda_tc)
        self._lambda_risk = float(lambda_risk)
        self._require_solver = bool(require_solver)

    # ── Public API ───────────────────────────────────────────────────

    def optimize(
        self,
        weights: Mapping[str, float],
        universe: tuple[str, ...],
        current_positions_usd: Mapping[str, float] | None = None,
    ) -> OptimizerResult:
        """Solve the optimization; return :class:`OptimizerResult`.

        The path is chosen by ``require_solver`` (set at construction),
        **not** by whether cvxpy is importable (audit P0-1).  This keeps
        the emitted intent stream bit-identical across environments that
        differ only in the presence of the optional ``[portfolio]`` extra.
        """
        if not universe:
            return OptimizerResult({}, 0.0, 0.0, "EMPTY_UNIVERSE")

        if self._require_solver:
            # Constructor guarantees cvxpy is present when require_solver.
            return self._optimize_cvxpy(
                weights,
                universe,
                current_positions_usd or {},
            )
        return self._optimize_closed_form(
            weights,
            universe,
            current_positions_usd or {},
        )

    # ── Strategies ───────────────────────────────────────────────────

    def _optimize_closed_form(
        self,
        weights: Mapping[str, float],
        universe: tuple[str, ...],
        current_positions_usd: Mapping[str, float],
    ) -> OptimizerResult:
        per_name_cap_usd = self._per_name_cap * self._capital
        gross_cap_usd = self._gross_cap * self._capital

        # Step 1: scale weights so the post-scale gross equals the target
        # ``capital * gross_cap``.  The prior ``min(..., capital)`` clamp
        # (audit P2-4) capped the scale at one unit of capital, which
        # *under-levered* whenever the raw weight gross fell below
        # ``gross_cap`` (the book then spanned ``gross * capital`` instead
        # of the intended ``gross_cap * capital``).  The per-name cap
        # (step 2) and the post-rounding gross shrink (step 4) bound the
        # result from above, so the clamp added no safety — only a
        # silent, dimensionally-confusing leverage haircut.
        gross = sum(abs(weights.get(s, 0.0)) for s in universe)
        if gross <= 0.0:
            return OptimizerResult({}, 0.0, 0.0, "ZERO_GROSS")
        scale = self._capital * self._gross_cap / gross
        scaled = {s: weights.get(s, 0.0) * scale for s in universe}

        # Step 2: cap per-name exposure.
        for s in universe:
            v = scaled[s]
            if v > per_name_cap_usd:
                scaled[s] = per_name_cap_usd
            elif v < -per_name_cap_usd:
                scaled[s] = -per_name_cap_usd

        # Step 3: round to whole cents for determinism.
        rounded = {s: round(scaled[s], 2) for s in universe if abs(scaled[s]) >= 0.01}

        # Step 4: enforce gross cap post-clip (rounding may push us
        # marginally over).
        cur_gross = sum(abs(v) for v in rounded.values())
        if cur_gross > gross_cap_usd and cur_gross > 0:
            shrink = gross_cap_usd / cur_gross
            rounded = {s: round(v * shrink, 2) for s, v in rounded.items()}

        turnover = sum(
            abs(rounded.get(s, 0.0) - current_positions_usd.get(s, 0.0)) for s in universe
        )
        gross_after = sum(abs(v) for v in rounded.values())
        return OptimizerResult(
            target_usd=rounded,
            expected_turnover_usd=turnover,
            expected_gross_exposure_usd=gross_after,
            solver_status="CLOSED_FORM",
        )

    def _optimize_cvxpy(
        self,
        weights: Mapping[str, float],
        universe: tuple[str, ...],
        current_positions_usd: Mapping[str, float],
    ) -> OptimizerResult:
        assert _HAS_CVXPY
        assert cp is not None and _np is not None
        n = len(universe)
        # Optimize in *weight space* (dimensionless fractions of capital)
        # so the alpha, risk, and turnover terms are commensurable and
        # well-scaled — the prior USD-space formulation let the risk term
        # ``(0.01*capital)**2`` dominate by ~10 orders of magnitude, so a
        # successful solve collapsed to the empty book (audit P0-1/P1-1).
        # The dollar targets are recovered by scaling the optimal weight
        # vector by ``capital`` at the end.
        mu = _np.asarray(
            [weights.get(s, 0.0) for s in universe],
            dtype=_np.float64,
        )
        w_cur = _np.asarray(
            [current_positions_usd.get(s, 0.0) / self._capital for s in universe],
            dtype=_np.float64,
        )
        # Static identity risk model (audit P2-1).  No intraday covariance
        # Σ is estimated (design Q5: daily refresh, intraday uses static
        # inputs), so the risk term is a *unit diagonal* ridge: every name
        # carries equal variance and zero pairwise covariance.  Two
        # consequences the operator must understand:
        #   * the term penalizes raw weight concentration uniformly — it is
        #     a convexity/dispersion regularizer, NOT a true risk model, so
        #     it does not down-weight genuinely high-vol names or net out
        #     correlated pairs;
        #   * because mu/w are O(1) in weight space, a unit ridge is well-
        #     conditioned and keeps the QP convex without swamping the alpha
        #     term (the prior USD-space ridge did swamp it — P0-1/P1-1).
        # Wiring an estimated diagonal vol (or full Σ) here is the natural
        # extension; it is deferred until an intraday estimator exists, and
        # would require re-baselining the Level-3 solver-parity hash.
        sigma_diag = _np.ones(n)

        w = cp.Variable(n)
        per_name_cap = self._per_name_cap  # weight-space caps (fractions)
        gross_cap = self._gross_cap

        objective = cp.Minimize(
            -mu @ w
            + self._lambda_risk * cp.sum(cp.multiply(sigma_diag, cp.square(w)))
            + self._lambda_tc * cp.norm(w - w_cur, 1)
        )
        constraints = [
            cp.norm(w, 1) <= gross_cap,
            cp.abs(w) <= per_name_cap,
        ]
        problem = cp.Problem(objective, constraints)
        try:
            problem.solve(
                solver=cp.ECOS,
                verbose=False,
                abstol=_ECOS_ABSTOL,
                reltol=_ECOS_RELTOL,
                feastol=_ECOS_FEASTOL,
                max_iters=_ECOS_MAX_ITERS,
            )
        except (cp.SolverError, ValueError) as exc:  # pragma: no cover
            _logger.warning(
                "TurnoverOptimizer: ECOS solve failed (%s); falling back to closed-form",
                exc,
            )
            # Mark the fallback distinctly so the monitoring layer can alert
            # on solver degradation (audit P1-8) — a verbatim closed-form
            # status would hide that the *required* solver failed.
            fallback = self._optimize_closed_form(
                weights,
                universe,
                current_positions_usd,
            )
            return replace(fallback, solver_status="ECOS_FAILED_FALLBACK")

        if w.value is None or problem.status not in ("optimal", "optimal_inaccurate"):
            _logger.warning(
                "TurnoverOptimizer: solver status=%s; returning empty allocation",
                problem.status,
            )
            return OptimizerResult({}, 0.0, 0.0, problem.status or "UNKNOWN")

        rounded: dict[str, float] = {}
        for i, s in enumerate(universe):
            v = round(float(w.value[i]) * self._capital, 2)
            if abs(v) >= 0.01:
                rounded[s] = v

        turnover = sum(
            abs(rounded.get(s, 0.0) - current_positions_usd.get(s, 0.0)) for s in universe
        )
        gross_after = sum(abs(v) for v in rounded.values())
        return OptimizerResult(
            target_usd=rounded,
            expected_turnover_usd=turnover,
            expected_gross_exposure_usd=gross_after,
            solver_status=problem.status,
        )


__all__ = [
    "MissingOptionalDependencyError",
    "OptimizerResult",
    "TurnoverOptimizer",
]
