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
from dataclasses import dataclass
from typing import Mapping

try:  # pragma: no cover - optional extra
    import cvxpy as cp  # type: ignore[import-not-found]
    import numpy as np
    _HAS_CVXPY = True
except ImportError:  # pragma: no cover
    _HAS_CVXPY = False
    np = None  # type: ignore[assignment]


_logger = logging.getLogger(__name__)


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
        When ``True``, raise :class:`MissingOptionalDependencyError`
        if CVXPY is not installed.  When ``False`` (default), fall
        back to the closed-form rescale.
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
        """Solve the optimization; return :class:`OptimizerResult`."""
        if not universe:
            return OptimizerResult({}, 0.0, 0.0, "EMPTY_UNIVERSE")

        if _HAS_CVXPY:
            return self._optimize_cvxpy(
                weights, universe, current_positions_usd or {},
            )
        return self._optimize_closed_form(
            weights, universe, current_positions_usd or {},
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

        # Step 1: scale weights to target gross.
        gross = sum(abs(weights.get(s, 0.0)) for s in universe)
        if gross <= 0.0:
            return OptimizerResult({}, 0.0, 0.0, "ZERO_GROSS")
        scale = min(self._capital * self._gross_cap / gross, self._capital)
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
            abs(rounded.get(s, 0.0) - current_positions_usd.get(s, 0.0))
            for s in universe
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
        n = len(universe)
        mu = np.asarray(
            [weights.get(s, 0.0) for s in universe], dtype=np.float64,
        )
        p_cur = np.asarray(
            [current_positions_usd.get(s, 0.0) for s in universe],
            dtype=np.float64,
        )
        # Diagonal "risk" — cross-sectional position penalization;
        # per Q5 we don't have an intraday Σ here, so use identity
        # scaled by an estimated per-name vol of 1% of capital.  This
        # keeps the optimizer well-conditioned and is pure / static.
        sigma_diag = (0.01 * self._capital) ** 2 * np.ones(n)

        x = cp.Variable(n)
        per_name_cap = self._per_name_cap * self._capital
        gross_cap = self._gross_cap * self._capital

        objective = cp.Minimize(
            -mu @ x
            + self._lambda_risk * cp.sum(cp.multiply(sigma_diag, cp.square(x)))
            + self._lambda_tc * cp.norm(x - p_cur, 1)
        )
        constraints = [
            cp.norm(x, 1) <= gross_cap,
            cp.abs(x) <= per_name_cap,
        ]
        problem = cp.Problem(objective, constraints)
        try:
            problem.solve(solver=cp.ECOS, verbose=False)
        except (cp.SolverError, ValueError) as exc:  # pragma: no cover
            _logger.warning(
                "TurnoverOptimizer: ECOS solve failed (%s); "
                "falling back to closed-form",
                exc,
            )
            return self._optimize_closed_form(
                weights, universe, current_positions_usd,
            )

        if x.value is None or problem.status not in ("optimal", "optimal_inaccurate"):
            _logger.warning(
                "TurnoverOptimizer: solver status=%s; returning empty allocation",
                problem.status,
            )
            return OptimizerResult({}, 0.0, 0.0, problem.status or "UNKNOWN")

        rounded: dict[str, float] = {}
        for i, s in enumerate(universe):
            v = round(float(x.value[i]), 2)
            if abs(v) >= 0.01:
                rounded[s] = v

        turnover = sum(
            abs(rounded.get(s, 0.0) - current_positions_usd.get(s, 0.0))
            for s in universe
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
