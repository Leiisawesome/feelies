"""Stage-0 residual measurement — the Stage-1 GO/NO-GO decision engine.

Implements the frozen decision rules of
``docs/research/stage0_residual_preregistration.md`` (design rev 5 §2.1, §2.3,
§2.8, §3.5, §4.2; staging law Inv-3 / Inv-4).  The staging law permits Stage 1
(the :math:`P^{\\mathrm{story}}` map + mercy cell) **only** once Stage 0 is shown
to leave a costly residual; this module decides whether that has been shown.

Two populations are decomposed from the ``open ∧ safe-OFF ∧ ¬caps``
subpopulation, per the pre-registration §5.5:

* **(a) WRONG HOLDS** — episodes where holding to the cap was worse than
  flattening at gate-OFF.  Judged on the **conditional left tail**, never the
  mean (§2.1): a mean-PnL comparison hides exactly the failure mode where
  hold-through is conditionally correlated with the flagged regime transition.
* **(b) MISSED EARLY STORY-DEATH** — the only population that motivates Stage 1.
  Bounded by a **hindsight-optimal exit**, which is the *ceiling* on what any
  causal story map could earn before its own noise and turnover costs.

The primary ceiling restricts the oracle to the alpha's own decision cadence
(horizon boundaries): uplift available only *between* boundaries is not
addressable by a map that is evaluated at boundaries, so counting it would
inflate the ceiling with timing luck no implementation could capture.  The
event-time oracle is carried alongside as a diagnostic on how much of the
apparent ceiling is exactly that.

Everything here is pure and deterministic (Inv-5): same episodes → identical
verdict.  Nothing in this module reads market data, and no threshold is derived
from the data it judges — the bars come from the pre-registration and from the
locked platform gate thresholds.

**An under-powered cell returns UNDERPOWERED, never GO.**  Design §3.5 makes an
un-powerable falsifier a promotion blocker rather than a default-accept; the
same logic runs in the other direction here, so an under-powered null does not
falsify Claim B either.  It is an absence of evidence, and Inv-3 makes absence
of evidence block Stage 1 just as a rejection does.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from feelies.core.inv12_stress import INV12_COST_STRESS_MULTIPLIER
from feelies.research.decouple_gates import conditional_cvar, effective_tail_sample

__all__ = [
    "PILOT_CONFIGS",
    "PRE_REGISTERED_CVAR_LEVEL",
    "PRE_REGISTERED_MIN_TAIL_SAMPLE",
    "PilotConfig",
    "SafeOffEpisode",
    "Stratum",
    "StratumResult",
    "StudyResult",
    "Verdict",
    "evaluate_stratum",
    "evaluate_study",
]


# ─────────────────────────────────────────────────────────────────────
#   Frozen pre-registered constants
# ─────────────────────────────────────────────────────────────────────

#: Pre-registered left-tail fraction (pre-registration §5.3).  Fixed in advance
#: and deliberately **not** widenable to reach the power floor: a larger level
#: halves the episodes needed for power, which is the cheapest way to fake it.
PRE_REGISTERED_CVAR_LEVEL: float = 0.05

#: Minimum distinct-episode tail sample per stratum (pre-registration §6).
#: Deliberately the locked platform value
#: (``GateThresholds.decouple_cvar_min_tail_sample``) so the measurement cannot
#: pass on a laxer private bar than the promotion gate it feeds.
PRE_REGISTERED_MIN_TAIL_SAMPLE: int = 20

#: B2 margin: the hindsight ceiling must clear this multiple of the pilot's
#: Inv-12-stressed round-trip cost.  Mirrors the platform's own cost-realism
#: margin (Inv-12: ``expected_edge > 1.5 × round_trip_cost``) — a causal map
#: captures only a fraction of a hindsight ceiling and pays for its own false
#: exits, so this is the weakest condition under which a realistic map could
#: survive.  Numerically equal to the Inv-12 *cost stress* multiplier but a
#: distinct constant: one is a pre-registered bar, the other a locked platform
#: fill-model parameter, and they must be free to move independently.
B2_CEILING_COST_MULTIPLE: float = 1.5

#: Tolerance for the oracle feasible-set orderings on
#: :class:`SafeOffEpisode`, in bps.  Absorbs float round-tripping in the
#: extraction without masking a real sign error.
_FEASIBILITY_TOL: float = 1e-9

#: B3 margin: perfect-foresight harvest must be at least this multiple of the
#: total damage done by wrong holds.  A real map cannot separate (a) from (b)
#: cleanly — it holds and exits on the same latent state — so a 2:1 margin is
#: the minimum under which a map misclassifying a third of cases still nets out
#: positive.
B3_HARVEST_DAMAGE_MULTIPLE: float = 2.0


class Stratum(Enum):
    """OFF-trigger cause.  Stratification is mandatory (pre-registration §5.4).

    The primary pilot's gate fires on *schedule expiry* as well as on a vol
    breakout.  Those populations are not exchangeable: pooling a benign expiry
    majority with a toxic weather minority can hide the very tail §2.1 is
    about, so every statistic is reported per stratum and the power floor
    applies per stratum.
    """

    #: OFF driven by a genuine latent-state trigger (vol breakout, spread
    #: blow-out, regime-posterior collapse).  Where §2.1's risk lives.
    WEATHER = "weather"
    #: OFF driven purely by deterministic schedule expiry (window closed, or
    #: too little time left in it).  No weather event occurred.
    EXPIRY = "expiry"


class Verdict(Enum):
    """Stage-1 decision.  ``UNDERPOWERED`` is not a GO and not a NO-GO."""

    GO = "GO"
    NO_GO = "NO_GO"
    UNDERPOWERED = "UNDERPOWERED"


@dataclass(frozen=True, kw_only=True, slots=True)
class PilotConfig:
    """A pilot alpha's frozen measurement configuration (pre-registration §3).

    Every field is *derived* from platform constants rather than chosen, so
    there is no free parameter to tune toward a residual:
    ``max_hold_after_safe_off`` is the per-family legal ceiling
    (``_FAMILY_MAX_HOLD_HALF_LIFE_MULTIPLE × expected_half_life_seconds``) and
    ``hard_exit_age_seconds`` is ``horizon_seconds + max_hold_after_safe_off``.
    """

    alpha_id: str
    family: str
    expected_half_life_seconds: int
    horizon_seconds: int
    max_hold_after_safe_off: int
    hard_exit_age_seconds: int
    one_way_cost_bps: float

    @property
    def round_trip_cost_bps(self) -> float:
        """Unstressed round-trip cost — two crossings of the one-way cost."""
        return 2.0 * self.one_way_cost_bps

    @property
    def stressed_round_trip_cost_bps(self) -> float:
        """Round-trip cost under the locked Inv-12 1.5× cost stress."""
        return INV12_COST_STRESS_MULTIPLIER * self.round_trip_cost_bps

    @property
    def b2_bar_bps(self) -> float:
        """The B2 bar: hindsight ceiling must clear 1.5× the stressed round-trip."""
        return B2_CEILING_COST_MULTIPLE * self.stressed_round_trip_cost_bps

    @property
    def evaluation_window_seconds(self) -> int:
        """Common scoring window from first ``safe→OFF`` (pre-registration §5.2)."""
        return self.max_hold_after_safe_off + self.horizon_seconds

    @property
    def horizon_bars(self) -> int:
        """Evaluation window expressed in the alpha's own horizon boundaries."""
        return self.evaluation_window_seconds // self.horizon_seconds


#: The two pre-registered pilots (pre-registration §2.1, §3.1, §3.2).  Frozen —
#: swapping the pilot set after seeing results is multiple testing without a
#: ledger, which §8.7 forbids.
PILOT_CONFIGS: dict[str, PilotConfig] = {
    "sig_moc_imbalance_v1": PilotConfig(
        alpha_id="sig_moc_imbalance_v1",
        family="SCHEDULED_FLOW",
        expected_half_life_seconds=240,
        horizon_seconds=120,
        max_hold_after_safe_off=480,  # 2 × 240, the SCHEDULED_FLOW legal ceiling
        hard_exit_age_seconds=600,  # 120 + 480
        one_way_cost_bps=6.0,  # 2.5 half-spread + 2.5 impact + 1.0 fee
    ),
    "sig_kyle_drift_v1": PilotConfig(
        alpha_id="sig_kyle_drift_v1",
        family="KYLE_INFO",
        expected_half_life_seconds=600,
        horizon_seconds=300,
        max_hold_after_safe_off=1800,  # 3 × 600, the KYLE_INFO legal ceiling
        hard_exit_age_seconds=2100,  # 300 + 1800
        one_way_cost_bps=6.5,  # 2.5 half-spread + 3.0 impact + 1.0 fee
    ),
}


# ─────────────────────────────────────────────────────────────────────
#   Episode record
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class SafeOffEpisode:
    """One ``open ∧ safe-OFF ∧ ¬caps`` episode, scored under both arms.

    Both arms are replays of the **same event log** under two
    ``safety_exit_policy`` modes (Inv-5), so there is no sampling noise between
    them: every difference is attributable to the actuation policy.  All returns
    are in basis points on **modeled fills under ``--inv12-stress``** — never mid
    marks, because the deferral tail is realized in the stressed exit, which is
    exactly where mid marks flatter the hold.

    Attributes
    ----------
    hold_return_bps
        Arm H (``decouple_caps_only``) realized return over the common
        evaluation window.
    flatten_return_bps
        Arm F (``gate_close_flat``) realized return over the same window.
    oracle_boundary_bps
        Best return achievable by exiting at a **horizon boundary** within the
        deferral window, or at the arm-H cap exit.  The arm-H cap exit is in the
        feasible set by construction, so this is always ``>= hold_return_bps``.
        This is the PRIMARY ceiling — a story map decides at boundaries.
    oracle_event_bps
        Best return achievable by exiting at **any bus event** in the window.
        DIAGNOSTIC only: the gap to ``oracle_boundary_bps`` measures sub-cadence
        timing luck that no boundary-evaluated map can capture.
    terminal_cap
        Which cap actually ended the arm-H hold — one of
        ``MAX_HOLD_AFTER_SAFE_OFF`` / ``HARD_EXIT_AGE`` / ``SESSION_FLATTEN`` /
        ``STOP_LOSS``.  If the deferral ceiling rarely binds, Stage 0's deferral
        is largely inoperative and Stage 1 has nothing to sit on.
    quote_frozen
        Whether the episode hit a post-safety-OFF quote freeze and rode the
        event-time bound to ``session_flatten`` (design §2.3).
    """

    strategy_id: str
    symbol: str
    first_safe_off_ns: int
    off_trigger: str
    stratum: Stratum
    hold_return_bps: float
    flatten_return_bps: float
    oracle_boundary_bps: float
    oracle_event_bps: float
    terminal_cap: str
    quote_frozen: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("hold_return_bps", self.hold_return_bps),
            ("flatten_return_bps", self.flatten_return_bps),
            ("oracle_boundary_bps", self.oracle_boundary_bps),
            ("oracle_event_bps", self.oracle_event_bps),
        ):
            if not math.isfinite(value):
                raise ValueError(f"SafeOffEpisode.{name} must be finite, got {value}")
        # The oracle's feasible set contains the arm-H cap exit by construction,
        # so a negative uplift means the extraction is wrong — a silent sign
        # error here would understate the ceiling and manufacture a NO-GO.
        if self.oracle_boundary_bps < self.hold_return_bps - _FEASIBILITY_TOL:
            raise ValueError(
                f"oracle_boundary_bps ({self.oracle_boundary_bps}) < hold_return_bps "
                f"({self.hold_return_bps}); hold-until-cap is in the oracle's "
                "feasible set, so this indicates a broken episode extraction"
            )
        if self.oracle_event_bps < self.oracle_boundary_bps - _FEASIBILITY_TOL:
            raise ValueError(
                f"oracle_event_bps ({self.oracle_event_bps}) < oracle_boundary_bps "
                f"({self.oracle_boundary_bps}); the boundary exit set is a subset "
                "of the event exit set, so this indicates a broken extraction"
            )

    @property
    def delta_bps(self) -> float:
        """Arm H minus arm F — the deferral's realized effect on this episode."""
        return self.hold_return_bps - self.flatten_return_bps

    @property
    def uplift_boundary_bps(self) -> float:
        """Hindsight uplift over hold-until-cap at decision cadence (>= 0)."""
        return self.oracle_boundary_bps - self.hold_return_bps

    @property
    def uplift_event_bps(self) -> float:
        """Hindsight uplift over hold-until-cap at event granularity (>= 0)."""
        return self.oracle_event_bps - self.hold_return_bps

    @property
    def is_wrong_hold(self) -> bool:
        """Population (a) membership: holding was worse than flattening."""
        return self.delta_bps < 0.0


# ─────────────────────────────────────────────────────────────────────
#   Per-stratum evaluation
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class StratumResult:
    """Decomposition and verdict for one stratum of one pilot."""

    alpha_id: str
    stratum: Stratum
    subpopulation_size: int
    effective_tail_sample: int
    # Population (a) — wrong holds, judged on the conditional left tail.
    wrong_hold_count: int
    cvar_delta_bps: float
    mean_delta_bps: float
    total_wrong_hold_damage_bps: float
    # Population (b) — missed early story-death, bounded by hindsight.
    mean_uplift_boundary_bps: float
    total_uplift_boundary_bps: float
    mean_uplift_event_bps: float
    # Cap-binding and freeze diagnostics.
    terminal_cap_counts: dict[str, int]
    quote_freeze_count: int
    # Frozen bars, recorded so the report cannot drift from what was registered.
    b2_bar_bps: float
    # Gate outcomes.
    b1_powered: bool
    b2_ceiling_clears: bool
    b3_harvest_dominates: bool
    verdict: Verdict
    reasons: tuple[str, ...]

    @property
    def sub_cadence_share(self) -> float:
        """Fraction of the event-time ceiling unavailable at decision cadence.

        High values mean the apparent residual is timing luck between
        boundaries, which no boundary-evaluated story map can capture.
        """
        if self.mean_uplift_event_bps <= 0.0:
            return 0.0
        gap = self.mean_uplift_event_bps - self.mean_uplift_boundary_bps
        return gap / self.mean_uplift_event_bps


def evaluate_stratum(
    episodes: Sequence[SafeOffEpisode],
    *,
    pilot: PilotConfig,
    stratum: Stratum,
    level: float = PRE_REGISTERED_CVAR_LEVEL,
    min_tail_sample: int = PRE_REGISTERED_MIN_TAIL_SAMPLE,
    cvar_delta_by_path: Sequence[float] | None = None,
) -> StratumResult:
    """Decompose one stratum and apply the frozen B1/B2/B3 rules.

    Parameters
    ----------
    episodes
        Every ``open ∧ safe-OFF ∧ ¬caps`` episode in this stratum.
    pilot
        The pilot's frozen config; supplies the B2 bar.
    level, min_tail_sample
        Pre-registered CVaR level and power floor.  Defaulted to the frozen
        values; overridable only so tests can exercise the rules.
    cvar_delta_by_path
        Optional purged-CPCV per-path CVaR deltas.  When supplied, the reported
        ``cvar_delta_bps`` is their mean (the CPCV estimate, per §5.1); when
        omitted, the single-pass tail is used and the caller is responsible for
        noting that in the report.

    Rule order matters: power is checked **first**, so an under-powered cell can
    never reach the GO branch on a lucky tail.
    """
    if not (0.0 < level <= 1.0):
        raise ValueError(f"level must be in (0, 1], got {level}")
    if min_tail_sample < 0:
        raise ValueError(f"min_tail_sample must be >= 0, got {min_tail_sample}")
    for ep in episodes:
        if ep.stratum is not stratum:
            raise ValueError(
                f"episode {ep.symbol}@{ep.first_safe_off_ns} is in stratum "
                f"{ep.stratum.value}, not {stratum.value} — strata must not be "
                "pooled (pre-registration §5.4, §8.5)"
            )

    n = len(episodes)
    tail_sample = effective_tail_sample(n, level)

    deltas = [ep.delta_bps for ep in episodes]
    uplifts_boundary = [ep.uplift_boundary_bps for ep in episodes]
    uplifts_event = [ep.uplift_event_bps for ep in episodes]
    wrong_holds = [ep for ep in episodes if ep.is_wrong_hold]
    damage = math.fsum(-ep.delta_bps for ep in wrong_holds)

    if cvar_delta_by_path:
        cvar_delta = statistics.fmean(cvar_delta_by_path)
    elif n:
        cvar_delta = conditional_cvar(deltas, level)
    else:
        cvar_delta = 0.0

    mean_uplift_boundary = statistics.fmean(uplifts_boundary) if n else 0.0
    total_uplift_boundary = math.fsum(uplifts_boundary)
    mean_uplift_event = statistics.fmean(uplifts_event) if n else 0.0

    terminal_cap_counts: dict[str, int] = {}
    for ep in episodes:
        terminal_cap_counts[ep.terminal_cap] = terminal_cap_counts.get(ep.terminal_cap, 0) + 1

    b1 = tail_sample >= min_tail_sample
    b2 = mean_uplift_boundary >= pilot.b2_bar_bps
    b3 = total_uplift_boundary >= B3_HARVEST_DAMAGE_MULTIPLE * damage

    reasons: list[str] = []
    if not b1:
        verdict = Verdict.UNDERPOWERED
        reasons.append(
            f"B1 FAIL (power): effective tail sample {tail_sample} < {min_tail_sample} "
            f"required — {n} episodes in the cell, "
            f"{math.ceil(min_tail_sample / level)} needed. Not evidence either way."
        )
    elif mean_uplift_boundary <= 0.0:
        verdict = Verdict.NO_GO
        reasons.append(
            f"R1 REJECT: mean hindsight ceiling {mean_uplift_boundary:.3f} bps <= 0 — "
            "no residual even with perfect foresight, so no map can beat it."
        )
    elif total_uplift_boundary < damage:
        verdict = Verdict.NO_GO
        reasons.append(
            f"R2 REJECT: total harvest {total_uplift_boundary:.1f} bps < total wrong-hold "
            f"damage {damage:.1f} bps — the residual is smaller than what the deferral "
            "drags along."
        )
    elif b2 and b3:
        verdict = Verdict.GO
        reasons.append(
            f"B1/B2/B3 pass: ceiling {mean_uplift_boundary:.3f} >= {pilot.b2_bar_bps:.3f} bps "
            f"bar; harvest {total_uplift_boundary:.1f} >= "
            f"{B3_HARVEST_DAMAGE_MULTIPLE:.0f}× damage {damage:.1f} bps. "
            "Necessary, not sufficient — B4 and R3 are study-level."
        )
    else:
        verdict = Verdict.NO_GO
        reasons.append(
            f"R4 REJECT: powered but sub-threshold — "
            f"B2 {'pass' if b2 else 'FAIL'} (ceiling {mean_uplift_boundary:.3f} vs "
            f"{pilot.b2_bar_bps:.3f} bps bar), "
            f"B3 {'pass' if b3 else 'FAIL'} (harvest {total_uplift_boundary:.1f} vs "
            f"{B3_HARVEST_DAMAGE_MULTIPLE:.0f}× damage {damage:.1f} bps). "
            "A real but sub-threshold residual is not worth the machinery."
        )

    return StratumResult(
        alpha_id=pilot.alpha_id,
        stratum=stratum,
        subpopulation_size=n,
        effective_tail_sample=tail_sample,
        wrong_hold_count=len(wrong_holds),
        cvar_delta_bps=cvar_delta,
        mean_delta_bps=statistics.fmean(deltas) if n else 0.0,
        total_wrong_hold_damage_bps=damage,
        mean_uplift_boundary_bps=mean_uplift_boundary,
        total_uplift_boundary_bps=total_uplift_boundary,
        mean_uplift_event_bps=mean_uplift_event,
        terminal_cap_counts=terminal_cap_counts,
        quote_freeze_count=sum(1 for ep in episodes if ep.quote_frozen),
        b2_bar_bps=pilot.b2_bar_bps,
        b1_powered=b1,
        b2_ceiling_clears=b2,
        b3_harvest_dominates=b3,
        verdict=verdict,
        reasons=tuple(reasons),
    )


# ─────────────────────────────────────────────────────────────────────
#   Study-level verdict (cross-stratum rules B4 / R3)
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True, slots=True)
class StudyResult:
    """The pilot's overall Stage-1 verdict across strata."""

    alpha_id: str
    strata: tuple[StratumResult, ...]
    stage0_cvar_delta_bps: float
    b4_stage0_gate_passes: bool
    r3_latent_state_confound: bool
    verdict: Verdict
    reasons: tuple[str, ...]


def evaluate_study(
    strata: Sequence[StratumResult],
    *,
    pilot: PilotConfig,
    stage0_cvar_delta_bps: float,
    stage0_cvar_tolerance_bps: float = 0.0,
) -> StudyResult:
    """Apply the cross-stratum rules and return the pilot's verdict.

    Two rules live here rather than per stratum:

    **B4 — Stage-0's own gate must pass.**  If the bounded deferral fails its
    own conditional-CVaR gate, the remedy is falling back to
    ``gate_close_flat``, not layering a story map on a deferral that should not
    be running.  A story map cannot rescue a Stage 0 that fails its own gate.

    **R3 — the §2.1 latent-state confound.**  Fires when the WEATHER stratum's
    left tail is worse than the EXPIRY stratum's by more than one stressed
    round-trip cost (a smaller gap is not economically material).  That is *the
    reason we held is the reason we should have left*: a map keyed on the same
    latent state would hold precisely in the toxic cell, so this rejects the
    **premise** of mercy, not merely its size — and it does so regardless of how
    large the ceiling looks.

    R3 needs both strata powered to be computable; when only one stratum is
    present or powered it cannot fire, and its silence is recorded as such
    rather than read as a pass.
    """
    if not strata:
        raise ValueError("evaluate_study requires at least one stratum result")

    by_stratum = {s.stratum: s for s in strata}
    reasons: list[str] = []

    b4 = stage0_cvar_delta_bps >= -stage0_cvar_tolerance_bps
    if not b4:
        reasons.append(
            f"B4 FAIL: Stage-0's own CVaR gate fails (cvar_delta "
            f"{stage0_cvar_delta_bps:.3f} < -{stage0_cvar_tolerance_bps:.3f} bps). "
            "The remedy is gate_close_flat, not a story map on top."
        )

    weather = by_stratum.get(Stratum.WEATHER)
    expiry = by_stratum.get(Stratum.EXPIRY)
    r3 = False
    if weather is not None and expiry is not None and weather.b1_powered and expiry.b1_powered:
        materiality = pilot.stressed_round_trip_cost_bps
        gap = expiry.cvar_delta_bps - weather.cvar_delta_bps
        if gap > materiality:
            r3 = True
            reasons.append(
                f"R3 REJECT (§2.1 latent-state confound): weather-stratum tail "
                f"{weather.cvar_delta_bps:.3f} bps is worse than expiry-stratum "
                f"{expiry.cvar_delta_bps:.3f} bps by {gap:.3f} bps, exceeding the "
                f"{materiality:.3f} bps materiality quantum. The reason we held is the "
                "reason we should have left — this rejects the premise of mercy."
            )
    else:
        reasons.append(
            "R3 not computable: needs both WEATHER and EXPIRY strata powered. "
            "Its silence is not a pass."
        )

    powered = [s for s in strata if s.b1_powered]
    if not powered:
        verdict = Verdict.UNDERPOWERED
        reasons.append(
            "No stratum cleared the power floor — the study is UNDERPOWERED. "
            "That is not a GO: Inv-3 makes 'not shown' block Stage 1."
        )
    elif r3 or not b4:
        verdict = Verdict.NO_GO
    elif any(s.verdict is Verdict.GO for s in powered):
        verdict = Verdict.GO
        reasons.append(
            "At least one powered stratum cleared B1/B2/B3 with B4 passing and R3 not firing."
        )
    else:
        verdict = Verdict.NO_GO
        reasons.append(
            "No powered stratum cleared the residual bar. Per design §4.2 this is an "
            "expected outcome and a successful result: Claim A (bounded deferral) "
            "stands independently of Claim B."
        )

    for s in strata:
        reasons.extend(f"[{s.stratum.value}] {r}" for r in s.reasons)

    return StudyResult(
        alpha_id=pilot.alpha_id,
        strata=tuple(strata),
        stage0_cvar_delta_bps=stage0_cvar_delta_bps,
        b4_stage0_gate_passes=b4,
        r3_latent_state_confound=r3,
        verdict=verdict,
        reasons=tuple(reasons),
    )
