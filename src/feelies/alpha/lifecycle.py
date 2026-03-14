"""Alpha lifecycle state machine and promotion gates.

Manages the progression of an alpha module from research through
paper trading to live capital deployment, with quarantine for
detected edge decay.

State transitions:
  RESEARCH -> PAPER         pass_paper_gate (schema valid, determinism OK)
  PAPER -> LIVE             pass_live_gate (evidence-based promotion)
  LIVE -> QUARANTINED       edge_decay_detected (auto-triggered)
  QUARANTINED -> PAPER      revalidation_passed (human + evidence)
  QUARANTINED -> DECOMMISSIONED  decommissioned (terminal)

Invariants preserved:
  - Inv 11 (fail-safe): quarantine only tightens; loosening requires
    human re-authorization
  - Inv 13 (provenance): every transition is logged with trigger,
    evidence, and correlation_id
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from feelies.core.clock import Clock
from feelies.core.state_machine import StateMachine


class AlphaLifecycleState(Enum):
    """Lifecycle states for an alpha module."""

    RESEARCH = auto()
    PAPER = auto()
    LIVE = auto()
    QUARANTINED = auto()
    DECOMMISSIONED = auto()


_LIFECYCLE_TRANSITIONS: dict[AlphaLifecycleState, frozenset[AlphaLifecycleState]] = {
    AlphaLifecycleState.RESEARCH: frozenset({AlphaLifecycleState.PAPER}),
    AlphaLifecycleState.PAPER: frozenset({AlphaLifecycleState.LIVE}),
    AlphaLifecycleState.LIVE: frozenset({AlphaLifecycleState.QUARANTINED}),
    AlphaLifecycleState.QUARANTINED: frozenset({
        AlphaLifecycleState.PAPER,
        AlphaLifecycleState.DECOMMISSIONED,
    }),
    AlphaLifecycleState.DECOMMISSIONED: frozenset(),
}


@dataclass(frozen=True, kw_only=True)
class PromotionEvidence:
    """Evidence package submitted when requesting a lifecycle transition.

    The gate checks this evidence against the requirements for the
    target state.  Insufficient evidence rejects the transition.
    """

    paper_days: int = 0
    paper_sharpe: float = 0.0
    paper_hit_rate: float = 0.0
    paper_max_drawdown_pct: float = 0.0
    determinism_test_passed: bool = False
    schema_valid: bool = False
    feature_values_finite: bool = False
    cost_model_validated: bool = False
    quarantine_triggers: int = 0
    revalidation_notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class GateRequirements:
    """Configurable thresholds for promotion gates."""

    paper_min_days: int = 30
    paper_min_sharpe: float = 1.0
    paper_min_hit_rate: float = 0.50
    paper_max_drawdown_pct: float = 5.0


def check_paper_gate(evidence: PromotionEvidence) -> list[str]:
    """Check evidence for RESEARCH -> PAPER promotion.

    Requirements:
      - Schema validation passes
      - Determinism smoke test passes
      - Feature values are finite
    """
    errors: list[str] = []
    if not evidence.schema_valid:
        errors.append("schema validation has not passed")
    if not evidence.determinism_test_passed:
        errors.append("determinism smoke test has not passed")
    if not evidence.feature_values_finite:
        errors.append("feature values not confirmed finite")
    return errors


def check_live_gate(
    evidence: PromotionEvidence,
    requirements: GateRequirements | None = None,
) -> list[str]:
    """Check evidence for PAPER -> LIVE promotion.

    Requirements:
      - N days of paper PnL
      - Sharpe above threshold
      - Hit rate above threshold
      - Max drawdown within budget
      - No quarantine triggers
      - Cost model validated
    """
    req = requirements or GateRequirements()
    errors: list[str] = []

    if evidence.paper_days < req.paper_min_days:
        errors.append(
            f"insufficient paper trading days: {evidence.paper_days} "
            f"< {req.paper_min_days} required"
        )
    if evidence.paper_sharpe < req.paper_min_sharpe:
        errors.append(
            f"paper Sharpe {evidence.paper_sharpe:.2f} "
            f"< {req.paper_min_sharpe:.2f} required"
        )
    if evidence.paper_hit_rate < req.paper_min_hit_rate:
        errors.append(
            f"paper hit rate {evidence.paper_hit_rate:.2%} "
            f"< {req.paper_min_hit_rate:.2%} required"
        )
    if evidence.paper_max_drawdown_pct > req.paper_max_drawdown_pct:
        errors.append(
            f"paper max drawdown {evidence.paper_max_drawdown_pct:.1f}% "
            f"> {req.paper_max_drawdown_pct:.1f}% limit"
        )
    if evidence.quarantine_triggers > 0:
        errors.append(
            f"{evidence.quarantine_triggers} quarantine triggers during paper period"
        )
    if not evidence.cost_model_validated:
        errors.append("cost model has not been validated")

    return errors


def check_revalidation_gate(evidence: PromotionEvidence) -> list[str]:
    """Check evidence for QUARANTINED -> PAPER re-entry.

    Requires determinism re-confirmed and human-authored notes.
    """
    errors: list[str] = []
    if not evidence.determinism_test_passed:
        errors.append("determinism re-test has not passed")
    if not evidence.revalidation_notes.strip():
        errors.append("revalidation notes required (human review)")
    return errors


class AlphaLifecycle:
    """Manages the lifecycle state machine for a single alpha module.

    Wraps the platform's generic ``StateMachine`` with alpha-specific
    gate checks.  Transitions that fail gate checks are rejected with
    descriptive error messages.
    """

    def __init__(
        self,
        alpha_id: str,
        clock: Clock,
        gate_requirements: GateRequirements | None = None,
    ) -> None:
        self._alpha_id = alpha_id
        self._gate_requirements = gate_requirements or GateRequirements()
        self._sm = StateMachine(
            name=f"alpha_lifecycle:{alpha_id}",
            initial_state=AlphaLifecycleState.RESEARCH,
            transitions=_LIFECYCLE_TRANSITIONS,
            clock=clock,
        )

    @property
    def state(self) -> AlphaLifecycleState:
        return self._sm.state

    @property
    def alpha_id(self) -> str:
        return self._alpha_id

    @property
    def history(self) -> list:
        return self._sm.history

    def promote_to_paper(
        self,
        evidence: PromotionEvidence,
        *,
        correlation_id: str = "",
    ) -> list[str]:
        """Attempt RESEARCH -> PAPER promotion.

        Returns list of gate check errors (empty = success).
        """
        errors = check_paper_gate(evidence)
        if errors:
            return errors

        self._sm.transition(
            AlphaLifecycleState.PAPER,
            trigger="pass_paper_gate",
            correlation_id=correlation_id,
            metadata={"evidence": _evidence_to_dict(evidence)},
        )
        return []

    def promote_to_live(
        self,
        evidence: PromotionEvidence,
        *,
        correlation_id: str = "",
    ) -> list[str]:
        """Attempt PAPER -> LIVE promotion.

        Returns list of gate check errors (empty = success).
        """
        errors = check_live_gate(evidence, self._gate_requirements)
        if errors:
            return errors

        self._sm.transition(
            AlphaLifecycleState.LIVE,
            trigger="pass_live_gate",
            correlation_id=correlation_id,
            metadata={"evidence": _evidence_to_dict(evidence)},
        )
        return []

    def quarantine(
        self,
        reason: str,
        *,
        correlation_id: str = "",
    ) -> None:
        """LIVE -> QUARANTINED (typically auto-triggered by forensics)."""
        self._sm.transition(
            AlphaLifecycleState.QUARANTINED,
            trigger="edge_decay_detected",
            correlation_id=correlation_id,
            metadata={"reason": reason},
        )

    def revalidate_to_paper(
        self,
        evidence: PromotionEvidence,
        *,
        correlation_id: str = "",
    ) -> list[str]:
        """Attempt QUARANTINED -> PAPER re-entry.

        Returns list of gate check errors (empty = success).
        """
        errors = check_revalidation_gate(evidence)
        if errors:
            return errors

        self._sm.transition(
            AlphaLifecycleState.PAPER,
            trigger="revalidation_passed",
            correlation_id=correlation_id,
            metadata={"evidence": _evidence_to_dict(evidence)},
        )
        return []

    def decommission(
        self,
        reason: str,
        *,
        correlation_id: str = "",
    ) -> None:
        """QUARANTINED -> DECOMMISSIONED (terminal)."""
        self._sm.transition(
            AlphaLifecycleState.DECOMMISSIONED,
            trigger="decommissioned",
            correlation_id=correlation_id,
            metadata={"reason": reason},
        )

    @property
    def is_active(self) -> bool:
        """Whether the alpha should generate signals (PAPER or LIVE)."""
        return self._sm.state in (
            AlphaLifecycleState.PAPER,
            AlphaLifecycleState.LIVE,
        )

    @property
    def is_live(self) -> bool:
        """Whether the alpha is deployed with real capital."""
        return self._sm.state == AlphaLifecycleState.LIVE


def _evidence_to_dict(evidence: PromotionEvidence) -> dict[str, Any]:
    return {
        "paper_days": evidence.paper_days,
        "paper_sharpe": evidence.paper_sharpe,
        "paper_hit_rate": evidence.paper_hit_rate,
        "paper_max_drawdown_pct": evidence.paper_max_drawdown_pct,
        "determinism_test_passed": evidence.determinism_test_passed,
        "schema_valid": evidence.schema_valid,
        "feature_values_finite": evidence.feature_values_finite,
        "cost_model_validated": evidence.cost_model_validated,
        "quarantine_triggers": evidence.quarantine_triggers,
        "revalidation_notes": evidence.revalidation_notes,
    }
