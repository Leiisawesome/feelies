"""Tests for the F-2 promotion-evidence schemas, gate matrix, and validators.

Covers:

  * Each evidence dataclass — defaults, frozen-ness, kw-only construction.
  * Each per-type validator — pass cases, individual-threshold-fail cases,
    cumulative-error cases.
  * The :class:`GateThresholds` dataclass — defaults match the
    testing-validation / post-trade-forensics skill thresholds.
  * The gate matrix — completeness (every :class:`GateId` present),
    validator coverage (every required type has a validator and a
    metadata-kind string), :func:`required_evidence_types` lookup.
  * :func:`validate_gate` — missing-evidence rejection, unsupported-type
    rejection, duplicate-type rejection, error-merging.
  * :func:`evidence_to_metadata` — JSON-safe projection, duplicate-kind
    rejection, schema-version stamping, round-trip through the existing
    :class:`PromotionLedger` (byte-identical replay).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass

import pytest

from feelies.alpha.promotion_evidence import (
    EVIDENCE_SCHEMA_VERSION,
    GATE_EVIDENCE_REQUIREMENTS,
    CapitalStageEvidence,
    CapitalStageTier,
    CPCVEvidence,
    DSREvidence,
    GateId,
    GateThresholds,
    PaperWindowEvidence,
    QuarantineTriggerEvidence,
    ResearchAcceptanceEvidence,
    RevalidationEvidence,
    evidence_to_metadata,
    required_evidence_types,
    validate_capital_stage,
    validate_cpcv,
    validate_dsr,
    validate_gate,
    validate_paper_window,
    validate_quarantine_trigger,
    validate_research_acceptance,
    validate_revalidation,
)
from feelies.alpha.promotion_ledger import (
    PromotionLedger,
    PromotionLedgerEntry,
)


# ─────────────────────────────────────────────────────────────────────
# Evidence dataclass shape
# ─────────────────────────────────────────────────────────────────────


class TestEvidenceDataclasses:
    """Each evidence dataclass must be frozen + kw-only with sensible
    defaults so it can be partially constructed during the typical
    research workflow."""

    def test_research_acceptance_defaults(self) -> None:
        ev = ResearchAcceptanceEvidence()
        assert ev.schema_valid is False
        assert ev.determinism_replay_passed is False
        assert ev.branch_coverage_pct == 0.0
        assert ev.line_coverage_pct == 0.0
        assert ev.lookahead_bias_check_passed is False
        assert ev.fault_injection_pass_count == 0
        assert ev.fault_injection_total == 0
        assert ev.cost_sensitivity_passed is False
        assert ev.latency_sensitivity_passed is False

    def test_cpcv_defaults(self) -> None:
        ev = CPCVEvidence()
        assert ev.fold_count == 0
        assert ev.embargo_bars == 0
        assert ev.fold_sharpes == ()
        assert ev.mean_sharpe == 0.0
        assert ev.median_sharpe == 0.0
        assert ev.mean_pnl == 0.0
        assert ev.p_value == 1.0
        assert ev.fold_pnl_curves_hash == ""

    def test_dsr_defaults(self) -> None:
        ev = DSREvidence()
        assert ev.observed_sharpe == 0.0
        assert ev.trials_count == 0
        assert ev.skewness == 0.0
        assert ev.kurtosis == 3.0
        assert ev.dsr == 0.0
        assert ev.dsr_p_value == 1.0

    def test_paper_window_defaults(self) -> None:
        ev = PaperWindowEvidence()
        assert ev.trading_days == 0
        assert ev.sample_size == 0
        assert ev.slippage_residual_bps == 0.0
        assert ev.fill_rate_drift_pct == 0.0
        assert ev.latency_ks_p == 1.0
        assert ev.pnl_compression_ratio == 1.0
        assert ev.anomalous_event_count == 0

    def test_capital_stage_defaults(self) -> None:
        ev = CapitalStageEvidence()
        assert ev.tier is CapitalStageTier.SMALL_CAPITAL
        assert ev.allocation_fraction == 0.0
        assert ev.deployment_days == 0
        assert ev.pnl_compression_ratio_realised == 1.0
        assert ev.slippage_residual_bps == 0.0
        assert ev.hit_rate_residual_pp == 0.0
        assert ev.fill_rate_drift_pct == 0.0

    def test_quarantine_trigger_defaults(self) -> None:
        ev = QuarantineTriggerEvidence()
        assert ev.net_alpha_negative_days == 0
        assert ev.hit_rate_residual_pp == 0.0
        assert ev.microstructure_metrics_breached == ()
        assert ev.crowding_symptoms == ()
        assert ev.pnl_compression_ratio_5d == 1.0

    def test_revalidation_defaults(self) -> None:
        ev = RevalidationEvidence()
        assert ev.hypothesis_re_derived is False
        assert ev.oos_walkforward_sharpe == 0.0
        assert ev.parameter_drift_resolved is False
        assert ev.human_signoff == ""
        assert ev.revalidation_notes == ""

    def test_evidence_is_frozen(self) -> None:
        ev = CPCVEvidence(fold_count=8, mean_sharpe=1.5)
        with pytest.raises(FrozenInstanceError):
            ev.fold_count = 9  # type: ignore[misc]

    def test_evidence_requires_kw_only(self) -> None:
        # Positional arg must fail because the dataclass is kw_only.
        with pytest.raises(TypeError):
            CPCVEvidence(8)  # type: ignore[misc]

    def test_capital_tier_enum_values(self) -> None:
        assert CapitalStageTier.SMALL_CAPITAL.value == "SMALL_CAPITAL"
        assert CapitalStageTier.SCALED.value == "SCALED"
        assert {t.value for t in CapitalStageTier} == {
            "SMALL_CAPITAL",
            "SCALED",
        }


# ─────────────────────────────────────────────────────────────────────
# Validators
# ─────────────────────────────────────────────────────────────────────


def _full_research_pass() -> ResearchAcceptanceEvidence:
    """Helper — construct an evidence package that passes every
    research-acceptance threshold."""
    return ResearchAcceptanceEvidence(
        schema_valid=True,
        determinism_replay_passed=True,
        branch_coverage_pct=92.0,
        line_coverage_pct=85.0,
        lookahead_bias_check_passed=True,
        fault_injection_pass_count=20,
        fault_injection_total=20,
        cost_sensitivity_passed=True,
        latency_sensitivity_passed=True,
    )


def _full_cpcv_pass() -> CPCVEvidence:
    return CPCVEvidence(
        fold_count=8,
        embargo_bars=20,
        fold_sharpes=tuple([1.1, 1.2, 1.0, 1.3, 1.1, 1.4, 1.0, 1.2]),
        mean_sharpe=1.16,
        median_sharpe=1.15,
        mean_pnl=12345.67,
        p_value=0.01,
        fold_pnl_curves_hash="sha256:abc123",
    )


def _full_dsr_pass() -> DSREvidence:
    return DSREvidence(
        observed_sharpe=1.5,
        trials_count=12,
        skewness=-0.1,
        kurtosis=3.2,
        dsr=1.25,
        dsr_p_value=0.02,
    )


def _full_paper_window_pass() -> PaperWindowEvidence:
    return PaperWindowEvidence(
        trading_days=5,
        sample_size=200,
        slippage_residual_bps=0.5,
        fill_rate_drift_pct=2.0,
        latency_ks_p=0.30,
        pnl_compression_ratio=0.8,
        anomalous_event_count=0,
    )


def _full_capital_stage_pass() -> CapitalStageEvidence:
    return CapitalStageEvidence(
        tier=CapitalStageTier.SMALL_CAPITAL,
        allocation_fraction=0.01,
        deployment_days=12,
        pnl_compression_ratio_realised=0.85,
        slippage_residual_bps=1.0,
        hit_rate_residual_pp=-2.0,
        fill_rate_drift_pct=3.0,
    )


def _full_revalidation_pass() -> RevalidationEvidence:
    return RevalidationEvidence(
        hypothesis_re_derived=True,
        oos_walkforward_sharpe=1.3,
        parameter_drift_resolved=True,
        human_signoff="ops:engineer-A",
        revalidation_notes="Re-derived on Q1 data; param shift documented.",
    )


class TestValidateResearchAcceptance:
    def test_full_pass(self) -> None:
        assert validate_research_acceptance(_full_research_pass()) == []

    def test_default_evidence_fails_every_check(self) -> None:
        errors = validate_research_acceptance(ResearchAcceptanceEvidence())
        joined = " | ".join(errors)
        assert "schema validation" in joined
        assert "determinism" in joined
        assert "branch coverage" in joined
        assert "line coverage" in joined
        assert "lookahead-bias" in joined
        assert "fault-injection" in joined
        assert "cost-sensitivity" in joined
        assert "latency-sensitivity" in joined

    def test_partial_fault_injection_fail(self) -> None:
        ev = ResearchAcceptanceEvidence(
            schema_valid=True,
            determinism_replay_passed=True,
            branch_coverage_pct=95.0,
            line_coverage_pct=85.0,
            lookahead_bias_check_passed=True,
            fault_injection_pass_count=18,
            fault_injection_total=20,
            cost_sensitivity_passed=True,
            latency_sensitivity_passed=True,
        )
        errors = validate_research_acceptance(ev)
        assert len(errors) == 1
        assert "fault-injection pass rate" in errors[0]
        assert "90.0%" in errors[0]

    def test_threshold_override_relaxes(self) -> None:
        ev = ResearchAcceptanceEvidence(
            schema_valid=True,
            determinism_replay_passed=True,
            branch_coverage_pct=80.0,
            line_coverage_pct=70.0,
            lookahead_bias_check_passed=True,
            fault_injection_pass_count=20,
            fault_injection_total=20,
            cost_sensitivity_passed=True,
            latency_sensitivity_passed=True,
        )
        relaxed = GateThresholds(
            research_min_branch_coverage_pct=70.0,
            research_min_line_coverage_pct=60.0,
        )
        assert validate_research_acceptance(ev, relaxed) == []


class TestValidateCPCV:
    def test_full_pass(self) -> None:
        assert validate_cpcv(_full_cpcv_pass()) == []

    def test_too_few_folds(self) -> None:
        ev = CPCVEvidence(
            fold_count=4,
            fold_sharpes=tuple([1.5, 1.5, 1.5, 1.5]),
            mean_sharpe=1.5,
            p_value=0.01,
        )
        errors = validate_cpcv(ev)
        assert any("fold_count" in e for e in errors)

    def test_inconsistent_fold_sharpes_length(self) -> None:
        ev = CPCVEvidence(
            fold_count=8,
            fold_sharpes=tuple([1.5, 1.5, 1.5]),
            mean_sharpe=1.5,
            p_value=0.01,
        )
        errors = validate_cpcv(ev)
        assert any("inconsistent" in e for e in errors)

    def test_low_mean_sharpe(self) -> None:
        ev = CPCVEvidence(
            fold_count=8,
            fold_sharpes=tuple([0.5] * 8),
            mean_sharpe=0.5,
            p_value=0.01,
        )
        errors = validate_cpcv(ev)
        assert any("mean Sharpe" in e for e in errors)

    def test_high_p_value(self) -> None:
        ev = CPCVEvidence(
            fold_count=8,
            fold_sharpes=tuple([1.5] * 8),
            mean_sharpe=1.5,
            p_value=0.20,
        )
        errors = validate_cpcv(ev)
        assert any("p-value" in e for e in errors)


class TestValidateDSR:
    def test_full_pass(self) -> None:
        assert validate_dsr(_full_dsr_pass()) == []

    def test_dsr_below_floor(self) -> None:
        ev = DSREvidence(
            observed_sharpe=1.5,
            trials_count=12,
            dsr=0.5,
            dsr_p_value=0.02,
        )
        errors = validate_dsr(ev)
        assert any("DSR" in e and "schema-1.1" in e for e in errors)

    def test_p_value_above_threshold(self) -> None:
        ev = DSREvidence(
            observed_sharpe=1.5,
            trials_count=12,
            dsr=1.2,
            dsr_p_value=0.10,
        )
        errors = validate_dsr(ev)
        assert any("DSR p-value" in e for e in errors)

    def test_zero_trials_rejected(self) -> None:
        ev = DSREvidence(
            observed_sharpe=1.5,
            trials_count=0,
            dsr=1.2,
            dsr_p_value=0.02,
        )
        errors = validate_dsr(ev)
        assert any("trials_count" in e for e in errors)


class TestValidatePaperWindow:
    def test_full_pass(self) -> None:
        assert validate_paper_window(_full_paper_window_pass()) == []

    def test_too_few_trading_days(self) -> None:
        ev = PaperWindowEvidence(
            trading_days=2,
            sample_size=100,
            slippage_residual_bps=0.5,
            fill_rate_drift_pct=2.0,
            latency_ks_p=0.30,
            pnl_compression_ratio=0.8,
            anomalous_event_count=0,
        )
        errors = validate_paper_window(ev)
        assert any("trading_days" in e for e in errors)

    def test_excess_slippage(self) -> None:
        ev = _full_paper_window_pass()
        ev = PaperWindowEvidence(**{**ev.__dict__, "slippage_residual_bps": 5.0})
        errors = validate_paper_window(ev)
        assert any("slippage residual" in e for e in errors)

    def test_fill_rate_drift_band_is_two_sided(self) -> None:
        # Negative drift exceeds the band as well as positive.
        ev_neg = PaperWindowEvidence(
            trading_days=5, sample_size=100, slippage_residual_bps=0.5,
            fill_rate_drift_pct=-15.0, latency_ks_p=0.30,
            pnl_compression_ratio=0.8, anomalous_event_count=0,
        )
        ev_pos = PaperWindowEvidence(
            trading_days=5, sample_size=100, slippage_residual_bps=0.5,
            fill_rate_drift_pct=+15.0, latency_ks_p=0.30,
            pnl_compression_ratio=0.8, anomalous_event_count=0,
        )
        assert any("fill-rate drift" in e for e in validate_paper_window(ev_neg))
        assert any("fill-rate drift" in e for e in validate_paper_window(ev_pos))

    def test_latency_ks_low_p_flagged(self) -> None:
        ev = _full_paper_window_pass()
        ev = PaperWindowEvidence(**{**ev.__dict__, "latency_ks_p": 0.05})
        errors = validate_paper_window(ev)
        assert any("latency KS" in e for e in errors)

    def test_pnl_compression_low(self) -> None:
        ev = _full_paper_window_pass()
        ev = PaperWindowEvidence(
            **{**ev.__dict__, "pnl_compression_ratio": 0.4}
        )
        errors = validate_paper_window(ev)
        assert any("PnL compression ratio" in e and "0.40" in e for e in errors)

    def test_pnl_compression_high(self) -> None:
        ev = _full_paper_window_pass()
        ev = PaperWindowEvidence(
            **{**ev.__dict__, "pnl_compression_ratio": 1.5}
        )
        errors = validate_paper_window(ev)
        assert any("upper alert" in e for e in errors)

    def test_anomalous_events_blocked(self) -> None:
        ev = _full_paper_window_pass()
        ev = PaperWindowEvidence(**{**ev.__dict__, "anomalous_event_count": 1})
        errors = validate_paper_window(ev)
        assert any("anomalous events" in e for e in errors)


class TestValidateCapitalStage:
    def test_full_pass(self) -> None:
        assert validate_capital_stage(_full_capital_stage_pass()) == []

    def test_too_few_deployment_days(self) -> None:
        ev = _full_capital_stage_pass()
        ev = CapitalStageEvidence(**{**ev.__dict__, "deployment_days": 5})
        errors = validate_capital_stage(ev)
        assert any("deployment_days" in e for e in errors)

    def test_pnl_compression_too_low(self) -> None:
        ev = _full_capital_stage_pass()
        ev = CapitalStageEvidence(
            **{**ev.__dict__, "pnl_compression_ratio_realised": 0.3}
        )
        errors = validate_capital_stage(ev)
        assert any("PnL compression" in e and "< 0.50" in e for e in errors)

    def test_pnl_compression_too_high(self) -> None:
        ev = _full_capital_stage_pass()
        ev = CapitalStageEvidence(
            **{**ev.__dict__, "pnl_compression_ratio_realised": 1.4}
        )
        errors = validate_capital_stage(ev)
        assert any("upper alert" in e for e in errors)

    def test_excess_slippage(self) -> None:
        ev = _full_capital_stage_pass()
        ev = CapitalStageEvidence(**{**ev.__dict__, "slippage_residual_bps": 5.0})
        errors = validate_capital_stage(ev)
        assert any("slippage residual" in e for e in errors)

    def test_hit_rate_residual_below_floor(self) -> None:
        ev = _full_capital_stage_pass()
        ev = CapitalStageEvidence(
            **{**ev.__dict__, "hit_rate_residual_pp": -10.0}
        )
        errors = validate_capital_stage(ev)
        assert any("hit-rate residual" in e for e in errors)

    def test_wrong_outgoing_tier_rejected(self) -> None:
        ev = _full_capital_stage_pass()
        ev = CapitalStageEvidence(
            **{**ev.__dict__, "tier": CapitalStageTier.SCALED}
        )
        errors = validate_capital_stage(ev)
        assert any("tier=SMALL_CAPITAL" in e for e in errors)


class TestValidateQuarantineTrigger:
    def test_net_alpha_trigger_passes(self) -> None:
        ev = QuarantineTriggerEvidence(net_alpha_negative_days=10)
        assert validate_quarantine_trigger(ev) == []

    def test_hit_rate_collapse_trigger(self) -> None:
        ev = QuarantineTriggerEvidence(hit_rate_residual_pp=-15.0)
        assert validate_quarantine_trigger(ev) == []

    def test_microstructure_breach_trigger(self) -> None:
        ev = QuarantineTriggerEvidence(
            microstructure_metrics_breached=tuple(["spread", "quote_freq"])
        )
        assert validate_quarantine_trigger(ev) == []

    def test_crowding_trigger(self) -> None:
        ev = QuarantineTriggerEvidence(
            crowding_symptoms=tuple(["adverse_selection", "quote_anticipation", "shortfall_growth"])
        )
        assert validate_quarantine_trigger(ev) == []

    def test_pnl_compression_trigger(self) -> None:
        ev = QuarantineTriggerEvidence(pnl_compression_ratio_5d=0.2)
        assert validate_quarantine_trigger(ev) == []

    def test_no_trigger_flagged_as_spurious(self) -> None:
        ev = QuarantineTriggerEvidence()  # all defaults
        errors = validate_quarantine_trigger(ev)
        assert len(errors) == 1
        assert "spurious trigger" in errors[0]


class TestValidateRevalidation:
    def test_full_pass(self) -> None:
        assert validate_revalidation(_full_revalidation_pass()) == []

    def test_default_evidence_fails(self) -> None:
        errors = validate_revalidation(RevalidationEvidence())
        joined = " | ".join(errors)
        assert "hypothesis" in joined
        assert "OOS walk-forward Sharpe" in joined
        assert "parameter drift" in joined
        assert "human_signoff" in joined

    def test_low_oos_sharpe(self) -> None:
        ev = _full_revalidation_pass()
        ev = RevalidationEvidence(**{**ev.__dict__, "oos_walkforward_sharpe": 0.5})
        errors = validate_revalidation(ev)
        assert any("OOS walk-forward Sharpe" in e for e in errors)

    def test_whitespace_signoff_rejected(self) -> None:
        ev = _full_revalidation_pass()
        ev = RevalidationEvidence(**{**ev.__dict__, "human_signoff": "   "})
        errors = validate_revalidation(ev)
        assert any("human_signoff" in e for e in errors)


# ─────────────────────────────────────────────────────────────────────
# Gate matrix
# ─────────────────────────────────────────────────────────────────────


class TestGateMatrix:
    def test_every_gate_id_has_entry(self) -> None:
        for gate in GateId:
            assert gate in GATE_EVIDENCE_REQUIREMENTS

    def test_required_evidence_lookup_returns_tuple(self) -> None:
        for gate in GateId:
            req = required_evidence_types(gate)
            assert isinstance(req, tuple)

    def test_research_to_paper_requires_only_research(self) -> None:
        assert required_evidence_types(GateId.RESEARCH_TO_PAPER) == (
            ResearchAcceptanceEvidence,
        )

    def test_paper_to_live_requires_paper_cpcv_dsr(self) -> None:
        req = required_evidence_types(GateId.PAPER_TO_LIVE)
        assert set(req) == {PaperWindowEvidence, CPCVEvidence, DSREvidence}

    def test_capital_tier_requires_capital_stage(self) -> None:
        assert required_evidence_types(GateId.LIVE_PROMOTE_CAPITAL_TIER) == (
            CapitalStageEvidence,
        )

    def test_decommission_requires_no_evidence(self) -> None:
        assert required_evidence_types(GateId.QUARANTINED_TO_DECOMMISSIONED) == ()

    def test_quarantined_to_paper_requires_revalidation(self) -> None:
        assert required_evidence_types(GateId.QUARANTINED_TO_PAPER) == (
            RevalidationEvidence,
        )

    def test_live_to_quarantined_requires_trigger(self) -> None:
        assert required_evidence_types(GateId.LIVE_TO_QUARANTINED) == (
            QuarantineTriggerEvidence,
        )


class TestValidateGate:
    def test_research_to_paper_full_pass(self) -> None:
        errors = validate_gate(
            GateId.RESEARCH_TO_PAPER, [_full_research_pass()]
        )
        assert errors == []

    def test_paper_to_live_full_pass(self) -> None:
        errors = validate_gate(
            GateId.PAPER_TO_LIVE,
            [
                _full_paper_window_pass(),
                _full_cpcv_pass(),
                _full_dsr_pass(),
            ],
        )
        assert errors == []

    def test_paper_to_live_missing_dsr(self) -> None:
        errors = validate_gate(
            GateId.PAPER_TO_LIVE,
            [_full_paper_window_pass(), _full_cpcv_pass()],
        )
        assert any(
            "requires evidence of type 'DSREvidence'" in e for e in errors
        )

    def test_paper_to_live_missing_all(self) -> None:
        errors = validate_gate(GateId.PAPER_TO_LIVE, [])
        # 3 missing-type errors expected
        missing_msgs = [e for e in errors if "requires evidence of type" in e]
        assert len(missing_msgs) == 3

    def test_decommission_accepts_empty_evidence(self) -> None:
        errors = validate_gate(GateId.QUARANTINED_TO_DECOMMISSIONED, [])
        assert errors == []

    def test_unsupported_evidence_type_rejected(self) -> None:
        @dataclass(frozen=True, kw_only=True)
        class BogusEvidence:
            x: int = 0

        errors = validate_gate(
            GateId.RESEARCH_TO_PAPER,
            [_full_research_pass(), BogusEvidence(x=1)],
        )
        assert any("unsupported evidence type" in e for e in errors)

    def test_duplicate_evidence_type_rejected(self) -> None:
        errors = validate_gate(
            GateId.RESEARCH_TO_PAPER,
            [_full_research_pass(), _full_research_pass()],
        )
        assert any("duplicate evidence type" in e for e in errors)

    def test_paper_to_live_validator_errors_are_merged(self) -> None:
        bad_paper = PaperWindowEvidence(
            trading_days=1,
            sample_size=10,
            slippage_residual_bps=5.0,
            fill_rate_drift_pct=2.0,
            latency_ks_p=0.30,
            pnl_compression_ratio=0.8,
            anomalous_event_count=0,
        )
        bad_cpcv = CPCVEvidence(
            fold_count=2,
            fold_sharpes=tuple([0.5, 0.5]),
            mean_sharpe=0.5,
            p_value=0.10,
        )
        errors = validate_gate(
            GateId.PAPER_TO_LIVE,
            [bad_paper, bad_cpcv, _full_dsr_pass()],
        )
        joined = " | ".join(errors)
        assert "trading_days" in joined
        assert "slippage residual" in joined
        assert "fold_count" in joined
        assert "mean Sharpe" in joined

    def test_thresholds_override_propagates(self) -> None:
        relaxed = GateThresholds(paper_min_trading_days=1)
        ev = PaperWindowEvidence(
            trading_days=1,
            sample_size=200,
            slippage_residual_bps=0.5,
            fill_rate_drift_pct=2.0,
            latency_ks_p=0.30,
            pnl_compression_ratio=0.8,
            anomalous_event_count=0,
        )
        errors = validate_gate(
            GateId.PAPER_TO_LIVE,
            [ev, _full_cpcv_pass(), _full_dsr_pass()],
            thresholds=relaxed,
        )
        # Only the threshold-relaxed paper-window check should pass; nothing else fails.
        assert errors == []


# ─────────────────────────────────────────────────────────────────────
# Metadata projection + ledger round-trip
# ─────────────────────────────────────────────────────────────────────


class TestEvidenceToMetadata:
    def test_empty_call_yields_just_schema_version(self) -> None:
        payload = evidence_to_metadata()
        assert payload == {"schema_version": EVIDENCE_SCHEMA_VERSION}

    def test_single_evidence_keyed_by_kind(self) -> None:
        cpcv = _full_cpcv_pass()
        payload = evidence_to_metadata(cpcv)
        assert "cpcv" in payload
        assert payload["cpcv"]["fold_count"] == 8
        assert payload["cpcv"]["mean_sharpe"] == pytest.approx(1.16)
        # Tuple → list for JSON.
        assert isinstance(payload["cpcv"]["fold_sharpes"], list)
        assert payload["cpcv"]["fold_sharpes"][0] == pytest.approx(1.1)

    def test_capital_stage_enum_serialised_as_value(self) -> None:
        ev = _full_capital_stage_pass()
        payload = evidence_to_metadata(ev)
        assert payload["capital_stage"]["tier"] == "SMALL_CAPITAL"

    def test_multiple_evidences_each_keyed(self) -> None:
        payload = evidence_to_metadata(
            _full_paper_window_pass(),
            _full_cpcv_pass(),
            _full_dsr_pass(),
        )
        assert {"paper_window", "cpcv", "dsr", "schema_version"} <= set(payload)

    def test_duplicate_kind_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate evidence kind"):
            evidence_to_metadata(_full_cpcv_pass(), _full_cpcv_pass())

    def test_unsupported_type_rejected(self) -> None:
        @dataclass(frozen=True, kw_only=True)
        class Bogus:
            x: int = 0

        with pytest.raises(TypeError, match="unsupported evidence type"):
            evidence_to_metadata(Bogus(x=1))

    def test_non_dataclass_input_rejected(self) -> None:
        # Anything that is registered in _KIND_BY_TYPE is by construction a
        # dataclass (we control the registration), so the only way to hit
        # the non-dataclass branch is to spoof a registered type via a
        # subclass.  We exercise the safe path: the unsupported-type
        # branch already covers non-dataclass inputs, but make sure the
        # internal helper still rejects non-dataclasses if called
        # directly via our supported-type registry.
        from feelies.alpha.promotion_evidence import (
            _evidence_to_jsonable,
        )

        with pytest.raises(TypeError, match="dataclass instance"):
            _evidence_to_jsonable(object())  # plain object, not a dataclass

    def test_schema_version_stamped(self) -> None:
        payload = evidence_to_metadata(_full_cpcv_pass())
        assert payload["schema_version"] == EVIDENCE_SCHEMA_VERSION


class TestLedgerRoundTrip:
    """Round-trip check: structured evidence → metadata dict → ledger
    (JSONL on disk) → re-parsed entry → metadata fields preserved.
    """

    def test_metadata_round_trips_through_ledger(self, tmp_path: object) -> None:
        from pathlib import Path

        path = Path(str(tmp_path)) / "ledger.jsonl"
        ledger = PromotionLedger(path)
        metadata = evidence_to_metadata(
            _full_paper_window_pass(),
            _full_cpcv_pass(),
            _full_dsr_pass(),
        )
        entry = PromotionLedgerEntry(
            alpha_id="alpha_test",
            from_state="PAPER",
            to_state="LIVE",
            trigger="pass_live_gate",
            timestamp_ns=42,
            correlation_id="corr-1",
            metadata=metadata,
        )
        ledger.append(entry)

        reread = list(ledger.entries())
        assert len(reread) == 1
        re_md = reread[0].metadata
        assert re_md["schema_version"] == EVIDENCE_SCHEMA_VERSION
        assert re_md["paper_window"]["trading_days"] == 5
        assert re_md["cpcv"]["fold_count"] == 8
        assert re_md["dsr"]["dsr"] == pytest.approx(1.25)

    def test_byte_identical_replay(self, tmp_path: object) -> None:
        """Two independent runs that submit the same evidence stream must
        produce byte-identical ledger files (Inv-5 replay determinism)."""
        from pathlib import Path

        def run(target: Path) -> None:
            ledger = PromotionLedger(target)
            md = evidence_to_metadata(
                _full_research_pass(),
            )
            ledger.append(
                PromotionLedgerEntry(
                    alpha_id="alpha_X",
                    from_state="RESEARCH",
                    to_state="PAPER",
                    trigger="pass_paper_gate",
                    timestamp_ns=100,
                    correlation_id="corr",
                    metadata=md,
                )
            )

        a = Path(str(tmp_path)) / "a.jsonl"
        b = Path(str(tmp_path)) / "b.jsonl"
        run(a)
        run(b)
        assert a.read_bytes() == b.read_bytes()


# ─────────────────────────────────────────────────────────────────────
# GateThresholds defaults
# ─────────────────────────────────────────────────────────────────────


class TestGateThresholds:
    """Spot-check that the documented platform defaults survive any
    accidental edit.  The values are pinned to specific skill rows in
    the testing-validation and post-trade-forensics skills."""

    def test_skill_pinned_defaults(self) -> None:
        t = GateThresholds()
        assert t.paper_min_trading_days == 5
        assert t.small_min_deployment_days == 10
        assert t.small_min_pnl_compression_ratio == 0.5
        assert t.small_max_pnl_compression_ratio == 1.0
        assert t.dsr_min == 1.0
        assert t.cpcv_min_folds == 8
        assert t.quarantine_max_net_alpha_negative_days == 10
        assert t.quarantine_max_hit_rate_residual_pp == -15.0
        assert t.quarantine_max_pnl_compression_ratio_5d == 0.3
        assert t.quarantine_min_microstructure_breaches == 2
        assert t.quarantine_min_crowding_symptoms == 3

    def test_thresholds_frozen(self) -> None:
        t = GateThresholds()
        with pytest.raises(FrozenInstanceError):
            t.paper_min_trading_days = 1  # type: ignore[misc]
