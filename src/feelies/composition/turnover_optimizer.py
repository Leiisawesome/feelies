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
import os
import platform as _platform
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
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


# Pin ECOS convergence settings for reproducible solutions across builds.
_ECOS_ABSTOL: float = 1e-8
_ECOS_RELTOL: float = 1e-8
_ECOS_FEASTOL: float = 1e-8
_ECOS_MAX_ITERS: int = 100


_CENT = Decimal("0.01")


def round_cents(x: float) -> float:
    """Round *x* to whole cents with the platform rounding mode.

    Uses ``Decimal(str(x))`` + ``ROUND_HALF_UP`` — the same mode the risk layer
    applies for the dollar→share conversion (``sized_intent_orders``) — so
    target-dollar rounding is half-up rather than binary-float
    round-half-to-even, removing subtle drift around cent-level thresholds
    (e.g. ``round(2.675, 2) == 2.67`` vs ``2.68`` here).  Deterministic.
    """
    return float(Decimal(str(x)).quantize(_CENT, rounding=ROUND_HALF_UP))


class MissingOptionalDependencyError(RuntimeError):
    """Raised when a feature requires the [portfolio] extras."""


class UnvalidatedSolverPlatformError(RuntimeError):
    """Raised when ``require_solver=True`` is selected on an unvalidated platform.

    ECOS/cvxpy is deterministic only for a fixed OS, architecture, and solver
    build. Operators must explicitly allow platforms that pass solver parity
    tests via ``FEELIES_ECOS_VALIDATED_PLATFORMS``.
    """


_ECOS_VALIDATED_PLATFORMS_ENV = "FEELIES_ECOS_VALIDATED_PLATFORMS"


def _current_platform_tag() -> str:
    """``{system}-{machine}`` tag for the running host, e.g. ``Linux-x86_64``."""
    return f"{_platform.system()}-{_platform.machine()}"


def _ecos_platform_validated() -> bool:
    """Whether the current host is in the operator-declared ECOS allowlist.

    Reads ``FEELIES_ECOS_VALIDATED_PLATFORMS`` as a comma-separated list of
    ``{system}-{machine}`` tags (e.g. ``"Linux-x86_64,Darwin-arm64"``).  Unset
    or empty means "not validated" — fail closed, matching Inv-11 (unknown
    states resolve to reduced capability, not increased).
    """
    raw = os.environ.get(_ECOS_VALIDATED_PLATFORMS_ENV, "")
    allowlist = {tag.strip() for tag in raw.split(",") if tag.strip()}
    return _current_platform_tag() in allowlist


@dataclass(frozen=True)
class OptimizerResult:
    target_usd: dict[str, float]
    expected_turnover_usd: float
    expected_gross_exposure_usd: float
    solver_status: str


class TurnoverOptimizer:
    """Translate target weights into capped dollar positions.

    Gross and per-name caps shape the desired book; downstream risk checks own
    account and share limits. ``lambda_tc`` penalizes turnover. ``lambda_risk``
    applies only to the optional solver path. ``require_solver=False`` always
    selects the deterministic closed-form path, regardless of installed extras.
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
        if require_solver and not _ecos_platform_validated():
            raise UnvalidatedSolverPlatformError(
                "TurnoverOptimizer: require_solver=True (composition_optimizer_mode: "
                "ecos) but this platform "
                f"({_current_platform_tag()}) is not in "
                f"{_ECOS_VALIDATED_PLATFORMS_ENV}.  ECOS/cvxpy determinism is only "
                "guaranteed on a fixed (OS, arch, ECOS/BLAS build) and this "
                "repository has no CI validating it across hosts (composition "
                "audit 2026-07-02).  Run "
                "tests/determinism/test_sized_intent_solver_replay.py on every "
                "platform you intend to deploy to, then set "
                f"{_ECOS_VALIDATED_PLATFORMS_ENV}="
                f"'{_current_platform_tag()}' (comma-separate multiple platforms) "
                "to confirm you have done so."
            )
        self._capital = float(capital_usd)
        self._gross_cap = float(gross_cap_pct)
        self._per_name_cap = float(per_name_cap_pct)
        self._lambda_tc = float(lambda_tc)
        self._lambda_risk = float(lambda_risk)
        self._require_solver = bool(require_solver)

    # ── Public API ───────────────────────────────────────────────────

    def provenance_digest(self) -> str:
        """Stable digest of the optimizer's decision-affecting parameters.

        Folded into ``decision_basis_hash`` with the per-solve
        ``solver_status`` so the digest moves
        when capital, caps, the turnover/risk penalties, or the solver-path
        selection change.
        """
        return (
            f"cap={self._capital:.10g}|gross={self._gross_cap:.10g}|"
            f"pername={self._per_name_cap:.10g}|ltc={self._lambda_tc:.10g}|"
            f"lrisk={self._lambda_risk:.10g}|solver={self._require_solver}"
        )

    def optimize(
        self,
        weights: Mapping[str, float],
        universe: tuple[str, ...],
        current_positions_usd: Mapping[str, float] | None = None,
    ) -> OptimizerResult:
        """Solve the optimization; return :class:`OptimizerResult`.

        The path is chosen by ``require_solver`` (set at construction),
        **not** by whether cvxpy is importable. This keeps
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

        # Scale low-gross weights up to the configured budget before applying caps.
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

        # Step 3: round to cents with deterministic half-up Decimal.
        rounded = {s: round_cents(scaled[s]) for s in universe if abs(scaled[s]) >= 0.01}

        # Step 4: enforce gross cap post-clip (rounding may push us
        # marginally over).
        cur_gross = sum(abs(v) for v in rounded.values())
        if cur_gross > gross_cap_usd and cur_gross > 0:
            shrink = gross_cap_usd / cur_gross
            rounded = {s: round_cents(v * shrink) for s, v in rounded.items()}

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
        # Solve in weight space so alpha, risk, and turnover remain commensurable.
        mu = _np.asarray(
            [weights.get(s, 0.0) for s in universe],
            dtype=_np.float64,
        )
        w_cur = _np.asarray(
            [current_positions_usd.get(s, 0.0) / self._capital for s in universe],
            dtype=_np.float64,
        )
        # Identity covariance is a concentration regularizer, not a risk model.
        # Replace it only when an intraday covariance estimate is available.
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
            # Preserve solver failure in status even when closed-form fallback succeeds.
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
            v = round_cents(float(w.value[i]) * self._capital)
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
    "UnvalidatedSolverPlatformError",
    "round_cents",
]
