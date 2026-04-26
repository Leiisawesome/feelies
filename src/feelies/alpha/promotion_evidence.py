"""Structured promotion-evidence schemas + gate matrix for Workstream F.

Defines the typed evidence dataclasses that promotion gates read, the
declarative ``GATE_EVIDENCE_REQUIREMENTS`` matrix wiring each gate to
its required evidence types, the ``GateThresholds`` configuration block
holding the platform's default acceptance thresholds, and the pure
validator functions that produce a ``list[str]`` of human-readable
errors when an evidence package falls short of its threshold.

Scope (Workstream F-2):

- **Definitions only.**  This PR does *not* mutate the
  :class:`feelies.alpha.lifecycle.AlphaLifecycle` state machine or its
  existing ``check_paper_gate`` / ``check_live_gate`` /
  ``check_revalidation_gate`` callers.  Workstream **F-4** will swap
  those legacy gate-checks for the structured validators introduced
  here once Workstream **C** (CPCV + DSR computation) and the
  post-trade-forensics quarantine pipeline are wired.

- **Forensic-only writer contract preserved.**  The
  :func:`evidence_to_metadata` helper produces a JSON-safe ``dict``
  suitable for direct insertion into
  :attr:`feelies.alpha.promotion_ledger.PromotionLedgerEntry.metadata`.
  No production code path will *read* the resulting metadata to make
  per-tick decisions (that would re-introduce a non-deterministic
  feedback loop with the durable ledger), so replay determinism
  (audit A-DET-02) is not perturbed.

- **No state-machine changes.**  Capital-stage tiers (SMALL_CAPITAL vs.
  SCALED) are modelled as *evidence* attached to a ``LIVE`` lifecycle
  rather than as separate states, so the existing five-state machine
  (``RESEARCH → PAPER → LIVE → QUARANTINED → DECOMMISSIONED``) is
  unchanged.  The capital tier is captured on
  :class:`CapitalStageEvidence` and travels with the
  promotion-ledger entry that recorded the LIVE-side promotion.

Schema sources (so reviewers can double-check the field choices):

- :doc:`testing-validation skill <.cursor/skills/testing-validation/SKILL.md>`
  §"Acceptance Criteria & Promotion Pipeline" — the four-stage ladder
  (Research → Paper → Small Capital → Scaled), the per-stage exit
  criteria, and the demotion triggers.
- :doc:`post-trade-forensics skill <.cursor/skills/post-trade-forensics/SKILL.md>`
  §"Strategy Quarantine" — the quarantine evidence list (net alpha,
  hit-rate residual, microstructure metrics, crowding symptoms, PnL
  compression).
- :doc:`schema 1.1 migration <docs/migration/schema_1_0_to_1_1.md>` —
  notes that ``OOS DSR < 1.0 across any single calendar quarter after
  LIVE`` is one of the falsification criteria, hence the Bailey &
  López de Prado *Deflated Sharpe Ratio* threshold defaults.
- :doc:`microstructure-alpha research-protocol
  <.cursor/skills/microstructure-alpha/research-protocol.md>` — the
  walk-forward / cross-validation / cost-hurdle cadence that
  Workstream C will compute via Combinatorial Purged Cross-Validation
  (CPCV).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, cast

EVIDENCE_SCHEMA_VERSION = "1.0.0"


# ─────────────────────────────────────────────────────────────────────
#   Capital-stage tier
# ─────────────────────────────────────────────────────────────────────


class CapitalStageTier(Enum):
    """Capital-allocation tiers applied to a ``LIVE`` alpha.

    Modelled as evidence (not as separate ``AlphaLifecycleState``
    members) so the existing 5-state lifecycle is unchanged.  The tier
    travels with :class:`CapitalStageEvidence` on the promotion-ledger
    entry that recorded the LIVE-side promotion, so the audit trail
    can answer "what fraction of target was deployed when ALPHA-X
    quarantined?" by reading the most recent ``CapitalStageEvidence``
    for that alpha.
    """

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
    """Stable identifiers for the F-2 gate matrix.

    Each gate covers exactly one ``(from_state, to_state)`` lifecycle
    transition (or, for ``LIVE_PROMOTE_CAPITAL_TIER``, the
    capital-tier escalation that does not change the lifecycle state).

    The matrix is the source of truth that Workstream **F-4** will
    consult to look up which structured evidence types must be
    supplied for a given transition.
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
    """LIVE @ SMALL_CAPITAL → LIVE @ SCALED (capital-tier escalation
    that does not change the lifecycle state)."""

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
    """Combinatorial Purged Cross-Validation evidence.

    Workstream **C** will compute this; F-2 only defines the schema.
    ``fold_sharpes`` is a tuple (immutable) so the evidence can be
    safely embedded in a frozen dataclass and round-tripped through
    JSON.

    Fields:
      fold_count           -- number of CPCV folds run
      embargo_bars         -- purge/embargo bars between train and test
      fold_sharpes         -- per-fold OOS Sharpe ratios
      mean_sharpe          -- arithmetic mean of fold_sharpes
      median_sharpe        -- median of fold_sharpes
      mean_pnl             -- arithmetic mean of fold realised PnL
      p_value              -- combined p-value across folds (e.g. Stouffer)
      fold_pnl_curves_hash -- pointer (sha256) to the artefact carrying
                              the per-fold equity curves; persisted in
                              the research-artefact store.  Optional —
                              evidence may travel without the heavy
                              artefact when the validator only needs
                              the summary stats.
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
    """Deflated Sharpe Ratio (Bailey & López de Prado, 2014).

    DSR adjusts the observed Sharpe ratio for the number of trials
    explored during research and the higher moments of the return
    distribution.  ``OOS DSR < 1.0 across any single calendar quarter
    after LIVE`` is one of the documented falsification criteria
    (schema 1.1 migration §"falsification_criteria").

    Fields:
      observed_sharpe -- raw OOS Sharpe of the candidate
      trials_count   -- number of variants explored before this one
      skewness       -- 3rd standardised moment of returns
      kurtosis       -- 4th standardised moment of returns
      dsr            -- deflated Sharpe ratio
      dsr_p_value    -- p-value for ``DSR > 0`` under the null
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
#   Threshold configuration
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class GateThresholds:
    """Default acceptance thresholds for every F-2 validator.

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

    # ── CPCV (Workstream C will compute) ──────────────────────────
    cpcv_min_folds: int = 8
    cpcv_min_mean_sharpe: float = 1.0
    cpcv_max_p_value: float = 0.05

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
        pass_pct = (
            100.0 * evidence.fault_injection_pass_count
            / evidence.fault_injection_total
        )
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


def validate_cpcv(
    evidence: CPCVEvidence,
    thresholds: GateThresholds | None = None,
) -> list[str]:
    """Validate :class:`CPCVEvidence` against thresholds.

    Pass conditions: enough folds run, mean Sharpe at or above
    threshold, p-value at or below threshold, and ``len(fold_sharpes)``
    must equal ``fold_count`` (else the evidence is internally
    inconsistent and we refuse it).
    """
    t = thresholds or GateThresholds()
    errors: list[str] = []

    if evidence.fold_count < t.cpcv_min_folds:
        errors.append(
            f"CPCV fold_count {evidence.fold_count} "
            f"< {t.cpcv_min_folds} required"
        )
    if evidence.fold_count > 0 and len(evidence.fold_sharpes) != evidence.fold_count:
        errors.append(
            f"CPCV inconsistent: fold_count={evidence.fold_count} but "
            f"{len(evidence.fold_sharpes)} fold_sharpes provided"
        )
    if evidence.mean_sharpe < t.cpcv_min_mean_sharpe:
        errors.append(
            f"CPCV mean Sharpe {evidence.mean_sharpe:.2f} "
            f"< {t.cpcv_min_mean_sharpe:.2f} required"
        )
    if evidence.p_value > t.cpcv_max_p_value:
        errors.append(
            f"CPCV p-value {evidence.p_value:.4f} "
            f"> {t.cpcv_max_p_value:.4f} threshold"
        )

    return errors


def validate_dsr(
    evidence: DSREvidence,
    thresholds: GateThresholds | None = None,
) -> list[str]:
    """Validate :class:`DSREvidence` against thresholds.

    Pass conditions: DSR at or above threshold *and* DSR p-value at
    or below threshold *and* ``trials_count`` recorded (a 0 trials
    count is suspicious — DSR's whole point is to deflate by trials).
    """
    t = thresholds or GateThresholds()
    errors: list[str] = []

    if evidence.dsr < t.dsr_min:
        errors.append(
            f"DSR {evidence.dsr:.3f} < {t.dsr_min:.3f} required "
            f"(schema-1.1 falsification rule)"
        )
    if evidence.dsr_p_value > t.dsr_max_p_value:
        errors.append(
            f"DSR p-value {evidence.dsr_p_value:.4f} "
            f"> {t.dsr_max_p_value:.4f} threshold"
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
            f"paper trading_days {evidence.trading_days} "
            f"< {t.paper_min_trading_days} required"
        )
    if evidence.sample_size < t.paper_min_sample_size:
        errors.append(
            f"paper sample_size {evidence.sample_size} "
            f"< {t.paper_min_sample_size} required"
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
    if (
        evidence.pnl_compression_ratio_realised
        < t.small_min_pnl_compression_ratio
    ):
        errors.append(
            f"small-capital realised PnL compression ratio "
            f"{evidence.pnl_compression_ratio_realised:.2f} "
            f"< {t.small_min_pnl_compression_ratio:.2f} required"
        )
    if (
        evidence.pnl_compression_ratio_realised
        > t.small_max_pnl_compression_ratio
    ):
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

    triggered = (
        evidence.net_alpha_negative_days
        >= t.quarantine_max_net_alpha_negative_days
    )
    triggered = triggered or (
        evidence.hit_rate_residual_pp
        <= t.quarantine_max_hit_rate_residual_pp
    )
    triggered = triggered or (
        evidence.pnl_compression_ratio_5d
        <= t.quarantine_max_pnl_compression_ratio_5d
    )
    triggered = triggered or (
        len(evidence.microstructure_metrics_breached)
        >= t.quarantine_min_microstructure_breaches
    )
    triggered = triggered or (
        len(evidence.crowding_symptoms)
        >= t.quarantine_min_crowding_symptoms
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
}
"""Declarative gate matrix.

Maps each :class:`GateId` to the tuple of evidence dataclasses that
the gate requires.  Workstream **F-4** will look up the requirement
list at promotion time and refuse to commit a transition unless every
required type is present in the supplied evidence package.

Empty tuples mean the gate has no structured-evidence requirement
(e.g. :attr:`GateId.QUARANTINED_TO_DECOMMISSIONED` records only a
free-form reason; the operator is the audit substrate)."""


_VALIDATOR_BY_TYPE: Mapping[
    _EvidenceType,
    Any,
] = {
    ResearchAcceptanceEvidence: validate_research_acceptance,
    CPCVEvidence: validate_cpcv,
    DSREvidence: validate_dsr,
    PaperWindowEvidence: validate_paper_window,
    CapitalStageEvidence: validate_capital_stage,
    QuarantineTriggerEvidence: validate_quarantine_trigger,
    RevalidationEvidence: validate_revalidation,
}


_KIND_BY_TYPE: Mapping[_EvidenceType, str] = {
    ResearchAcceptanceEvidence: "research_acceptance",
    CPCVEvidence: "cpcv",
    DSREvidence: "dsr",
    PaperWindowEvidence: "paper_window",
    CapitalStageEvidence: "capital_stage",
    QuarantineTriggerEvidence: "quarantine_trigger",
    RevalidationEvidence: "revalidation",
}
"""Stable string keys used in the JSON metadata payload — never
rename without bumping :data:`EVIDENCE_SCHEMA_VERSION`."""


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
    :data:`_KIND_BY_TYPE`).  The dispatcher:

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

    The validator does *not* mutate any state, write to the ledger,
    or commit a lifecycle transition — that is Workstream **F-4**'s
    job.
    """
    required = required_evidence_types(gate_id)
    errors: list[str] = []

    by_type: dict[_EvidenceType, object] = {}
    for ev in evidences:
        ev_type = type(ev)
        if ev_type not in _VALIDATOR_BY_TYPE:
            errors.append(
                f"unsupported evidence type {ev_type.__name__!r}; "
                f"supported types: "
                f"{sorted(t.__name__ for t in _VALIDATOR_BY_TYPE)}"
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
        validator = _VALIDATOR_BY_TYPE[req_type]
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
        string from :data:`_KIND_BY_TYPE`
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
        kind = _KIND_BY_TYPE.get(ev_type)
        if kind is None:
            raise TypeError(
                f"unsupported evidence type {ev_type.__name__!r}; "
                f"supported types: "
                f"{sorted(t.__name__ for t in _KIND_BY_TYPE)}"
            )
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
    F-2 evidence dataclass uses only flat scalars / tuples — no nested
    dataclasses, no nested mappings.
    """
    if not is_dataclass(ev) or isinstance(ev, type):
        raise TypeError(
            f"_evidence_to_jsonable expected a dataclass instance, "
            f"got {type(ev).__name__!r}"
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
    missing = sorted(
        member.value
        for member in GateId
        if member not in GATE_EVIDENCE_REQUIREMENTS
    )
    if missing:
        raise RuntimeError(
            "GATE_EVIDENCE_REQUIREMENTS is missing entries for "
            f"GateId members: {missing}"
        )


def _check_validator_coverage() -> None:
    """Enforce that every evidence type listed in
    :data:`GATE_EVIDENCE_REQUIREMENTS` has a registered validator
    *and* a registered ``kind`` string.
    """
    for gate, types in GATE_EVIDENCE_REQUIREMENTS.items():
        for t in types:
            if t not in _VALIDATOR_BY_TYPE:
                raise RuntimeError(
                    f"Gate {gate.value!r} requires evidence type "
                    f"{t.__name__!r} but no validator is registered"
                )
            if t not in _KIND_BY_TYPE:
                raise RuntimeError(
                    f"Gate {gate.value!r} requires evidence type "
                    f"{t.__name__!r} but no metadata kind is registered"
                )


_check_matrix_completeness()
_check_validator_coverage()


__all__ = (
    "EVIDENCE_SCHEMA_VERSION",
    "CPCVEvidence",
    "CapitalStageEvidence",
    "CapitalStageTier",
    "DSREvidence",
    "GATE_EVIDENCE_REQUIREMENTS",
    "GateId",
    "GateThresholds",
    "PaperWindowEvidence",
    "QuarantineTriggerEvidence",
    "ResearchAcceptanceEvidence",
    "RevalidationEvidence",
    "evidence_to_metadata",
    "required_evidence_types",
    "validate_capital_stage",
    "validate_cpcv",
    "validate_dsr",
    "validate_gate",
    "validate_paper_window",
    "validate_quarantine_trigger",
    "validate_research_acceptance",
    "validate_revalidation",
)
