"""Workstream F-4: structured-evidence path tests for AlphaLifecycle.

These tests exercise the new ``structured_evidence=...`` keyword on
every promote/revalidate/quarantine method.  The legacy
``PromotionEvidence`` path is covered by ``test_lifecycle.py``; the
two test files must stay green in lockstep.

Coverage axes:
  * happy path per gate (RESEARCH→PAPER, PAPER→LIVE, QUARANTINED→PAPER)
  * sad path per gate (validator returns errors → no transition,
    no ledger write)
  * missing-required-evidence error surfacing
  * exclusivity invariants (both paths supplied, neither path
    supplied)
  * quarantine consistency-only behaviour (Inv-11: spurious trigger
    evidence still commits the demotion, with a logged warning)
  * registry-level forwarding of ``structured_evidence``
  * round-trip metadata payload through
    :func:`feelies.alpha.promotion_evidence.metadata_to_evidence`
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from feelies.alpha.lifecycle import (
    AlphaLifecycle,
    AlphaLifecycleState,
    GateRequirements,
    PromotionEvidence,
)
from feelies.alpha.module import AlphaManifest, AlphaRiskBudget
from feelies.alpha.promotion_evidence import (
    EVIDENCE_SCHEMA_VERSION,
    CapitalStageEvidence,
    CapitalStageTier,
    CPCVEvidence,
    DSREvidence,
    GateThresholds,
    PaperWindowEvidence,
    QuarantineTriggerEvidence,
    ResearchAcceptanceEvidence,
    RevalidationEvidence,
    metadata_to_evidence,
)
from feelies.alpha.promotion_ledger import PromotionLedger
from feelies.alpha.registry import AlphaRegistry, AlphaRegistryError
from feelies.core.clock import SimulatedClock
from feelies.features.definition import FeatureDefinition

# ── Helpers ────────────────────────────────────────────────────────


def _passing_research_acceptance() -> ResearchAcceptanceEvidence:
    return ResearchAcceptanceEvidence(
        schema_valid=True,
        determinism_replay_passed=True,
        branch_coverage_pct=92.0,
        line_coverage_pct=85.0,
        lookahead_bias_check_passed=True,
        fault_injection_pass_count=12,
        fault_injection_total=12,
        cost_sensitivity_passed=True,
        latency_sensitivity_passed=True,
    )


def _passing_paper_window() -> PaperWindowEvidence:
    return PaperWindowEvidence(
        trading_days=10,
        sample_size=400,
        slippage_residual_bps=0.7,
        fill_rate_drift_pct=2.0,
        latency_ks_p=0.5,
        pnl_compression_ratio=0.85,
        anomalous_event_count=0,
    )


def _passing_cpcv() -> CPCVEvidence:
    return CPCVEvidence(
        fold_count=8,
        embargo_bars=10,
        fold_sharpes=(1.1, 1.3, 0.9, 1.4, 1.2, 1.0, 1.5, 1.1),
        mean_sharpe=1.1875,
        median_sharpe=1.15,
        mean_pnl=4200.0,
        p_value=0.012,
        fold_pnl_curves_hash="sha256:abc123",
    )


def _passing_dsr() -> DSREvidence:
    return DSREvidence(
        observed_sharpe=1.6,
        trials_count=18,
        skewness=-0.1,
        kurtosis=3.2,
        dsr=1.25,
        dsr_p_value=0.018,
    )


def _passing_revalidation() -> RevalidationEvidence:
    return RevalidationEvidence(
        hypothesis_re_derived=True,
        oos_walkforward_sharpe=1.4,
        parameter_drift_resolved=True,
        human_signoff="pm-jane.doe",
        revalidation_notes="Re-derived from current order-book regime; "
        "drift resolved by parameter recalibration on 2026-Q1 data.",
    )


def _quarantine_evidence_real() -> QuarantineTriggerEvidence:
    """Quarantine trigger evidence that crosses at least one threshold."""
    return QuarantineTriggerEvidence(
        net_alpha_negative_days=12,  # ≥ default 10 → trigger
        hit_rate_residual_pp=-3.0,
        microstructure_metrics_breached=(),
        crowding_symptoms=(),
        pnl_compression_ratio_5d=0.8,
    )


def _quarantine_evidence_spurious() -> QuarantineTriggerEvidence:
    """All metrics nominal → validator complains 'spurious trigger'."""
    return QuarantineTriggerEvidence(
        net_alpha_negative_days=2,
        hit_rate_residual_pp=-1.0,
        microstructure_metrics_breached=(),
        crowding_symptoms=(),
        pnl_compression_ratio_5d=0.95,
    )


def _walk_to_paper(lc: AlphaLifecycle) -> None:
    errors = lc.promote_to_paper(
        structured_evidence=[_passing_research_acceptance()],
    )
    assert errors == []


def _walk_to_live(lc: AlphaLifecycle) -> None:
    _walk_to_paper(lc)
    errors = lc.promote_to_live(
        structured_evidence=[
            _passing_paper_window(),
            _passing_cpcv(),
            _passing_dsr(),
        ],
    )
    assert errors == []


# ── promote_to_paper ───────────────────────────────────────────────


class TestPromoteToPaperStructured:
    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    def test_happy_path_transitions(self, clock: SimulatedClock) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        errors = lc.promote_to_paper(
            structured_evidence=[_passing_research_acceptance()],
            correlation_id="c1",
        )
        assert errors == []
        assert lc.state == AlphaLifecycleState.PAPER

    def test_failed_research_validator_blocks_transition(
        self, clock: SimulatedClock
    ) -> None:
        bad = ResearchAcceptanceEvidence(
            schema_valid=False,
            determinism_replay_passed=False,
            branch_coverage_pct=10.0,
            line_coverage_pct=5.0,
            lookahead_bias_check_passed=False,
            fault_injection_pass_count=0,
            fault_injection_total=0,
            cost_sensitivity_passed=False,
            latency_sensitivity_passed=False,
        )
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        errors = lc.promote_to_paper(structured_evidence=[bad])
        assert len(errors) > 0
        assert lc.state == AlphaLifecycleState.RESEARCH

    def test_missing_required_evidence_blocks_transition(
        self, clock: SimulatedClock
    ) -> None:
        # No ResearchAcceptanceEvidence in the sequence.
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        errors = lc.promote_to_paper(structured_evidence=[])
        assert any(
            "ResearchAcceptanceEvidence" in e and "none was supplied" in e
            for e in errors
        )
        assert lc.state == AlphaLifecycleState.RESEARCH

    def test_unsupported_evidence_type_blocks_transition(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)

        class NotEvidence:
            pass

        errors = lc.promote_to_paper(structured_evidence=[NotEvidence()])
        assert any(
            "unsupported evidence type" in e for e in errors
        )
        assert lc.state == AlphaLifecycleState.RESEARCH

    def test_neither_evidence_nor_structured_raises(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        with pytest.raises(ValueError, match="must supply either"):
            lc.promote_to_paper()

    def test_both_evidence_paths_raises(self, clock: SimulatedClock) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        legacy = PromotionEvidence(
            schema_valid=True,
            determinism_test_passed=True,
            feature_values_finite=True,
        )
        with pytest.raises(ValueError, match="either.*not both|not both"):
            lc.promote_to_paper(
                legacy,
                structured_evidence=[_passing_research_acceptance()],
            )


# ── promote_to_live ────────────────────────────────────────────────


class TestPromoteToLiveStructured:
    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    def test_happy_path_transitions(self, clock: SimulatedClock) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_paper(lc)
        errors = lc.promote_to_live(
            structured_evidence=[
                _passing_paper_window(),
                _passing_cpcv(),
                _passing_dsr(),
            ],
        )
        assert errors == []
        assert lc.state == AlphaLifecycleState.LIVE

    def test_missing_cpcv_evidence_blocks_transition(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_paper(lc)
        errors = lc.promote_to_live(
            structured_evidence=[_passing_paper_window(), _passing_dsr()],
        )
        assert any("CPCVEvidence" in e for e in errors)
        assert lc.state == AlphaLifecycleState.PAPER

    def test_low_cpcv_sharpe_blocks_transition(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_paper(lc)
        bad_cpcv = CPCVEvidence(
            fold_count=8,
            embargo_bars=10,
            fold_sharpes=(0.1, 0.2, 0.0, 0.1, 0.0, 0.05, 0.1, 0.0),
            mean_sharpe=0.07,
            median_sharpe=0.08,
            mean_pnl=100.0,
            p_value=0.40,
            fold_pnl_curves_hash="sha256:bad",
        )
        errors = lc.promote_to_live(
            structured_evidence=[
                _passing_paper_window(),
                bad_cpcv,
                _passing_dsr(),
            ],
        )
        assert any("Sharpe" in e for e in errors)
        assert lc.state == AlphaLifecycleState.PAPER

    def test_low_dsr_blocks_transition(self, clock: SimulatedClock) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_paper(lc)
        bad_dsr = DSREvidence(
            observed_sharpe=1.6,
            trials_count=18,
            skewness=-0.1,
            kurtosis=3.2,
            dsr=0.4,
            dsr_p_value=0.6,
        )
        errors = lc.promote_to_live(
            structured_evidence=[
                _passing_paper_window(),
                _passing_cpcv(),
                bad_dsr,
            ],
        )
        assert any("DSR" in e for e in errors)
        assert lc.state == AlphaLifecycleState.PAPER

    def test_short_paper_window_blocks_transition(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_paper(lc)
        bad_paper = PaperWindowEvidence(
            trading_days=2,
            sample_size=10,
            slippage_residual_bps=0.7,
            fill_rate_drift_pct=2.0,
            latency_ks_p=0.5,
            pnl_compression_ratio=0.85,
            anomalous_event_count=0,
        )
        errors = lc.promote_to_live(
            structured_evidence=[bad_paper, _passing_cpcv(), _passing_dsr()],
        )
        assert any("trading_days" in e for e in errors)
        assert lc.state == AlphaLifecycleState.PAPER


# ── revalidate_to_paper ───────────────────────────────────────────


class TestRevalidateToPaperStructured:
    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    def test_happy_path_transitions(self, clock: SimulatedClock) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        lc.quarantine("ic decay")
        errors = lc.revalidate_to_paper(
            structured_evidence=[_passing_revalidation()],
        )
        assert errors == []
        assert lc.state == AlphaLifecycleState.PAPER

    def test_missing_human_signoff_blocks_transition(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        lc.quarantine("ic decay")

        bad = RevalidationEvidence(
            hypothesis_re_derived=True,
            oos_walkforward_sharpe=1.4,
            parameter_drift_resolved=True,
            human_signoff="",
            revalidation_notes="notes",
        )
        errors = lc.revalidate_to_paper(structured_evidence=[bad])
        assert any("human_signoff" in e for e in errors)
        assert lc.state == AlphaLifecycleState.QUARANTINED


# ── quarantine (consistency-only validator) ────────────────────────


class TestQuarantineStructured:
    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    @pytest.fixture
    def ledger(self, tmp_path: Path) -> PromotionLedger:
        return PromotionLedger(tmp_path / "promotion.jsonl")

    def test_real_trigger_evidence_no_warning(
        self,
        clock: SimulatedClock,
        ledger: PromotionLedger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock, ledger=ledger)
        _walk_to_live(lc)

        with caplog.at_level(logging.WARNING, logger="feelies.alpha.lifecycle"):
            lc.quarantine(
                "net_alpha < 0 for 12 days",
                structured_evidence=[_quarantine_evidence_real()],
            )

        assert lc.state == AlphaLifecycleState.QUARANTINED
        # No spurious-trigger warning expected — the evidence crossed a
        # documented threshold (≥ 10 negative-net-alpha days).
        assert not any(
            "spurious" in rec.getMessage()
            for rec in caplog.records
            if rec.name == "feelies.alpha.lifecycle"
        )

    def test_spurious_trigger_evidence_logs_warning_but_commits(
        self,
        clock: SimulatedClock,
        ledger: PromotionLedger,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Inv-11 fail-safe: the demotion MUST commit even when the
        # trigger evidence is below every documented threshold.
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock, ledger=ledger)
        _walk_to_live(lc)

        with caplog.at_level(logging.WARNING, logger="feelies.alpha.lifecycle"):
            lc.quarantine(
                "manual override",
                structured_evidence=[_quarantine_evidence_spurious()],
            )

        assert lc.state == AlphaLifecycleState.QUARANTINED
        assert any(
            "suspicious" in rec.getMessage()
            for rec in caplog.records
            if rec.name == "feelies.alpha.lifecycle"
        )

    def test_metadata_carries_reason_and_evidence_payload(
        self, clock: SimulatedClock, ledger: PromotionLedger
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock, ledger=ledger)
        _walk_to_live(lc)
        lc.quarantine(
            "net_alpha < 0 for 12 days",
            structured_evidence=[_quarantine_evidence_real()],
        )

        last = list(ledger.entries())[-1]
        assert last.to_state == "QUARANTINED"
        assert last.metadata["reason"] == "net_alpha < 0 for 12 days"
        assert last.metadata["schema_version"] == EVIDENCE_SCHEMA_VERSION
        assert "quarantine_trigger" in last.metadata

    def test_no_structured_evidence_writes_legacy_reason_only(
        self, clock: SimulatedClock, ledger: PromotionLedger
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock, ledger=ledger)
        _walk_to_live(lc)
        lc.quarantine("ic decay")

        last = list(ledger.entries())[-1]
        assert last.metadata == {"reason": "ic decay"}


# ── Ledger metadata invariants for the structured path ─────────────


class TestLedgerMetadataStructured:
    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    @pytest.fixture
    def ledger(self, tmp_path: Path) -> PromotionLedger:
        return PromotionLedger(tmp_path / "promotion.jsonl")

    def test_research_to_paper_metadata_round_trips(
        self, clock: SimulatedClock, ledger: PromotionLedger
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock, ledger=ledger)
        ev = _passing_research_acceptance()
        lc.promote_to_paper(structured_evidence=[ev])

        last = list(ledger.entries())[-1]
        assert last.metadata["schema_version"] == EVIDENCE_SCHEMA_VERSION

        reconstructed = metadata_to_evidence(last.metadata)
        assert len(reconstructed) == 1
        assert isinstance(reconstructed[0], ResearchAcceptanceEvidence)
        assert reconstructed[0] == ev

    def test_paper_to_live_metadata_round_trips_three_evidences(
        self, clock: SimulatedClock, ledger: PromotionLedger
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock, ledger=ledger)
        _walk_to_paper(lc)

        paper = _passing_paper_window()
        cpcv = _passing_cpcv()
        dsr = _passing_dsr()
        lc.promote_to_live(structured_evidence=[paper, cpcv, dsr])

        last = list(ledger.entries())[-1]
        reconstructed = metadata_to_evidence(last.metadata)
        kinds = sorted(type(e).__name__ for e in reconstructed)
        assert kinds == ["CPCVEvidence", "DSREvidence", "PaperWindowEvidence"]

    def test_failed_promotion_does_not_write_ledger(
        self, clock: SimulatedClock, ledger: PromotionLedger
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock, ledger=ledger)
        bad = ResearchAcceptanceEvidence(schema_valid=False)
        errors = lc.promote_to_paper(structured_evidence=[bad])
        assert errors  # gate rejected
        assert list(ledger.entries()) == []
        assert lc.state == AlphaLifecycleState.RESEARCH


# ── Threshold customization ────────────────────────────────────────


class TestGateThresholds:
    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    def test_custom_thresholds_relaxed_lets_borderline_pass(
        self, clock: SimulatedClock
    ) -> None:
        relaxed = GateThresholds(
            research_min_branch_coverage_pct=50.0,
            research_min_line_coverage_pct=40.0,
        )
        lc = AlphaLifecycle(
            alpha_id="kyle", clock=clock, gate_thresholds=relaxed
        )
        borderline = ResearchAcceptanceEvidence(
            schema_valid=True,
            determinism_replay_passed=True,
            branch_coverage_pct=55.0,
            line_coverage_pct=45.0,
            lookahead_bias_check_passed=True,
            fault_injection_pass_count=10,
            fault_injection_total=10,
            cost_sensitivity_passed=True,
            latency_sensitivity_passed=True,
        )
        errors = lc.promote_to_paper(structured_evidence=[borderline])
        assert errors == []

    def test_custom_thresholds_tightened_rejects_default_pass(
        self, clock: SimulatedClock
    ) -> None:
        tightened = GateThresholds(research_min_branch_coverage_pct=99.0)
        lc = AlphaLifecycle(
            alpha_id="kyle", clock=clock, gate_thresholds=tightened
        )
        ev = _passing_research_acceptance()  # 92% branch coverage
        errors = lc.promote_to_paper(structured_evidence=[ev])
        assert any("branch coverage" in e for e in errors)
        assert lc.state == AlphaLifecycleState.RESEARCH


# ── Capital-stage tier validator (gate matrix entry, no SM transition) ─


class TestCapitalStageEvidenceValidatorOnly:
    """Workstream F-4 wires *state-changing* gates only; the
    LIVE@SMALL→LIVE@SCALED capital-tier escalation is deferred to
    F-6 (LIVE→LIVE self-loop is a separate architectural change).

    Until then, callers can exercise the validator directly through
    :func:`feelies.alpha.promotion_evidence.validate_gate` — that
    surface is already covered by ``test_promotion_evidence.py``,
    so this test only documents the placeholder.
    """

    def test_capital_stage_validator_remains_callable(self) -> None:
        from feelies.alpha.promotion_evidence import GateId, validate_gate

        good = CapitalStageEvidence(
            tier=CapitalStageTier.SMALL_CAPITAL,
            allocation_fraction=0.01,
            deployment_days=12,
            pnl_compression_ratio_realised=0.85,
            slippage_residual_bps=1.2,
            hit_rate_residual_pp=-2.0,
            fill_rate_drift_pct=3.0,
        )
        assert validate_gate(GateId.LIVE_PROMOTE_CAPITAL_TIER, [good]) == []


# ── AlphaRegistry forwarding ───────────────────────────────────────


class _StubModule:
    """Minimal AlphaModule implementation for registry tests."""

    def __init__(self, alpha_id: str, layer: str = "SIGNAL") -> None:
        self._manifest = AlphaManifest(
            alpha_id=alpha_id,
            version="1.0.0",
            description=f"stub for {alpha_id}",
            hypothesis="test",
            falsification_criteria=("none",),
            required_features=frozenset(),
            layer=layer,
            risk_budget=AlphaRiskBudget(
                max_position_per_symbol=100,
                max_gross_exposure_pct=5.0,
                max_drawdown_pct=1.0,
                capital_allocation_pct=10.0,
            ),
        )

    @property
    def manifest(self) -> AlphaManifest:
        return self._manifest

    def feature_definitions(self) -> tuple[FeatureDefinition, ...]:
        return ()

    def validate(self) -> list[str]:
        return []


class TestAlphaRegistryStructuredEvidence:
    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    def test_registry_promote_forwards_structured_evidence(
        self, clock: SimulatedClock
    ) -> None:
        registry = AlphaRegistry(clock=clock)
        registry.register(_StubModule("kyle"))

        errors = registry.promote(
            "kyle",
            structured_evidence=[_passing_research_acceptance()],
            correlation_id="c1",
        )
        assert errors == []
        assert registry.lifecycle_states()["kyle"] == AlphaLifecycleState.PAPER

    def test_registry_promote_forwards_to_live(
        self, clock: SimulatedClock
    ) -> None:
        registry = AlphaRegistry(clock=clock)
        registry.register(_StubModule("kyle"))
        registry.promote(
            "kyle", structured_evidence=[_passing_research_acceptance()]
        )

        errors = registry.promote(
            "kyle",
            structured_evidence=[
                _passing_paper_window(),
                _passing_cpcv(),
                _passing_dsr(),
            ],
        )
        assert errors == []
        assert registry.lifecycle_states()["kyle"] == AlphaLifecycleState.LIVE

    def test_registry_quarantine_forwards_structured_evidence(
        self, clock: SimulatedClock, tmp_path: Path
    ) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        registry = AlphaRegistry(clock=clock, promotion_ledger=ledger)
        registry.register(_StubModule("kyle"))

        registry.promote(
            "kyle", structured_evidence=[_passing_research_acceptance()]
        )
        registry.promote(
            "kyle",
            structured_evidence=[
                _passing_paper_window(),
                _passing_cpcv(),
                _passing_dsr(),
            ],
        )
        registry.quarantine(
            "kyle",
            "ic decay",
            structured_evidence=[_quarantine_evidence_real()],
            correlation_id="quarantine-1",
        )

        last = list(ledger.entries())[-1]
        assert last.to_state == "QUARANTINED"
        assert last.metadata["reason"] == "ic decay"
        assert "quarantine_trigger" in last.metadata
        assert last.correlation_id == "quarantine-1"

    def test_registry_neither_path_raises(
        self, clock: SimulatedClock
    ) -> None:
        registry = AlphaRegistry(clock=clock)
        registry.register(_StubModule("kyle"))
        with pytest.raises(ValueError, match="must supply either"):
            registry.promote("kyle")

    def test_registry_both_paths_raises(self, clock: SimulatedClock) -> None:
        registry = AlphaRegistry(clock=clock)
        registry.register(_StubModule("kyle"))
        legacy = PromotionEvidence(
            schema_valid=True,
            determinism_test_passed=True,
            feature_values_finite=True,
        )
        with pytest.raises(ValueError):
            registry.promote(
                "kyle",
                legacy,
                structured_evidence=[_passing_research_acceptance()],
            )

    def test_registry_unregistered_alpha_raises(
        self, clock: SimulatedClock
    ) -> None:
        registry = AlphaRegistry(clock=clock)
        with pytest.raises(KeyError):
            registry.promote(
                "missing",
                structured_evidence=[_passing_research_acceptance()],
            )

    def test_registry_no_clock_raises(self) -> None:
        registry = AlphaRegistry()
        registry.register(_StubModule("kyle"))
        with pytest.raises(AlphaRegistryError):
            registry.promote(
                "kyle",
                structured_evidence=[_passing_research_acceptance()],
            )

    def test_registry_uses_custom_gate_thresholds(
        self, clock: SimulatedClock
    ) -> None:
        tightened = GateThresholds(research_min_branch_coverage_pct=99.0)
        registry = AlphaRegistry(clock=clock, gate_thresholds=tightened)
        registry.register(_StubModule("kyle"))

        errors = registry.promote(
            "kyle",
            structured_evidence=[_passing_research_acceptance()],
        )
        assert any("branch coverage" in e for e in errors)
        assert registry.lifecycle_states()["kyle"] == AlphaLifecycleState.RESEARCH


# ── Mixed-path workflow (legacy + structured can coexist per alpha) ─


class TestMixedPathWorkflow:
    """Legacy and structured paths can be mixed across a single
    alpha's lifecycle (e.g. structured PAPER promotion, legacy LIVE
    promotion).  Each method picks its path independently.
    """

    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    def test_structured_paper_then_legacy_live(
        self, clock: SimulatedClock
    ) -> None:
        gate = GateRequirements(paper_min_days=1, paper_min_sharpe=0.0)
        lc = AlphaLifecycle(
            alpha_id="kyle", clock=clock, gate_requirements=gate
        )
        # Structured RESEARCH→PAPER
        errors = lc.promote_to_paper(
            structured_evidence=[_passing_research_acceptance()]
        )
        assert errors == []
        assert lc.state == AlphaLifecycleState.PAPER

        # Legacy PAPER→LIVE (using the loose PromotionEvidence path)
        live_legacy = PromotionEvidence(
            paper_days=10,
            paper_sharpe=1.0,
            paper_hit_rate=0.55,
            cost_model_validated=True,
        )
        errors = lc.promote_to_live(live_legacy)
        assert errors == []
        assert lc.state == AlphaLifecycleState.LIVE
