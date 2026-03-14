"""Unit tests for AlphaLifecycle and gate check functions."""

from __future__ import annotations

import pytest

from feelies.alpha.lifecycle import (
    AlphaLifecycle,
    AlphaLifecycleState,
    GateRequirements,
    PromotionEvidence,
    check_live_gate,
    check_paper_gate,
    check_revalidation_gate,
)
from feelies.core.clock import SimulatedClock


class TestCheckPaperGate:
    """Tests for check_paper_gate."""

    def test_passes_when_all_evidence_present(self) -> None:
        evidence = PromotionEvidence(
            schema_valid=True,
            determinism_test_passed=True,
            feature_values_finite=True,
        )
        assert check_paper_gate(evidence) == []

    def test_fails_when_schema_invalid(self) -> None:
        evidence = PromotionEvidence(
            schema_valid=False,
            determinism_test_passed=True,
            feature_values_finite=True,
        )
        errors = check_paper_gate(evidence)
        assert len(errors) == 1
        assert "schema" in errors[0].lower()

    def test_fails_when_determinism_not_passed(self) -> None:
        evidence = PromotionEvidence(
            schema_valid=True,
            determinism_test_passed=False,
            feature_values_finite=True,
        )
        errors = check_paper_gate(evidence)
        assert len(errors) == 1
        assert "determinism" in errors[0].lower()

    def test_fails_when_feature_values_not_finite(self) -> None:
        evidence = PromotionEvidence(
            schema_valid=True,
            determinism_test_passed=True,
            feature_values_finite=False,
        )
        errors = check_paper_gate(evidence)
        assert len(errors) == 1
        assert "finite" in errors[0].lower()


class TestCheckLiveGate:
    """Tests for check_live_gate."""

    def test_passes_when_all_requirements_met(self) -> None:
        evidence = PromotionEvidence(
            paper_days=60,
            paper_sharpe=1.5,
            paper_hit_rate=0.55,
            paper_max_drawdown_pct=2.0,
            cost_model_validated=True,
            quarantine_triggers=0,
        )
        assert check_live_gate(evidence) == []

    def test_fails_insufficient_paper_days(self) -> None:
        req = GateRequirements(paper_min_days=30)
        evidence = PromotionEvidence(
            paper_days=10,
            paper_sharpe=1.5,
            paper_hit_rate=0.55,
            cost_model_validated=True,
        )
        errors = check_live_gate(evidence, req)
        assert any("days" in e.lower() for e in errors)

    def test_fails_low_sharpe(self) -> None:
        req = GateRequirements(paper_min_sharpe=1.0)
        evidence = PromotionEvidence(
            paper_days=60,
            paper_sharpe=0.5,
            paper_hit_rate=0.55,
            cost_model_validated=True,
        )
        errors = check_live_gate(evidence, req)
        assert any("sharpe" in e.lower() for e in errors)

    def test_fails_low_hit_rate(self) -> None:
        req = GateRequirements(paper_min_hit_rate=0.5)
        evidence = PromotionEvidence(
            paper_days=60,
            paper_sharpe=1.5,
            paper_hit_rate=0.4,
            cost_model_validated=True,
        )
        errors = check_live_gate(evidence, req)
        assert any("hit rate" in e.lower() for e in errors)

    def test_fails_high_drawdown(self) -> None:
        req = GateRequirements(paper_max_drawdown_pct=5.0)
        evidence = PromotionEvidence(
            paper_days=60,
            paper_sharpe=1.5,
            paper_hit_rate=0.55,
            paper_max_drawdown_pct=8.0,
            cost_model_validated=True,
        )
        errors = check_live_gate(evidence, req)
        assert any("drawdown" in e.lower() for e in errors)

    def test_fails_quarantine_triggers(self) -> None:
        evidence = PromotionEvidence(
            paper_days=60,
            paper_sharpe=1.5,
            paper_hit_rate=0.55,
            cost_model_validated=True,
            quarantine_triggers=2,
        )
        errors = check_live_gate(evidence)
        assert any("quarantine" in e.lower() for e in errors)

    def test_fails_cost_model_not_validated(self) -> None:
        evidence = PromotionEvidence(
            paper_days=60,
            paper_sharpe=1.5,
            paper_hit_rate=0.55,
            cost_model_validated=False,
        )
        errors = check_live_gate(evidence)
        assert any("cost" in e.lower() for e in errors)

    def test_uses_default_requirements_when_none(self) -> None:
        evidence = PromotionEvidence(
            paper_days=100,
            paper_sharpe=2.0,
            paper_hit_rate=0.6,
            paper_max_drawdown_pct=1.0,
            cost_model_validated=True,
        )
        assert check_live_gate(evidence, None) == []


class TestCheckRevalidationGate:
    """Tests for check_revalidation_gate."""

    def test_passes_when_all_present(self) -> None:
        evidence = PromotionEvidence(
            determinism_test_passed=True,
            revalidation_notes="human reviewed and approved",
        )
        assert check_revalidation_gate(evidence) == []

    def test_fails_determinism_not_passed(self) -> None:
        evidence = PromotionEvidence(
            determinism_test_passed=False,
            revalidation_notes="reviewed",
        )
        errors = check_revalidation_gate(evidence)
        assert any("determinism" in e.lower() for e in errors)

    def test_fails_empty_revalidation_notes(self) -> None:
        evidence = PromotionEvidence(
            determinism_test_passed=True,
            revalidation_notes="",
        )
        errors = check_revalidation_gate(evidence)
        assert any("notes" in e.lower() for e in errors)

    def test_fails_whitespace_only_notes(self) -> None:
        evidence = PromotionEvidence(
            determinism_test_passed=True,
            revalidation_notes="   \n\t  ",
        )
        errors = check_revalidation_gate(evidence)
        assert any("notes" in e.lower() for e in errors)


class TestAlphaLifecycle:
    """Tests for AlphaLifecycle state machine."""

    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=0)

    @pytest.fixture
    def lifecycle(self, clock: SimulatedClock) -> AlphaLifecycle:
        return AlphaLifecycle(alpha_id="test_alpha", clock=clock)

    def test_initial_state_is_research(self, lifecycle: AlphaLifecycle) -> None:
        assert lifecycle.state == AlphaLifecycleState.RESEARCH

    def test_alpha_id_property(self, lifecycle: AlphaLifecycle) -> None:
        assert lifecycle.alpha_id == "test_alpha"

    def test_history_empty_initially(self, lifecycle: AlphaLifecycle) -> None:
        assert lifecycle.history == []

    def test_is_active_false_in_research(self, lifecycle: AlphaLifecycle) -> None:
        assert lifecycle.is_active is False

    def test_is_live_false_in_research(self, lifecycle: AlphaLifecycle) -> None:
        assert lifecycle.is_live is False

    def test_promote_to_paper_success(
        self, lifecycle: AlphaLifecycle
    ) -> None:
        evidence = PromotionEvidence(
            schema_valid=True,
            determinism_test_passed=True,
            feature_values_finite=True,
        )
        errors = lifecycle.promote_to_paper(evidence)
        assert errors == []
        assert lifecycle.state == AlphaLifecycleState.PAPER
        assert lifecycle.is_active is True
        assert lifecycle.is_live is False

    def test_promote_to_paper_fails_gate(
        self, lifecycle: AlphaLifecycle
    ) -> None:
        evidence = PromotionEvidence(
            schema_valid=False,
            determinism_test_passed=True,
            feature_values_finite=True,
        )
        errors = lifecycle.promote_to_paper(evidence)
        assert len(errors) > 0
        assert lifecycle.state == AlphaLifecycleState.RESEARCH

    def test_promote_to_live_success(
        self, lifecycle: AlphaLifecycle, clock: SimulatedClock
    ) -> None:
        gate = GateRequirements(
            paper_min_days=1,
            paper_min_sharpe=0.5,
            paper_min_hit_rate=0.4,
            paper_max_drawdown_pct=10.0,
        )
        lc = AlphaLifecycle(
            alpha_id="test",
            clock=clock,
            gate_requirements=gate,
        )
        paper_ev = PromotionEvidence(
            schema_valid=True,
            determinism_test_passed=True,
            feature_values_finite=True,
        )
        lc.promote_to_paper(paper_ev)

        live_ev = PromotionEvidence(
            paper_days=10,
            paper_sharpe=1.0,
            paper_hit_rate=0.55,
            paper_max_drawdown_pct=2.0,
            cost_model_validated=True,
        )
        errors = lc.promote_to_live(live_ev)
        assert errors == []
        assert lc.state == AlphaLifecycleState.LIVE
        assert lc.is_active is True
        assert lc.is_live is True

    def test_promote_to_live_fails_gate(
        self, lifecycle: AlphaLifecycle, clock: SimulatedClock
    ) -> None:
        gate = GateRequirements(paper_min_days=100)
        lc = AlphaLifecycle(
            alpha_id="test",
            clock=clock,
            gate_requirements=gate,
        )
        paper_ev = PromotionEvidence(
            schema_valid=True,
            determinism_test_passed=True,
            feature_values_finite=True,
        )
        lc.promote_to_paper(paper_ev)

        live_ev = PromotionEvidence(
            paper_days=10,
            paper_sharpe=1.0,
            paper_hit_rate=0.55,
            cost_model_validated=True,
        )
        errors = lc.promote_to_live(live_ev)
        assert len(errors) > 0
        assert lc.state == AlphaLifecycleState.PAPER

    def test_quarantine_from_live(
        self, lifecycle: AlphaLifecycle, clock: SimulatedClock
    ) -> None:
        gate = GateRequirements(paper_min_days=1)
        lc = AlphaLifecycle(
            alpha_id="test",
            clock=clock,
            gate_requirements=gate,
        )
        lc.promote_to_paper(
            PromotionEvidence(
                schema_valid=True,
                determinism_test_passed=True,
                feature_values_finite=True,
            )
        )
        lc.promote_to_live(
            PromotionEvidence(
                paper_days=10,
                paper_sharpe=1.0,
                paper_hit_rate=0.55,
                cost_model_validated=True,
            )
        )

        lc.quarantine("edge decay detected", correlation_id="corr123")
        assert lc.state == AlphaLifecycleState.QUARANTINED
        assert lc.is_active is False
        assert lc.is_live is False

    def test_revalidate_to_paper_success(
        self, lifecycle: AlphaLifecycle, clock: SimulatedClock
    ) -> None:
        gate = GateRequirements(paper_min_days=1)
        lc = AlphaLifecycle(
            alpha_id="test",
            clock=clock,
            gate_requirements=gate,
        )
        lc.promote_to_paper(
            PromotionEvidence(
                schema_valid=True,
                determinism_test_passed=True,
                feature_values_finite=True,
            )
        )
        lc.promote_to_live(
            PromotionEvidence(
                paper_days=10,
                paper_sharpe=1.0,
                paper_hit_rate=0.55,
                cost_model_validated=True,
            )
        )
        lc.quarantine("decay")

        errors = lc.revalidate_to_paper(
            PromotionEvidence(
                determinism_test_passed=True,
                revalidation_notes="human approved",
            )
        )
        assert errors == []
        assert lc.state == AlphaLifecycleState.PAPER

    def test_revalidate_to_paper_fails_gate(
        self, lifecycle: AlphaLifecycle, clock: SimulatedClock
    ) -> None:
        gate = GateRequirements(paper_min_days=1)
        lc = AlphaLifecycle(alpha_id="test", clock=clock, gate_requirements=gate)
        lc.promote_to_paper(
            PromotionEvidence(
                schema_valid=True,
                determinism_test_passed=True,
                feature_values_finite=True,
            )
        )
        lc.promote_to_live(
            PromotionEvidence(
                paper_days=10,
                paper_sharpe=1.0,
                paper_hit_rate=0.55,
                cost_model_validated=True,
            )
        )
        lc.quarantine("decay")

        errors = lc.revalidate_to_paper(
            PromotionEvidence(
                determinism_test_passed=False,
                revalidation_notes="notes",
            )
        )
        assert len(errors) > 0
        assert lc.state == AlphaLifecycleState.QUARANTINED

    def test_decommission(
        self, lifecycle: AlphaLifecycle, clock: SimulatedClock
    ) -> None:
        gate = GateRequirements(paper_min_days=1)
        lc = AlphaLifecycle(alpha_id="test", clock=clock, gate_requirements=gate)
        lc.promote_to_paper(
            PromotionEvidence(
                schema_valid=True,
                determinism_test_passed=True,
                feature_values_finite=True,
            )
        )
        lc.promote_to_live(
            PromotionEvidence(
                paper_days=10,
                paper_sharpe=1.0,
                paper_hit_rate=0.55,
                cost_model_validated=True,
            )
        )
        lc.quarantine("decay")

        lc.decommission("retired", correlation_id="c1")
        assert lc.state == AlphaLifecycleState.DECOMMISSIONED
        assert lc.is_active is False
