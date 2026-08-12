"""Stage-0 ``decouple_caps_only`` promotion-gate harness (design rev 5 §3.5).

Builds the two *research-grade* falsifiers that gate an alpha's adoption of the
bounded-deferral ``decouple_caps_only`` safety-exit policy:

* :func:`build_conditional_cvar_evidence` — the conditional-CVaR left-tail
  comparison of *hold-until-cap* versus *flatten-on-gate-OFF* in the
  ``open ∧ safe-OFF ∧ ¬caps`` subpopulation, on **modeled fills under Inv-12
  stress**, estimated under **purged CPCV**, with a **minimum effective
  tail-sample** so an under-powered cell FAILs rather than passes.
* :func:`build_turnover_bound_evidence` — the realized round-trip comparison
  versus the flatten-on-gate-OFF baseline (Inv-12).

Both builders are pure and deterministic (Inv-5): same inputs → bit-identical
evidence.  The CPCV scaffolding is reused from :mod:`feelies.research.cpcv`; the
Inv-12 cost leg is applied through
:data:`~feelies.core.inv12_stress.INV12_COST_STRESS_MULTIPLIER` so the "modeled
fills under ``--inv12-stress``" contract is enforced by construction, not by the
caller's word.

The quote-freeze / session-backstop leg of the Stage-0 gate is post-trade
forensics and lives in :mod:`feelies.forensics.decouple_backstop`.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from feelies.promotion.evidence import (
    ConditionalCVaREvidence,
    TurnoverBoundEvidence,
)
from feelies.core.inv12_stress import (
    INV12_COST_STRESS_MULTIPLIER,
    INV12_LATENCY_STRESS_MULTIPLIER,
)
from feelies.research.cpcv import (
    CPCVConfig,
    CPCVSplit,
    assemble_path_returns,
    generate_cpcv_splits,
    reconstruct_paths,
)

__all__ = [
    "apply_inv12_cost_stress",
    "build_conditional_cvar_evidence",
    "build_turnover_bound_evidence",
    "conditional_cvar",
]


# ─────────────────────────────────────────────────────────────────────
#   Conditional CVaR (expected shortfall)
# ─────────────────────────────────────────────────────────────────────


def conditional_cvar(returns: Sequence[float], level: float) -> float:
    """Return the conditional CVaR (expected shortfall) at ``level``.

    The mean of the worst ``level`` fraction of ``returns`` — i.e. the average
    outcome in the left tail.  A loss-heavy tail yields a **negative** number;
    a higher (less negative) CVaR is a *better* tail.

    The tail count is ``max(1, ⌊level · n⌋)`` so the statistic is always defined
    for a non-empty series; the *power* of the estimate (whether ⌊level · n⌋
    clears the declared minimum) is judged separately by the gate validator via
    :attr:`ConditionalCVaREvidence.effective_tail_sample`.

    Raises ``ValueError`` for an empty series or ``level`` outside ``(0, 1]``.
    """
    if not (0.0 < level <= 1.0):
        raise ValueError(f"conditional_cvar level must be in (0, 1], got {level}")
    n = len(returns)
    if n == 0:
        raise ValueError("conditional_cvar requires a non-empty return series")
    tail_count = max(1, int(level * n))
    worst = sorted(float(r) for r in returns)[:tail_count]
    return statistics.fmean(worst)


def effective_tail_sample(subpopulation_size: int, level: float) -> int:
    """Distinct-episode tail sample ``⌊level · subpopulation_size⌋``.

    This is the *honest* power measure for a CPCV-estimated tail: it counts
    distinct subpopulation episodes in the α-tail and is therefore **not**
    inflated by CPCV path multiplicity (each episode recurs across many
    reconstructed paths but is one underlying observation).  The gate FAILs
    when this falls below the declared minimum.
    """
    if subpopulation_size < 0:
        raise ValueError(f"subpopulation_size must be >= 0, got {subpopulation_size}")
    if not (0.0 < level <= 1.0):
        raise ValueError(f"level must be in (0, 1], got {level}")
    return int(level * subpopulation_size)


# ─────────────────────────────────────────────────────────────────────
#   Inv-12 cost stress applied to per-episode returns
# ─────────────────────────────────────────────────────────────────────


def apply_inv12_cost_stress(
    gross_returns: Sequence[float],
    round_trip_costs: Sequence[float],
) -> tuple[float, ...]:
    """Return net per-episode returns after the Inv-12 cost stress.

    ``net = gross - 1.5 · round_trip_cost`` per episode
    (:data:`~feelies.core.inv12_stress.INV12_COST_STRESS_MULTIPLIER`).  Costs are
    in the same return units as ``gross_returns`` and must be non-negative (a
    round-trip cost is a charge, never a credit).

    This applies only the **cost** leg of Inv-12 stress.  The **latency** leg
    (2× fill latency) changes which fills happen and at what price, so it must
    already be reflected in ``gross_returns`` by the caller's fill model;
    :func:`build_conditional_cvar_evidence` records the latency multiplier as
    provenance and the gate validator enforces both legs.

    Raises ``ValueError`` on a length mismatch or a negative cost.
    """
    if len(gross_returns) != len(round_trip_costs):
        raise ValueError(
            f"gross_returns ({len(gross_returns)}) and round_trip_costs "
            f"({len(round_trip_costs)}) must be the same length"
        )
    out: list[float] = []
    for gross, cost in zip(gross_returns, round_trip_costs, strict=True):
        if cost < 0.0:
            raise ValueError(f"round_trip_cost must be >= 0, got {cost}")
        out.append(float(gross) - INV12_COST_STRESS_MULTIPLIER * float(cost))
    return tuple(out)


# ─────────────────────────────────────────────────────────────────────
#   CPCV path reconstruction for a single realized episode series
# ─────────────────────────────────────────────────────────────────────


def _reconstruct_policy_paths(
    net_returns: Sequence[float],
    *,
    config: CPCVConfig,
    splits: Sequence[CPCVSplit],
    paths: Sequence[Sequence[int]],
) -> tuple[tuple[float, ...], ...]:
    """Reconstruct full-length CPCV paths for one policy's episode returns.

    Uses the identity OOS projection (the realized per-episode return *is* the
    OOS observation for whichever split holds that episode in test) — the same
    scaffolding the PAPER→LIVE CPCV pipeline uses.  Purge/embargo shape the
    (unused) train side; the reconstructed OOS paths carry the realized tail
    the CVaR statistic is computed on.
    """
    test_returns_by_split = [[net_returns[i] for i in split.test_indices] for split in splits]
    return assemble_path_returns(
        n_bars=len(net_returns),
        n_groups=config.n_groups,
        splits=splits,
        test_returns_by_split=test_returns_by_split,
        paths=paths,
    )


# ─────────────────────────────────────────────────────────────────────
#   Conditional-CVaR evidence builder
# ─────────────────────────────────────────────────────────────────────


def build_conditional_cvar_evidence(
    *,
    config: CPCVConfig,
    hold_returns: Sequence[float],
    flatten_returns: Sequence[float],
    round_trip_costs: Sequence[float],
    level: float,
    horizon_bars: int,
) -> ConditionalCVaREvidence:
    """Build the powered conditional-CVaR falsifier (design rev 5 §3.5).

    Parameters
    ----------
    config
        CPCV hyperparameters.  The episode series is partitioned into
        ``config.n_groups`` contiguous groups; ``config.embargo_bars`` is
        recorded as the estimate's purge/embargo and must clear the gate floor.
    hold_returns, flatten_returns
        Per-episode **gross** returns over the ``open ∧ safe-OFF ∧ ¬caps``
        subpopulation, aligned by episode, under *hold-until-cap* and
        *flatten-on-gate-OFF* respectively.  Both MUST be computed on fills
        modeled at 2× latency (Inv-12); the 1.5× cost leg is applied here.
    round_trip_costs
        Per-episode round-trip cost (return units, non-negative), aligned by
        episode.  Applied to both policies via :func:`apply_inv12_cost_stress`.
    level
        Pre-registered left-tail fraction α (e.g. 0.05).
    horizon_bars
        Pre-registered PnL horizon (recorded as provenance).

    Returns
    -------
    ConditionalCVaREvidence
        With ``modeled_fills=True`` and the Inv-12 multipliers stamped from the
        locked constants.  The per-path CVaR deltas are recorded so the gate
        validator can detect a fabricated summary; ``effective_tail_sample`` is
        the distinct-episode tail count (the power measure).

    Determinism (Inv-5): same inputs → bit-identical evidence.
    """
    n = len(hold_returns)
    if len(flatten_returns) != n:
        raise ValueError(
            f"hold_returns ({n}) and flatten_returns ({len(flatten_returns)}) "
            "must be the same length"
        )
    if len(round_trip_costs) != n:
        raise ValueError(
            f"round_trip_costs ({len(round_trip_costs)}) must match the episode count ({n})"
        )
    if not (0.0 < level <= 1.0):
        raise ValueError(f"level must be in (0, 1], got {level}")
    if horizon_bars <= 0:
        raise ValueError(f"horizon_bars must be > 0, got {horizon_bars}")

    hold_net = apply_inv12_cost_stress(hold_returns, round_trip_costs)
    flatten_net = apply_inv12_cost_stress(flatten_returns, round_trip_costs)

    splits = generate_cpcv_splits(n, config)
    paths = reconstruct_paths(config.n_groups, config.k_test_groups, splits)
    hold_paths = _reconstruct_policy_paths(hold_net, config=config, splits=splits, paths=paths)
    flatten_paths = _reconstruct_policy_paths(
        flatten_net, config=config, splits=splits, paths=paths
    )

    hold_cvars = [conditional_cvar(p, level) for p in hold_paths]
    flatten_cvars = [conditional_cvar(p, level) for p in flatten_paths]
    path_deltas = tuple(h - f for h, f in zip(hold_cvars, flatten_cvars, strict=True))

    hold_cvar = statistics.fmean(hold_cvars)
    flatten_cvar = statistics.fmean(flatten_cvars)

    return ConditionalCVaREvidence(
        cvar_level=level,
        horizon_bars=horizon_bars,
        subpopulation_size=n,
        effective_tail_sample=effective_tail_sample(n, level),
        hold_cvar=hold_cvar,
        flatten_cvar=flatten_cvar,
        cvar_delta=hold_cvar - flatten_cvar,
        cpcv_fold_count=len(paths),
        cpcv_embargo_bars=config.embargo_bars,
        inv12_cost_multiplier=INV12_COST_STRESS_MULTIPLIER,
        inv12_latency_multiplier=float(INV12_LATENCY_STRESS_MULTIPLIER),
        modeled_fills=True,
        path_cvar_deltas=path_deltas,
    )


# ─────────────────────────────────────────────────────────────────────
#   Turnover-bound evidence builder
# ─────────────────────────────────────────────────────────────────────


def build_turnover_bound_evidence(
    *,
    baseline_round_trips: int,
    deferral_round_trips: int,
    declared_max_ratio: float,
    subpopulation_size: int,
) -> TurnoverBoundEvidence:
    """Build the turnover-bound falsifier (design rev 5 §2.7 / §3.5, Inv-12).

    ``observed_ratio = deferral_round_trips / baseline_round_trips``.  The gate
    (in :func:`~feelies.promotion.evidence.validate_turnover_bound`) rejects
    an alpha whose deferral churns beyond its ``declared_max_ratio`` — or whose
    declared bound itself exceeds the platform ceiling.

    Raises ``ValueError`` on negative counts or a non-positive baseline (no
    ratio is defined without a baseline round-trip).
    """
    if baseline_round_trips <= 0:
        raise ValueError(
            f"baseline_round_trips must be > 0 to form a ratio, got {baseline_round_trips}"
        )
    if deferral_round_trips < 0:
        raise ValueError(f"deferral_round_trips must be >= 0, got {deferral_round_trips}")
    observed_ratio = deferral_round_trips / baseline_round_trips
    return TurnoverBoundEvidence(
        baseline_round_trips=baseline_round_trips,
        deferral_round_trips=deferral_round_trips,
        declared_max_ratio=declared_max_ratio,
        observed_ratio=observed_ratio,
        subpopulation_size=subpopulation_size,
    )
