"""Alpha lifecycle state machine and promotion gates.

Manages the progression of an alpha module from research through
paper trading to live capital deployment, with quarantine for
detected edge decay.

State transitions:
  RESEARCH -> PAPER         pass_paper_gate (schema valid, determinism OK)
  PAPER -> LIVE             pass_live_gate (evidence-based promotion)
  LIVE -> LIVE              promote_capital_tier (SMALL_CAPITAL -> SCALED;
                            metadata-only escalation, state stays LIVE)
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

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from feelies.alpha.promotion_evidence import (
    PROMOTE_CAPITAL_TIER_TRIGGER,
    CapitalStageEvidence,
    CapitalStageTier,
    GateId,
    GateThresholds,
    evidence_to_metadata,
    validate_gate,
)
from feelies.alpha.promotion_ledger import PromotionLedger, PromotionLedgerEntry
from feelies.core.clock import Clock
from feelies.core.state_machine import StateMachine, TransitionRecord

_logger = logging.getLogger(__name__)

_RESTORE_TOKEN: object = object()


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
    # LIVE -> LIVE is the Workstream F-6 capital-tier escalation
    # (SMALL_CAPITAL -> SCALED).  The lifecycle state is unchanged;
    # the tier flip is recorded as a metadata-only ledger entry whose
    # ``trigger`` distinguishes it from the LIVE -> QUARANTINED demotion.
    AlphaLifecycleState.LIVE: frozenset({
        AlphaLifecycleState.LIVE,
        AlphaLifecycleState.QUARANTINED,
    }),
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

    Two evidence paths are supported on every promote/revalidate
    method (Workstream **F-4**):

    1. **Structured path (preferred).**  Pass
       ``structured_evidence=[ResearchAcceptanceEvidence(...), ...]``.
       The lifecycle dispatches to
       :func:`feelies.alpha.promotion_evidence.validate_gate` against
       the gate-specific :class:`GateThresholds` (default values come
       from the testing-validation and post-trade-forensics skills,
       and Workstream **F-5** will allow per-alpha YAML overrides).
       The committed ledger entry's ``metadata`` is the JSON-safe
       projection produced by
       :func:`feelies.alpha.promotion_evidence.evidence_to_metadata`,
       carrying ``schema_version`` so :func:`metadata_to_evidence`
       can reverse it for forensic replay.

    2. **Legacy path (backwards compat).**  Pass a
       :class:`PromotionEvidence` positional / keyword.  The
       lifecycle dispatches to the lightweight
       ``check_paper_gate`` / ``check_live_gate`` /
       ``check_revalidation_gate`` validators against
       :class:`GateRequirements`.  The committed ledger entry's
       ``metadata`` is the loose ``{"evidence": {...}}`` shape used
       since Workstream F-1.

    Supplying *both* or *neither* raises :class:`ValueError` — the
    caller must pick one path.

    The two paths produce *different* metadata shapes on purpose: the
    structured payload is round-trippable through
    :func:`metadata_to_evidence` and the F-3 ``feelies promote
    replay-evidence`` CLI; the legacy payload retains the historical
    shape for pre-F-4 tooling.

    .. note::
       :py:meth:`quarantine` is a fail-safe demotion (Inv-11 — the
       state machine only tightens).  When ``structured_evidence`` is
       supplied, the per-evidence consistency validators
       (:func:`validate_quarantine_trigger`) are run for forensics:
       inconsistencies log a ``WARNING`` but do *not* block the
       transition.

    Workstream **F-6** added :py:meth:`promote_capital_tier` for the
    LIVE @ SMALL_CAPITAL -> LIVE @ SCALED escalation.  The lifecycle
    state remains ``LIVE`` (the tier is *evidence on LIVE*, not a
    distinct state), but the underlying state machine commits a
    ``LIVE -> LIVE`` self-loop transition with
    :data:`PROMOTE_CAPITAL_TIER_TRIGGER` so the ledger captures a
    durable provenance record.  See :py:meth:`current_capital_tier`
    for the live-epoch tier inference.
    """

    def __init__(
        self,
        alpha_id: str,
        clock: Clock,
        gate_requirements: GateRequirements | None = None,
        gate_thresholds: GateThresholds | None = None,
        ledger: PromotionLedger | None = None,
    ) -> None:
        self._alpha_id = alpha_id
        self._gate_requirements = gate_requirements or GateRequirements()
        self._gate_thresholds = gate_thresholds or GateThresholds()
        self._ledger = ledger
        # Workstream F-6 P1 fix: when ``restore()`` rehydrates an alpha
        # from a checkpoint, the in-memory ``StateMachine.history`` is
        # empty but the alpha may still have been at LIVE @ SCALED in
        # the previous process.  ``current_capital_tier`` consults this
        # fallback hint **only** when the live-epoch scan over history
        # is silent; once any fresh ``PAPER -> LIVE`` (or
        # ``PROMOTE_CAPITAL_TIER_TRIGGER``) record lands in history
        # post-restore, the scan finds it first and the hint is
        # naturally bypassed (history > hint).
        self._persisted_capital_tier: CapitalStageTier | None = None
        self._sm = StateMachine(
            name=f"alpha_lifecycle:{alpha_id}",
            initial_state=AlphaLifecycleState.RESEARCH,
            transitions=_LIFECYCLE_TRANSITIONS,
            clock=clock,
        )
        # Workstream F-1: forensic evidence ledger receives every
        # successfully-committed transition.  Wired through
        # ``StateMachine.on_transition`` (callbacks fire pre-commit, so
        # a ledger-write failure rolls the SM back atomically — Inv-13
        # provenance + Inv-11 fail-safe).
        if self._ledger is not None:
            self._sm.on_transition(self._record_to_ledger)

    @property
    def state(self) -> AlphaLifecycleState:
        return self._sm.state

    @property
    def alpha_id(self) -> str:
        return self._alpha_id

    @property
    def history(self) -> list[TransitionRecord]:
        return self._sm.history

    def promote_to_paper(
        self,
        evidence: PromotionEvidence | None = None,
        *,
        structured_evidence: Sequence[object] | None = None,
        correlation_id: str = "",
    ) -> list[str]:
        """Attempt RESEARCH -> PAPER promotion.

        Returns list of gate check errors (empty = success).

        Provide *either* ``evidence`` (legacy :class:`PromotionEvidence`
        path, validated by :func:`check_paper_gate`) *or*
        ``structured_evidence`` (Workstream F-4 path, validated by
        :func:`validate_gate` against
        :data:`GateId.RESEARCH_TO_PAPER`'s required evidence types).
        Supplying both or neither raises :class:`ValueError`.
        """
        legacy_ev, errors = self._select_evidence(
            evidence,
            structured_evidence,
            gate_id=GateId.RESEARCH_TO_PAPER,
            legacy_validator=check_paper_gate,
        )
        if errors:
            return errors

        metadata = self._build_metadata(legacy_ev, structured_evidence)
        self._sm.transition(
            AlphaLifecycleState.PAPER,
            trigger="pass_paper_gate",
            correlation_id=correlation_id,
            metadata=metadata,
        )
        return []

    def promote_to_live(
        self,
        evidence: PromotionEvidence | None = None,
        *,
        structured_evidence: Sequence[object] | None = None,
        correlation_id: str = "",
    ) -> list[str]:
        """Attempt PAPER -> LIVE promotion.

        Returns list of gate check errors (empty = success).

        Provide *either* ``evidence`` (legacy :class:`PromotionEvidence`
        path, validated by :func:`check_live_gate` against
        :class:`GateRequirements`) *or* ``structured_evidence``
        (Workstream F-4 path, validated by :func:`validate_gate`
        against :data:`GateId.PAPER_TO_LIVE`'s required evidence
        types — :class:`PaperWindowEvidence` + :class:`CPCVEvidence`
        + :class:`DSREvidence`).  Supplying both or neither raises
        :class:`ValueError`.
        """
        legacy_ev, errors = self._select_evidence(
            evidence,
            structured_evidence,
            gate_id=GateId.PAPER_TO_LIVE,
            legacy_validator=lambda ev: check_live_gate(
                ev, self._gate_requirements
            ),
        )
        if errors:
            return errors

        metadata = self._build_metadata(legacy_ev, structured_evidence)
        self._sm.transition(
            AlphaLifecycleState.LIVE,
            trigger="pass_live_gate",
            correlation_id=correlation_id,
            metadata=metadata,
        )
        return []

    def quarantine(
        self,
        reason: str,
        *,
        structured_evidence: Sequence[object] | None = None,
        correlation_id: str = "",
    ) -> None:
        """LIVE -> QUARANTINED (typically auto-triggered by forensics).

        Inv-11 fail-safe: a quarantine demotion **must** succeed —
        the validator is consistency-only.  When
        ``structured_evidence`` is supplied (typically a
        :class:`QuarantineTriggerEvidence`),
        :func:`validate_quarantine_trigger` runs for forensics and any
        "spurious-trigger" complaints are logged at ``WARNING``
        without blocking the transition.

        The committed ledger entry's ``metadata`` always carries
        ``{"reason": reason}``; structured evidence is merged in as
        additional kind-keyed sections plus a ``schema_version``.
        """
        metadata: dict[str, Any] = {"reason": reason}
        if structured_evidence is not None:
            warnings = validate_gate(
                GateId.LIVE_TO_QUARANTINED,
                structured_evidence,
                self._gate_thresholds,
            )
            if warnings:
                _logger.warning(
                    "alpha %r quarantine trigger evidence is suspicious "
                    "(transition still committed per Inv-11 fail-safe): %s",
                    self._alpha_id,
                    "; ".join(warnings),
                )
            metadata.update(evidence_to_metadata(*structured_evidence))

        self._sm.transition(
            AlphaLifecycleState.QUARANTINED,
            trigger="edge_decay_detected",
            correlation_id=correlation_id,
            metadata=metadata,
        )

    def revalidate_to_paper(
        self,
        evidence: PromotionEvidence | None = None,
        *,
        structured_evidence: Sequence[object] | None = None,
        correlation_id: str = "",
    ) -> list[str]:
        """Attempt QUARANTINED -> PAPER re-entry.

        Returns list of gate check errors (empty = success).

        Provide *either* ``evidence`` (legacy :class:`PromotionEvidence`
        path, validated by :func:`check_revalidation_gate`) *or*
        ``structured_evidence`` (Workstream F-4 path, validated by
        :func:`validate_gate` against
        :data:`GateId.QUARANTINED_TO_PAPER`'s required evidence
        types — :class:`RevalidationEvidence`).  Supplying both or
        neither raises :class:`ValueError`.
        """
        legacy_ev, errors = self._select_evidence(
            evidence,
            structured_evidence,
            gate_id=GateId.QUARANTINED_TO_PAPER,
            legacy_validator=check_revalidation_gate,
        )
        if errors:
            return errors

        metadata = self._build_metadata(legacy_ev, structured_evidence)
        self._sm.transition(
            AlphaLifecycleState.PAPER,
            trigger="revalidation_passed",
            correlation_id=correlation_id,
            metadata=metadata,
        )
        return []

    def promote_capital_tier(
        self,
        evidence: CapitalStageEvidence,
        *,
        correlation_id: str = "",
    ) -> list[str]:
        """Attempt LIVE @ SMALL_CAPITAL -> LIVE @ SCALED escalation.

        The lifecycle state stays ``LIVE``; the capital tier flips
        from ``SMALL_CAPITAL`` to ``SCALED`` as recorded by a
        ``LIVE -> LIVE`` self-loop transition with the
        :data:`PROMOTE_CAPITAL_TIER_TRIGGER` trigger.  The supplied
        :class:`CapitalStageEvidence` is the small-capital window's
        execution-quality and PnL-compression summary; the validator
        enforces every threshold from the testing-validation skill's
        Small-Capital exit criteria via
        :data:`GateId.LIVE_PROMOTE_CAPITAL_TIER`.

        Returns the list of gate-check errors (empty = success).  No
        ``IllegalTransition`` is raised when the alpha is not in LIVE
        or is already at SCALED — the caller receives a descriptive
        error string instead, mirroring :py:meth:`promote_to_paper`
        and friends.

        Unlike the other promote/revalidate methods this one is
        structured-evidence-only: there is no legacy
        :class:`PromotionEvidence` shape that captures the
        Small-Capital exit criteria, so accepting one would be
        ambiguous.
        """
        errors: list[str] = []

        if self._sm.state is not AlphaLifecycleState.LIVE:
            errors.append(
                f"capital-tier promotion requires state=LIVE; "
                f"current state is {self._sm.state.name}"
            )
            return errors

        current_tier = self.current_capital_tier
        if current_tier is CapitalStageTier.SCALED:
            errors.append(
                "capital-tier promotion already complete: alpha is at "
                "tier=SCALED; no further escalation defined"
            )
            return errors

        gate_errors = validate_gate(
            GateId.LIVE_PROMOTE_CAPITAL_TIER,
            (evidence,),
            self._gate_thresholds,
        )
        if gate_errors:
            return list(gate_errors)

        metadata = evidence_to_metadata(evidence)
        self._sm.transition(
            AlphaLifecycleState.LIVE,
            trigger=PROMOTE_CAPITAL_TIER_TRIGGER,
            correlation_id=correlation_id,
            metadata=metadata,
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

    @property
    def current_capital_tier(self) -> CapitalStageTier | None:
        """Capital-stage tier of the *current* LIVE epoch.

        Returns ``None`` when the alpha is not currently in the LIVE
        state (capital tier is only meaningful while live).

        Otherwise scans :py:attr:`history` backwards from the most
        recent record to the most recent transition *into* LIVE
        (typically a ``PAPER -> LIVE`` promotion or a
        ``QUARANTINED -> PAPER`` revalidation followed by another
        promotion to LIVE).  The tier returned is:

        * :attr:`CapitalStageTier.SCALED` if at least one
          ``LIVE -> LIVE`` self-loop with
          :data:`PROMOTE_CAPITAL_TIER_TRIGGER` is present in the
          current epoch.
        * :attr:`CapitalStageTier.SMALL_CAPITAL` otherwise (the
          default at first entry into LIVE).

        Quarantine -> revalidate -> LIVE re-entry resets the tier
        back to ``SMALL_CAPITAL`` because the LIVE-entry transition
        starts a new epoch.
        """
        if self._sm.state is not AlphaLifecycleState.LIVE:
            return None
        live_name = AlphaLifecycleState.LIVE.name
        history = self._sm.history
        for record in reversed(history):
            if record.trigger == PROMOTE_CAPITAL_TIER_TRIGGER:
                return CapitalStageTier.SCALED
            if record.to_state == live_name and record.from_state != live_name:
                return CapitalStageTier.SMALL_CAPITAL
        # History exhausted without determining the tier — fall back to
        # the hint persisted at checkpoint time, if any.  This matters
        # when ``restore()`` rehydrates an alpha that reached
        # ``LIVE @ SCALED`` in a prior process: the in-memory history
        # is empty but the alpha is still SCALED for the operator.
        # Without this fallback, ``promote_capital_tier()`` would
        # happily commit a *duplicate* SCALED escalation post-restart
        # because the SCALED-rejection guard would mis-read the tier
        # as SMALL_CAPITAL.
        if self._persisted_capital_tier is not None:
            return self._persisted_capital_tier
        return CapitalStageTier.SMALL_CAPITAL

    # ── Evidence dispatch helpers (Workstream F-4) ───────────

    def _select_evidence(
        self,
        evidence: PromotionEvidence | None,
        structured_evidence: Sequence[object] | None,
        *,
        gate_id: GateId,
        legacy_validator: Any,
    ) -> tuple[PromotionEvidence | None, list[str]]:
        """Resolve which evidence path to use and run its validator.

        Enforces the "exactly one of ``evidence``/``structured_evidence``"
        contract.  Returns ``(legacy_evidence_or_None,
        validation_errors)``: the legacy evidence is forwarded back so
        :py:meth:`_build_metadata` can project it; the structured
        evidence sequence is captured by the closure for the same
        purpose.

        Raises :class:`ValueError` if both or neither path is supplied.
        """
        if evidence is not None and structured_evidence is not None:
            raise ValueError(
                "AlphaLifecycle: supply either 'evidence' (legacy "
                "PromotionEvidence) or 'structured_evidence' "
                "(Workstream F-4 sequence), not both"
            )
        if evidence is None and structured_evidence is None:
            raise ValueError(
                "AlphaLifecycle: must supply either 'evidence' "
                "(legacy PromotionEvidence) or 'structured_evidence' "
                "(Workstream F-4 sequence)"
            )
        if structured_evidence is not None:
            errors = validate_gate(
                gate_id, structured_evidence, self._gate_thresholds
            )
            return None, errors
        # legacy path
        assert evidence is not None  # narrowed by the early returns above
        errors = legacy_validator(evidence)
        return evidence, list(errors)

    def _build_metadata(
        self,
        legacy_evidence: PromotionEvidence | None,
        structured_evidence: Sequence[object] | None,
    ) -> dict[str, Any]:
        """Project the chosen evidence path into ledger metadata.

        Legacy path → ``{"evidence": _evidence_to_dict(ev)}`` (the
        F-1 shape).  Structured path → :func:`evidence_to_metadata`
        output (carries ``schema_version`` + kind-keyed sections,
        round-trippable via :func:`metadata_to_evidence`).
        """
        if structured_evidence is not None:
            return evidence_to_metadata(*structured_evidence)
        assert legacy_evidence is not None
        return {"evidence": _evidence_to_dict(legacy_evidence)}

    # ── Promotion ledger ─────────────────────────────────────

    def _record_to_ledger(self, record: TransitionRecord) -> None:
        """``StateMachine.on_transition`` callback that projects a
        ``TransitionRecord`` into a :class:`PromotionLedgerEntry` and
        appends it.  Only attached when a ledger is provided.
        """
        assert self._ledger is not None  # invariant: only registered when set
        entry = PromotionLedgerEntry(
            alpha_id=self._alpha_id,
            from_state=record.from_state,
            to_state=record.to_state,
            trigger=record.trigger,
            timestamp_ns=record.timestamp_ns,
            correlation_id=record.correlation_id,
            metadata=dict(record.metadata),
        )
        self._ledger.append(entry)

    # ── Persistence ──────────────────────────────────────────

    def checkpoint(self) -> bytes:
        """Serialize lifecycle state for persistence.

        Returns a JSON-encoded blob containing the current state name
        and — when the alpha is currently in ``LIVE`` — the capital
        tier of the live epoch.

        The ``capital_tier`` field was added by Workstream **F-6 P1**:
        without it, restoring a ``LIVE @ SCALED`` alpha from a prior
        process would silently revert the in-memory tier to
        ``SMALL_CAPITAL`` (because the inferred tier reads
        ``StateMachine.history``, which is empty after restore), and a
        subsequent ``promote_capital_tier()`` call would commit a
        *duplicate* SCALED escalation to the ledger.  The field is
        only emitted when ``state == LIVE`` because the tier is
        meaningless in any other state (mirrors
        :py:attr:`current_capital_tier`).

        The format is forward-compatible: older blobs without
        ``capital_tier`` restore as ``SMALL_CAPITAL`` (the historic
        default), so existing on-disk checkpoints remain loadable.
        """
        payload: dict[str, Any] = {
            "alpha_id": self._alpha_id,
            "state": self._sm.state.name,
        }
        if self._sm.state is AlphaLifecycleState.LIVE:
            tier = self.current_capital_tier
            assert tier is not None  # state==LIVE => tier defined
            payload["capital_tier"] = tier.name
        return json.dumps(payload).encode()

    def restore(self, data: bytes) -> None:
        """Restore lifecycle state from a checkpoint.

        Raises ``ValueError`` if the data is corrupt or references an
        unknown state or capital tier.
        """
        try:
            payload = json.loads(data.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(
                f"Corrupt lifecycle checkpoint for '{self._alpha_id}'"
            ) from exc

        state_name = payload.get("state")
        if state_name is None:
            raise ValueError(
                f"Missing 'state' in lifecycle checkpoint for '{self._alpha_id}'"
            )

        try:
            target = AlphaLifecycleState[state_name]
        except KeyError:
            raise ValueError(
                f"Unknown lifecycle state '{state_name}' in checkpoint "
                f"for '{self._alpha_id}'"
            )

        # Rehydrate the F-6 capital-tier hint *before* the state is
        # actually flipped: ``current_capital_tier`` consults the hint
        # only after exhausting history, so the order doesn't change
        # behavior, but persisted-tier-before-state-set keeps the
        # invariant tidy (no transient window where state==LIVE and
        # the tier hint is stale).
        tier_name = payload.get("capital_tier")
        if tier_name is not None:
            if target is not AlphaLifecycleState.LIVE:
                raise ValueError(
                    f"checkpoint for '{self._alpha_id}' carries "
                    f"capital_tier={tier_name!r} but state={state_name!r} "
                    f"(capital tier is only meaningful in LIVE)"
                )
            try:
                self._persisted_capital_tier = CapitalStageTier[tier_name]
            except KeyError:
                raise ValueError(
                    f"Unknown capital_tier '{tier_name}' in checkpoint "
                    f"for '{self._alpha_id}'"
                )
        else:
            # Legacy checkpoint (pre-F-6) or non-LIVE state — clear any
            # hint from a prior restore to avoid stale-fallback bugs.
            self._persisted_capital_tier = None

        self._restore_to_checkpoint(target, _RESTORE_TOKEN)

    def _restore_to_checkpoint(
        self,
        target: AlphaLifecycleState,
        token: object,
    ) -> None:
        """Set lifecycle state directly — restricted to holders of the
        sentinel token (i.e. this module and the registry).
        """
        if token is not _RESTORE_TOKEN:
            raise PermissionError(
                "Direct state restoration requires the internal token. "
                "Use restore(data) instead."
            )
        self._sm._state = target  # noqa: SLF001


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
