"""``feelies promote`` surfaces for the Stage-0 decouple gate (Phase 6).

  * ``gate-matrix`` lists ``decouple_caps_only`` with its three evidence types
    (text + JSON).
  * ``replay-evidence`` infers :attr:`GateId.DECOUPLE_CAPS_ONLY` for a
    ``("LIVE", "LIVE")`` transition triggered by
    :data:`AUTHORIZE_DECOUPLE_TRIGGER` and re-validates the round-tripped
    evidence against current thresholds — OK for a clean authorization, FAIL for
    a historical entry that no longer clears the gate (e.g. an under-powered
    tail).

The CLI is read-only and forensic-only; these tests build small ledger files in
``tmp_path`` and assert on stdout / exit codes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from feelies.promotion.evidence import (
    AUTHORIZE_DECOUPLE_TRIGGER,
    ConditionalCVaREvidence,
    QuoteFreezeBackstopEvidence,
    TurnoverBoundEvidence,
    evidence_to_metadata,
)
from feelies.promotion.ledger import PromotionLedger, PromotionLedgerEntry
from feelies.cli.main import (
    EXIT_OK,
    EXIT_VALIDATION_FAILED,
    main as cli_main,
)


def _cvar(**overrides: object) -> ConditionalCVaREvidence:
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


def _turnover() -> TurnoverBoundEvidence:
    return TurnoverBoundEvidence(
        baseline_round_trips=100,
        deferral_round_trips=110,
        declared_max_ratio=1.2,
        observed_ratio=1.1,
        subpopulation_size=400,
    )


def _quote_freeze() -> QuoteFreezeBackstopEvidence:
    return QuoteFreezeBackstopEvidence(
        quote_freeze_episodes=5,
        exited_by_session_flatten=5,
        breached_session_backstop=0,
        session_flatten_bound_seconds=3600.0,
        max_hold_seconds_observed=1800.0,
    )


def _write_decouple_entry(
    ledger_path: Path,
    cvar: ConditionalCVaREvidence,
) -> None:
    ledger = PromotionLedger(ledger_path)
    metadata = evidence_to_metadata(cvar, _turnover(), _quote_freeze())
    metadata["config_version"] = "kyle@1.2:decouple_caps_only"
    metadata["authorized_by"] = "pm-alice"
    ledger.append(
        PromotionLedgerEntry(
            alpha_id="kyle",
            from_state="LIVE",
            to_state="LIVE",
            trigger=AUTHORIZE_DECOUPLE_TRIGGER,
            timestamp_ns=1_700_000_000_000_000_000,
            metadata=metadata,
        )
    )


class TestGateMatrixListsDecouple:
    def test_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cli_main(["promote", "gate-matrix"])
        out = capsys.readouterr().out
        assert rc == EXIT_OK
        assert "decouple_caps_only" in out
        assert "ConditionalCVaREvidence" in out
        assert "TurnoverBoundEvidence" in out
        assert "QuoteFreezeBackstopEvidence" in out

    def test_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cli_main(["promote", "gate-matrix", "--json"])
        out = capsys.readouterr().out
        assert rc == EXIT_OK
        payload = json.loads(out)
        row = next(g for g in payload["gates"] if g["gate_id"] == "decouple_caps_only")
        assert row["required_evidence"] == [
            "ConditionalCVaREvidence",
            "TurnoverBoundEvidence",
            "QuoteFreezeBackstopEvidence",
        ]


class TestReplayEvidenceDecouple:
    def test_clean_authorization_replays_ok(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_path = tmp_path / "l.jsonl"
        _write_decouple_entry(ledger_path, _cvar())
        rc = cli_main(["promote", "replay-evidence", "kyle", "--ledger", str(ledger_path)])
        out = capsys.readouterr().out
        assert rc == EXIT_OK, out
        assert "decouple_caps_only" in out
        assert "[OK]" in out
        assert "SKIPPED" not in out
        assert "FAIL" not in out

    def test_under_powered_authorization_replays_fail(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A historical decouple entry whose tail no longer clears the power
        # floor must surface as a FAIL (exit 3), not be silently accepted.
        ledger_path = tmp_path / "l.jsonl"
        _write_decouple_entry(ledger_path, _cvar(effective_tail_sample=5, subpopulation_size=100))
        rc = cli_main(["promote", "replay-evidence", "kyle", "--ledger", str(ledger_path)])
        out = capsys.readouterr().out
        assert rc == EXIT_VALIDATION_FAILED, out
        assert "under-powered" in out

    def test_json_payload_reports_gate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger_path = tmp_path / "l.jsonl"
        _write_decouple_entry(ledger_path, _cvar())
        rc = cli_main(
            ["promote", "replay-evidence", "kyle", "--ledger", str(ledger_path), "--json"]
        )
        out = capsys.readouterr().out
        assert rc == EXIT_OK
        payload = json.loads(out)
        (result,) = payload["results"]
        assert result["gate"] == "decouple_caps_only"
        assert result["ok"] is True
        assert result["errors"] == []
