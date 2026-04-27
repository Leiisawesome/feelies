"""Workstream F-6 ``feelies promote`` CLI surfaces.

These tests assert that the operator CLI correctly recognises the
LIVE → LIVE capital-tier escalation introduced by F-6:

  * ``inspect`` (text + JSON) renders the tier suffix in the header,
    formats the LIVE @ SMALL_CAPITAL → LIVE @ SCALED arrow specially,
    and exposes ``current_capital_tier`` in the JSON output.
  * ``list`` (text + JSON) renders ``LIVE @ SCALED`` (or
    ``LIVE @ SMALL_CAPITAL``) in the state column and exposes
    ``current_capital_tier`` in the JSON output.
  * ``replay-evidence`` infers
    :attr:`GateId.LIVE_PROMOTE_CAPITAL_TIER` for ``("LIVE", "LIVE")``
    transitions with trigger ``promote_capital_tier`` and validates
    the round-tripped ``CapitalStageEvidence`` against current
    thresholds (no ``skipped_reason`` for these entries).
  * Quarantine after a SCALED escalation drops the tier back to
    ``None`` in both ``inspect`` and ``list``.

The CLI is read-only and forensic-only — these tests build small
ledger files in ``tmp_path`` and assert on stdout; they never import
the orchestrator or risk engine and therefore preserve replay
determinism (audit A-DET-02).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    evidence_to_metadata,
)
from feelies.alpha.promotion_ledger import (
    PromotionLedger,
    PromotionLedgerEntry,
)
from feelies.cli.main import (
    EXIT_OK,
    EXIT_VALIDATION_FAILED,
    main,
)


# ── Helpers ───────────────────────────────────────────────────────


def _research() -> ResearchAcceptanceEvidence:
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


def _paper() -> PaperWindowEvidence:
    return PaperWindowEvidence(
        trading_days=10,
        sample_size=400,
        slippage_residual_bps=0.7,
        fill_rate_drift_pct=2.0,
        latency_ks_p=0.5,
        pnl_compression_ratio=0.85,
        anomalous_event_count=0,
    )


def _cpcv() -> CPCVEvidence:
    return CPCVEvidence(
        fold_count=8,
        embargo_bars=10,
        fold_sharpes=(1.1, 1.3, 0.9, 1.4, 1.2, 1.0, 1.5, 1.1),
        mean_sharpe=1.1875,
        median_sharpe=1.15,
        mean_pnl=4200.0,
        p_value=0.012,
        fold_pnl_curves_hash="sha256:abc",
    )


def _dsr() -> DSREvidence:
    return DSREvidence(
        observed_sharpe=1.6,
        trials_count=18,
        skewness=-0.1,
        kurtosis=3.2,
        dsr=1.25,
        dsr_p_value=0.018,
    )


def _capital_passing() -> CapitalStageEvidence:
    return CapitalStageEvidence(
        tier=CapitalStageTier.SMALL_CAPITAL,
        allocation_fraction=0.01,
        deployment_days=12,
        pnl_compression_ratio_realised=0.85,
        slippage_residual_bps=1.0,
        hit_rate_residual_pp=-2.0,
        fill_rate_drift_pct=3.0,
    )


def _capital_failing() -> CapitalStageEvidence:
    """Insufficient deployment days — must fail the gate today."""
    return CapitalStageEvidence(
        tier=CapitalStageTier.SMALL_CAPITAL,
        allocation_fraction=0.01,
        deployment_days=2,
        pnl_compression_ratio_realised=0.85,
        slippage_residual_bps=1.0,
        hit_rate_residual_pp=-2.0,
        fill_rate_drift_pct=3.0,
    )


def _make_entry(
    *,
    alpha_id: str,
    from_state: str,
    to_state: str,
    trigger: str,
    timestamp_ns: int,
    metadata: dict[str, object] | None = None,
    correlation_id: str = "",
) -> PromotionLedgerEntry:
    return PromotionLedgerEntry(
        alpha_id=alpha_id,
        from_state=from_state,
        to_state=to_state,
        trigger=trigger,
        timestamp_ns=timestamp_ns,
        correlation_id=correlation_id,
        metadata=dict(metadata) if metadata is not None else {},
    )


def _seed_live_history(
    ledger: PromotionLedger,
    alpha_id: str,
    *,
    base_ns: int = 1_700_000_000_000_000_000,
) -> None:
    ledger.append(
        _make_entry(
            alpha_id=alpha_id,
            from_state="RESEARCH",
            to_state="PAPER",
            trigger="promote_to_paper",
            timestamp_ns=base_ns,
            metadata=evidence_to_metadata(_research()),
        )
    )
    ledger.append(
        _make_entry(
            alpha_id=alpha_id,
            from_state="PAPER",
            to_state="LIVE",
            trigger="promote_to_live",
            timestamp_ns=base_ns + 1_000_000_000,
            metadata=evidence_to_metadata(_paper(), _cpcv(), _dsr()),
        )
    )


def _seed_scaled(
    ledger: PromotionLedger,
    alpha_id: str,
    *,
    base_ns: int = 1_700_000_000_000_000_000,
    correlation_id: str = "cap-1",
) -> None:
    """Seed RESEARCH → PAPER → LIVE → LIVE@SCALED for ``alpha_id``."""
    _seed_live_history(ledger, alpha_id, base_ns=base_ns)
    ledger.append(
        _make_entry(
            alpha_id=alpha_id,
            from_state="LIVE",
            to_state="LIVE",
            trigger=PROMOTE_CAPITAL_TIER_TRIGGER,
            timestamp_ns=base_ns + 2_000_000_000,
            metadata=evidence_to_metadata(_capital_passing()),
            correlation_id=correlation_id,
        )
    )


# ── inspect ───────────────────────────────────────────────────────


class TestInspectShowsCapitalTier:
    def test_inspect_text_header_shows_tier_when_scaled(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        _seed_scaled(ledger, "ALPHA-CAP")

        rc = main(
            ["promote", "inspect", "ALPHA-CAP", "--ledger", str(ledger_path)]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        assert "tier=SCALED" in captured.out
        # Special-cased arrow rendering.
        assert "LIVE @ SMALL_CAPITAL -> LIVE @ SCALED" in captured.out
        # Capital-tier entry must use the F-6 trigger.
        assert "'promote_capital_tier'" in captured.out

    def test_inspect_text_header_shows_small_capital_when_pre_escalation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        _seed_live_history(ledger, "ALPHA-LIVE")

        rc = main(
            ["promote", "inspect", "ALPHA-LIVE", "--ledger", str(ledger_path)]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        # First entry into LIVE without an escalation -> SMALL_CAPITAL
        assert "tier=SMALL_CAPITAL" in captured.out

    def test_inspect_json_exposes_current_capital_tier(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        _seed_scaled(ledger, "ALPHA-CAP")

        rc = main(
            [
                "promote",
                "inspect",
                "ALPHA-CAP",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        assert payload["current_capital_tier"] == "SCALED"
        # Self-loop entry preserved verbatim in transitions[].
        last = payload["transitions"][-1]
        assert last["from_state"] == "LIVE"
        assert last["to_state"] == "LIVE"
        assert last["trigger"] == PROMOTE_CAPITAL_TIER_TRIGGER

    def test_inspect_json_returns_none_for_paper_alpha(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        ledger.append(
            _make_entry(
                alpha_id="ALPHA-PAPER",
                from_state="RESEARCH",
                to_state="PAPER",
                trigger="promote_to_paper",
                timestamp_ns=1_700_000_000_000_000_000,
                metadata=evidence_to_metadata(_research()),
            )
        )

        rc = main(
            [
                "promote",
                "inspect",
                "ALPHA-PAPER",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        assert payload["current_capital_tier"] is None

    def test_inspect_after_quarantine_clears_tier(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        base = 1_700_000_000_000_000_000
        _seed_scaled(ledger, "ALPHA-Q", base_ns=base)
        # QUARANTINED after the SCALED escalation -> tier must drop to None.
        ledger.append(
            _make_entry(
                alpha_id="ALPHA-Q",
                from_state="LIVE",
                to_state="QUARANTINED",
                trigger="quarantine",
                timestamp_ns=base + 3_000_000_000,
                metadata={"reason": "ic decay"},
            )
        )

        rc = main(
            [
                "promote",
                "inspect",
                "ALPHA-Q",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        assert payload["current_capital_tier"] is None


# ── list ─────────────────────────────────────────────────────────


class TestListShowsCapitalTier:
    def test_list_text_renders_state_with_tier(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        _seed_scaled(ledger, "ALPHA-SCALED", base_ns=1_700_000_000_000_000_000)
        _seed_live_history(ledger, "ALPHA-SMALL", base_ns=1_700_000_010_000_000_000)
        ledger.append(
            _make_entry(
                alpha_id="ALPHA-PAPER",
                from_state="RESEARCH",
                to_state="PAPER",
                trigger="promote_to_paper",
                timestamp_ns=1_700_000_020_000_000_000,
                metadata=evidence_to_metadata(_research()),
            )
        )

        rc = main(["promote", "list", "--ledger", str(ledger_path)])
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        assert "LIVE @ SCALED" in captured.out
        assert "LIVE @ SMALL_CAPITAL" in captured.out
        # Non-LIVE alphas have no tier suffix.
        # Find the line containing ALPHA-PAPER and assert no '@' appears
        # on it (the column would otherwise contain a tier marker).
        paper_line = [
            ln for ln in captured.out.splitlines() if "ALPHA-PAPER" in ln
        ][0]
        assert "@" not in paper_line

    def test_list_json_exposes_current_capital_tier(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        _seed_scaled(ledger, "ALPHA-SCALED", base_ns=1_700_000_000_000_000_000)
        _seed_live_history(ledger, "ALPHA-SMALL", base_ns=1_700_000_010_000_000_000)

        rc = main(
            ["promote", "list", "--ledger", str(ledger_path), "--json"]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        by_id = {row["alpha_id"]: row for row in payload["alphas"]}

        assert by_id["ALPHA-SCALED"]["current_state"] == "LIVE"
        assert by_id["ALPHA-SCALED"]["current_capital_tier"] == "SCALED"
        assert by_id["ALPHA-SMALL"]["current_state"] == "LIVE"
        assert (
            by_id["ALPHA-SMALL"]["current_capital_tier"] == "SMALL_CAPITAL"
        )

    def test_list_json_quarantined_alpha_has_no_tier(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        base = 1_700_000_000_000_000_000
        _seed_scaled(ledger, "ALPHA-Q", base_ns=base)
        ledger.append(
            _make_entry(
                alpha_id="ALPHA-Q",
                from_state="LIVE",
                to_state="QUARANTINED",
                trigger="quarantine",
                timestamp_ns=base + 3_000_000_000,
                metadata={"reason": "ic decay"},
            )
        )

        rc = main(
            ["promote", "list", "--ledger", str(ledger_path), "--json"]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        by_id = {row["alpha_id"]: row for row in payload["alphas"]}
        assert by_id["ALPHA-Q"]["current_state"] == "QUARANTINED"
        assert by_id["ALPHA-Q"]["current_capital_tier"] is None


# ── replay-evidence ───────────────────────────────────────────────


class TestReplayEvidenceCapitalTier:
    def test_passing_capital_stage_replays_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        _seed_scaled(ledger, "ALPHA-CAP")

        rc = main(
            [
                "promote",
                "replay-evidence",
                "ALPHA-CAP",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        # Find the LIVE -> LIVE row.
        cap_rows = [
            r
            for r in payload["results"]
            if r["from_state"] == "LIVE" and r["to_state"] == "LIVE"
        ]
        assert len(cap_rows) == 1
        row = cap_rows[0]
        assert row["gate"] == "live_promote_capital_tier"
        assert row["skipped_reason"] is None
        assert row["errors"] == []
        assert "capital_stage" in row["evidence_kinds"]

    def test_failing_capital_stage_surfaces_validation_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        _seed_live_history(ledger, "ALPHA-BAD")
        # Append a LIVE -> LIVE entry whose evidence violates the gate
        # (deployment_days=2 < 10).  The replay must raise an error.
        ledger.append(
            _make_entry(
                alpha_id="ALPHA-BAD",
                from_state="LIVE",
                to_state="LIVE",
                trigger=PROMOTE_CAPITAL_TIER_TRIGGER,
                timestamp_ns=1_700_000_000_002_000_000,
                metadata=evidence_to_metadata(_capital_failing()),
            )
        )

        rc = main(
            [
                "promote",
                "replay-evidence",
                "ALPHA-BAD",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        # Validation failure surfaces as exit code 3.
        assert rc == EXIT_VALIDATION_FAILED
        payload = json.loads(captured.out)
        cap_rows = [
            r
            for r in payload["results"]
            if r["from_state"] == "LIVE" and r["to_state"] == "LIVE"
        ]
        assert len(cap_rows) == 1
        row = cap_rows[0]
        assert row["gate"] == "live_promote_capital_tier"
        assert row["skipped_reason"] is None
        assert any("deployment_days" in e for e in row["errors"])


# ── F-6 P2: trigger-aware ("LIVE", "LIVE") gate inference ─────────


class TestReplayEvidenceTriggerAwareLiveSelfLoop:
    """The Codex-bot P2 review issue on PR #23.

    Pre-fix, the CLI's ``_STATE_PAIR_TO_GATE`` mapping classified
    *every* ``("LIVE", "LIVE")`` ledger entry as
    :attr:`GateId.LIVE_PROMOTE_CAPITAL_TIER`, regardless of the
    entry's ``trigger`` field.  That meant any future (or
    accidental) ``LIVE -> LIVE`` self-loop carrying a different
    trigger would be silently mis-replayed against the
    capital-tier gate's evidence schema, masking real audit issues
    behind a misleading row.

    Post-fix, the CLI requires the trigger to match
    :data:`PROMOTE_CAPITAL_TIER_TRIGGER` to apply the
    capital-tier gate; any other ``LIVE -> LIVE`` trigger is
    reported as *skipped — no gate registered* (the safe default
    documented for unknown transitions).
    """

    def test_live_to_live_with_unknown_trigger_is_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        _seed_live_history(ledger, "ALPHA-MISC")
        # A hand-crafted (or future-feature) self-loop with a trigger
        # that is NOT the capital-tier sentinel.  The CLI must NOT
        # silently classify this as LIVE_PROMOTE_CAPITAL_TIER.
        ledger.append(
            _make_entry(
                alpha_id="ALPHA-MISC",
                from_state="LIVE",
                to_state="LIVE",
                trigger="some_other_live_loop_trigger",
                timestamp_ns=1_700_000_000_002_000_000,
                metadata={"schema_version": EVIDENCE_SCHEMA_VERSION},
            )
        )

        rc = main(
            [
                "promote",
                "replay-evidence",
                "ALPHA-MISC",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        # Skipped, not failed: the entry was not mis-classified, and
        # there is nothing to validate.  Exit code 0 (OK).
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        cap_rows = [
            r
            for r in payload["results"]
            if r["from_state"] == "LIVE" and r["to_state"] == "LIVE"
        ]
        assert len(cap_rows) == 1
        row = cap_rows[0]
        assert row["gate"] is None
        assert row["skipped_reason"] is not None
        assert "no gate registered" in row["skipped_reason"]
        assert row["errors"] == []

    def test_live_to_live_with_capital_tier_trigger_still_replays(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Sanity check: the trigger-aware lookup did not break the
        # happy path — a properly-triggered entry still classifies
        # as LIVE_PROMOTE_CAPITAL_TIER and replays normally.
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        _seed_scaled(ledger, "ALPHA-OK")

        rc = main(
            [
                "promote",
                "replay-evidence",
                "ALPHA-OK",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        cap_rows = [
            r
            for r in payload["results"]
            if r["from_state"] == "LIVE" and r["to_state"] == "LIVE"
        ]
        assert len(cap_rows) == 1
        row = cap_rows[0]
        assert row["gate"] == "live_promote_capital_tier"
        assert row["skipped_reason"] is None

    def test_text_output_skip_notice_for_unknown_trigger(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The text path renders "SKIPPED" + "skipped: ..." line.
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        _seed_live_history(ledger, "ALPHA-TXT")
        ledger.append(
            _make_entry(
                alpha_id="ALPHA-TXT",
                from_state="LIVE",
                to_state="LIVE",
                trigger="future_unknown_trigger",
                timestamp_ns=1_700_000_000_002_000_000,
                metadata={"schema_version": EVIDENCE_SCHEMA_VERSION},
            )
        )

        rc = main(
            [
                "promote",
                "replay-evidence",
                "ALPHA-TXT",
                "--ledger",
                str(ledger_path),
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        assert "SKIPPED" in captured.out
        assert "no gate registered" in captured.out
        assert "LIVE->LIVE" in captured.out
