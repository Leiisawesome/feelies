"""Unit tests for AlphaLifecycle and gate check functions."""

from __future__ import annotations

from pathlib import Path

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
from feelies.alpha.promotion_ledger import PromotionLedger
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


# ── Workstream F-1: PromotionLedger wiring ──────────────────────────────


def _paper_evidence() -> PromotionEvidence:
    return PromotionEvidence(
        schema_valid=True,
        determinism_test_passed=True,
        feature_values_finite=True,
    )


def _live_evidence() -> PromotionEvidence:
    return PromotionEvidence(
        paper_days=60,
        paper_sharpe=1.5,
        paper_hit_rate=0.55,
        paper_max_drawdown_pct=2.0,
        cost_model_validated=True,
    )


def _revalidation_evidence() -> PromotionEvidence:
    return PromotionEvidence(
        determinism_test_passed=True,
        revalidation_notes="re-audited; structural drivers intact",
    )


class TestAlphaLifecycleWithLedger:
    """F-1: every successful transition is appended to the
    promotion ledger; rejected transitions are NOT recorded."""

    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    @pytest.fixture
    def ledger(self, tmp_path: Path) -> PromotionLedger:
        return PromotionLedger(tmp_path / "promotion.jsonl")

    def test_promote_to_paper_appends_one_entry(
        self, clock: SimulatedClock, ledger: PromotionLedger
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock, ledger=ledger)

        errors = lc.promote_to_paper(
            _paper_evidence(), correlation_id="corr-paper"
        )

        assert errors == []
        entries = list(ledger.entries())
        assert len(entries) == 1
        entry = entries[0]
        assert entry.alpha_id == "kyle"
        assert entry.from_state == "RESEARCH"
        assert entry.to_state == "PAPER"
        assert entry.trigger == "pass_paper_gate"
        assert entry.correlation_id == "corr-paper"
        assert entry.timestamp_ns == clock.now_ns()
        assert "evidence" in entry.metadata

    def test_failed_promote_to_paper_does_not_write(
        self, clock: SimulatedClock, ledger: PromotionLedger
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock, ledger=ledger)

        errors = lc.promote_to_paper(
            PromotionEvidence(
                schema_valid=False,
                determinism_test_passed=True,
                feature_values_finite=True,
            )
        )

        assert errors  # gate rejected the promotion
        assert lc.state == AlphaLifecycleState.RESEARCH
        assert list(ledger.entries()) == []

    def test_full_lifecycle_writes_one_entry_per_transition(
        self, clock: SimulatedClock, ledger: PromotionLedger
    ) -> None:
        gate = GateRequirements(paper_min_days=1)
        lc = AlphaLifecycle(
            alpha_id="kyle",
            clock=clock,
            gate_requirements=gate,
            ledger=ledger,
        )

        # 5 successful transitions:
        # RESEARCH → PAPER → LIVE → QUARANTINED → PAPER → QUARANTINED
        lc.promote_to_paper(_paper_evidence(), correlation_id="c1")
        lc.promote_to_live(_live_evidence(), correlation_id="c2")
        lc.quarantine("ic decayed", correlation_id="c3")
        lc.revalidate_to_paper(_revalidation_evidence(), correlation_id="c4")
        # need to walk back to LIVE before another quarantine works
        lc.promote_to_live(_live_evidence(), correlation_id="c5")
        lc.quarantine("ic decayed again", correlation_id="c6")

        entries = list(ledger.entries())
        assert len(entries) == 6
        triggers = [e.trigger for e in entries]
        assert triggers == [
            "pass_paper_gate",
            "pass_live_gate",
            "edge_decay_detected",
            "revalidation_passed",
            "pass_live_gate",
            "edge_decay_detected",
        ]
        correlation_ids = [e.correlation_id for e in entries]
        assert correlation_ids == ["c1", "c2", "c3", "c4", "c5", "c6"]

    def test_decommission_writes_with_reason(
        self, clock: SimulatedClock, ledger: PromotionLedger
    ) -> None:
        gate = GateRequirements(paper_min_days=1)
        lc = AlphaLifecycle(
            alpha_id="kyle",
            clock=clock,
            gate_requirements=gate,
            ledger=ledger,
        )
        lc.promote_to_paper(_paper_evidence())
        lc.promote_to_live(_live_evidence())
        lc.quarantine("decay")

        lc.decommission("structural break", correlation_id="decom-1")

        entries = list(ledger.entries())
        assert entries[-1].to_state == "DECOMMISSIONED"
        assert entries[-1].trigger == "decommissioned"
        assert entries[-1].metadata.get("reason") == "structural break"
        assert entries[-1].correlation_id == "decom-1"

    def test_evidence_payload_preserved_in_ledger_metadata(
        self, clock: SimulatedClock, ledger: PromotionLedger
    ) -> None:
        gate = GateRequirements(paper_min_days=1)
        lc = AlphaLifecycle(
            alpha_id="kyle",
            clock=clock,
            gate_requirements=gate,
            ledger=ledger,
        )
        evidence = PromotionEvidence(
            paper_days=42,
            paper_sharpe=1.23,
            paper_hit_rate=0.61,
            paper_max_drawdown_pct=1.5,
            cost_model_validated=True,
        )
        lc.promote_to_paper(_paper_evidence())
        lc.promote_to_live(evidence)

        live_entry = list(ledger.entries())[-1]
        ev = live_entry.metadata["evidence"]
        assert isinstance(ev, dict)
        assert ev["paper_days"] == 42
        assert ev["paper_sharpe"] == 1.23
        assert ev["paper_hit_rate"] == 0.61
        assert ev["paper_max_drawdown_pct"] == 1.5
        assert ev["cost_model_validated"] is True

    def test_no_ledger_means_no_writes_anywhere(
        self, clock: SimulatedClock, tmp_path: Path
    ) -> None:
        # Backward-compat: without a ledger arg, the lifecycle behaves
        # exactly as before — no on_transition callback registered, no
        # filesystem side-effects.
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        lc.promote_to_paper(_paper_evidence())

        # tmp_path is empty: nothing was written under it
        assert list(tmp_path.iterdir()) == []
        # but the lifecycle still transitioned
        assert lc.state == AlphaLifecycleState.PAPER

    def test_failed_quarantine_via_illegal_state_does_not_write(
        self, clock: SimulatedClock, ledger: PromotionLedger
    ) -> None:
        # Quarantining from RESEARCH is an illegal transition (raises
        # IllegalTransition); the SM never invokes the callback, so the
        # ledger remains empty.
        from feelies.core.state_machine import IllegalTransition

        lc = AlphaLifecycle(alpha_id="kyle", clock=clock, ledger=ledger)

        with pytest.raises(IllegalTransition):
            lc.quarantine("not allowed from research")

        assert list(ledger.entries()) == []
        assert lc.state == AlphaLifecycleState.RESEARCH
