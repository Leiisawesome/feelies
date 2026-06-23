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
    EXIT_ONLY_MECHANISMS,
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
# Single source of truth lives in core.events (also consumed by the SIGNAL-
# layer runtime guardrail).  Re-exported under the historical private name.
_EXIT_ONLY_MECHANISMS: frozenset[TrendMechanism] = EXIT_ONLY_MECHANISMS


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
    mechanism_by_symbol: dict[str, TrendMechanism] = field(default_factory=dict)
    # Gross share per mechanism family AFTER concentration cap.
    mechanism_breakdown: dict[TrendMechanism, float] = field(default_factory=dict)


@dataclass(frozen=True)
class SleeveRankResult:
    """Per-mechanism standardized sleeves + combined provenance (audit P0-4).

    ``weights_by_mech`` maps each mechanism family to a standardized
    ``symbol -> weight`` vector built from *only* that family's signal
    contributions (a symbol fed by two families appears in both sleeves).
    The ``None`` key is the unattributed sleeve (signals with no declared
    mechanism); it participates in the book but is exempt from family caps
    and the breakdown.  ``raw_scores`` / ``decay_factors`` /
    ``mechanism_by_symbol`` are the *combined* per-symbol values (summed raw,
    min decay, largest-contribution family) carried for the decision hash.
    """

    weights_by_mech: dict[TrendMechanism | None, dict[str, float]]
    raw_scores: dict[str, float]
    decay_factors: dict[str, float]
    mechanism_by_symbol: dict[str, TrendMechanism] = field(default_factory=dict)


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
            raise ValueError(f"decay_floor must be in (0, 1), got {decay_floor}")
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

    def rank(
        self,
        ctx: CrossSectionalContext,
        *,
        feeder_strategy_ids: tuple[str, ...] = (),
        mechanism_caps: Mapping[TrendMechanism, float] | None = None,
        global_mechanism_cap: float | None = None,
        decay_weighting_enabled: bool | None = None,
        consumes_mechanisms: tuple[TrendMechanism, ...] | None = None,
    ) -> RankResult:
        """Rank ``ctx``; return :class:`RankResult`.

        When *feeder_strategy_ids* is non-empty and the synchronizer
        populated ``signals_by_strategy_by_symbol``, raw scores sum the
        marginal contribution of each upstream SIGNAL alpha (deterministic
        iteration order).  Otherwise the legacy single-slot
        ``signals_by_symbol`` path is used.

        *mechanism_caps* / *global_mechanism_cap* are the per-alpha
        ``trend_mechanism.consumes[*].max_share_of_gross`` and the global
        ``trend_mechanism.max_share_of_gross`` declared on the PORTFOLIO
        alpha YAML (audit P0-4).  When supplied they **override** the
        ranker's instance-level ``mechanism_max_share_of_gross`` for this
        call, so an alpha's declared caps are enforced at emit time
        (G16 rule 8) rather than only validated at load.  When omitted the
        instance default applies (back-compat).

        *decay_weighting_enabled* (audit P1-6) overrides the ranker's
        instance-level decay toggle **per call**, so the shared ranker can
        serve one PORTFOLIO alpha with decay ON and another with decay OFF
        without the global ``any(...)`` leakage.  ``None`` (default) uses
        the instance flag (back-compat).

        *consumes_mechanisms* is the PORTFOLIO alpha's declared
        ``trend_mechanism.consumes`` family whitelist (audit P0-6).  When
        non-empty, any consumed ``Signal`` whose ``trend_mechanism`` is a
        concrete family **outside** the whitelist is excluded fail-safe
        (its contribution is zeroed and it never enters the book), so an
        undeclared mechanism family cannot be traded at runtime.  ``None``
        or an empty tuple disables the filter (back-compat); a ``None``
        mechanism is always allowed (it declares no family to police —
        exit-only families are guarded separately).
        """
        caps = self._resolve_caps(mechanism_caps, global_mechanism_cap)
        decay_enabled = (
            self._decay_enabled if decay_weighting_enabled is None else bool(decay_weighting_enabled)
        )
        whitelist = frozenset(consumes_mechanisms) if consumes_mechanisms else None
        if feeder_strategy_ids and ctx.signals_by_strategy_by_symbol:
            return self._rank_multi_feeder(
                ctx, feeder_strategy_ids, caps, decay_enabled, whitelist
            )
        return self._rank_legacy(ctx, caps, decay_enabled, whitelist)

    @staticmethod
    def _is_allowed(
        mech: TrendMechanism | None,
        whitelist: frozenset[TrendMechanism] | None,
    ) -> bool:
        """``True`` when *mech* may enter the book under *whitelist* (P0-6)."""
        if whitelist is None or mech is None:
            return True
        return mech in whitelist

    def resolve_caps(
        self,
        mechanism_caps: Mapping[TrendMechanism, float] | None,
        global_mechanism_cap: float | None,
    ) -> tuple[dict[TrendMechanism, float], float]:
        """Public wrapper over :meth:`_resolve_caps` for sleeve capping.

        The composition engine resolves the same effective caps the ranker
        would, then applies them structurally to the per-family sleeves
        (audit P0-3/P0-4).
        """
        return self._resolve_caps(mechanism_caps, global_mechanism_cap)

    def rank_sleeves(
        self,
        ctx: CrossSectionalContext,
        *,
        feeder_strategy_ids: tuple[str, ...] = (),
        decay_weighting_enabled: bool | None = None,
        consumes_mechanisms: tuple[TrendMechanism, ...] | None = None,
    ) -> SleeveRankResult:
        """Standardize each mechanism family into its own sleeve (audit P0-4).

        Unlike :meth:`rank` (which standardizes the combined book and applies
        caps in-place), this partitions each symbol's signal contributions by
        mechanism family and z-scores each family over its *own* active
        symbols, so a symbol fed by two families splits across two sleeves.
        Capping is deferred to the engine (:func:`cap_family_vectors`) so it
        is enforced structurally on the combined book and at emit time.
        """
        decay_enabled = (
            self._decay_enabled if decay_weighting_enabled is None else bool(decay_weighting_enabled)
        )
        whitelist = frozenset(consumes_mechanisms) if consumes_mechanisms else None
        raw_by_mech, raw_scores, decay_factors, mechanism_by_symbol = self._gather_raw_by_mech(
            ctx,
            tuple(feeder_strategy_ids),
            decay_enabled,
            whitelist,
        )
        weights_by_mech: dict[TrendMechanism | None, dict[str, float]] = {}
        for mech, raw_map in raw_by_mech.items():
            weights_by_mech[mech] = self._standardize(raw_map, ctx.universe, set(raw_map))
        return SleeveRankResult(
            weights_by_mech=weights_by_mech,
            raw_scores=raw_scores,
            decay_factors=decay_factors,
            mechanism_by_symbol=mechanism_by_symbol,
        )

    def _raw_and_decay(
        self,
        sig: Signal,
        ctx: CrossSectionalContext,
        decay_enabled: bool,
    ) -> tuple[float, float]:
        """Signed raw score and decay multiplier for one *sig* at the barrier."""
        sign = self._direction_to_sign(sig.direction)
        raw = sign * sig.strength * sig.edge_estimate_bps
        decay = 1.0
        if decay_enabled and sig.expected_half_life_seconds > 0:
            age_ns = max(0, ctx.timestamp_ns - sig.timestamp_ns)
            age_s = age_ns / 1e9
            hl = float(sig.expected_half_life_seconds)
            decay = max(self._decay_floor, math.exp(-age_s / hl))
            raw *= decay
        return raw, decay

    def _gather_raw_by_mech(
        self,
        ctx: CrossSectionalContext,
        feeder_strategy_ids: tuple[str, ...],
        decay_enabled: bool,
        whitelist: frozenset[TrendMechanism] | None,
    ) -> tuple[
        dict[TrendMechanism | None, dict[str, float]],
        dict[str, float],
        dict[str, float],
        dict[str, TrendMechanism],
    ]:
        """Per-(family, symbol) signed raw contribution + combined provenance.

        Honours the consumes whitelist and the exit-only set (both drop a
        contribution), and aggregates per-family raw within a symbol when
        several feeders share a family.  ``None`` keys the unattributed
        sleeve.  The combined maps (summed raw, min decay, largest-|raw|
        family) feed the decision hash.
        """
        raw_by_mech: dict[TrendMechanism | None, dict[str, float]] = {}
        raw_scores: dict[str, float] = {}
        decay_factors: dict[str, float] = {}
        mechanism_by_symbol: dict[str, TrendMechanism] = {}
        use_multi = bool(feeder_strategy_ids) and bool(ctx.signals_by_strategy_by_symbol)

        for symbol in ctx.universe:
            contribs: list[tuple[TrendMechanism | None, float, float]] = []
            if use_multi:
                row = ctx.signals_by_strategy_by_symbol.get(symbol, {})
                for sid in feeder_strategy_ids:
                    sig = row.get(sid)
                    if sig is None:
                        continue
                    mech = sig.trend_mechanism
                    if not self._is_allowed(mech, whitelist) or mech in _EXIT_ONLY_MECHANISMS:
                        continue
                    raw, decay = self._raw_and_decay(sig, ctx, decay_enabled)
                    contribs.append((mech, raw, decay))
            else:
                sig = ctx.signals_by_symbol.get(symbol)
                if sig is not None:
                    mech = sig.trend_mechanism
                    if self._is_allowed(mech, whitelist) and mech not in _EXIT_ONLY_MECHANISMS:
                        raw, decay = self._raw_and_decay(sig, ctx, decay_enabled)
                        contribs.append((mech, raw, decay))

            if not contribs:
                raw_scores[symbol] = 0.0
                decay_factors[symbol] = 0.0
                continue

            local_raw: dict[TrendMechanism | None, float] = {}
            local_decay: dict[TrendMechanism | None, float] = {}
            for mech, raw, decay in contribs:
                local_raw[mech] = local_raw.get(mech, 0.0) + raw
                local_decay[mech] = min(local_decay.get(mech, 1.0), decay)
            for mech, raw in local_raw.items():
                raw_by_mech.setdefault(mech, {})[symbol] = raw
            raw_scores[symbol] = sum(local_raw.values())
            decay_factors[symbol] = min(local_decay.values())
            best_mech: TrendMechanism | None = None
            best_abs = -1.0
            for mech, raw in local_raw.items():
                if mech is None:
                    continue
                if abs(raw) > best_abs:
                    best_abs = abs(raw)
                    best_mech = mech
            if best_mech is not None:
                mechanism_by_symbol[symbol] = best_mech

        return raw_by_mech, raw_scores, decay_factors, mechanism_by_symbol

    def _resolve_caps(
        self,
        mechanism_caps: Mapping[TrendMechanism, float] | None,
        global_mechanism_cap: float | None,
    ) -> tuple[dict[TrendMechanism, float], float]:
        """Resolve effective per-family caps and a default cap for a call.

        The effective cap for a family is ``min(per_family_cap,
        global_cap)`` so neither the family-specific nor the global
        declaration can be exceeded; families with no explicit entry use
        the global (or instance) default.
        """
        default_cap = (
            float(global_mechanism_cap) if global_mechanism_cap is not None else self._mech_cap
        )
        per_family: dict[TrendMechanism, float] = {}
        if mechanism_caps:
            for mech, cap in mechanism_caps.items():
                per_family[mech] = min(float(cap), default_cap)
        return per_family, default_cap

    def _rank_legacy(
        self,
        ctx: CrossSectionalContext,
        caps: tuple[dict[TrendMechanism, float], float],
        decay_enabled: bool,
        whitelist: frozenset[TrendMechanism] | None = None,
    ) -> RankResult:
        """Single-signal-per-symbol ranking (pre–fan-in behaviour)."""
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
            if not self._is_allowed(mech, whitelist):
                # Undeclared mechanism family — exclude fail-safe (P0-6).
                _logger.debug(
                    "CrossSectionalRanker: excluding %s — mechanism %s outside consumes whitelist",
                    symbol,
                    mech.name if mech is not None else None,
                )
                raw_scores[symbol] = 0.0
                decay_factors[symbol] = 0.0
                continue
            if mech is not None:
                mechanism_by_symbol[symbol] = mech

            if mech in _EXIT_ONLY_MECHANISMS:
                raw_scores[symbol] = 0.0
                decay_factors[symbol] = 0.0
                continue

            sign = self._direction_to_sign(sig.direction)
            raw = sign * sig.strength * sig.edge_estimate_bps
            decay = 1.0
            if decay_enabled and sig.expected_half_life_seconds > 0:
                age_ns = max(0, ctx.timestamp_ns - sig.timestamp_ns)
                age_s = age_ns / 1e9
                hl = float(sig.expected_half_life_seconds)
                decay = max(self._decay_floor, math.exp(-age_s / hl))
                raw *= decay

            raw_scores[symbol] = raw
            decay_factors[symbol] = decay
            active.add(symbol)

        weights = self._standardize(raw_scores, ctx.universe, active)
        weights, breakdown = self._apply_mechanism_cap(
            weights,
            mechanism_by_symbol,
            caps,
        )
        return RankResult(
            weights=weights,
            raw_scores=raw_scores,
            decay_factors=decay_factors,
            mechanism_by_symbol=mechanism_by_symbol,
            mechanism_breakdown=breakdown,
        )

    def _rank_multi_feeder(
        self,
        ctx: CrossSectionalContext,
        feeder_strategy_ids: tuple[str, ...],
        caps: tuple[dict[TrendMechanism, float], float],
        decay_enabled: bool,
        whitelist: frozenset[TrendMechanism] | None = None,
    ) -> RankResult:
        """Aggregate ranked contribution across upstream SIGNAL alphas."""
        raw_scores: dict[str, float] = {}
        decay_factors: dict[str, float] = {}
        mechanism_by_symbol: dict[str, TrendMechanism] = {}
        active: set[str] = set()

        for symbol in ctx.universe:
            row = ctx.signals_by_strategy_by_symbol.get(symbol, {})
            raw_total = 0.0
            decay_track = 1.0
            best_abs = -1.0
            best_mech: TrendMechanism | None = None
            found_any_signal = False
            had_entry_eligible = False
            exit_only_mech: TrendMechanism | None = None

            for sid in feeder_strategy_ids:
                sig = row.get(sid)
                if sig is None:
                    continue
                found_any_signal = True
                mech = sig.trend_mechanism
                if not self._is_allowed(mech, whitelist):
                    # Undeclared family on this feeder — drop only this
                    # contribution; other feeders on the symbol stand (P0-6).
                    _logger.debug(
                        "CrossSectionalRanker: excluding %s feeder %s — "
                        "mechanism %s outside consumes whitelist",
                        symbol,
                        sid,
                        mech.name if mech is not None else None,
                    )
                    continue
                if mech in _EXIT_ONLY_MECHANISMS:
                    if mech is not None:
                        exit_only_mech = mech
                    continue

                had_entry_eligible = True
                sign = self._direction_to_sign(sig.direction)
                raw = sign * sig.strength * sig.edge_estimate_bps
                decay = 1.0
                if decay_enabled and sig.expected_half_life_seconds > 0:
                    age_ns = max(0, ctx.timestamp_ns - sig.timestamp_ns)
                    age_s = age_ns / 1e9
                    hl = float(sig.expected_half_life_seconds)
                    decay = max(self._decay_floor, math.exp(-age_s / hl))
                    raw *= decay

                raw_total += raw
                decay_track = min(decay_track, decay)
                contrib_abs = abs(raw)
                if contrib_abs > best_abs:
                    best_abs = contrib_abs
                    best_mech = mech

            if not found_any_signal:
                raw_scores[symbol] = 0.0
                decay_factors[symbol] = 0.0
                continue

            if not had_entry_eligible:
                raw_scores[symbol] = 0.0
                decay_factors[symbol] = 0.0
                if exit_only_mech is not None:
                    mechanism_by_symbol[symbol] = exit_only_mech
                continue

            raw_scores[symbol] = raw_total
            decay_factors[symbol] = decay_track
            if best_mech is not None:
                mechanism_by_symbol[symbol] = best_mech
            active.add(symbol)

        weights = self._standardize(raw_scores, ctx.universe, active)
        weights, breakdown = self._apply_mechanism_cap(
            weights,
            mechanism_by_symbol,
            caps,
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
        caps: tuple[dict[TrendMechanism, float], float],
    ) -> tuple[dict[str, float], dict[TrendMechanism, float]]:
        """Cap each mechanism's gross share to its effective per-family cap.

        *caps* is ``(per_family, default_cap)`` from :meth:`_resolve_caps`:
        a family's cap is ``per_family.get(mech, default_cap)``.  When no
        cap binds (all relevant caps ``>= 1.0``) the weights are returned
        unchanged and the breakdown is reported as-is.
        """
        per_family, default_cap = caps

        def cap_for(mech: TrendMechanism) -> float:
            return per_family.get(mech, default_cap)

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

        # No binding cap on any present family → report breakdown unchanged.
        if not gross_by_mech or all(cap_for(m) >= 1.0 for m in gross_by_mech):
            breakdown_unchanged: dict[TrendMechanism, float] = {
                m: g / gross_total for m, g in gross_by_mech.items()
            }
            return weights, breakdown_unchanged

        # Recursive scaling: each over-cap mechanism is scaled to exactly
        # its cap (using current gross_total).  Because scaling reduces
        # gross_total, we iterate until stable (max 5 iterations — every
        # family's share is monotonically decreasing).
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
                cap_share = cap_for(mech)
                if cap_share >= 1.0:
                    continue
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


def compute_mechanism_breakdown(
    gross_by_symbol: Mapping[str, float],
    mechanism_by_symbol: Mapping[str, TrendMechanism],
) -> dict[TrendMechanism, float]:
    """Realised gross-exposure share per mechanism family (audit P0-5).

    Computed from the *final* per-symbol signed exposures
    (``gross_by_symbol`` — typically ``intent.target_positions`` dollar
    targets) so the reported breakdown reflects the emitted book after
    neutralization / sector matching / optimization, not the ranker's
    pre-construction weights.  The denominator is total gross over *all*
    positions; the numerator for a family is the gross of the positions
    whose consumed signal carried that mechanism.
    """
    gross_total = sum(abs(v) for v in gross_by_symbol.values())
    if gross_total <= 0.0:
        return {}
    by_mech: dict[TrendMechanism, float] = {}
    for symbol, v in gross_by_symbol.items():
        mech = mechanism_by_symbol.get(symbol)
        if mech is None:
            continue
        by_mech[mech] = by_mech.get(mech, 0.0) + abs(v)
    return {m: g / gross_total for m, g in by_mech.items()}


def cap_family_vectors(
    vectors_by_mech: Mapping["TrendMechanism | None", Mapping[str, float]],
    caps: tuple[Mapping[TrendMechanism, float], float],
) -> tuple[dict["TrendMechanism | None", dict[str, float]], dict[TrendMechanism, float]]:
    """Scale per-family value vectors so each family's gross share ≤ its cap.

    *vectors_by_mech* maps a mechanism family (``None`` = unattributed) to a
    ``symbol -> signed value`` vector (weights or dollars).  A family's gross
    is ``Σ|value|`` over its symbols; the denominator is the total over all
    families.  Over-cap families are scaled down proportionally — iteratively,
    because scaling one family lowers the denominator — until stable (max 5
    passes; shares decrease monotonically).  The unattributed (``None``)
    family and families whose effective cap is ``>= 1.0`` are never scaled.

    Used for both the weight-space structural cap and the final dollar-space
    backstop (audit P0-3/P0-4).  Deterministic: families are processed in
    mechanism-name order.  Returns the scaled vectors and the realised
    per-(real)-family gross-share breakdown.
    """
    per_family, default_cap = caps

    def cap_for(mech: "TrendMechanism | None") -> float:
        if mech is None:
            return 1.0
        return per_family.get(mech, default_cap)

    scaled: dict[TrendMechanism | None, dict[str, float]] = {
        m: dict(v) for m, v in vectors_by_mech.items()
    }

    def gross_of(mech: "TrendMechanism | None") -> float:
        return sum(abs(x) for x in scaled[mech].values())

    real_mechs = sorted((m for m in scaled if m is not None), key=lambda m: m.name)
    for _ in range(5):
        cur_total = sum(gross_of(m) for m in scaled)
        if cur_total <= 0.0:
            break
        adjusted = False
        for mech in real_mechs:
            cap_share = cap_for(mech)
            if cap_share >= 1.0:
                continue
            g = gross_of(mech)
            if g <= 0.0 or g / cur_total <= cap_share:
                continue
            denom = (1.0 - cap_share) * g
            if denom <= 0.0:
                continue
            s = cap_share * (cur_total - g) / denom
            if s < 1.0:
                scaled[mech] = {sym: x * s for sym, x in scaled[mech].items()}
                adjusted = True
        if not adjusted:
            break

    new_total = sum(gross_of(m) for m in scaled)
    breakdown: dict[TrendMechanism, float] = {}
    if new_total > 0.0:
        for mech_key in scaled:
            if mech_key is None:
                continue
            g = gross_of(mech_key)
            if g > 0.0:
                breakdown[mech_key] = g / new_total
    return scaled, breakdown


def compute_sleeve_breakdown(
    gross_by_symbol: Mapping[str, float],
    weights_by_mech: Mapping["TrendMechanism | None", Mapping[str, float]],
) -> dict[TrendMechanism, float]:
    """Realised per-family gross share, splitting mixed symbols (audit P0-4).

    Each symbol's final gross (``|gross_by_symbol[s]|``) is attributed across
    the families that built it, in proportion to each family's ``|weight|``
    contribution to that symbol (so a 60/40 KYLE/INVENTORY symbol contributes
    0.6 / 0.4 of its gross to the two families).  The unattributed (``None``)
    family is counted in the denominator but never reported.
    """
    total = sum(abs(v) for v in gross_by_symbol.values())
    if total <= 0.0:
        return {}
    by_mech: dict[TrendMechanism, float] = {}
    for symbol, value in gross_by_symbol.items():
        denom = sum(abs(weights_by_mech[m].get(symbol, 0.0)) for m in weights_by_mech)
        if denom <= 0.0:
            continue
        for mech in weights_by_mech:
            if mech is None:
                continue
            wv = weights_by_mech[mech].get(symbol, 0.0)
            if wv == 0.0:
                continue
            by_mech[mech] = by_mech.get(mech, 0.0) + abs(value) * (abs(wv) / denom)
    return {m: g / total for m, g in by_mech.items()}


__all__ = [
    "CrossSectionalRanker",
    "RankResult",
    "RankedAlpha",
    "SleeveRankResult",
    "cap_family_vectors",
    "compute_mechanism_breakdown",
    "compute_sleeve_breakdown",
]
