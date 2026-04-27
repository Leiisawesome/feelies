"""Workstream F-6: capital-tier escalation tests for AlphaLifecycle.

These tests exercise the new ``promote_capital_tier`` method, the
``current_capital_tier`` property, and the LIVE -> LIVE self-loop
transition that records the SMALL_CAPITAL -> SCALED escalation as a
metadata-only ledger entry.

Coverage axes:
  * happy-path SMALL_CAPITAL -> SCALED via valid CapitalStageEvidence
  * gate-validator rejection paths (insufficient days, PnL compression
    out of band, slippage, hit-rate floor, fill-rate drift, wrong tier)
  * state precondition (must be LIVE; not RESEARCH/PAPER/QUARANTINED)
  * idempotency-style refusal: already-SCALED rejects further calls
  * tier reset across QUARANTINE -> revalidate -> LIVE re-entry
  * registry-level forwarding of ``promote_capital_tier``
  * ledger entry metadata round-trips through metadata_to_evidence
  * StateMachine self-loop preserves state but logs the transition
"""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.alpha.lifecycle import (
    AlphaLifecycle,
    AlphaLifecycleState,
)
from feelies.alpha.module import AlphaManifest, AlphaRiskBudget
from feelies.alpha.promotion_evidence import (
    EVIDENCE_SCHEMA_VERSION,
    PROMOTE_CAPITAL_TIER_TRIGGER,
    CapitalStageEvidence,
    CapitalStageTier,
    CPCVEvidence,
    DSREvidence,
    GateThresholds,
    PaperWindowEvidence,
    ResearchAcceptanceEvidence,
    RevalidationEvidence,
    metadata_to_evidence,
)
from feelies.alpha.promotion_ledger import PromotionLedger
from feelies.alpha.registry import AlphaRegistry, AlphaRegistryError
from feelies.core.clock import SimulatedClock
from feelies.features.definition import FeatureDefinition

# ── Fixture builders ───────────────────────────────────────────────


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
        revalidation_notes="re-derived from current order-book regime",
    )


def _passing_capital_stage() -> CapitalStageEvidence:
    return CapitalStageEvidence(
        tier=CapitalStageTier.SMALL_CAPITAL,
        allocation_fraction=0.01,
        deployment_days=12,
        pnl_compression_ratio_realised=0.85,
        slippage_residual_bps=1.0,
        hit_rate_residual_pp=-2.0,
        fill_rate_drift_pct=3.0,
    )


def _walk_to_live(lc: AlphaLifecycle) -> None:
    assert lc.promote_to_paper(
        structured_evidence=[_passing_research_acceptance()],
    ) == []
    assert lc.promote_to_live(
        structured_evidence=[
            _passing_paper_window(),
            _passing_cpcv(),
            _passing_dsr(),
        ],
    ) == []


# ── promote_capital_tier ───────────────────────────────────────────


class TestPromoteCapitalTierHappyPath:
    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    def test_small_to_scaled_keeps_state_live(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        assert lc.current_capital_tier is CapitalStageTier.SMALL_CAPITAL
        errors = lc.promote_capital_tier(_passing_capital_stage())
        assert errors == []
        # Lifecycle state is unchanged; only the tier flipped.
        assert lc.state is AlphaLifecycleState.LIVE
        assert lc.current_capital_tier is CapitalStageTier.SCALED

    def test_self_loop_records_history_with_promote_capital_tier_trigger(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        lc.promote_capital_tier(
            _passing_capital_stage(), correlation_id="cap-1"
        )

        last = lc.history[-1]
        assert last.from_state == "LIVE"
        assert last.to_state == "LIVE"
        assert last.trigger == PROMOTE_CAPITAL_TIER_TRIGGER
        assert last.correlation_id == "cap-1"

    def test_ledger_entry_round_trips_capital_stage_evidence(
        self, clock: SimulatedClock, tmp_path: Path
    ) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock, ledger=ledger)
        _walk_to_live(lc)

        ev = _passing_capital_stage()
        assert lc.promote_capital_tier(ev) == []

        last = list(ledger.entries())[-1]
        assert last.from_state == "LIVE"
        assert last.to_state == "LIVE"
        assert last.trigger == PROMOTE_CAPITAL_TIER_TRIGGER
        assert last.metadata["schema_version"] == EVIDENCE_SCHEMA_VERSION

        reconstructed = metadata_to_evidence(last.metadata)
        assert len(reconstructed) == 1
        assert isinstance(reconstructed[0], CapitalStageEvidence)
        assert reconstructed[0] == ev


# ── promote_capital_tier — sad paths (gate-validator rejections) ───


class TestPromoteCapitalTierValidatorRejections:
    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    def test_short_deployment_window_rejected(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        bad = CapitalStageEvidence(
            tier=CapitalStageTier.SMALL_CAPITAL,
            allocation_fraction=0.01,
            deployment_days=3,
            pnl_compression_ratio_realised=0.85,
            slippage_residual_bps=1.0,
            hit_rate_residual_pp=-2.0,
            fill_rate_drift_pct=3.0,
        )
        errors = lc.promote_capital_tier(bad)
        assert any("deployment_days" in e for e in errors)
        assert lc.current_capital_tier is CapitalStageTier.SMALL_CAPITAL

    def test_pnl_compression_below_floor_rejected(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        bad = CapitalStageEvidence(
            tier=CapitalStageTier.SMALL_CAPITAL,
            allocation_fraction=0.01,
            deployment_days=12,
            pnl_compression_ratio_realised=0.30,
            slippage_residual_bps=1.0,
            hit_rate_residual_pp=-2.0,
            fill_rate_drift_pct=3.0,
        )
        errors = lc.promote_capital_tier(bad)
        assert any("PnL compression" in e for e in errors)
        assert lc.current_capital_tier is CapitalStageTier.SMALL_CAPITAL

    def test_slippage_residual_above_ceiling_rejected(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        bad = CapitalStageEvidence(
            tier=CapitalStageTier.SMALL_CAPITAL,
            allocation_fraction=0.01,
            deployment_days=12,
            pnl_compression_ratio_realised=0.85,
            slippage_residual_bps=10.0,
            hit_rate_residual_pp=-2.0,
            fill_rate_drift_pct=3.0,
        )
        errors = lc.promote_capital_tier(bad)
        assert any("slippage" in e for e in errors)

    def test_outgoing_tier_must_be_small_capital(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        bad = CapitalStageEvidence(
            tier=CapitalStageTier.SCALED,
            allocation_fraction=0.01,
            deployment_days=12,
            pnl_compression_ratio_realised=0.85,
            slippage_residual_bps=1.0,
            hit_rate_residual_pp=-2.0,
            fill_rate_drift_pct=3.0,
        )
        errors = lc.promote_capital_tier(bad)
        assert any("tier=SMALL_CAPITAL" in e for e in errors)

    def test_failed_validator_does_not_write_ledger(
        self, clock: SimulatedClock, tmp_path: Path
    ) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock, ledger=ledger)
        _walk_to_live(lc)

        ledger_count_before = len(list(ledger.entries()))

        bad = CapitalStageEvidence(deployment_days=1)
        errors = lc.promote_capital_tier(bad)
        assert errors  # rejected

        ledger_count_after = len(list(ledger.entries()))
        assert ledger_count_after == ledger_count_before


# ── promote_capital_tier — state precondition ──────────────────────


class TestPromoteCapitalTierStatePrecondition:
    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    def test_research_state_rejects_call(self, clock: SimulatedClock) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        errors = lc.promote_capital_tier(_passing_capital_stage())
        assert any("requires state=LIVE" in e for e in errors)
        assert lc.state is AlphaLifecycleState.RESEARCH

    def test_paper_state_rejects_call(self, clock: SimulatedClock) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        lc.promote_to_paper(
            structured_evidence=[_passing_research_acceptance()]
        )
        errors = lc.promote_capital_tier(_passing_capital_stage())
        assert any("requires state=LIVE" in e for e in errors)
        assert lc.state is AlphaLifecycleState.PAPER

    def test_quarantined_state_rejects_call(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        lc.quarantine("manual override")
        errors = lc.promote_capital_tier(_passing_capital_stage())
        assert any("requires state=LIVE" in e for e in errors)
        assert lc.state is AlphaLifecycleState.QUARANTINED


# ── current_capital_tier semantics ─────────────────────────────────


class TestCurrentCapitalTier:
    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    def test_research_returns_none(self, clock: SimulatedClock) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        assert lc.current_capital_tier is None

    def test_paper_returns_none(self, clock: SimulatedClock) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        lc.promote_to_paper(
            structured_evidence=[_passing_research_acceptance()]
        )
        assert lc.current_capital_tier is None

    def test_first_live_entry_is_small_capital(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        assert lc.current_capital_tier is CapitalStageTier.SMALL_CAPITAL

    def test_after_promote_capital_tier_returns_scaled(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        lc.promote_capital_tier(_passing_capital_stage())
        assert lc.current_capital_tier is CapitalStageTier.SCALED

    def test_quarantined_returns_none(self, clock: SimulatedClock) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        lc.promote_capital_tier(_passing_capital_stage())
        lc.quarantine("ic decay")
        assert lc.current_capital_tier is None

    def test_relive_after_quarantine_resets_tier(
        self, clock: SimulatedClock
    ) -> None:
        # SMALL -> SCALED, then quarantine, revalidate, re-promote: the
        # new LIVE epoch starts at SMALL_CAPITAL again.
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        lc.promote_capital_tier(_passing_capital_stage())
        lc.quarantine("ic decay")
        lc.revalidate_to_paper(structured_evidence=[_passing_revalidation()])
        # PAPER -> LIVE again
        assert lc.promote_to_live(
            structured_evidence=[
                _passing_paper_window(),
                _passing_cpcv(),
                _passing_dsr(),
            ],
        ) == []
        assert lc.state is AlphaLifecycleState.LIVE
        # New epoch must reset to SMALL_CAPITAL — the prior epoch's
        # SCALED escalation belongs to the old epoch and must not
        # bleed into this one.
        assert lc.current_capital_tier is CapitalStageTier.SMALL_CAPITAL


# ── Already-SCALED idempotency ─────────────────────────────────────


class TestAlreadyScaledRejection:
    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    def test_second_call_at_scaled_rejected(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        assert lc.promote_capital_tier(_passing_capital_stage()) == []
        # Second call: lifecycle is at SCALED already.
        errors = lc.promote_capital_tier(_passing_capital_stage())
        assert any(
            "tier=SCALED" in e or "already complete" in e for e in errors
        )

    def test_already_scaled_does_not_write_a_second_ledger_entry(
        self, clock: SimulatedClock, tmp_path: Path
    ) -> None:
        ledger = PromotionLedger(tmp_path / "ledger.jsonl")
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock, ledger=ledger)
        _walk_to_live(lc)
        lc.promote_capital_tier(_passing_capital_stage())

        count_before = len(list(ledger.entries()))
        errors = lc.promote_capital_tier(_passing_capital_stage())
        count_after = len(list(ledger.entries()))

        assert errors  # rejected
        assert count_after == count_before  # no second self-loop logged


# ── Custom GateThresholds ──────────────────────────────────────────


class TestPromoteCapitalTierGateThresholds:
    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    def test_relaxed_thresholds_let_borderline_pass(
        self, clock: SimulatedClock
    ) -> None:
        relaxed = GateThresholds(
            small_min_deployment_days=3,
            small_min_pnl_compression_ratio=0.4,
        )
        lc = AlphaLifecycle(
            alpha_id="kyle", clock=clock, gate_thresholds=relaxed
        )
        _walk_to_live(lc)
        borderline = CapitalStageEvidence(
            tier=CapitalStageTier.SMALL_CAPITAL,
            allocation_fraction=0.01,
            deployment_days=4,
            pnl_compression_ratio_realised=0.45,
            slippage_residual_bps=1.0,
            hit_rate_residual_pp=-2.0,
            fill_rate_drift_pct=3.0,
        )
        assert lc.promote_capital_tier(borderline) == []
        assert lc.current_capital_tier is CapitalStageTier.SCALED

    def test_tightened_thresholds_reject_default_pass(
        self, clock: SimulatedClock
    ) -> None:
        tightened = GateThresholds(small_min_deployment_days=30)
        lc = AlphaLifecycle(
            alpha_id="kyle", clock=clock, gate_thresholds=tightened
        )
        _walk_to_live(lc)
        # default helper has deployment_days=12 < 30
        errors = lc.promote_capital_tier(_passing_capital_stage())
        assert any("deployment_days" in e for e in errors)
        assert lc.current_capital_tier is CapitalStageTier.SMALL_CAPITAL


# ── AlphaRegistry.promote_capital_tier ──────────────────────────────


class _StubModule:
    """Minimal AlphaModule for registry tests."""

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


def _walk_registry_to_live(registry: AlphaRegistry, alpha_id: str) -> None:
    assert registry.promote(
        alpha_id, structured_evidence=[_passing_research_acceptance()]
    ) == []
    assert registry.promote(
        alpha_id,
        structured_evidence=[
            _passing_paper_window(),
            _passing_cpcv(),
            _passing_dsr(),
        ],
    ) == []


class TestRegistryPromoteCapitalTier:
    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    def test_registry_forwards_to_lifecycle(
        self, clock: SimulatedClock
    ) -> None:
        registry = AlphaRegistry(clock=clock)
        registry.register(_StubModule("kyle"))
        _walk_registry_to_live(registry, "kyle")

        errors = registry.promote_capital_tier(
            "kyle", _passing_capital_stage(), correlation_id="cap-1"
        )
        assert errors == []
        lc = registry.get_lifecycle("kyle")
        assert lc is not None
        assert lc.state is AlphaLifecycleState.LIVE
        assert lc.current_capital_tier is CapitalStageTier.SCALED

    def test_registry_unregistered_alpha_raises(
        self, clock: SimulatedClock
    ) -> None:
        registry = AlphaRegistry(clock=clock)
        with pytest.raises(KeyError, match="missing"):
            registry.promote_capital_tier("missing", _passing_capital_stage())

    def test_registry_no_clock_raises(self) -> None:
        registry = AlphaRegistry()
        registry.register(_StubModule("kyle"))
        with pytest.raises(AlphaRegistryError):
            registry.promote_capital_tier("kyle", _passing_capital_stage())

    def test_registry_validator_errors_surface_through_delegate(
        self, clock: SimulatedClock
    ) -> None:
        registry = AlphaRegistry(clock=clock)
        registry.register(_StubModule("kyle"))
        _walk_registry_to_live(registry, "kyle")

        bad = CapitalStageEvidence(deployment_days=1)
        errors = registry.promote_capital_tier("kyle", bad)
        assert errors  # gate rejected
        lc = registry.get_lifecycle("kyle")
        assert lc is not None
        assert lc.current_capital_tier is CapitalStageTier.SMALL_CAPITAL


# ── F-6 P1: capital tier survives checkpoint/restore ───────────────


class TestCapitalTierCheckpointRestore:
    """The Codex-bot P1 review issue on PR #23.

    ``AlphaLifecycle.checkpoint()`` historically persisted only the
    state name, so restoring a ``LIVE @ SCALED`` alpha would silently
    revert the in-memory tier to ``SMALL_CAPITAL`` (because
    ``current_capital_tier`` reads ``StateMachine.history``, which is
    empty after restore).  A subsequent ``promote_capital_tier()``
    would then commit a duplicate SCALED escalation to the ledger.

    These tests pin the corrected behavior: the checkpoint blob now
    carries ``capital_tier`` whenever ``state == LIVE``, and
    ``restore()`` rehydrates it onto a private fallback consulted by
    ``current_capital_tier`` when in-memory history is silent.
    """

    @pytest.fixture
    def clock(self) -> SimulatedClock:
        return SimulatedClock(start_ns=1_700_000_000_000_000_000)

    def test_scaled_survives_checkpoint_restore_round_trip(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        assert lc.promote_capital_tier(_passing_capital_stage()) == []
        assert lc.current_capital_tier is CapitalStageTier.SCALED

        blob = lc.checkpoint()

        # Fresh instance — no in-memory history at all.
        restored = AlphaLifecycle(alpha_id="kyle", clock=clock)
        restored.restore(blob)
        assert restored.state is AlphaLifecycleState.LIVE
        assert restored.current_capital_tier is CapitalStageTier.SCALED

    def test_small_capital_round_trip_keeps_small(
        self, clock: SimulatedClock
    ) -> None:
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        assert lc.current_capital_tier is CapitalStageTier.SMALL_CAPITAL

        blob = lc.checkpoint()
        restored = AlphaLifecycle(alpha_id="kyle", clock=clock)
        restored.restore(blob)
        assert restored.current_capital_tier is CapitalStageTier.SMALL_CAPITAL

    def test_legacy_blob_without_capital_tier_restores_as_small(
        self, clock: SimulatedClock
    ) -> None:
        # Pre-F-6 checkpoint format: no ``capital_tier`` field.
        legacy_blob = b'{"alpha_id": "kyle", "state": "LIVE"}'
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        lc.restore(legacy_blob)
        assert lc.state is AlphaLifecycleState.LIVE
        # Backwards-compat: no field → historic SMALL_CAPITAL default.
        assert lc.current_capital_tier is CapitalStageTier.SMALL_CAPITAL

    def test_restored_scaled_blocks_duplicate_escalation(
        self, clock: SimulatedClock, tmp_path: Path
    ) -> None:
        # Scenario: restart of an already-SCALED alpha.  The new
        # process must NOT happily commit a second SCALED escalation
        # against a fresh ledger.
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        lc.promote_capital_tier(_passing_capital_stage())
        blob = lc.checkpoint()

        ledger = PromotionLedger(tmp_path / "post_restart.jsonl")
        restored = AlphaLifecycle(
            alpha_id="kyle", clock=clock, ledger=ledger
        )
        restored.restore(blob)

        errors = restored.promote_capital_tier(_passing_capital_stage())
        assert errors  # rejected
        assert any(
            "tier=SCALED" in e or "already complete" in e for e in errors
        )
        # And critically: nothing was written.
        assert list(ledger.entries()) == []

    def test_quarantine_after_restore_clears_tier_semantics(
        self, clock: SimulatedClock
    ) -> None:
        # After restore + quarantine, current_capital_tier is None
        # (state != LIVE) and a subsequent revalidate -> live re-entry
        # starts a brand-new SMALL_CAPITAL epoch — the persisted
        # SCALED hint must NOT bleed into the fresh epoch.
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        lc.promote_capital_tier(_passing_capital_stage())
        blob = lc.checkpoint()

        restored = AlphaLifecycle(alpha_id="kyle", clock=clock)
        restored.restore(blob)
        assert restored.current_capital_tier is CapitalStageTier.SCALED

        restored.quarantine("post-restart edge decay")
        assert restored.current_capital_tier is None

        assert restored.revalidate_to_paper(
            structured_evidence=[_passing_revalidation()]
        ) == []
        assert restored.promote_to_live(
            structured_evidence=[
                _passing_paper_window(),
                _passing_cpcv(),
                _passing_dsr(),
            ],
        ) == []
        # Fresh LIVE epoch: starts at SMALL_CAPITAL, NOT the
        # persisted SCALED hint from the prior process.
        assert restored.current_capital_tier is CapitalStageTier.SMALL_CAPITAL

    def test_checkpoint_does_not_emit_capital_tier_when_not_live(
        self, clock: SimulatedClock
    ) -> None:
        import json as _json

        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        # State == RESEARCH; no tier field expected.
        blob = lc.checkpoint()
        payload = _json.loads(blob.decode())
        assert "capital_tier" not in payload
        assert payload["state"] == "RESEARCH"

        # PAPER: also no tier.
        assert lc.promote_to_paper(
            structured_evidence=[_passing_research_acceptance()]
        ) == []
        payload = _json.loads(lc.checkpoint().decode())
        assert "capital_tier" not in payload
        assert payload["state"] == "PAPER"

    def test_corrupt_capital_tier_in_checkpoint_raises(
        self, clock: SimulatedClock
    ) -> None:
        bad_blob = (
            b'{"alpha_id": "kyle", "state": "LIVE", '
            b'"capital_tier": "MEGA_CAPITAL"}'
        )
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        with pytest.raises(ValueError, match="MEGA_CAPITAL"):
            lc.restore(bad_blob)

    def test_capital_tier_on_non_live_state_rejected(
        self, clock: SimulatedClock
    ) -> None:
        # A capital_tier on a non-LIVE state is malformed — reject
        # rather than silently storing a stale hint.
        bad_blob = (
            b'{"alpha_id": "kyle", "state": "PAPER", '
            b'"capital_tier": "SCALED"}'
        )
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        with pytest.raises(ValueError, match="capital_tier"):
            lc.restore(bad_blob)

    def test_restore_clears_stale_hint_when_legacy_blob_loaded(
        self, clock: SimulatedClock
    ) -> None:
        # If an instance has a hint from a prior restore() and is then
        # restored from a *legacy* blob (no capital_tier field), the
        # stale hint must NOT bleed through.
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        scaled_blob = (
            b'{"alpha_id": "kyle", "state": "LIVE", '
            b'"capital_tier": "SCALED"}'
        )
        lc.restore(scaled_blob)
        assert lc.current_capital_tier is CapitalStageTier.SCALED

        legacy_blob = b'{"alpha_id": "kyle", "state": "LIVE"}'
        lc.restore(legacy_blob)
        assert lc.current_capital_tier is CapitalStageTier.SMALL_CAPITAL


# ── F-6 P2: CLI gate inference is trigger-aware ────────────────────


class TestCapitalTierTriggerSentinel:
    """The Codex-bot P2 review issue on PR #23.

    The wire-format trigger ``promote_capital_tier`` is the **only**
    string that distinguishes a capital-tier escalation from any
    future ``LIVE -> LIVE`` self-loop the platform might gain.  This
    test pins the symbol to a stable value so a refactor cannot
    silently rename it (which would simultaneously break ``feelies
    promote replay-evidence`` gate inference and ledger archeology).
    """

    def test_trigger_sentinel_is_stable(self) -> None:
        assert PROMOTE_CAPITAL_TIER_TRIGGER == "promote_capital_tier"

    def test_lifecycle_records_trigger_sentinel_on_self_loop(
        self,
    ) -> None:
        clock = SimulatedClock(start_ns=1_700_000_000_000_000_000)
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        assert lc.promote_capital_tier(_passing_capital_stage()) == []

        history = lc.history
        live = AlphaLifecycleState.LIVE.name
        scaled_records = [
            r
            for r in history
            if r.from_state == live and r.to_state == live
        ]
        assert len(scaled_records) == 1
        assert scaled_records[0].trigger == PROMOTE_CAPITAL_TIER_TRIGGER

    def test_metadata_round_trip_preserves_tier(
        self,
    ) -> None:
        clock = SimulatedClock(start_ns=1_700_000_000_000_000_000)
        lc = AlphaLifecycle(alpha_id="kyle", clock=clock)
        _walk_to_live(lc)
        lc.promote_capital_tier(_passing_capital_stage())

        live = AlphaLifecycleState.LIVE.name
        record = next(
            r
            for r in reversed(lc.history)
            if r.from_state == live and r.to_state == live
        )
        assert record.metadata.get("schema_version") == EVIDENCE_SCHEMA_VERSION
        evs = metadata_to_evidence(record.metadata)
        # Exactly one CapitalStageEvidence on the round-trip.
        assert len(evs) == 1
        ev = evs[0]
        assert isinstance(ev, CapitalStageEvidence)
        assert ev.tier is CapitalStageTier.SMALL_CAPITAL
