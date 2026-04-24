"""``CrossSectionalRanker`` — converts signals to standardized weights.

Phase-4 v0.2 behaviour
----------------------

For every symbol in ``ctx.universe`` with a non-``None`` signal, the
ranker produces a *raw alpha score*:

    raw[symbol] = sign(direction) * strength * f(edge_estimate_bps)

where ``sign`` is ``+1`` for ``LONG``, ``-1`` for ``SHORT``, and the
edge multiplier ``f`` is currently the identity (``edge_estimate_bps``
in basis points).  The output of ``rank`` is a mapping
``symbol → standardized_weight`` cross-sectionally z-scored across the
universe and clipped to ``[-clip, +clip]`` (default ``clip=4.0``).

Phase-4.1 v0.3 decay weighting (§20.4.1)
----------------------------------------

When ``decay_weighting_enabled=True`` the raw score is multiplied by
``exp(-Δt / expected_half_life_seconds)`` where ``Δt`` is the
event-time age of the signal at barrier close.  Signals whose
``expected_half_life_seconds == 0`` (legacy / unspecified) are
skipped (raw score retained).  Mechanism families known to be
exit-only (``LIQUIDITY_STRESS``) are forced to zero raw score on the
*entry* path; the hazard-exit path consumes them separately.

Mechanism concentration cap (Phase-4.1, §20.4.4)
------------------------------------------------

After standardization, weights of any single ``TrendMechanism``
family that exceeds ``mechanism_max_share_of_gross`` are scaled down
proportionally so the family's share of gross book equals the cap.
The reduction is reported on
:attr:`SizedPositionIntent.mechanism_breakdown`.

Determinism
-----------

* Iteration order over ``ctx.universe`` is the sorted tuple already
  guaranteed by the synchronizer.
* All numeric operations use Python ``float`` (IEEE-754).  No NumPy
  reductions whose order may differ across builds.  The standardizer
  uses an explicit sample mean and population standard deviation
  computed in the same iteration order on every replay.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Mapping

from feelies.core.events import (
    CrossSectionalContext,
    Signal,
    SignalDirection,
    TrendMechanism,
)

_logger = logging.getLogger(__name__)


# Mechanisms that may only be consumed on the *exit* path.  See §20.2:
# LIQUIDITY_STRESS is a hazard signal — entries are forbidden by Gate
# G16 rule 5 — but we still defend against malformed alphas slipping
# through validation.
_EXIT_ONLY_MECHANISMS: frozenset[TrendMechanism] = frozenset({
    TrendMechanism.LIQUIDITY_STRESS,
})


@dataclass(frozen=True)
class RankedAlpha:
    """Standardized cross-sectional weight + provenance per symbol."""

    symbol: str
    raw_score: float
    weight: float
    decay_factor: float
    mechanism: TrendMechanism | None
    signal: Signal


@dataclass(frozen=True)
class RankResult:
    """Output of :meth:`CrossSectionalRanker.rank`."""

    weights: dict[str, float]
    raw_scores: dict[str, float]
    decay_factors: dict[str, float]
    mechanism_by_symbol: dict[str, TrendMechanism] = field(
        default_factory=dict
    )
    # Gross share per mechanism family AFTER concentration cap.
    mechanism_breakdown: dict[TrendMechanism, float] = field(
        default_factory=dict
    )


class CrossSectionalRanker:
    """Standardize cross-sectional alpha scores deterministically.

    Parameters
    ----------
    clip :
        Symmetric clip on the standardized weight (default ``4.0``).
    decay_weighting_enabled :
        Phase-4.1 toggle (default ``False`` — pure v0.2 behaviour).
    decay_floor :
        Minimum decay multiplier (clamped to avoid divide-by-zero on
        very-old signals).  Default ``1e-6``.
    mechanism_max_share_of_gross :
        Phase-4.1 mechanism concentration cap in ``[0, 1]``.  Default
        ``1.0`` (disabled).  When ``< 1.0`` and any mechanism family
        accounts for more than the cap of total gross, the family's
        weights are scaled down proportionally.
    """

    __slots__ = (
        "_clip",
        "_decay_enabled",
        "_decay_floor",
        "_mech_cap",
    )

    def __init__(
        self,
        *,
        clip: float = 4.0,
        decay_weighting_enabled: bool = False,
        decay_floor: float = 1e-6,
        mechanism_max_share_of_gross: float = 1.0,
    ) -> None:
        if clip <= 0:
            raise ValueError(f"clip must be positive, got {clip}")
        if not 0.0 < decay_floor < 1.0:
            raise ValueError(
                f"decay_floor must be in (0, 1), got {decay_floor}"
            )
        if not 0.0 < mechanism_max_share_of_gross <= 1.0:
            raise ValueError(
                "mechanism_max_share_of_gross must be in (0, 1], "
                f"got {mechanism_max_share_of_gross}"
            )
        self._clip = float(clip)
        self._decay_enabled = bool(decay_weighting_enabled)
        self._decay_floor = float(decay_floor)
        self._mech_cap = float(mechanism_max_share_of_gross)

    # ── Public API ───────────────────────────────────────────────────

    def rank(self, ctx: CrossSectionalContext) -> RankResult:
        """Rank ``ctx``; return :class:`RankResult`.

        Symbols with ``signals_by_symbol[symbol] is None`` produce
        ``weights[symbol] = 0.0`` (hold existing position).
        """
        raw_scores: dict[str, float] = {}
        decay_factors: dict[str, float] = {}
        mechanism_by_symbol: dict[str, TrendMechanism] = {}
        active: set[str] = set()

        for symbol in ctx.universe:
            sig = ctx.signals_by_symbol.get(symbol)
            if sig is None:
                raw_scores[symbol] = 0.0
                decay_factors[symbol] = 0.0
                continue

            mech = sig.trend_mechanism
            if mech is not None:
                mechanism_by_symbol[symbol] = mech

            if mech in _EXIT_ONLY_MECHANISMS:
                raw_scores[symbol] = 0.0
                decay_factors[symbol] = 0.0
                continue

            sign = self._direction_to_sign(sig.direction)
            raw = sign * sig.strength * sig.edge_estimate_bps
            decay = 1.0
            if self._decay_enabled and sig.expected_half_life_seconds > 0:
                age_ns = max(0, ctx.timestamp_ns - sig.timestamp_ns)
                age_s = age_ns / 1e9
                hl = float(sig.expected_half_life_seconds)
                # exp(-Δt / hl) ∈ (0, 1]; floor for numerical stability.
                decay = max(self._decay_floor, math.exp(-age_s / hl))
                raw *= decay

            raw_scores[symbol] = raw
            decay_factors[symbol] = decay
            active.add(symbol)

        weights = self._standardize(raw_scores, ctx.universe, active)

        # Apply mechanism-concentration cap (Phase 4.1).
        weights, breakdown = self._apply_mechanism_cap(
            weights, mechanism_by_symbol,
        )
        return RankResult(
            weights=weights,
            raw_scores=raw_scores,
            decay_factors=decay_factors,
            mechanism_by_symbol=mechanism_by_symbol,
            mechanism_breakdown=breakdown,
        )

    # ── Internals ────────────────────────────────────────────────────

    @staticmethod
    def _direction_to_sign(direction: SignalDirection) -> float:
        if direction is SignalDirection.LONG:
            return 1.0
        if direction is SignalDirection.SHORT:
            return -1.0
        return 0.0

    def _standardize(
        self,
        raw_scores: Mapping[str, float],
        universe: tuple[str, ...],
        active: set[str] | None = None,
    ) -> dict[str, float]:
        """Z-score raw scores cross-sectionally; clip to ±self._clip.

        ``active`` is the subset of symbols with a non-``None`` signal
        contributing to the standardization.  Symbols absent from
        ``active`` are emitted with ``weight = 0.0`` (hold existing
        position).  The standardization moments (mean, std) are
        computed over ``active`` only — adding zero-imputed missing
        symbols would silently bias the cross-section away from the
        "hold" interpretation.

        Uses sample mean and *population* std; if std == 0 (everyone
        equal or only zeros), returns zeros.
        """
        n = len(universe)
        if n == 0:
            return {}
        if active is None:
            active = set(universe)
        active_universe = [s for s in universe if s in active]
        out: dict[str, float] = {s: 0.0 for s in universe}
        m = len(active_universe)
        if m == 0:
            return out
        values = [raw_scores.get(s, 0.0) for s in active_universe]
        mean = sum(values) / m
        var = sum((v - mean) ** 2 for v in values) / m
        std = math.sqrt(var)
        if std == 0.0:
            return out
        clip = self._clip
        for s, v in zip(active_universe, values):
            z = (v - mean) / std
            if z > clip:
                z = clip
            elif z < -clip:
                z = -clip
            out[s] = z
        return out

    def _apply_mechanism_cap(
        self,
        weights: dict[str, float],
        mechanism_by_symbol: Mapping[str, TrendMechanism],
    ) -> tuple[dict[str, float], dict[TrendMechanism, float]]:
        """Cap each mechanism's gross share to ``mechanism_max_share_of_gross``."""
        gross_total = sum(abs(w) for w in weights.values())
        if gross_total <= 0.0:
            return weights, {}

        # Aggregate gross by mechanism.
        gross_by_mech: dict[TrendMechanism, float] = {}
        for symbol, w in weights.items():
            mech = mechanism_by_symbol.get(symbol)
            if mech is None:
                continue
            gross_by_mech[mech] = gross_by_mech.get(mech, 0.0) + abs(w)

        if self._mech_cap >= 1.0 or not gross_by_mech:
            # No cap → just report the breakdown unchanged.
            breakdown_unchanged: dict[TrendMechanism, float] = {
                m: g / gross_total for m, g in gross_by_mech.items()
            }
            return weights, breakdown_unchanged

        cap_share = self._mech_cap
        # Recursive scaling: each over-cap mechanism is scaled to exactly
        # the cap (using current gross_total).  Because scaling reduces
        # gross_total, we iterate until stable (max 5 iterations — the
        # cap is monotonically decreasing).
        scaled = dict(weights)
        for _ in range(5):
            cur_gross = sum(abs(w) for w in scaled.values())
            if cur_gross <= 0:
                break
            adjusted = False
            cur_by_mech: dict[TrendMechanism, float] = {}
            for symbol, w in scaled.items():
                mech = mechanism_by_symbol.get(symbol)
                if mech is None:
                    continue
                cur_by_mech[mech] = cur_by_mech.get(mech, 0.0) + abs(w)
            for mech, g in cur_by_mech.items():
                share = g / cur_gross
                if share <= cap_share:
                    continue
                # Scale this mechanism so its share == cap_share.  Solve
                # for ``s`` such that ``s * g / (cur_gross - g + s*g) ==
                # cap_share`` ⇒  s = cap_share * (cur_gross - g) /
                # ((1 - cap_share) * g).
                denom = (1.0 - cap_share) * g
                if denom <= 0:
                    continue
                s = cap_share * (cur_gross - g) / denom
                if s < 1.0:
                    for symbol, w in list(scaled.items()):
                        if mechanism_by_symbol.get(symbol) is mech:
                            scaled[symbol] = w * s
                    adjusted = True
            if not adjusted:
                break

        new_gross = sum(abs(w) for w in scaled.values())
        breakdown: dict[TrendMechanism, float] = {}
        if new_gross > 0:
            new_by_mech: dict[TrendMechanism, float] = {}
            for symbol, w in scaled.items():
                mech = mechanism_by_symbol.get(symbol)
                if mech is None:
                    continue
                new_by_mech[mech] = new_by_mech.get(mech, 0.0) + abs(w)
            breakdown = {m: g / new_gross for m, g in new_by_mech.items()}
        return scaled, breakdown


__all__ = ["CrossSectionalRanker", "RankResult", "RankedAlpha"]
