"""Typed promotion evidence, gate requirements, and threshold validators.

Evidence metadata is JSON-safe and used only for offline lifecycle decisions.
It never feeds the per-tick trading path. Capital tiers are evidence attached
to LIVE rather than additional lifecycle states.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from enum import Enum
from typing import Any, cast

from feelies.core.inv12_stress import (
    INV12_COST_STRESS_MULTIPLIER,
    INV12_LATENCY_STRESS_MULTIPLIER,
)

EVIDENCE_SCHEMA_VERSION = "1.0.0"

PROMOTE_CAPITAL_TIER_TRIGGER = "promote_capital_tier"
"""Stable trigger that distinguishes LIVE capital-tier escalations."""

AUTHORIZE_DECOUPLE_TRIGGER = "authorize_decouple_caps_only"
"""Stable trigger for the Stage-0 ``decouple_caps_only`` authorization.

Recorded as a ``LIVE -> LIVE`` self-loop (like
:data:`PROMOTE_CAPITAL_TIER_TRIGGER`) so the promotion ledger carries the
dual-permission Stage-0 gate outcome + config version without adding a
lifecycle state (design rev 5 §2.5 — human re-authorization is an opt-in
promotion recorded in the ledger)."""

# Small absolute tolerance for the Inv-12 stress-multiplier floor checks.  The
# harness stamps the multipliers from the locked constants, so this only guards
# against float-repr drift on round-trip through JSON, never a real shortfall.
_INV12_MULTIPLIER_TOL = 1e-9


# ─────────────────────────────────────────────────────────────────────
#   Capital-stage tier
# ─────────────────────────────────────────────────────────────────────


class CapitalStageTier(Enum):
    """Capital-allocation tiers recorded as evidence for a LIVE alpha."""

    SMALL_CAPITAL = "SMALL_CAPITAL"
    """Initial live deployment at ≤ 1% of target allocation, ≥ 10
    trading days minimum (testing-validation skill §"Promotion
    Pipeline")."""

    SCALED = "SCALED"
    """Full target allocation, ongoing.  Reachable from
    ``SMALL_CAPITAL`` only after PnL compression ratio remains in
    [0.5, 1.0] for the small-capital window with execution quality
    nominal."""


# ─────────────────────────────────────────────────────────────────────
#   Gate identifiers
# ─────────────────────────────────────────────────────────────────────


class GateId(Enum):
    """Stable identifiers for lifecycle evidence gates.

    Each gate covers exactly one ``(from_state, to_state)`` lifecycle
    transition (or, for ``LIVE_PROMOTE_CAPITAL_TIER``, the
    capital-tier escalation that does not change the lifecycle state).

    The gate matrix defines the evidence required for each transition.
    """

    RESEARCH_TO_PAPER = "research_to_paper"
    """RESEARCH → PAPER.  Pre-deployment acceptance criteria
    (testing-validation skill table §"Pre-Deployment Acceptance
    Criteria")."""

    PAPER_TO_LIVE = "paper_to_live"
    """PAPER → LIVE (initial small-capital deployment).  Requires
    paper-window divergence stats *plus* CPCV statistical-significance
    evidence *plus* DSR evidence."""

    LIVE_PROMOTE_CAPITAL_TIER = "live_promote_capital_tier"
    """LIVE @ SMALL_CAPITAL → LIVE @ SCALED self-transition."""

    LIVE_TO_QUARANTINED = "live_to_quarantined"
    """LIVE → QUARANTINED.  Quarantine is normally auto-triggered by
    the post-trade-forensics layer; the evidence captured here is
    *what tripped the trigger*, not a permission check."""

    QUARANTINED_TO_PAPER = "quarantined_to_paper"
    """QUARANTINED → PAPER (revalidation).  Requires hypothesis
    re-derivation, walk-forward OOS Sharpe, parameter-drift
    resolution, and an explicit human sign-off."""

    QUARANTINED_TO_DECOMMISSIONED = "quarantined_to_decommissioned"
    """QUARANTINED → DECOMMISSIONED (terminal retirement).  No
    structured evidence is required — the operator records a free-form
    reason on the lifecycle call."""

    DECOUPLE_CAPS_ONLY = "decouple_caps_only"
    """LIVE @ ``gate_close_flat`` → LIVE @ ``decouple_caps_only`` authorization
    (dual-permission Stage-0, design rev 5 §3.5).  Recorded as a ``LIVE -> LIVE``
    self-loop with :data:`AUTHORIZE_DECOUPLE_TRIGGER`.  Requires the powered
    conditional-CVaR falsifier, the turnover bound, and the quote-freeze /
    session-backstop check — a failing or under-powered gate blocks the
    promotion."""


# ─────────────────────────────────────────────────────────────────────
#   Evidence dataclasses
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class ResearchAcceptanceEvidence:
    """Pre-deployment acceptance evidence for RESEARCH → PAPER.

    Mirrors the testing-validation skill's pre-deployment table:
    schema validation, determinism, coverage, lookahead-bias check,
    fault-injection coverage, cost & latency sensitivity.
    """

    schema_valid: bool = False
    determinism_replay_passed: bool = False
    branch_coverage_pct: float = 0.0
    line_coverage_pct: float = 0.0
    lookahead_bias_check_passed: bool = False
    fault_injection_pass_count: int = 0
    fault_injection_total: int = 0
    cost_sensitivity_passed: bool = False
    """1.5x cost-assumption sensitivity gate (skill table)."""
    latency_sensitivity_passed: bool = False
    """2x latency-assumption sensitivity gate (skill table)."""


@dataclass(frozen=True, kw_only=True)
class CPCVEvidence:
    """Combinatorial purged cross-validation evidence.

    ``fold_count`` and ``fold_sharpes`` describe reconstructed full paths, not
    split combinations. The optional hash points to the heavier path-return
    artifact while this immutable record carries validation statistics.
    """

    fold_count: int = 0
    embargo_bars: int = 0
    fold_sharpes: tuple[float, ...] = ()
    mean_sharpe: float = 0.0
    median_sharpe: float = 0.0
    mean_pnl: float = 0.0
    p_value: float = 1.0
    fold_pnl_curves_hash: str = ""


@dataclass(frozen=True, kw_only=True)
class DSREvidence:
    """Deflated Sharpe evidence adjusted for trials and higher moments.

    Platform ``dsr`` is Sharpe excess ``observed - E[max]``. The canonical
    Bailey–López de Prado probability is ``1 - dsr_p_value``.
    """

    observed_sharpe: float = 0.0
    trials_count: int = 0
    skewness: float = 0.0
    kurtosis: float = 3.0
    """Default 3.0 = Gaussian kurtosis (Bailey/LdP convention)."""
    dsr: float = 0.0
    dsr_p_value: float = 1.0


@dataclass(frozen=True, kw_only=True)
class PaperWindowEvidence:
    """Paper-trading window divergence evidence for PAPER → LIVE.

    Captures the sim-vs-live divergence metrics from the
    testing-validation skill's "Sim-vs-live baseline" gate row, plus
    the trading-day count required by the promotion ladder.
    """

    trading_days: int = 0
    sample_size: int = 0
    """Number of paper trades observed in the window."""
    slippage_residual_bps: float = 0.0
    """Realised − expected slippage, basis points (skill §1)."""
    fill_rate_drift_pct: float = 0.0
    """Realised − expected fill rate, as a percentage of expected
    (skill §2)."""
    latency_ks_p: float = 1.0
    """KS-test p-value comparing measured latency to backtest-injected
    distribution (skill §"Sim-vs-live divergence")."""
    pnl_compression_ratio: float = 1.0
    """Live-PnL / backtest-PnL on the same paper window (skill
    §"Sim-vs-live divergence", row "PnL compression ratio")."""
    anomalous_event_count: int = 0
    """Count of per-day anomalies flagged by the forensic layer
    during the paper window (e.g. unexpected reject bursts)."""


@dataclass(frozen=True, kw_only=True)
class CapitalStageEvidence:
    """Capital-stage tier evidence for LIVE_PROMOTE_CAPITAL_TIER.

    Captures the realised execution quality during the small-capital
    deployment window and the realised PnL compression ratio that
    must remain in [0.5, 1.0] before promotion to ``SCALED``.
    """

    tier: CapitalStageTier = CapitalStageTier.SMALL_CAPITAL
    allocation_fraction: float = 0.0
    """Fraction of target allocation deployed during the window."""
    deployment_days: int = 0
    pnl_compression_ratio_realised: float = 1.0
    slippage_residual_bps: float = 0.0
    hit_rate_residual_pp: float = 0.0
    """Realised − expected hit rate, percentage points (skill §1)."""
    fill_rate_drift_pct: float = 0.0


@dataclass(frozen=True, kw_only=True)
class QuarantineTriggerEvidence:
    """Evidence that *triggered* a LIVE → QUARANTINED demotion.

    Recorded for forensics, not as a permission check (quarantine is
    auto-triggered).  The validators here flag inconsistent evidence
    (e.g. all metrics nominal yet a quarantine fired anyway) so the
    operator can investigate spurious triggers.
    """

    net_alpha_negative_days: int = 0
    """Consecutive trading days with realised net alpha < 0
    (post-trade-forensics §"Strategy Quarantine")."""
    hit_rate_residual_pp: float = 0.0
    """Realised − expected hit rate, percentage points; quarantine
    fires when this drops below ``-15pp`` with statistical
    significance (forensics skill §1)."""
    microstructure_metrics_breached: tuple[str, ...] = ()
    """Names of microstructure metrics whose alert thresholds were
    crossed in the trigger window (forensics skill §3)."""
    crowding_symptoms: tuple[str, ...] = ()
    """Crowding scorecard symptoms present (forensics skill §3
    "Edge Crowding Symptoms")."""
    pnl_compression_ratio_5d: float = 1.0
    """Five-day rolling PnL compression ratio at trigger time."""


@dataclass(frozen=True, kw_only=True)
class RevalidationEvidence:
    """Evidence supporting a QUARANTINED → PAPER re-entry.

    Per-skill (post-trade-forensics §"Hypothesis Revalidation"),
    re-entry requires the hypothesis to be re-derived from current
    market structure, walk-forward OOS validation, parameter-drift
    resolution, and an explicit human sign-off.
    """

    hypothesis_re_derived: bool = False
    oos_walkforward_sharpe: float = 0.0
    parameter_drift_resolved: bool = False
    human_signoff: str = ""
    """Identifier of the human (engineer / PM) who signed off."""
    revalidation_notes: str = ""
    """Free-form notes attached to the revalidation; may be empty
    only if a sign-off ID is supplied."""


# ─────────────────────────────────────────────────────────────────────
#   Stage-0 decouple_caps_only evidence (dual-permission design rev 5 §3.5)
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class ConditionalCVaREvidence:
    """Conditional-CVaR falsifier for ``decouple_caps_only`` promotion.

    Compares the conditional left tail of *hold-until-cap* against
    *flatten-on-gate-OFF* in the ``open ∧ safe-OFF ∧ ¬caps`` subpopulation
    (design rev 5 §2.1 / §3.5).  The gate passes only when holding through the
    flagged regime does **not** deepen the left tail beyond a tolerance.

    Estimation contract (all three are load-bearing — the validator rejects
    evidence that violates any of them):

    * **Modeled fills under Inv-12 stress.** ``hold_cvar`` / ``flatten_cvar``
      MUST be computed on modeled fills at 1.5× cost and 2× latency, not mid
      marks (:data:`~feelies.core.inv12_stress.INV12_COST_STRESS_MULTIPLIER` /
      ``INV12_LATENCY_STRESS_MULTIPLIER``).  ``modeled_fills`` records that the
      returns came from a fill model rather than mid quotes.
    * **Purged CPCV.** The tail is estimated over ``cpcv_fold_count``
      reconstructed CPCV paths with ``cpcv_embargo_bars`` purge/embargo, not a
      single in-sample tail.
    * **Powered.** ``effective_tail_sample`` is the count of *distinct*
      subpopulation episodes in the α-tail (``⌊cvar_level · subpopulation_size⌋``
      — not inflated by CPCV path multiplicity).  An under-powered cell is a
      FAIL, never a default-accept (design rev 5 §3.5).
    """

    cvar_level: float = 0.05
    """Pre-registered left-tail fraction α (e.g. 0.05 = worst 5%)."""
    horizon_bars: int = 0
    """Pre-registered PnL horizon over which each episode return is measured."""
    subpopulation_size: int = 0
    """Distinct ``open ∧ safe-OFF ∧ ¬caps`` episodes in the cell."""
    effective_tail_sample: int = 0
    """Distinct episodes in the α-tail (the power measure; see class docstring)."""
    hold_cvar: float = 0.0
    """Mean of the worst α-fraction of *hold-until-cap* returns (a loss ⇒ negative)."""
    flatten_cvar: float = 0.0
    """Mean of the worst α-fraction of *flatten-on-gate-OFF* returns."""
    cvar_delta: float = 0.0
    """``hold_cvar - flatten_cvar``; ``>= -tolerance`` ⇒ hold tail not worse."""
    cpcv_fold_count: int = 0
    """Reconstructed CPCV paths the tail was estimated over."""
    cpcv_embargo_bars: int = 0
    inv12_cost_multiplier: float = 1.0
    """Cost-stress multiplier applied to the fills (must be ≥ 1.5)."""
    inv12_latency_multiplier: float = 1.0
    """Fill-latency stress multiplier applied to the fills (must be ≥ 2)."""
    modeled_fills: bool = False
    """``True`` ⇒ returns came from modeled fills, not mid marks."""
    path_cvar_deltas: tuple[float, ...] = ()
    """Per-CPCV-path ``hold_cvar - flatten_cvar`` deltas; mean must equal
    ``cvar_delta`` (integrity check against a fabricated summary)."""


@dataclass(frozen=True, kw_only=True)
class TurnoverBoundEvidence:
    """Turnover-bound falsifier for ``decouple_caps_only`` promotion.

    The bounded deferral must not raise realized round-trips beyond a declared
    bound versus the ``flatten-on-gate-OFF`` baseline (design rev 5 §2.7 / §3.5;
    Inv-12).  Deferring an exit then re-entering can burn extra round-trips —
    the mirror image of the churn the decoupling is meant to reduce.
    """

    baseline_round_trips: int = 0
    """Realized round-trips under ``flatten-on-gate-OFF`` (must be > 0)."""
    deferral_round_trips: int = 0
    """Realized round-trips under ``hold-until-cap``."""
    declared_max_ratio: float = 1.0
    """Alpha-declared upper bound on ``deferral / baseline`` round-trips."""
    observed_ratio: float = 1.0
    """Measured ``deferral_round_trips / baseline_round_trips``."""
    subpopulation_size: int = 0
    """Episodes the turnover comparison was measured over (power)."""


@dataclass(frozen=True, kw_only=True)
class QuoteFreezeBackstopEvidence:
    """Quote-freeze / session-backstop check for ``decouple_caps_only``.

    Deferral deadlines are enforced in **event-time** (Inv-7); during a
    post-safety-OFF quote freeze the position may be held past the nominal
    ceiling until the next event, so ``session_flatten`` is the wall-clock
    backstop of last resort (design rev 5 §2.3 / §3.5).  This evidence proves
    that every frozen-quote episode still exits by ``session_flatten`` at latest
    — a stranded book past the session boundary is a defect, not a pass.
    """

    quote_freeze_episodes: int = 0
    """Episodes exercised with a post-safety-OFF quote freeze (must be ≥ 1)."""
    exited_by_session_flatten: int = 0
    """Freeze episodes that exited by the session-flatten backstop."""
    breached_session_backstop: int = 0
    """Freeze episodes still open past ``session_flatten`` (must be 0)."""
    session_flatten_bound_seconds: float = 0.0
    """The wall-clock session-flatten bound the episodes were checked against."""
    max_hold_seconds_observed: float = 0.0
    """Longest observed hold across the freeze episodes (must be ≤ the bound)."""


# ─────────────────────────────────────────────────────────────────────
#   Threshold configuration
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class GateThresholds:
    """Default acceptance thresholds for evidence validators.

    Defaults are derived from the testing-validation and
    post-trade-forensics skills.  Operators may override per-platform
    by constructing a :class:`GateThresholds` with custom values and
    passing it to the validator functions.

    All thresholds are positive numbers (or ``True``-valued booleans)
    interpreted as "evidence value must satisfy this".  See each
    validator's docstring for the exact pass condition.
    """

    # ── Research → Paper (pre-deployment acceptance) ──────────────
    research_min_branch_coverage_pct: float = 90.0
    """Branch coverage gate for risk + execution layers (skill table
    "Pre-Deployment Acceptance Criteria")."""
    research_min_line_coverage_pct: float = 80.0
    research_min_fault_injection_pass_pct: float = 100.0

    # ── Paper → Live(SMALL_CAPITAL) ────────────────────────────────
    paper_min_trading_days: int = 5
    """Minimum paper-window length (skill §"Promotion Pipeline")."""
    paper_min_sample_size: int = 0
    """Optional minimum trade count in the paper window."""
    paper_max_slippage_residual_bps: float = 1.5
    """Forensics §1 alert level — drop further before live."""
    paper_max_fill_rate_drift_pct: float = 10.0
    """Forensics §2 — passive fill-rate drift alert."""
    paper_min_latency_ks_p: float = 0.10
    """Skill §"Sim-vs-live divergence" — alert below 0.10."""
    paper_min_pnl_compression_ratio: float = 0.6
    """Skill alert threshold; promotion requires ≥ 0.6."""
    paper_max_pnl_compression_ratio: float = 1.2
    """Skill upper alert threshold (PnL > 1.2x backtest also flagged)."""
    paper_max_anomalous_events: int = 0

    # CPCV thresholds.
    cpcv_min_folds: int = 8
    """Minimum number of reconstructed CPCV **paths** (``C(N-1, k-1)``).
    Despite the field name, ``CPCVEvidence.fold_count`` carries the path
    count, not the combination count ``C(N, k)`` — see that field's
    docstring."""
    cpcv_min_mean_sharpe: float = 1.0
    """Minimum mean fold Sharpe.  Interpreted in the **same unit** the
    evidence was built with: pass ``annualization_factor=sqrt(252)`` to
    :func:`feelies.research.cpcv.build_cpcv_evidence` so this annualised
    default is commensurate with the annualised ``dsr_min``."""
    cpcv_max_p_value: float = 0.05
    cpcv_min_embargo_bars: int = 1
    """Minimum embargo (purge/embargo bars between train and test).  A
    zero-embargo CPCV run applies no serial-correlation guard at all, so
    promotion requires at least one bar by default."""

    # ── DSR ────────────────────────────────────────────────────────
    dsr_min: float = 1.0
    """Schema 1.1 falsification rule — ``DSR < 1.0`` is a kill
    criterion."""
    dsr_max_p_value: float = 0.05

    # ── Capital-stage tier (SMALL → SCALED) ───────────────────────
    small_min_deployment_days: int = 10
    small_min_pnl_compression_ratio: float = 0.5
    small_max_pnl_compression_ratio: float = 1.0
    small_max_slippage_residual_bps: float = 2.5
    """Forensics §1 escalation level — must remain below."""
    small_max_hit_rate_residual_pp: float = -5.0
    """Hit-rate residual *floor* — below this we don't promote.
    Stored as a negative number; pass condition is ``residual ≥ floor``."""
    small_max_fill_rate_drift_pct: float = 10.0

    # ── Quarantine triggers (consistency check, not permission) ───
    quarantine_max_net_alpha_negative_days: int = 10
    """Forensics §"Strategy Quarantine" — quarantine fires after 10
    consecutive negative-net-alpha days.  Used by the consistency
    validator: an evidence package marking *fewer* days plus *no*
    other triggers is suspicious."""
    quarantine_max_hit_rate_residual_pp: float = -15.0
    """Hit-rate collapse trigger from forensics §1."""
    quarantine_max_pnl_compression_ratio_5d: float = 0.3
    """Forensics row "Unexplained PnL divergence (live vs paper)"."""
    quarantine_min_microstructure_breaches: int = 2
    """Forensics §3 "Microstructure Regime Change" — 2+ metrics."""
    quarantine_min_crowding_symptoms: int = 3
    """Forensics §3 "Edge Crowding Symptoms" — 3+ symptoms."""

    # ── Revalidation (QUARANTINED → PAPER re-entry) ──────────────
    revalidation_min_oos_sharpe: float = 1.0

    # ── Stage-0 decouple_caps_only gates (design rev 5 §3.5) ──────
    decouple_cvar_max_level: float = 0.10
    """Max left-tail fraction α the CVaR gate accepts.  A "tail" wider than
    this is not a tail — a per-alpha override may only *lower* it."""
    decouple_cvar_min_tail_sample: int = 20
    """Minimum effective (distinct-episode) tail sample.  Below this the
    conditional-CVaR cell is under-powered and the gate FAILs (never a
    default-accept)."""
    decouple_cvar_tolerance: float = 0.0
    """Max amount by which *hold-until-cap* CVaR may fall below
    *flatten-on-gate-OFF* CVaR (in return units).  Default 0.0 = strict "not
    worse".  A per-alpha override may only *lower* it (tighten)."""
    decouple_cvar_min_folds: int = 8
    """Minimum reconstructed CPCV paths behind the conditional-CVaR estimate."""
    decouple_cvar_min_embargo_bars: int = 1
    """Minimum CPCV purge/embargo bars for the conditional-CVaR estimate."""
    decouple_turnover_ceiling_ratio: float = 1.5
    """Platform ceiling on an alpha's *declared* turnover bound — a decoupled
    alpha may not declare a looser deferral/baseline round-trip bound than
    this."""
    decouple_turnover_min_sample: int = 20
    """Minimum episodes behind the turnover comparison (power)."""
    decouple_quote_freeze_min_episodes: int = 1
    """Minimum quote-freeze episodes the session-backstop check must exercise —
    an empty check is not evidence."""


# ─────────────────────────────────────────────────────────────────────
#   Validators (pure functions, no side effects)
# ─────────────────────────────────────────────────────────────────────


def validate_research_acceptance(
    evidence: ResearchAcceptanceEvidence,
    thresholds: GateThresholds | None = None,
) -> list[str]:
    """Validate :class:`ResearchAcceptanceEvidence` against thresholds.

    Returns a list of human-readable error strings; the empty list
    signals "evidence is sufficient".  Pure function — no I/O, no
    state mutation.
    """
    t = thresholds or GateThresholds()
    errors: list[str] = []

    if not evidence.schema_valid:
        errors.append("schema validation has not passed")
    if not evidence.determinism_replay_passed:
        errors.append("determinism replay has not passed")
    if evidence.branch_coverage_pct < t.research_min_branch_coverage_pct:
        errors.append(
            f"branch coverage {evidence.branch_coverage_pct:.1f}% "
            f"< {t.research_min_branch_coverage_pct:.1f}% required"
        )
    if evidence.line_coverage_pct < t.research_min_line_coverage_pct:
        errors.append(
            f"line coverage {evidence.line_coverage_pct:.1f}% "
            f"< {t.research_min_line_coverage_pct:.1f}% required"
        )
    if not evidence.lookahead_bias_check_passed:
        errors.append("lookahead-bias check has not passed")
    if evidence.fault_injection_total <= 0:
        errors.append("no fault-injection cases run")
    else:
        pass_pct = 100.0 * evidence.fault_injection_pass_count / evidence.fault_injection_total
        if pass_pct < t.research_min_fault_injection_pass_pct:
            errors.append(
                f"fault-injection pass rate {pass_pct:.1f}% "
                f"< {t.research_min_fault_injection_pass_pct:.1f}% required"
            )
    if not evidence.cost_sensitivity_passed:
        errors.append("cost-sensitivity gate (1.5x) has not passed")
    if not evidence.latency_sensitivity_passed:
        errors.append("latency-sensitivity gate (2x) has not passed")

    return errors


def _is_well_formed_curve_hash(value: str) -> bool:
    """``True`` iff ``value`` is a ``sha256:<64 lowercase hex>`` pointer."""
    prefix = "sha256:"
    if not value.startswith(prefix):
        return False
    tail = value[len(prefix) :]
    return len(tail) == 64 and all(c in "0123456789abcdef" for c in tail)


def validate_cpcv(
    evidence: CPCVEvidence,
    thresholds: GateThresholds | None = None,
) -> list[str]:
    """Validate :class:`CPCVEvidence` against thresholds.

    Pass conditions:

    - enough paths (``fold_count >= cpcv_min_folds``) and a non-zero
      embargo (``embargo_bars >= cpcv_min_embargo_bars``);
    - ``mean_sharpe >= cpcv_min_mean_sharpe`` and
      ``p_value <= cpcv_max_p_value``;
    - **internal integrity** (the evidence is not trust-on-submit):
      ``len(fold_sharpes) == fold_count``, every fold Sharpe is finite,
      ``p_value`` lies in ``(0, 1]``, the reported ``mean_sharpe`` /
      ``median_sharpe`` actually match ``mean`` / ``median`` of
      ``fold_sharpes``, and any non-empty ``fold_pnl_curves_hash`` is a
      well-formed ``sha256:`` pointer.  These catch fabricated or
      drifted summary statistics that the threshold checks alone miss.
    """
    t = thresholds or GateThresholds()
    errors: list[str] = []

    if evidence.fold_count < t.cpcv_min_folds:
        errors.append(f"CPCV fold_count {evidence.fold_count} < {t.cpcv_min_folds} required")
    if evidence.fold_count > 0 and len(evidence.fold_sharpes) != evidence.fold_count:
        errors.append(
            f"CPCV inconsistent: fold_count={evidence.fold_count} but "
            f"{len(evidence.fold_sharpes)} fold_sharpes provided"
        )

    nonfinite = [s for s in evidence.fold_sharpes if not math.isfinite(s)]
    if nonfinite:
        errors.append(f"CPCV fold_sharpes contains non-finite values: {nonfinite}")
    elif evidence.fold_sharpes:
        # Recompute the summaries from fold_sharpes so a fabricated or
        # drifted mean/median cannot pass on the operator's word alone.
        recomputed_mean = statistics.fmean(evidence.fold_sharpes)
        if not math.isclose(evidence.mean_sharpe, recomputed_mean, rel_tol=1e-6, abs_tol=1e-9):
            errors.append(
                f"CPCV mean_sharpe {evidence.mean_sharpe:.4f} does not match "
                f"mean(fold_sharpes)={recomputed_mean:.4f} (fabricated/drifted summary?)"
            )
        recomputed_median = statistics.median(evidence.fold_sharpes)
        if not math.isclose(evidence.median_sharpe, recomputed_median, rel_tol=1e-6, abs_tol=1e-9):
            errors.append(
                f"CPCV median_sharpe {evidence.median_sharpe:.4f} does not match "
                f"median(fold_sharpes)={recomputed_median:.4f} (fabricated/drifted summary?)"
            )

    if evidence.mean_sharpe < t.cpcv_min_mean_sharpe:
        errors.append(
            f"CPCV mean Sharpe {evidence.mean_sharpe:.2f} < {t.cpcv_min_mean_sharpe:.2f} required"
        )
    if not (0.0 < evidence.p_value <= 1.0):
        errors.append(f"CPCV p_value {evidence.p_value} is outside (0, 1]")
    elif evidence.p_value > t.cpcv_max_p_value:
        errors.append(f"CPCV p-value {evidence.p_value:.4f} > {t.cpcv_max_p_value:.4f} threshold")
    if evidence.embargo_bars < t.cpcv_min_embargo_bars:
        errors.append(
            f"CPCV embargo_bars {evidence.embargo_bars} < {t.cpcv_min_embargo_bars} required "
            "(a zero-embargo run applies no serial-correlation guard)"
        )
    if evidence.fold_pnl_curves_hash and not _is_well_formed_curve_hash(
        evidence.fold_pnl_curves_hash
    ):
        errors.append(
            f"CPCV fold_pnl_curves_hash {evidence.fold_pnl_curves_hash!r} is malformed "
            "(expected 'sha256:' + 64 lowercase hex chars)"
        )

    return errors


def validate_dsr(
    evidence: DSREvidence,
    thresholds: GateThresholds | None = None,
) -> list[str]:
    """Validate :class:`DSREvidence` against thresholds.

    Pass conditions: DSR (a Sharpe *excess*) at or above threshold
    *and* DSR p-value at or below threshold *and* ``trials_count``
    recorded (a 0 trials count is suspicious — DSR's whole point is to
    deflate by trials).  Integrity checks additionally reject
    non-finite moments / DSR and a ``dsr_p_value`` outside ``[0, 1]``
    so a malformed package cannot pass on the operator's word alone.
    """
    t = thresholds or GateThresholds()
    errors: list[str] = []

    for name, value in (
        ("observed_sharpe", evidence.observed_sharpe),
        ("skewness", evidence.skewness),
        ("kurtosis", evidence.kurtosis),
        ("dsr", evidence.dsr),
        ("dsr_p_value", evidence.dsr_p_value),
    ):
        if not math.isfinite(value):
            errors.append(f"DSR {name} is non-finite ({value})")
    if not (0.0 <= evidence.dsr_p_value <= 1.0):
        errors.append(f"DSR dsr_p_value {evidence.dsr_p_value} is outside [0, 1]")

    if evidence.dsr < t.dsr_min:
        errors.append(
            f"DSR {evidence.dsr:.3f} < {t.dsr_min:.3f} required (schema-1.1 falsification rule)"
        )
    if evidence.dsr_p_value > t.dsr_max_p_value:
        errors.append(
            f"DSR p-value {evidence.dsr_p_value:.4f} > {t.dsr_max_p_value:.4f} threshold "
            f"(canonical Bailey-LdP DSR = 1 - p = {1.0 - evidence.dsr_p_value:.4f})"
        )
    if evidence.trials_count <= 0:
        errors.append(
            "DSR trials_count must be > 0 (DSR deflates by the number "
            "of variants explored — a zero trial count nullifies the "
            "deflation)"
        )

    return errors


def validate_paper_window(
    evidence: PaperWindowEvidence,
    thresholds: GateThresholds | None = None,
) -> list[str]:
    """Validate :class:`PaperWindowEvidence` against thresholds.

    Pass conditions cover the testing-validation skill's
    "Sim-vs-live baseline" gate row plus the promotion-pipeline
    paper-window minimums.
    """
    t = thresholds or GateThresholds()
    errors: list[str] = []

    if evidence.trading_days < t.paper_min_trading_days:
        errors.append(
            f"paper trading_days {evidence.trading_days} < {t.paper_min_trading_days} required"
        )
    if evidence.sample_size < t.paper_min_sample_size:
        errors.append(
            f"paper sample_size {evidence.sample_size} < {t.paper_min_sample_size} required"
        )
    if evidence.slippage_residual_bps > t.paper_max_slippage_residual_bps:
        errors.append(
            f"paper slippage residual {evidence.slippage_residual_bps:.2f} bps "
            f"> {t.paper_max_slippage_residual_bps:.2f} bps limit"
        )
    if abs(evidence.fill_rate_drift_pct) > t.paper_max_fill_rate_drift_pct:
        errors.append(
            f"paper fill-rate drift {evidence.fill_rate_drift_pct:.1f}% "
            f"exceeds ±{t.paper_max_fill_rate_drift_pct:.1f}% band"
        )
    if evidence.latency_ks_p < t.paper_min_latency_ks_p:
        errors.append(
            f"paper latency KS p-value {evidence.latency_ks_p:.4f} "
            f"< {t.paper_min_latency_ks_p:.4f} threshold "
            f"(latency distribution diverged)"
        )
    if evidence.pnl_compression_ratio < t.paper_min_pnl_compression_ratio:
        errors.append(
            f"paper PnL compression ratio {evidence.pnl_compression_ratio:.2f} "
            f"< {t.paper_min_pnl_compression_ratio:.2f} required"
        )
    if evidence.pnl_compression_ratio > t.paper_max_pnl_compression_ratio:
        errors.append(
            f"paper PnL compression ratio {evidence.pnl_compression_ratio:.2f} "
            f"> {t.paper_max_pnl_compression_ratio:.2f} upper alert "
            f"(unexpectedly large live outperformance is also a divergence)"
        )
    if evidence.anomalous_event_count > t.paper_max_anomalous_events:
        errors.append(
            f"paper window flagged {evidence.anomalous_event_count} "
            f"anomalous events (> {t.paper_max_anomalous_events} allowed)"
        )

    return errors


def validate_capital_stage(
    evidence: CapitalStageEvidence,
    thresholds: GateThresholds | None = None,
) -> list[str]:
    """Validate :class:`CapitalStageEvidence` for SMALL → SCALED escalation.

    Pass conditions enforce the testing-validation skill's
    "Small Capital" exit criteria: PnL compression ratio in
    [0.5, 1.0], deployment days ≥ 10, execution quality nominal
    (slippage residual at or below the forensic-skill escalation
    level, hit-rate residual at or above the floor, fill-rate drift
    within band).
    """
    t = thresholds or GateThresholds()
    errors: list[str] = []

    if evidence.deployment_days < t.small_min_deployment_days:
        errors.append(
            f"small-capital deployment_days {evidence.deployment_days} "
            f"< {t.small_min_deployment_days} required"
        )
    if evidence.pnl_compression_ratio_realised < t.small_min_pnl_compression_ratio:
        errors.append(
            f"small-capital realised PnL compression ratio "
            f"{evidence.pnl_compression_ratio_realised:.2f} "
            f"< {t.small_min_pnl_compression_ratio:.2f} required"
        )
    if evidence.pnl_compression_ratio_realised > t.small_max_pnl_compression_ratio:
        errors.append(
            f"small-capital realised PnL compression ratio "
            f"{evidence.pnl_compression_ratio_realised:.2f} "
            f"> {t.small_max_pnl_compression_ratio:.2f} upper alert"
        )
    if evidence.slippage_residual_bps > t.small_max_slippage_residual_bps:
        errors.append(
            f"small-capital slippage residual "
            f"{evidence.slippage_residual_bps:.2f} bps "
            f"> {t.small_max_slippage_residual_bps:.2f} bps limit"
        )
    if evidence.hit_rate_residual_pp < t.small_max_hit_rate_residual_pp:
        errors.append(
            f"small-capital hit-rate residual "
            f"{evidence.hit_rate_residual_pp:.1f}pp "
            f"< {t.small_max_hit_rate_residual_pp:.1f}pp floor"
        )
    if abs(evidence.fill_rate_drift_pct) > t.small_max_fill_rate_drift_pct:
        errors.append(
            f"small-capital fill-rate drift "
            f"{evidence.fill_rate_drift_pct:.1f}% "
            f"exceeds ±{t.small_max_fill_rate_drift_pct:.1f}% band"
        )
    if evidence.tier is not CapitalStageTier.SMALL_CAPITAL:
        errors.append(
            f"capital-stage promotion evidence must carry "
            f"tier=SMALL_CAPITAL (got {evidence.tier.value!r}) — "
            f"the SMALL→SCALED gate reads the *outgoing* tier"
        )

    return errors


def validate_quarantine_trigger(
    evidence: QuarantineTriggerEvidence,
    thresholds: GateThresholds | None = None,
) -> list[str]:
    """Validate :class:`QuarantineTriggerEvidence` for *consistency*.

    Quarantine is auto-triggered by the post-trade-forensics layer,
    so this validator does not gate the demotion.  Instead, it flags
    *spurious-looking* quarantine entries (none of the documented
    triggers reached its threshold) so operators can investigate
    false-positive triggers in the forensic layer.

    Returns errors only when *no* documented trigger crossed any
    threshold — that is the suspicious case ("why did we quarantine?").
    """
    t = thresholds or GateThresholds()

    triggered = evidence.net_alpha_negative_days >= t.quarantine_max_net_alpha_negative_days
    triggered = triggered or (
        evidence.hit_rate_residual_pp <= t.quarantine_max_hit_rate_residual_pp
    )
    triggered = triggered or (
        evidence.pnl_compression_ratio_5d <= t.quarantine_max_pnl_compression_ratio_5d
    )
    triggered = triggered or (
        len(evidence.microstructure_metrics_breached) >= t.quarantine_min_microstructure_breaches
    )
    triggered = triggered or (
        len(evidence.crowding_symptoms) >= t.quarantine_min_crowding_symptoms
    )

    if triggered:
        return []
    return [
        "quarantine trigger evidence is below every documented "
        "threshold — investigate spurious trigger "
        "(net_alpha_negative_days="
        f"{evidence.net_alpha_negative_days}, hit_rate_residual_pp="
        f"{evidence.hit_rate_residual_pp:.1f}, pnl_compression_5d="
        f"{evidence.pnl_compression_ratio_5d:.2f}, "
        f"microstructure_breaches={len(evidence.microstructure_metrics_breached)}, "
        f"crowding_symptoms={len(evidence.crowding_symptoms)})"
    ]


def validate_revalidation(
    evidence: RevalidationEvidence,
    thresholds: GateThresholds | None = None,
) -> list[str]:
    """Validate :class:`RevalidationEvidence` for QUARANTINED → PAPER.

    Pass conditions: hypothesis re-derived, OOS walk-forward Sharpe
    at or above threshold, parameter drift resolved, and a non-empty
    human sign-off identifier (revalidation notes are recommended but
    not strictly required when a sign-off is present).
    """
    t = thresholds or GateThresholds()
    errors: list[str] = []

    if not evidence.hypothesis_re_derived:
        errors.append("hypothesis has not been re-derived")
    if evidence.oos_walkforward_sharpe < t.revalidation_min_oos_sharpe:
        errors.append(
            f"OOS walk-forward Sharpe "
            f"{evidence.oos_walkforward_sharpe:.2f} "
            f"< {t.revalidation_min_oos_sharpe:.2f} required"
        )
    if not evidence.parameter_drift_resolved:
        errors.append("parameter drift has not been resolved")
    if not evidence.human_signoff.strip():
        errors.append("revalidation requires a non-empty human_signoff")

    return errors


def validate_conditional_cvar(
    evidence: ConditionalCVaREvidence,
    thresholds: GateThresholds | None = None,
) -> list[str]:
    """Validate :class:`ConditionalCVaREvidence` for ``decouple_caps_only``.

    Pass conditions (design rev 5 §3.5, "Conditional CVaR (mandatory, powered)"):

    - **modeled fills under Inv-12 stress** — ``modeled_fills`` set and the cost
      / latency multipliers at or above the locked 1.5× / 2× floors (a mid-mark
      or un-stressed estimate is refused);
    - **powered** — ``effective_tail_sample >= decouple_cvar_min_tail_sample``;
      an under-powered cell is a FAIL, not a pass;
    - **purged CPCV** — ``cpcv_fold_count`` and ``cpcv_embargo_bars`` at or above
      their floors;
    - **tail not worse** — ``cvar_delta >= -decouple_cvar_tolerance`` (holding
      through the flagged regime does not deepen the left tail);
    - **internal integrity** — ``cvar_level`` in ``(0, decouple_cvar_max_level]``,
      a positive horizon, ``effective_tail_sample`` equal to
      ``floor(cvar_level * subpopulation_size)`` (the honest power measure cannot
      be spoofed), all CVaR figures finite, ``cvar_delta`` matches
      ``hold - flatten`` and the mean of ``path_cvar_deltas``, and
      ``len(path_cvar_deltas)`` matches ``cpcv_fold_count`` whenever paths are
      claimed (catches a fabricated/drifted summary or omitted path evidence).
    """
    t = thresholds or GateThresholds()
    errors: list[str] = []

    # ── Integrity ────────────────────────────────────────────────
    if not (0.0 < evidence.cvar_level <= t.decouple_cvar_max_level):
        errors.append(
            f"CVaR level {evidence.cvar_level} outside (0, "
            f"{t.decouple_cvar_max_level}] — a tail wider than the ceiling is "
            "not a left tail"
        )
    if evidence.horizon_bars <= 0:
        errors.append(f"CVaR horizon_bars {evidence.horizon_bars} must be > 0")
    if evidence.subpopulation_size < 0:
        errors.append(f"CVaR subpopulation_size {evidence.subpopulation_size} must be >= 0")
    if evidence.effective_tail_sample < 0:
        errors.append(f"CVaR effective_tail_sample {evidence.effective_tail_sample} must be >= 0")
    if evidence.effective_tail_sample > evidence.subpopulation_size:
        errors.append(
            f"CVaR effective_tail_sample {evidence.effective_tail_sample} > "
            f"subpopulation_size {evidence.subpopulation_size} (impossible)"
        )
    if 0.0 < evidence.cvar_level <= 1.0 and evidence.subpopulation_size >= 0:
        expected_tail = int(evidence.cvar_level * evidence.subpopulation_size)
        if evidence.effective_tail_sample != expected_tail:
            errors.append(
                f"CVaR effective_tail_sample {evidence.effective_tail_sample} != "
                f"floor(cvar_level * subpopulation_size) = {expected_tail} "
                "(spoofed tail power?)"
            )
    for name, value in (
        ("hold_cvar", evidence.hold_cvar),
        ("flatten_cvar", evidence.flatten_cvar),
        ("cvar_delta", evidence.cvar_delta),
    ):
        if not math.isfinite(value):
            errors.append(f"CVaR {name} is non-finite ({value})")
    nonfinite = [d for d in evidence.path_cvar_deltas if not math.isfinite(d)]
    if nonfinite:
        errors.append(f"CVaR path_cvar_deltas contains non-finite values: {nonfinite}")
    else:
        if not math.isclose(
            evidence.cvar_delta,
            evidence.hold_cvar - evidence.flatten_cvar,
            rel_tol=1e-6,
            abs_tol=1e-12,
        ):
            errors.append(
                f"CVaR cvar_delta {evidence.cvar_delta} does not match "
                f"hold_cvar - flatten_cvar = {evidence.hold_cvar - evidence.flatten_cvar} "
                "(fabricated/drifted summary?)"
            )
        if evidence.path_cvar_deltas:
            recomputed = statistics.fmean(evidence.path_cvar_deltas)
            if not math.isclose(evidence.cvar_delta, recomputed, rel_tol=1e-6, abs_tol=1e-12):
                errors.append(
                    f"CVaR cvar_delta {evidence.cvar_delta} does not match "
                    f"mean(path_cvar_deltas)={recomputed} (fabricated/drifted summary?)"
                )
    if evidence.cpcv_fold_count > 0 and len(evidence.path_cvar_deltas) != evidence.cpcv_fold_count:
        errors.append(
            f"CVaR inconsistent: cpcv_fold_count={evidence.cpcv_fold_count} but "
            f"{len(evidence.path_cvar_deltas)} path_cvar_deltas provided"
        )

    # ── Modeled fills under Inv-12 stress (not mid marks) ─────────
    if not evidence.modeled_fills:
        errors.append(
            "CVaR must be estimated on modeled fills, not mid marks (modeled_fills is False)"
        )
    if evidence.inv12_cost_multiplier < INV12_COST_STRESS_MULTIPLIER - _INV12_MULTIPLIER_TOL:
        errors.append(
            f"CVaR inv12_cost_multiplier {evidence.inv12_cost_multiplier} < "
            f"{INV12_COST_STRESS_MULTIPLIER} required (Inv-12 cost stress)"
        )
    if evidence.inv12_latency_multiplier < INV12_LATENCY_STRESS_MULTIPLIER - _INV12_MULTIPLIER_TOL:
        errors.append(
            f"CVaR inv12_latency_multiplier {evidence.inv12_latency_multiplier} < "
            f"{INV12_LATENCY_STRESS_MULTIPLIER} required (Inv-12 latency stress)"
        )

    # ── Power: under-powered tail is a FAIL, never a default-accept ─
    if evidence.effective_tail_sample < t.decouple_cvar_min_tail_sample:
        errors.append(
            f"CVaR effective tail sample {evidence.effective_tail_sample} < "
            f"{t.decouple_cvar_min_tail_sample} required — the "
            "open∧safe-OFF∧¬caps cell is under-powered; the gate FAILs rather "
            "than default-accept (fall back to gate_close_flat)"
        )

    # ── Purged-CPCV requirements ─────────────────────────────────
    if evidence.cpcv_fold_count < t.decouple_cvar_min_folds:
        errors.append(
            f"CVaR cpcv_fold_count {evidence.cpcv_fold_count} < "
            f"{t.decouple_cvar_min_folds} required"
        )
    if evidence.cpcv_embargo_bars < t.decouple_cvar_min_embargo_bars:
        errors.append(
            f"CVaR cpcv_embargo_bars {evidence.cpcv_embargo_bars} < "
            f"{t.decouple_cvar_min_embargo_bars} required (a zero-embargo run "
            "applies no serial-correlation guard)"
        )

    # ── The gate: hold-until-cap left tail not worse than flatten ─
    if evidence.cvar_delta < -t.decouple_cvar_tolerance:
        errors.append(
            f"CVaR hold-until-cap left tail worse than flatten-on-gate-OFF: "
            f"cvar_delta {evidence.cvar_delta} < -{t.decouple_cvar_tolerance} "
            "tolerance (holding through the flagged regime deepens the tail)"
        )

    return errors


def validate_turnover_bound(
    evidence: TurnoverBoundEvidence,
    thresholds: GateThresholds | None = None,
) -> list[str]:
    """Validate :class:`TurnoverBoundEvidence` for ``decouple_caps_only``.

    Pass conditions (design rev 5 §3.5, "Turnover bound (mandatory)"):

    - a positive baseline (a ratio needs a non-zero denominator) and enough
      episodes to measure (``subpopulation_size >= decouple_turnover_min_sample``);
    - the alpha's *declared* bound is itself within the platform ceiling
      ``decouple_turnover_ceiling_ratio`` (an alpha cannot self-authorize an
      unbounded churn);
    - the *observed* ratio matches the round-trip counts and does not exceed the
      declared bound.
    """
    t = thresholds or GateThresholds()
    errors: list[str] = []

    if evidence.baseline_round_trips <= 0:
        errors.append(
            f"turnover baseline_round_trips {evidence.baseline_round_trips} must "
            "be > 0 to form a ratio"
        )
    if evidence.deferral_round_trips < 0:
        errors.append(
            f"turnover deferral_round_trips {evidence.deferral_round_trips} must be >= 0"
        )
    if evidence.subpopulation_size < t.decouple_turnover_min_sample:
        errors.append(
            f"turnover subpopulation_size {evidence.subpopulation_size} < "
            f"{t.decouple_turnover_min_sample} required (under-powered)"
        )
    if evidence.declared_max_ratio <= 0.0:
        errors.append(f"turnover declared_max_ratio {evidence.declared_max_ratio} must be > 0")
    elif evidence.declared_max_ratio > t.decouple_turnover_ceiling_ratio:
        errors.append(
            f"turnover declared_max_ratio {evidence.declared_max_ratio} > platform "
            f"ceiling {t.decouple_turnover_ceiling_ratio} (an alpha may not declare "
            "a looser round-trip bound than the platform allows)"
        )

    if evidence.baseline_round_trips > 0:
        recomputed = evidence.deferral_round_trips / evidence.baseline_round_trips
        if not math.isclose(evidence.observed_ratio, recomputed, rel_tol=1e-6, abs_tol=1e-12):
            errors.append(
                f"turnover observed_ratio {evidence.observed_ratio} does not match "
                f"deferral/baseline = {recomputed} (fabricated/drifted summary?)"
            )

    if evidence.observed_ratio > evidence.declared_max_ratio:
        errors.append(
            f"turnover observed_ratio {evidence.observed_ratio} > declared bound "
            f"{evidence.declared_max_ratio} — deferral churns beyond the declared "
            "round-trip bound (Inv-12)"
        )

    return errors


def validate_quote_freeze_backstop(
    evidence: QuoteFreezeBackstopEvidence,
    thresholds: GateThresholds | None = None,
) -> list[str]:
    """Validate :class:`QuoteFreezeBackstopEvidence` for ``decouple_caps_only``.

    Pass conditions (design rev 5 §2.3 / §3.5, quote-freeze backstop):

    - at least ``decouple_quote_freeze_min_episodes`` freeze episodes exercised
      (an empty check is not evidence);
    - a positive session-flatten bound, and every freeze episode exited by it —
      ``exited_by_session_flatten == quote_freeze_episodes`` with **zero**
      ``breached_session_backstop`` (a stranded book past ``session_flatten`` is
      a defect);
    - the longest observed hold is within the session-flatten bound.
    """
    t = thresholds or GateThresholds()
    errors: list[str] = []

    if evidence.quote_freeze_episodes < t.decouple_quote_freeze_min_episodes:
        errors.append(
            f"quote-freeze episodes {evidence.quote_freeze_episodes} < "
            f"{t.decouple_quote_freeze_min_episodes} required — the session "
            "backstop was not exercised"
        )
    if evidence.session_flatten_bound_seconds <= 0.0:
        errors.append(
            f"quote-freeze session_flatten_bound_seconds "
            f"{evidence.session_flatten_bound_seconds} must be > 0"
        )
    if evidence.breached_session_backstop > 0:
        errors.append(
            f"quote-freeze {evidence.breached_session_backstop} episode(s) still "
            "open past session_flatten — deferred book stranded past the wall-clock "
            "backstop (design §2.3 defect)"
        )
    if evidence.exited_by_session_flatten != evidence.quote_freeze_episodes:
        errors.append(
            f"quote-freeze only {evidence.exited_by_session_flatten} of "
            f"{evidence.quote_freeze_episodes} freeze episodes exited by "
            "session_flatten"
        )
    if evidence.max_hold_seconds_observed > evidence.session_flatten_bound_seconds:
        errors.append(
            f"quote-freeze max hold {evidence.max_hold_seconds_observed}s exceeds "
            f"session_flatten bound {evidence.session_flatten_bound_seconds}s"
        )

    return errors


# ─────────────────────────────────────────────────────────────────────
#   Gate matrix + top-level dispatcher
# ─────────────────────────────────────────────────────────────────────


_EvidenceType = type
"""Alias for the type-of-evidence-dataclass (used in the matrix)."""


GATE_EVIDENCE_REQUIREMENTS: Mapping[GateId, tuple[_EvidenceType, ...]] = {
    GateId.RESEARCH_TO_PAPER: (ResearchAcceptanceEvidence,),
    GateId.PAPER_TO_LIVE: (
        PaperWindowEvidence,
        CPCVEvidence,
        DSREvidence,
    ),
    GateId.LIVE_PROMOTE_CAPITAL_TIER: (CapitalStageEvidence,),
    GateId.LIVE_TO_QUARANTINED: (QuarantineTriggerEvidence,),
    GateId.QUARANTINED_TO_PAPER: (RevalidationEvidence,),
    GateId.QUARANTINED_TO_DECOMMISSIONED: (),
    GateId.DECOUPLE_CAPS_ONLY: (
        ConditionalCVaREvidence,
        TurnoverBoundEvidence,
        QuoteFreezeBackstopEvidence,
    ),
}
"""Declarative gate matrix.

Maps each gate to the evidence dataclasses required for its transition.

Empty tuples mean the gate has no structured-evidence requirement
(e.g. :attr:`GateId.QUARANTINED_TO_DECOMMISSIONED` records only a
free-form reason; the operator is the audit substrate)."""


@dataclass(frozen=True)
class _EvidenceRegistration:
    """Stable metadata kind and validator for one evidence type."""

    kind: str
    validator: Any


def required_evidence_types(gate_id: GateId) -> tuple[_EvidenceType, ...]:
    """Look up the evidence types required by ``gate_id``.

    Returns the empty tuple when the gate has no structured-evidence
    requirement.  Raises :class:`KeyError` if ``gate_id`` is unknown
    (defensive — every :class:`GateId` member must have an entry, and
    a constructor-time check enforces that invariant below).
    """
    return GATE_EVIDENCE_REQUIREMENTS[gate_id]


def validate_gate(
    gate_id: GateId,
    evidences: Sequence[object],
    thresholds: GateThresholds | None = None,
) -> list[str]:
    """Validate a sequence of structured evidence packages against a gate.

    ``evidences`` is an arbitrary-order list of evidence dataclasses
    (each must be one of the supported types in
    :data:`_EVIDENCE_REGISTRY`).  The dispatcher:

      1. Looks up the required evidence types for ``gate_id``.
      2. Indexes the supplied evidences by their type.
      3. Reports any missing required types.
      4. Reports any *extra* (unrecognised or duplicate) evidence —
         duplicates are rejected to keep the metadata payload
         unambiguous.
      5. Runs the per-type validator for each required evidence and
         merges the resulting error lists.

    Returns the merged list of human-readable error strings.  Empty
    list signals "all required evidence supplied and within
    thresholds".

    The validator does not mutate lifecycle state or write the ledger.
    """
    required = required_evidence_types(gate_id)
    errors: list[str] = []

    by_type: dict[_EvidenceType, object] = {}
    for ev in evidences:
        ev_type = type(ev)
        if ev_type not in _EVIDENCE_REGISTRY:
            errors.append(
                f"unsupported evidence type {ev_type.__name__!r}; "
                f"supported types: "
                f"{sorted(t.__name__ for t in _EVIDENCE_REGISTRY)}"
            )
            continue
        if ev_type in by_type:
            errors.append(
                f"duplicate evidence type {ev_type.__name__!r} — "
                f"each type may appear at most once per gate"
            )
            continue
        by_type[ev_type] = ev

    for req_type in required:
        if req_type not in by_type:
            errors.append(
                f"gate {gate_id.value!r} requires evidence of type "
                f"{req_type.__name__!r} but none was supplied"
            )

    for req_type in required:
        ev = by_type.get(req_type)
        if ev is None:
            continue
        validator = _EVIDENCE_REGISTRY[req_type].validator
        sub_errors: list[str] = validator(ev, thresholds)
        errors.extend(sub_errors)

    return errors


# ─────────────────────────────────────────────────────────────────────
#   Ledger metadata projection
# ─────────────────────────────────────────────────────────────────────


def evidence_to_metadata(*evidences: object) -> dict[str, Any]:
    """Project structured evidence into a JSON-safe metadata dict.

    Produces a payload suitable for embedding directly into
    :attr:`feelies.alpha.promotion_ledger.PromotionLedgerEntry.metadata`.
    The payload always carries:

      * ``"schema_version"`` — :data:`EVIDENCE_SCHEMA_VERSION`
      * one entry per supplied evidence, keyed by its stable ``kind``
        string from :data:`_EVIDENCE_REGISTRY`
      * any nested :class:`tuple` is serialised as a list (round-trips
        via JSON), :class:`Decimal` is left in place — the ledger's
        :func:`feelies.alpha.promotion_ledger._json_default` hook
        already handles it.

    Raises :class:`TypeError` if any evidence is not a known type.
    Raises :class:`ValueError` if two evidences share the same kind
    (duplicate-kind submissions are ambiguous and refused).
    """
    payload: dict[str, Any] = {"schema_version": EVIDENCE_SCHEMA_VERSION}
    seen: set[str] = set()

    for ev in evidences:
        ev_type = type(ev)
        registration = _EVIDENCE_REGISTRY.get(ev_type)
        if registration is None:
            raise TypeError(
                f"unsupported evidence type {ev_type.__name__!r}; "
                f"supported types: "
                f"{sorted(t.__name__ for t in _EVIDENCE_REGISTRY)}"
            )
        kind = registration.kind
        if kind in seen:
            raise ValueError(
                f"duplicate evidence kind {kind!r} — each kind may "
                f"appear at most once in a metadata payload"
            )
        seen.add(kind)
        payload[kind] = _evidence_to_jsonable(ev)

    return payload


def _evidence_to_jsonable(ev: object) -> dict[str, Any]:
    """Convert one evidence dataclass to a JSON-serialisable dict.

    Uses :func:`dataclasses.asdict` and post-processes:

      * :class:`Enum` values → their ``.value``
      * :class:`tuple` → :class:`list` (JSON does not have tuples)
      * :class:`Decimal` is *kept* (the ledger has a JSON encoder hook
        that serialises it to a canonical string).

    Non-recursive top-level conversion is sufficient because every
    evidence dataclass uses only flat scalars and tuples, with no nested
    dataclasses, no nested mappings.
    """
    if not is_dataclass(ev) or isinstance(ev, type):
        raise TypeError(
            f"_evidence_to_jsonable expected a dataclass instance, got {type(ev).__name__!r}"
        )
    raw = asdict(cast(Any, ev))
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(v, Enum):
            out[k] = v.value
        elif isinstance(v, tuple):
            out[k] = list(v)
        else:
            out[k] = v
    return out


# ─────────────────────────────────────────────────────────────────────
#   Inverse projection (metadata dict → evidence dataclasses)
# ─────────────────────────────────────────────────────────────────────


RESERVED_METADATA_KEYS: frozenset[str] = frozenset(
    {"schema_version", "reason", "config_version", "authorized_by"}
)
"""Non-evidence metadata co-keys that may legitimately accompany F-2
evidence sections in a ledger entry's ``metadata`` and therefore must be
**ignored** (not treated as an unknown evidence ``kind``) by
:func:`metadata_to_evidence`.

* ``schema_version`` — the payload version stamp written by
  :func:`evidence_to_metadata`.
* ``reason`` — the free-form operator string that
  :meth:`feelies.alpha.lifecycle.AlphaLifecycle.quarantine` (and
  ``decommission``) always writes alongside any structured evidence
  (``{"reason": ...}`` merged with ``evidence_to_metadata(*evs)``).
* ``config_version`` / ``authorized_by`` — the config-provenance and
  human-signoff co-keys that
  :meth:`feelies.alpha.lifecycle.AlphaLifecycle.authorize_decouple` merges
  alongside the Stage-0 ``decouple_caps_only`` gate evidence (Inv-11 / Inv-13).

Without this allow-list, replaying a quarantine-with-evidence entry
raised ``ValueError: metadata carries unknown kind(s) ['reason']`` and
``feelies promote replay-evidence`` mis-reported the healthy entry as a
gate FAIL (exit 3).  Keep this in sync with the co-keys any lifecycle
writer merges into evidence metadata."""


def _reconstruct_evidence(
    evidence_type: _EvidenceType,
    payload: Mapping[str, Any],
) -> object:
    """Restore tuple and enum fields from JSON using dataclass defaults."""
    fixed = dict(payload)
    for evidence_field in fields(evidence_type):
        default = evidence_field.default
        if isinstance(default, tuple):
            fixed[evidence_field.name] = tuple(payload.get(evidence_field.name, default))
        elif isinstance(default, Enum):
            raw = payload.get(evidence_field.name, default.value)
            fixed[evidence_field.name] = type(default)(raw)
    return evidence_type(**fixed)


_EVIDENCE_REGISTRY: Mapping[_EvidenceType, _EvidenceRegistration] = {
    ResearchAcceptanceEvidence: _EvidenceRegistration(
        "research_acceptance", validate_research_acceptance
    ),
    CPCVEvidence: _EvidenceRegistration("cpcv", validate_cpcv),
    DSREvidence: _EvidenceRegistration("dsr", validate_dsr),
    PaperWindowEvidence: _EvidenceRegistration("paper_window", validate_paper_window),
    CapitalStageEvidence: _EvidenceRegistration("capital_stage", validate_capital_stage),
    QuarantineTriggerEvidence: _EvidenceRegistration(
        "quarantine_trigger", validate_quarantine_trigger
    ),
    RevalidationEvidence: _EvidenceRegistration("revalidation", validate_revalidation),
    ConditionalCVaREvidence: _EvidenceRegistration("conditional_cvar", validate_conditional_cvar),
    TurnoverBoundEvidence: _EvidenceRegistration("turnover_bound", validate_turnover_bound),
    QuoteFreezeBackstopEvidence: _EvidenceRegistration(
        "quote_freeze_backstop", validate_quote_freeze_backstop
    ),
}
"""Single registration source for validation and metadata round-tripping.

The stable ``kind`` strings must not change without bumping
:data:`EVIDENCE_SCHEMA_VERSION`."""


KIND_TO_TYPE: Mapping[str, _EvidenceType] = {
    registration.kind: evidence_type for evidence_type, registration in _EVIDENCE_REGISTRY.items()
}
"""Public reverse mapping of :data:`_EVIDENCE_REGISTRY`.

Stable ``"kind"`` string → evidence dataclass type.  Used by
:func:`metadata_to_evidence` and the replay-evidence CLI to reconstruct
typed evidence dataclasses from the JSON metadata persisted on a
:class:`feelies.alpha.promotion_ledger.PromotionLedgerEntry`."""


def metadata_to_evidence(metadata: Mapping[str, Any]) -> list[object]:
    """Reverse :func:`evidence_to_metadata`.

    Reconstructs typed evidence dataclasses from an
    :func:`evidence_to_metadata` payload (a dict
    carrying ``"schema_version"`` plus zero or more
    ``"kind": {field: value, ...}`` entries).

    Returns the list of reconstructed evidence dataclass instances in
    the canonical kind-iteration order of :data:`_EVIDENCE_REGISTRY`.  An
    empty list signals that the metadata has no structured evidence sections.

    Raises:
      ValueError -- if ``schema_version`` is present but does not
                    match :data:`EVIDENCE_SCHEMA_VERSION`, or if a
                    recognised ``"kind"`` key carries a non-mapping
                    payload, or if a kind is unknown.

    The replay-evidence CLI validates reconstructed evidence against current thresholds.
    """
    if not isinstance(metadata, Mapping):
        raise ValueError(
            f"metadata_to_evidence expected a mapping, got {type(metadata).__name__!r}"
        )

    schema_version = metadata.get("schema_version")
    if schema_version is None:
        return []
    if schema_version != EVIDENCE_SCHEMA_VERSION:
        raise ValueError(
            f"metadata schema_version {schema_version!r} does not match "
            f"current EVIDENCE_SCHEMA_VERSION {EVIDENCE_SCHEMA_VERSION!r}"
        )

    evidences: list[object] = []
    for evidence_type, registration in _EVIDENCE_REGISTRY.items():
        kind = registration.kind
        if kind not in metadata:
            continue
        payload = metadata[kind]
        if not isinstance(payload, Mapping):
            raise ValueError(
                f"metadata[{kind!r}] must be an object, got {type(payload).__name__!r}"
            )
        evidences.append(_reconstruct_evidence(evidence_type, payload))

    unknown = sorted(
        k for k in metadata.keys() if k not in RESERVED_METADATA_KEYS and k not in KIND_TO_TYPE
    )
    if unknown:
        raise ValueError(
            f"metadata carries unknown kind(s) {unknown}; supported kinds: "
            f"{sorted(KIND_TO_TYPE.keys())} (reserved co-keys: "
            f"{sorted(RESERVED_METADATA_KEYS)})"
        )

    return evidences


# Gate-threshold override parsing and merging.


def _gate_threshold_field_types() -> dict[str, type]:
    """Return ``{field_name: expected_python_type}`` for
    :class:`GateThresholds`.

    Used by :func:`parse_gate_thresholds_overrides` to validate that
    operator-supplied keys correspond to a real ``GateThresholds``
    field and to coerce the supplied value into the dataclass's
    declared scalar type (``int`` / ``float`` / ``bool``).
    """
    out: dict[str, type] = {}
    for f in fields(GateThresholds):
        annotation = f.type
        if isinstance(annotation, str):
            if annotation == "int":
                out[f.name] = int
            elif annotation == "float":
                out[f.name] = float
            elif annotation == "bool":
                out[f.name] = bool
            else:
                raise RuntimeError(
                    f"GateThresholds field {f.name!r} has unsupported "
                    f"annotation {annotation!r}; only int/float/bool are "
                    "supported by F-5 override parsing"
                )
        else:
            out[f.name] = annotation
    return out


_GATE_THRESHOLD_FIELD_TYPES: dict[str, type] = _gate_threshold_field_types()


def parse_gate_thresholds_overrides(
    raw: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate and coerce gate-threshold overrides without mutation.

    Keys must name ``GateThresholds`` fields and values must already be scalar,
    non-string inputs of the declared type. Cross-field numeric invariants are
    checked when the resulting thresholds are consumed.
    """
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"gate_thresholds overrides must be a mapping; got {type(raw).__name__}")

    known = _GATE_THRESHOLD_FIELD_TYPES
    unknown = sorted(k for k in raw if k not in known)
    if unknown:
        raise ValueError(
            "gate_thresholds overrides reference unknown field(s) "
            f"{unknown}; valid fields are {sorted(known)}"
        )

    out: dict[str, Any] = {}
    for key, value in raw.items():
        expected = known[key]
        coerced = _coerce_threshold_value(key, value, expected)
        out[key] = coerced
    return out


def _coerce_threshold_value(key: str, value: Any, expected: type) -> Any:
    """Coerce ``value`` into ``expected`` for a ``GateThresholds`` field.

    Strict on type (``bool`` is *not* an ``int``, strings are not
    auto-parsed) so that YAML typos surface as :class:`ValueError`
    rather than silently mis-typed thresholds.
    """
    if expected is bool:
        if isinstance(value, bool):
            return value
        raise ValueError(
            f"gate_thresholds[{key!r}] expects bool; got {type(value).__name__}={value!r}"
        )
    if expected is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"gate_thresholds[{key!r}] expects int; got {type(value).__name__}={value!r}"
            )
        return value
    if expected is float:
        if isinstance(value, bool):
            raise ValueError(f"gate_thresholds[{key!r}] expects float; got bool={value!r}")
        if isinstance(value, (int, float)):
            return float(value)
        raise ValueError(
            f"gate_thresholds[{key!r}] expects float; got {type(value).__name__}={value!r}"
        )
    raise RuntimeError(f"unsupported expected type {expected!r} for gate_thresholds[{key!r}]")


def apply_gate_thresholds_overrides(
    base: GateThresholds, overrides: Mapping[str, Any] | None
) -> GateThresholds:
    """Return a new :class:`GateThresholds` derived from ``base`` with
    ``overrides`` applied on top.

    Overrides are passed through :func:`parse_gate_thresholds_overrides`
    first so the same key/type validation applies regardless of how the
    overrides were loaded.  Empty / ``None`` overrides return ``base``
    unchanged (identity).
    """
    parsed = parse_gate_thresholds_overrides(overrides)
    if not parsed:
        return base
    return replace(base, **parsed)


# Per-alpha threshold-floor enforcement.


class _FloorDirection(Enum):
    """Monotonicity of a :class:`GateThresholds` field, used to decide
    whether a per-alpha override *tightens* or *loosens* a gate relative
    to an operator-pinned ``platform.yaml`` floor.
    """

    MIN = "min"
    """Lower-bound threshold (evidence value must be ``>=`` it).  Higher
    is stricter; a per-alpha override may only *raise* it."""

    MAX = "max"
    """Upper-bound threshold (evidence value must be ``<=`` it).  Lower
    is stricter; a per-alpha override may only *lower* it."""

    FREE = "free"
    """Consistency-only / non-gating threshold (the quarantine-trigger
    fields, which never block a transition).  No floor constraint — a
    per-alpha override cannot grant capital access by changing it."""


_GATE_THRESHOLD_DIRECTIONS: dict[str, _FloorDirection] = {
    # ── Research → Paper (minimums: evidence must meet or exceed) ──────
    "research_min_branch_coverage_pct": _FloorDirection.MIN,
    "research_min_line_coverage_pct": _FloorDirection.MIN,
    "research_min_fault_injection_pass_pct": _FloorDirection.MIN,
    # ── Paper → Live ───────────────────────────────────────────────────
    "paper_min_trading_days": _FloorDirection.MIN,
    "paper_min_sample_size": _FloorDirection.MIN,
    "paper_max_slippage_residual_bps": _FloorDirection.MAX,
    "paper_max_fill_rate_drift_pct": _FloorDirection.MAX,
    "paper_min_latency_ks_p": _FloorDirection.MIN,
    "paper_min_pnl_compression_ratio": _FloorDirection.MIN,
    "paper_max_pnl_compression_ratio": _FloorDirection.MAX,
    "paper_max_anomalous_events": _FloorDirection.MAX,
    "cpcv_min_folds": _FloorDirection.MIN,
    "cpcv_min_mean_sharpe": _FloorDirection.MIN,
    "cpcv_max_p_value": _FloorDirection.MAX,
    "cpcv_min_embargo_bars": _FloorDirection.MIN,
    "dsr_min": _FloorDirection.MIN,
    "dsr_max_p_value": _FloorDirection.MAX,
    # ── Capital-stage tier (SMALL → SCALED) ────────────────────────────
    "small_min_deployment_days": _FloorDirection.MIN,
    "small_min_pnl_compression_ratio": _FloorDirection.MIN,
    "small_max_pnl_compression_ratio": _FloorDirection.MAX,
    "small_max_slippage_residual_bps": _FloorDirection.MAX,
    # ``small_max_hit_rate_residual_pp`` is a *floor* despite the "max"
    # name — the validator passes when ``residual >= threshold`` (stored
    # negative, e.g. -5.0), so a higher value is stricter → MIN.
    "small_max_hit_rate_residual_pp": _FloorDirection.MIN,
    "small_max_fill_rate_drift_pct": _FloorDirection.MAX,
    # ── Quarantine triggers (consistency-only, never gate) ─────────────
    "quarantine_max_net_alpha_negative_days": _FloorDirection.FREE,
    "quarantine_max_hit_rate_residual_pp": _FloorDirection.FREE,
    "quarantine_max_pnl_compression_ratio_5d": _FloorDirection.FREE,
    "quarantine_min_microstructure_breaches": _FloorDirection.FREE,
    "quarantine_min_crowding_symptoms": _FloorDirection.FREE,
    # ── Revalidation ───────────────────────────────────────────────────
    "revalidation_min_oos_sharpe": _FloorDirection.MIN,
    # ── Stage-0 decouple_caps_only gates ───────────────────────────────
    # A per-alpha override may only tighten: raise a power/CPCV floor, or
    # lower a tail-worsening tolerance / turnover ceiling / tail width.
    "decouple_cvar_max_level": _FloorDirection.MAX,
    "decouple_cvar_min_tail_sample": _FloorDirection.MIN,
    "decouple_cvar_tolerance": _FloorDirection.MAX,
    "decouple_cvar_min_folds": _FloorDirection.MIN,
    "decouple_cvar_min_embargo_bars": _FloorDirection.MIN,
    "decouple_turnover_ceiling_ratio": _FloorDirection.MAX,
    "decouple_turnover_min_sample": _FloorDirection.MIN,
    "decouple_quote_freeze_min_episodes": _FloorDirection.MIN,
}
"""Per-field monotonicity used by :func:`assert_per_alpha_overrides_respect_floor`.

Every :class:`GateThresholds` field MUST appear here; a construction-time
check (:func:`_check_threshold_direction_coverage`) fails the import if a
new field is added without a direction, so the floor rule can never
silently miss a gate."""


class GateThresholdFloorError(ValueError):
    """Raised when a per-alpha ``promotion.gate_thresholds`` override would
    loosen a threshold below an operator-pinned ``platform.yaml`` floor.

    Inv-11 (loosening a safety control requires human re-authorization)
    and Inv-13 (provenance): the platform operator pins acceptance floors
    in ``platform.yaml: gate_thresholds:``; a per-alpha override authored
    in the alpha bundle may *tighten* any gate but may not *loosen* one
    the operator explicitly pinned.  Per-alpha overrides on fields the
    operator did **not** pin still apply (they only relax the skill-pinned
    defaults, which are not operator policy)."""


def assert_per_alpha_overrides_respect_floor(
    *,
    platform_floor: GateThresholds,
    platform_pinned_fields: Iterable[str],
    per_alpha_overrides: Mapping[str, Any],
) -> None:
    """Reject per-alpha overrides that loosen an operator-pinned floor.

    ``platform_floor`` is the materialised platform-level
    :class:`GateThresholds` (skill defaults overlaid by
    ``platform.yaml: gate_thresholds:``).  ``platform_pinned_fields`` is
    the set of field names the operator *explicitly* set in
    ``platform.yaml`` (i.e. the keys of
    :attr:`PlatformConfig.gate_thresholds_overrides`) — only those are
    treated as operator floors; fields left at their skill default remain
    freely loosenable per alpha.

    Raises :class:`GateThresholdFloorError` listing every offending field
    if any per-alpha override loosens a pinned floor in its
    direction-appropriate sense; returns ``None`` otherwise.
    """
    pinned = set(platform_pinned_fields)
    violations: list[str] = []
    for name, proposed in per_alpha_overrides.items():
        if name not in pinned:
            continue
        direction = _GATE_THRESHOLD_DIRECTIONS.get(name, _FloorDirection.FREE)
        if direction is _FloorDirection.FREE:
            continue
        floor = getattr(platform_floor, name)
        if direction is _FloorDirection.MIN and proposed < floor:
            violations.append(
                f"{name!r}={proposed} loosens below operator-pinned platform "
                f"floor {floor} (minimum threshold — per-alpha may only raise it)"
            )
        elif direction is _FloorDirection.MAX and proposed > floor:
            violations.append(
                f"{name!r}={proposed} loosens above operator-pinned platform "
                f"ceiling {floor} (maximum threshold — per-alpha may only lower it)"
            )
    if violations:
        raise GateThresholdFloorError(
            "per-alpha promotion.gate_thresholds may not loosen an operator-pinned "
            "platform floor (Inv-11 / Inv-13): " + "; ".join(sorted(violations))
        )


# ─────────────────────────────────────────────────────────────────────
#   Construction-time invariant checks
# ─────────────────────────────────────────────────────────────────────


def _check_matrix_completeness() -> None:
    """Enforce that every :class:`GateId` has an entry in the matrix.

    Mirrors the construction-time enum-completeness check used by the
    platform's :class:`feelies.core.state_machine.StateMachine`.  A
    contributor adding a new ``GateId`` member without populating
    :data:`GATE_EVIDENCE_REQUIREMENTS` triggers a hard failure on
    import.
    """
    missing = sorted(member.value for member in GateId if member not in GATE_EVIDENCE_REQUIREMENTS)
    if missing:
        raise RuntimeError(
            f"GATE_EVIDENCE_REQUIREMENTS is missing entries for GateId members: {missing}"
        )


def _check_validator_coverage() -> None:
    """Enforce that every evidence type listed in
    :data:`GATE_EVIDENCE_REQUIREMENTS` has a registered validator
    *and* a registered ``kind`` string.
    """
    for gate, types in GATE_EVIDENCE_REQUIREMENTS.items():
        for t in types:
            registration = _EVIDENCE_REGISTRY.get(t)
            if registration is None:
                raise RuntimeError(
                    f"Gate {gate.value!r} requires evidence type "
                    f"{t.__name__!r} but no validator is registered"
                )
            if not registration.kind:
                raise RuntimeError(
                    f"Gate {gate.value!r} requires evidence type "
                    f"{t.__name__!r} but no metadata kind is registered"
                )


def _check_threshold_direction_coverage() -> None:
    """Enforce that every :class:`GateThresholds` field is classified in
    :data:`_GATE_THRESHOLD_DIRECTIONS`.

    Import-time validation keeps the floor rule total over the schema.
    """
    classified = set(_GATE_THRESHOLD_DIRECTIONS)
    actual = {f.name for f in fields(GateThresholds)}
    missing = sorted(actual - classified)
    extra = sorted(classified - actual)
    if missing or extra:
        raise RuntimeError(
            "_GATE_THRESHOLD_DIRECTIONS is out of sync with GateThresholds: "
            f"missing direction for {missing}; stale entries {extra}"
        )


_check_matrix_completeness()
_check_validator_coverage()
_check_threshold_direction_coverage()


__all__ = (
    "AUTHORIZE_DECOUPLE_TRIGGER",
    "EVIDENCE_SCHEMA_VERSION",
    "PROMOTE_CAPITAL_TIER_TRIGGER",
    "CPCVEvidence",
    "CapitalStageEvidence",
    "CapitalStageTier",
    "ConditionalCVaREvidence",
    "DSREvidence",
    "GATE_EVIDENCE_REQUIREMENTS",
    "GateId",
    "GateThresholdFloorError",
    "GateThresholds",
    "KIND_TO_TYPE",
    "PaperWindowEvidence",
    "QuarantineTriggerEvidence",
    "QuoteFreezeBackstopEvidence",
    "RESERVED_METADATA_KEYS",
    "ResearchAcceptanceEvidence",
    "RevalidationEvidence",
    "TurnoverBoundEvidence",
    "apply_gate_thresholds_overrides",
    "assert_per_alpha_overrides_respect_floor",
    "evidence_to_metadata",
    "metadata_to_evidence",
    "parse_gate_thresholds_overrides",
    "required_evidence_types",
    "validate_capital_stage",
    "validate_conditional_cvar",
    "validate_cpcv",
    "validate_dsr",
    "validate_gate",
    "validate_paper_window",
    "validate_quarantine_trigger",
    "validate_quote_freeze_backstop",
    "validate_research_acceptance",
    "validate_revalidation",
    "validate_turnover_bound",
)
