"""Stage-0 ``decouple_caps_only`` promotion gate (dual-permission Phase 6).

Covers the gate surface added to :mod:`feelies.promotion.evidence` and the
:meth:`feelies.promotion.lifecycle.AlphaLifecycle.authorize_decouple` write path:

  * the three evidence dataclasses (frozen, kw-only);
  * each validator's individual failure modes (mid-marks, un-stressed fills,
    integrity drift, turnover ceiling, backstop breach);
  * gate-matrix membership + :func:`validate_gate` composition;
  * metadata round-trip through the promotion ledger;
  * ``authorize_decouple`` — LIVE-only, human sign-off + config version required,
    a failing/under-powered gate blocks the promotion (nothing written), and a
    successful authorization records the outcome + config version in the ledger
    without disturbing the capital tier.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from feelies.promotion.lifecycle import AlphaLifecycle, AlphaLifecycleState
from feelies.promotion.evidence import (
    AUTHORIZE_DECOUPLE_TRIGGER,
    GATE_EVIDENCE_REQUIREMENTS,
    ConditionalCVaREvidence,
    GateId,
    QuoteFreezeBackstopEvidence,
    TurnoverBoundEvidence,
    evidence_to_metadata,
    metadata_to_evidence,
    validate_conditional_cvar,
    validate_gate,
    validate_quote_freeze_backstop,
    validate_turnover_bound,
)
from feelies.promotion.ledger import PromotionLedger, PromotionLedgerEntry
from feelies.core.clock import SimulatedClock

# ─────────────────────────────────────────────────────────────────────
#   Passing-evidence factories (a clean decouple gate)
# ─────────────────────────────────────────────────────────────────────


def _passing_cvar(**overrides: object) -> ConditionalCVaREvidence:
    base = dict(
        cvar_level=0.05,
        horizon_bars=10,
        subpopulation_size=400,
        effective_tail_sample=20,
        hold_cvar=-0.020,
        flatten_cvar=-0.021,
        cvar_delta=0.001,
        cpcv_fold_count=9,
        cpcv_embargo_bars=5,
        inv12_cost_multiplier=1.5,
        inv12_latency_multiplier=2.0,
        modeled_fills=True,
        path_cvar_deltas=(0.001,) * 9,
    )
    base.update(overrides)
    return ConditionalCVaREvidence(**base)  # type: ignore[arg-type]


def _passing_turnover(**overrides: object) -> TurnoverBoundEvidence:
    base = dict(
        baseline_round_trips=100,
        deferral_round_trips=110,
        declared_max_ratio=1.2,
        observed_ratio=1.1,
        subpopulation_size=400,
    )
    base.update(overrides)
    return TurnoverBoundEvidence(**base)  # type: ignore[arg-type]


def _passing_quote_freeze(**overrides: object) -> QuoteFreezeBackstopEvidence:
    base = dict(
        quote_freeze_episodes=5,
        exited_by_session_flatten=5,
        breached_session_backstop=0,
        session_flatten_bound_seconds=3600.0,
        max_hold_seconds_observed=1800.0,
    )
    base.update(overrides)
    return QuoteFreezeBackstopEvidence(**base)  # type: ignore[arg-type]


def _live_lifecycle(
    alpha_id: str = "kyle",
    *,
    ledger: PromotionLedger | None = None,
) -> AlphaLifecycle:
    """A lifecycle restored straight to LIVE @ SMALL_CAPITAL.

    ``authorize_decouple`` is a LIVE-only self-loop; ``restore`` sets the state
    without walking the promotion ladder (and without writing the ledger), so a
    test that only cares about the decouple entry starts from a clean ledger.
    """
    lc = AlphaLifecycle(
        alpha_id=alpha_id,
        clock=SimulatedClock(start_ns=1_700_000_000_000_000_000),
        ledger=ledger,
    )
    lc.restore(
        b'{"alpha_id": "%s", "state": "LIVE", "capital_tier": "SMALL_CAPITAL"}' % alpha_id.encode()
    )
    return lc


# ─────────────────────────────────────────────────────────────────────
#   Evidence dataclasses
# ─────────────────────────────────────────────────────────────────────


class TestEvidenceDataclasses:
    def test_frozen(self) -> None:
        ev = _passing_cvar()
        with pytest.raises(FrozenInstanceError):
            ev.hold_cvar = 0.0  # type: ignore[misc]

    def test_kw_only(self) -> None:
        with pytest.raises(TypeError):
            ConditionalCVaREvidence(0.05)  # type: ignore[misc]

    def test_gate_matrix_membership(self) -> None:
        required = GATE_EVIDENCE_REQUIREMENTS[GateId.DECOUPLE_CAPS_ONLY]
        assert required == (
            ConditionalCVaREvidence,
            TurnoverBoundEvidence,
            QuoteFreezeBackstopEvidence,
        )


# ─────────────────────────────────────────────────────────────────────
#   Validators — individual failure modes
# ─────────────────────────────────────────────────────────────────────


class TestConditionalCVaRValidator:
    def test_clean_evidence_passes(self) -> None:
        assert validate_conditional_cvar(_passing_cvar()) == []

    def test_mid_marks_rejected(self) -> None:
        errors = validate_conditional_cvar(_passing_cvar(modeled_fills=False))
        assert any("modeled fills" in e for e in errors)

    def test_unstressed_cost_rejected(self) -> None:
        errors = validate_conditional_cvar(_passing_cvar(inv12_cost_multiplier=1.0))
        assert any("cost stress" in e for e in errors)

    def test_unstressed_latency_rejected(self) -> None:
        errors = validate_conditional_cvar(_passing_cvar(inv12_latency_multiplier=1.0))
        assert any("latency stress" in e for e in errors)

    def test_tail_wider_than_ceiling_rejected(self) -> None:
        errors = validate_conditional_cvar(_passing_cvar(cvar_level=0.5))
        assert any("not a left tail" in e for e in errors)

    def test_fabricated_delta_rejected(self) -> None:
        # cvar_delta inconsistent with hold - flatten.
        errors = validate_conditional_cvar(_passing_cvar(cvar_delta=0.5))
        assert any("does not match" in e for e in errors)

    def test_path_delta_count_mismatch_rejected(self) -> None:
        errors = validate_conditional_cvar(_passing_cvar(path_cvar_deltas=(0.001,) * 3))
        assert any("path_cvar_deltas" in e for e in errors)

    def test_too_few_cpcv_folds_rejected(self) -> None:
        errors = validate_conditional_cvar(
            _passing_cvar(cpcv_fold_count=3, path_cvar_deltas=(0.001,) * 3)
        )
        assert any("cpcv_fold_count" in e for e in errors)

    def test_zero_embargo_rejected(self) -> None:
        errors = validate_conditional_cvar(_passing_cvar(cpcv_embargo_bars=0))
        assert any("embargo" in e for e in errors)


class TestTurnoverValidator:
    def test_clean_evidence_passes(self) -> None:
        assert validate_turnover_bound(_passing_turnover()) == []

    def test_fabricated_ratio_rejected(self) -> None:
        errors = validate_turnover_bound(_passing_turnover(observed_ratio=1.0))
        assert any("does not match" in e for e in errors)

    def test_under_powered_sample_rejected(self) -> None:
        errors = validate_turnover_bound(_passing_turnover(subpopulation_size=5))
        assert any("under-powered" in e for e in errors)


class TestQuoteFreezeValidator:
    def test_clean_evidence_passes(self) -> None:
        assert validate_quote_freeze_backstop(_passing_quote_freeze()) == []

    def test_partial_exit_rejected(self) -> None:
        errors = validate_quote_freeze_backstop(_passing_quote_freeze(exited_by_session_flatten=4))
        assert any("freeze episodes exited" in e for e in errors)


# ─────────────────────────────────────────────────────────────────────
#   validate_gate composition + metadata round-trip
# ─────────────────────────────────────────────────────────────────────


class TestGateCompositionAndRoundTrip:
    def test_full_gate_passes(self) -> None:
        assert (
            validate_gate(
                GateId.DECOUPLE_CAPS_ONLY,
                [_passing_cvar(), _passing_turnover(), _passing_quote_freeze()],
            )
            == []
        )

    def test_missing_evidence_rejected(self) -> None:
        errors = validate_gate(GateId.DECOUPLE_CAPS_ONLY, [_passing_cvar()])
        assert any("TurnoverBoundEvidence" in e for e in errors)
        assert any("QuoteFreezeBackstopEvidence" in e for e in errors)

    def test_metadata_round_trips_through_ledger(self, tmp_path: Path) -> None:
        cvar, turn, qf = _passing_cvar(), _passing_turnover(), _passing_quote_freeze()
        metadata = evidence_to_metadata(cvar, turn, qf)
        entry = PromotionLedgerEntry(
            alpha_id="kyle",
            from_state="LIVE",
            to_state="LIVE",
            trigger=AUTHORIZE_DECOUPLE_TRIGGER,
            timestamp_ns=1,
            metadata=metadata,
        )
        ledger = PromotionLedger(tmp_path / "l.jsonl")
        ledger.append(entry)
        (loaded,) = list(ledger.entries())
        by_kind = {type(e).__name__: e for e in metadata_to_evidence(loaded.metadata)}
        assert by_kind["ConditionalCVaREvidence"] == cvar
        assert by_kind["TurnoverBoundEvidence"] == turn
        assert by_kind["QuoteFreezeBackstopEvidence"] == qf


# ─────────────────────────────────────────────────────────────────────
#   AlphaLifecycle.authorize_decouple
# ─────────────────────────────────────────────────────────────────────


class TestAuthorizeDecouple:
    def test_records_gate_outcome_and_config_version(self, tmp_path: Path) -> None:
        # ACCEPTANCE (design §4.3 / Inv-11): the promotion ledger records the
        # gate outcome + config version + human sign-off.
        ledger = PromotionLedger(tmp_path / "l.jsonl")
        lc = _live_lifecycle(ledger=ledger)
        errors = lc.authorize_decouple(
            structured_evidence=[_passing_cvar(), _passing_turnover(), _passing_quote_freeze()],
            config_version="kyle@1.2:decouple_caps_only",
            authorized_by="pm-alice",
        )
        assert errors == []
        (entry,) = list(ledger.entries())
        assert (entry.from_state, entry.to_state) == ("LIVE", "LIVE")
        assert entry.trigger == AUTHORIZE_DECOUPLE_TRIGGER
        assert entry.metadata["config_version"] == "kyle@1.2:decouple_caps_only"
        assert entry.metadata["authorized_by"] == "pm-alice"
        # The gate evidence round-trips alongside the authorization co-keys.
        kinds = {type(e).__name__ for e in metadata_to_evidence(entry.metadata)}
        assert kinds == {
            "ConditionalCVaREvidence",
            "TurnoverBoundEvidence",
            "QuoteFreezeBackstopEvidence",
        }

    def test_requires_live_state(self, tmp_path: Path) -> None:
        ledger = PromotionLedger(tmp_path / "l.jsonl")
        lc = AlphaLifecycle(
            alpha_id="kyle",
            clock=SimulatedClock(start_ns=1),
            ledger=ledger,
        )  # starts in RESEARCH
        errors = lc.authorize_decouple(
            structured_evidence=[_passing_cvar(), _passing_turnover(), _passing_quote_freeze()],
            config_version="v1",
            authorized_by="pm",
        )
        assert any("requires state=LIVE" in e for e in errors)
        assert list(ledger.entries()) == []

    def test_under_powered_gate_blocks_and_writes_nothing(self, tmp_path: Path) -> None:
        # ACCEPTANCE: a failing/under-powered gate blocks the promotion.
        ledger = PromotionLedger(tmp_path / "l.jsonl")
        lc = _live_lifecycle(ledger=ledger)
        errors = lc.authorize_decouple(
            structured_evidence=[
                _passing_cvar(effective_tail_sample=5),
                _passing_turnover(),
                _passing_quote_freeze(),
            ],
            config_version="v1",
            authorized_by="pm",
        )
        assert any("under-powered" in e for e in errors)
        assert list(ledger.entries()) == []
        assert lc.state is AlphaLifecycleState.LIVE

    def test_requires_human_signoff(self) -> None:
        lc = _live_lifecycle()
        errors = lc.authorize_decouple(
            structured_evidence=[_passing_cvar(), _passing_turnover(), _passing_quote_freeze()],
            config_version="v1",
            authorized_by="   ",
        )
        assert any("authorized_by" in e for e in errors)

    def test_requires_config_version(self) -> None:
        lc = _live_lifecycle()
        errors = lc.authorize_decouple(
            structured_evidence=[_passing_cvar(), _passing_turnover(), _passing_quote_freeze()],
            config_version="",
            authorized_by="pm",
        )
        assert any("config_version" in e for e in errors)

    def test_does_not_disturb_capital_tier(self) -> None:
        # A decouple self-loop must not be mistaken for a capital-tier
        # escalation: the tier stays SMALL_CAPITAL.
        lc = _live_lifecycle()
        lc.authorize_decouple(
            structured_evidence=[_passing_cvar(), _passing_turnover(), _passing_quote_freeze()],
            config_version="v1",
            authorized_by="pm",
        )
        from feelies.promotion.evidence import CapitalStageTier

        assert lc.current_capital_tier is CapitalStageTier.SMALL_CAPITAL
