"""End-to-end tests for the ``feelies promote`` CLI surface.

Covers each subcommand × text/JSON output × happy/sad paths, plus
the ``--ledger`` / ``--config`` resolution forks and the documented
exit-code convention from :mod:`feelies.cli.main`.

The CLI is read-only and forensic-only — these tests build small
ledger files in ``tmp_path`` and assert what the CLI prints; they do
not exercise the orchestrator or risk engine and therefore cannot
perturb replay determinism.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from feelies.alpha.promotion_evidence import (
    EVIDENCE_SCHEMA_VERSION,
    CapitalStageTier,
    CapitalStageEvidence,
    CPCVEvidence,
    DSREvidence,
    GateThresholds,
    PaperWindowEvidence,
    QuarantineTriggerEvidence,
    ResearchAcceptanceEvidence,
    evidence_to_metadata,
)
from feelies.alpha.promotion_ledger import (
    LEDGER_SCHEMA_VERSION,
    PromotionLedger,
    PromotionLedgerEntry,
)
from feelies.cli.main import (
    EXIT_DATA_ERROR,
    EXIT_OK,
    EXIT_USER_ERROR,
    EXIT_VALIDATION_FAILED,
    main,
)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _full_paper_window() -> PaperWindowEvidence:
    return PaperWindowEvidence(
        trading_days=5,
        sample_size=200,
        slippage_residual_bps=0.5,
        fill_rate_drift_pct=2.0,
        latency_ks_p=0.30,
        pnl_compression_ratio=0.8,
        anomalous_event_count=0,
    )


def _full_cpcv() -> CPCVEvidence:
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


def _full_dsr() -> DSREvidence:
    return DSREvidence(
        observed_sharpe=1.5,
        trials_count=12,
        skewness=-0.1,
        kurtosis=3.2,
        dsr=1.25,
        dsr_p_value=0.02,
    )


def _full_research() -> ResearchAcceptanceEvidence:
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


def _populate_ledger(path: Path) -> PromotionLedger:
    """Populate a ledger with three transitions for ALPHA-A and one for ALPHA-B."""
    ledger = PromotionLedger(path)

    # ALPHA-A: RESEARCH -> PAPER (full F-2 research evidence — passes)
    ledger.append(
        _make_entry(
            alpha_id="ALPHA-A",
            from_state="RESEARCH",
            to_state="PAPER",
            trigger="pass_paper_gate",
            timestamp_ns=1_700_000_000_000_000_000,
            correlation_id="corr-a1",
            metadata=evidence_to_metadata(_full_research()),
        )
    )
    # ALPHA-A: PAPER -> LIVE (full F-2 paper+cpcv+dsr evidence — passes)
    ledger.append(
        _make_entry(
            alpha_id="ALPHA-A",
            from_state="PAPER",
            to_state="LIVE",
            trigger="pass_live_gate",
            timestamp_ns=1_700_000_500_000_000_000,
            correlation_id="corr-a2",
            metadata=evidence_to_metadata(
                _full_paper_window(), _full_cpcv(), _full_dsr()
            ),
        )
    )
    # ALPHA-A: LIVE -> QUARANTINED (legacy F-1-era reason-only metadata)
    ledger.append(
        _make_entry(
            alpha_id="ALPHA-A",
            from_state="LIVE",
            to_state="QUARANTINED",
            trigger="edge_decay_detected",
            timestamp_ns=1_700_001_000_000_000_000,
            correlation_id="corr-a3",
            metadata={"reason": "drawdown breach"},
        )
    )

    # ALPHA-B: RESEARCH -> PAPER (legacy loose evidence shape — pre-F-2)
    ledger.append(
        _make_entry(
            alpha_id="ALPHA-B",
            from_state="RESEARCH",
            to_state="PAPER",
            trigger="pass_paper_gate",
            timestamp_ns=1_700_002_000_000_000_000,
            correlation_id="corr-b1",
            metadata={
                "evidence": {
                    "paper_days": 30,
                    "paper_sharpe": 1.5,
                    "paper_hit_rate": 0.55,
                }
            },
        )
    )
    return ledger


# ─────────────────────────────────────────────────────────────────────
# Top-level dispatcher
# ─────────────────────────────────────────────────────────────────────


class TestDispatcher:
    def test_no_args_prints_help_and_returns_user_error(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main([])
        assert excinfo.value.code == 2  # argparse missing-required

    def test_unknown_subcommand_argparse_error(self) -> None:
        with pytest.raises(SystemExit):
            main(["promote", "definitely-not-a-subcommand"])

    def test_promote_help_does_not_crash(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit):
            main(["promote", "--help"])
        captured = capsys.readouterr()
        assert "inspect" in captured.out
        assert "list" in captured.out
        assert "replay-evidence" in captured.out
        assert "validate" in captured.out
        assert "gate-matrix" in captured.out


# ─────────────────────────────────────────────────────────────────────
# gate-matrix
# ─────────────────────────────────────────────────────────────────────


class TestGateMatrixSubcommand:
    def test_text_mode_prints_every_gate(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main(["promote", "gate-matrix"])
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        assert "research_to_paper" in captured.out
        assert "paper_to_live" in captured.out
        assert "live_promote_capital_tier" in captured.out
        assert "live_to_quarantined" in captured.out
        assert "quarantined_to_paper" in captured.out
        assert "quarantined_to_decommissioned" in captured.out
        assert EVIDENCE_SCHEMA_VERSION in captured.out

    def test_json_mode_emits_stable_payload(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main(["promote", "gate-matrix", "--json"])
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        assert payload["schema_version"] == EVIDENCE_SCHEMA_VERSION
        gate_ids = {g["gate_id"] for g in payload["gates"]}
        assert gate_ids == {
            "research_to_paper",
            "paper_to_live",
            "live_promote_capital_tier",
            "live_to_quarantined",
            "quarantined_to_paper",
            "quarantined_to_decommissioned",
        }
        # paper_to_live carries the three F-2 evidence types.
        paper_to_live = next(
            g for g in payload["gates"] if g["gate_id"] == "paper_to_live"
        )
        assert set(paper_to_live["required_evidence"]) == {
            "PaperWindowEvidence",
            "CPCVEvidence",
            "DSREvidence",
        }


# ─────────────────────────────────────────────────────────────────────
# Ledger-arg resolution
# ─────────────────────────────────────────────────────────────────────


class TestLedgerResolution:
    def test_inspect_without_ledger_or_config_returns_user_error(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main(["promote", "inspect", "ALPHA-A"])
        captured = capsys.readouterr()
        assert rc == EXIT_USER_ERROR
        assert "must supply --ledger" in captured.err

    def test_inspect_with_nonexistent_ledger_returns_user_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main(
            [
                "promote",
                "inspect",
                "ALPHA-A",
                "--ledger",
                str(tmp_path / "missing.jsonl"),
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_USER_ERROR
        assert "does not exist" in captured.err

    def test_inspect_with_directory_path_returns_user_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main(
            ["promote", "inspect", "ALPHA-A", "--ledger", str(tmp_path)]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_USER_ERROR
        assert "not a regular file" in captured.err

    def test_inspect_with_ledger_and_config_argparse_rejects(
        self,
        tmp_path: Path,
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        config_path = tmp_path / "platform.yaml"
        ledger_path.touch()
        config_path.write_text("symbols: [AAPL]\n")
        with pytest.raises(SystemExit):
            main(
                [
                    "promote",
                    "inspect",
                    "ALPHA-A",
                    "--ledger",
                    str(ledger_path),
                    "--config",
                    str(config_path),
                ]
            )

    def test_config_resolution_uses_promotion_ledger_path(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        config_path = tmp_path / "platform.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "symbols": ["AAPL"],
                    "alpha_specs": ["alphas/_template/template_signal.alpha.yaml"],
                    "promotion_ledger_path": str(ledger_path),
                }
            )
        )
        rc = main(
            [
                "promote",
                "inspect",
                "ALPHA-A",
                "--config",
                str(config_path),
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        assert "ALPHA-A" in captured.out
        assert "RESEARCH ->" in captured.out

    def test_config_without_promotion_ledger_path_returns_user_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        config_path = tmp_path / "platform.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "symbols": ["AAPL"],
                    "alpha_specs": [
                        "alphas/_template/template_signal.alpha.yaml",
                    ],
                }
            )
        )
        rc = main(
            [
                "promote",
                "list",
                "--config",
                str(config_path),
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_USER_ERROR
        assert "promotion_ledger_path" in captured.err

    def test_config_with_corrupt_yaml_returns_data_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        config_path = tmp_path / "platform.yaml"
        config_path.write_text("not: [valid yaml: at all")
        rc = main(
            [
                "promote",
                "list",
                "--config",
                str(config_path),
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_DATA_ERROR
        assert "failed to load config" in captured.err


# ─────────────────────────────────────────────────────────────────────
# inspect
# ─────────────────────────────────────────────────────────────────────


class TestInspectSubcommand:
    def test_text_mode_renders_three_alpha_a_transitions(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        rc = main(
            [
                "promote",
                "inspect",
                "ALPHA-A",
                "--ledger",
                str(ledger_path),
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        assert "3 transitions" in captured.out
        assert "RESEARCH ->" in captured.out
        assert "PAPER " in captured.out
        assert "LIVE " in captured.out
        assert "QUARANTINED" in captured.out

    def test_json_mode_returns_three_transitions(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        rc = main(
            [
                "promote",
                "inspect",
                "ALPHA-A",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        assert payload["alpha_id"] == "ALPHA-A"
        assert payload["ledger_path"] == str(ledger_path)
        assert len(payload["transitions"]) == 3
        first = payload["transitions"][0]
        assert first["from_state"] == "RESEARCH"
        assert first["to_state"] == "PAPER"
        assert first["correlation_id"] == "corr-a1"
        assert "timestamp_iso" in first
        assert first["metadata"]["schema_version"] == EVIDENCE_SCHEMA_VERSION

    def test_unknown_alpha_id_text_mode_reports_no_entries(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        rc = main(
            [
                "promote",
                "inspect",
                "ALPHA-NOPE",
                "--ledger",
                str(ledger_path),
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        assert "no ledger entries found" in captured.out

    def test_unknown_alpha_id_json_mode_returns_empty_list(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        rc = main(
            [
                "promote",
                "inspect",
                "ALPHA-NOPE",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        assert payload["alpha_id"] == "ALPHA-NOPE"
        assert payload["transitions"] == []


# ─────────────────────────────────────────────────────────────────────
# list
# ─────────────────────────────────────────────────────────────────────


class TestListSubcommand:
    def test_text_mode_lists_both_alphas_with_current_state(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        rc = main(["promote", "list", "--ledger", str(ledger_path)])
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        assert "ALPHA-A" in captured.out
        assert "ALPHA-B" in captured.out
        # ALPHA-A's current state is QUARANTINED, ALPHA-B's is PAPER.
        assert "QUARANTINED" in captured.out
        assert "PAPER" in captured.out

    def test_json_mode_returns_summaries(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        rc = main(
            [
                "promote",
                "list",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        assert payload["schema_version"] == LEDGER_SCHEMA_VERSION
        by_id = {a["alpha_id"]: a for a in payload["alphas"]}
        assert set(by_id) == {"ALPHA-A", "ALPHA-B"}
        assert by_id["ALPHA-A"]["current_state"] == "QUARANTINED"
        assert by_id["ALPHA-A"]["transition_count"] == 3
        assert by_id["ALPHA-B"]["current_state"] == "PAPER"
        assert by_id["ALPHA-B"]["transition_count"] == 1
        assert payload["parse_errors"] == []

    def test_empty_ledger_returns_empty_list(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        ledger_path.touch()
        rc = main(
            [
                "promote",
                "list",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        assert payload["alphas"] == []

    def test_corrupt_ledger_surfaces_parse_error_and_exits_2(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        ledger_path.write_text("this is not json\n")
        rc = main(
            [
                "promote",
                "list",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_DATA_ERROR
        payload = json.loads(captured.out)
        assert len(payload["parse_errors"]) == 1
        assert "Corrupt promotion-ledger" in payload["parse_errors"][0]


# ─────────────────────────────────────────────────────────────────────
# validate
# ─────────────────────────────────────────────────────────────────────


class TestValidateSubcommand:
    def test_clean_ledger_returns_ok(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        rc = main(
            [
                "promote",
                "validate",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        assert payload["ok"] is True
        assert payload["entry_count"] == 4
        assert payload["parse_errors"] == []
        assert payload["schema_mismatches"] == []

    def test_corrupt_line_reported(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        # Append a corrupt line.
        with ledger_path.open("a", encoding="utf-8") as fh:
            fh.write("not-json\n")
        rc = main(
            [
                "promote",
                "validate",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_DATA_ERROR
        payload = json.loads(captured.out)
        assert payload["ok"] is False
        assert len(payload["parse_errors"]) == 1

    def test_schema_version_mismatch_reported(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        # Hand-craft an entry with a future schema_version so reading
        # parses but validation surfaces the mismatch.
        bad_line = json.dumps(
            {
                "schema_version": "9.9.9",
                "alpha_id": "X",
                "from_state": "RESEARCH",
                "to_state": "PAPER",
                "trigger": "pass_paper_gate",
                "timestamp_ns": 1,
                "correlation_id": "",
                "metadata": {},
            },
            sort_keys=True,
        )
        ledger_path.write_text(bad_line + "\n", encoding="utf-8")
        rc = main(
            [
                "promote",
                "validate",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_DATA_ERROR
        payload = json.loads(captured.out)
        assert payload["ok"] is False
        assert len(payload["schema_mismatches"]) == 1
        assert "9.9.9" in payload["schema_mismatches"][0]

    def test_text_mode_prints_OK(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        rc = main(
            [
                "promote",
                "validate",
                "--ledger",
                str(ledger_path),
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        assert captured.out.strip().endswith("OK")


# ─────────────────────────────────────────────────────────────────────
# replay-evidence
# ─────────────────────────────────────────────────────────────────────


class TestReplayEvidenceSubcommand:
    def test_alpha_a_passes_replay(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        rc = main(
            [
                "promote",
                "replay-evidence",
                "ALPHA-A",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        assert payload["ok"] is True
        assert payload["alpha_id"] == "ALPHA-A"
        assert len(payload["results"]) == 3
        # First two transitions carry F-2 evidence and pass the gate.
        assert payload["results"][0]["gate"] == "research_to_paper"
        assert payload["results"][0]["errors"] == []
        assert payload["results"][1]["gate"] == "paper_to_live"
        assert payload["results"][1]["errors"] == []
        # Third transition is a quarantine with reason-only metadata —
        # it gets skipped (no schema_version).
        third = payload["results"][2]
        assert third["gate"] == "live_to_quarantined"
        assert third["skipped_reason"] is not None
        assert "schema_version" in third["skipped_reason"]

    def test_alpha_b_legacy_metadata_gets_skipped(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        rc = main(
            [
                "promote",
                "replay-evidence",
                "ALPHA-B",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        assert payload["ok"] is True
        assert len(payload["results"]) == 1
        result = payload["results"][0]
        assert result["skipped_reason"] is not None
        assert "schema_version" in result["skipped_reason"]
        assert result["errors"] == []

    def test_replay_failure_returns_validation_failed_exit(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Hand-craft a ledger entry whose F-2 evidence would no longer
        # satisfy current GateThresholds (DSR below the floor).
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        bad_dsr = DSREvidence(
            observed_sharpe=0.5,
            trials_count=5,
            skewness=0.0,
            kurtosis=3.0,
            dsr=0.5,  # below the dsr_min=1.0 threshold
            dsr_p_value=0.5,  # also above the dsr_max_p_value=0.05
        )
        metadata = evidence_to_metadata(
            _full_paper_window(),
            _full_cpcv(),
            bad_dsr,
        )
        ledger.append(
            _make_entry(
                alpha_id="ALPHA-FAIL",
                from_state="PAPER",
                to_state="LIVE",
                trigger="pass_live_gate",
                timestamp_ns=42,
                metadata=metadata,
            )
        )
        rc = main(
            [
                "promote",
                "replay-evidence",
                "ALPHA-FAIL",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_VALIDATION_FAILED
        payload = json.loads(captured.out)
        assert payload["ok"] is False
        result = payload["results"][0]
        assert result["gate"] == "paper_to_live"
        assert any("DSR" in err for err in result["errors"])

    def test_replay_unknown_alpha_returns_ok_empty(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        rc = main(
            [
                "promote",
                "replay-evidence",
                "ALPHA-DOES-NOT-EXIST",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        payload = json.loads(captured.out)
        assert payload["ok"] is True
        assert payload["results"] == []

    def test_replay_text_mode_prints_status_per_transition(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        rc = main(
            [
                "promote",
                "replay-evidence",
                "ALPHA-A",
                "--ledger",
                str(ledger_path),
            ]
        )
        captured = capsys.readouterr()
        assert rc == EXIT_OK
        assert "[OK]" in captured.out
        assert "[SKIPPED]" in captured.out

    def test_capital_stage_evidence_round_trips_through_replay(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # SMALL → SCALED capital-tier escalation does not change the
        # lifecycle state today, so no LIVE→LIVE entries land on the
        # ledger.  But the F-3 reconstructor must round-trip the
        # CapitalStageTier enum cleanly when F-4 starts writing them.
        ledger_path = tmp_path / "ledger.jsonl"
        ledger = PromotionLedger(ledger_path)
        cap = CapitalStageEvidence(
            tier=CapitalStageTier.SMALL_CAPITAL,
            allocation_fraction=0.01,
            deployment_days=12,
            pnl_compression_ratio_realised=0.85,
            slippage_residual_bps=1.0,
            hit_rate_residual_pp=-2.0,
            fill_rate_drift_pct=3.0,
        )
        # We cheat and write a synthetic LIVE→LIVE entry to exercise
        # the reconstructor path; F-3 doesn't *infer* a gate for this
        # state pair (LIVE_PROMOTE_CAPITAL_TIER is non-state-changing),
        # so the entry surfaces as "no gate registered".
        ledger.append(
            _make_entry(
                alpha_id="ALPHA-CAP",
                from_state="LIVE",
                to_state="LIVE",
                trigger="capital_tier_promote",
                timestamp_ns=100,
                metadata=evidence_to_metadata(cap),
            )
        )
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
        assert len(payload["results"]) == 1
        result = payload["results"][0]
        # F-4 will introduce the LIVE→LIVE gate inference; for now the
        # replay marks the entry as "no gate registered".
        assert result["gate"] is None
        assert result["skipped_reason"] is not None
        assert "no gate registered" in result["skipped_reason"]


# ─────────────────────────────────────────────────────────────────────
# Determinism / forensic-only invariant
# ─────────────────────────────────────────────────────────────────────


class TestDeterminismInvariants:
    def test_two_invocations_emit_identical_json(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The CLI is forensic and read-only — re-running it on the
        same ledger MUST produce byte-identical JSON output."""
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)

        main(
            [
                "promote",
                "list",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        first = capsys.readouterr().out

        main(
            [
                "promote",
                "list",
                "--ledger",
                str(ledger_path),
                "--json",
            ]
        )
        second = capsys.readouterr().out

        assert first == second

    def test_cli_does_not_mutate_ledger_file(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ledger_path = tmp_path / "ledger.jsonl"
        _populate_ledger(ledger_path)
        before = ledger_path.read_bytes()

        for argv in (
            ["promote", "list", "--ledger", str(ledger_path), "--json"],
            ["promote", "inspect", "ALPHA-A", "--ledger", str(ledger_path)],
            [
                "promote",
                "replay-evidence",
                "ALPHA-A",
                "--ledger",
                str(ledger_path),
                "--json",
            ],
            ["promote", "validate", "--ledger", str(ledger_path)],
        ):
            main(argv)
            capsys.readouterr()

        after = ledger_path.read_bytes()
        assert before == after
