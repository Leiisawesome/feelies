"""Unit tests for scripts/run_audit_pack.py helper workflow."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "run_audit_pack.py"


def _load_mod() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_audit_pack", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_audit_pack"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fake_repo(tmp_path: Path, monkeypatch) -> ModuleType:
    mod = _load_mod()
    monkeypatch.setattr(mod, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_PROMPTS_DIR", tmp_path / "docs" / "prompts")
    monkeypatch.setattr(mod, "_AUDITS_DIR", tmp_path / "docs" / "audits")

    _write(tmp_path / "AGENTS.md", "# AGENTS\n\nUse `uv run`.\n")
    _write(
        tmp_path / ".cursor/rules/platform-invariants.mdc", "# Platform Invariants\n\nInv-11.\n"
    )
    _write(tmp_path / ".cursor/rules/karpathy-guidelines.mdc", "# Guidelines\n\nRead-only.\n")
    _write(tmp_path / ".cursor/skills/README.md", "# Skill index\n")
    _write(tmp_path / ".cursor/skills/risk-engine/SKILL.md", "# Risk engine\n")
    _write(
        tmp_path / "docs/prompts/audit_risk_engine.md",
        """# Risk engine audit

## Mission

Do a read-only audit.

## Agent context (mandatory)

| Step | Resource |
|------|----------|
| 1 | `.cursor/rules/platform-invariants.mdc` -- **Inv-11** |
| 2 | `.cursor/rules/karpathy-guidelines.mdc` |
| 3 | `.cursor/skills/README.md` |
| 4 | `.cursor/skills/risk-engine/SKILL.md` (**owner**) |

Before running commands, `.cursor/rules/` and `.cursor/skills/` take precedence.

---

## Output format

Write the audit report to `docs/audits/risk_engine_audit_YYYY-MM-DD.md`.
""",
    )
    return mod


def test_prepare_run_writes_manifest_and_cursor_bundle(tmp_path: Path, monkeypatch) -> None:
    mod = _fake_repo(tmp_path, monkeypatch)
    run_dir = tmp_path / "docs" / "audits" / "_runs" / "2026-07-01"

    result = mod.prepare_run(run_date="2026-07-01", run_dir=run_dir, force=False)

    assert result == run_dir
    manifest = (run_dir / "manifest.json").read_text(encoding="utf-8")
    assert '"bundle_count": 1' in manifest
    bundle = (run_dir / "audit_risk_engine.bundle.md").read_text(encoding="utf-8")
    assert "Target report: `docs/audits/risk_engine_audit_2026-07-01.md`" in bundle
    assert "--- BEGIN CONTEXT: AGENTS.md ---" in bundle
    assert "--- BEGIN CONTEXT: .cursor/skills/risk-engine/SKILL.md ---" in bundle
    assert "--- BEGIN AUDIT PROMPT: docs/prompts/audit_risk_engine.md ---" in bundle


def test_verify_reports_checks_owner_skill_inv_and_evidence(tmp_path: Path, monkeypatch) -> None:
    mod = _fake_repo(tmp_path, monkeypatch)
    reports_dir = tmp_path / "docs" / "audits"
    _write(
        reports_dir / "risk_engine_audit_2026-07-01.md",
        """# Risk report

Owner skill: risk-engine

## Findings

| Severity | Finding | Evidence |
|----------|---------|----------|
| P1 | Inv-11 fail-safe gap | src/feelies/risk/basic.py:12 |

## Test gap matrix

| Item | Status |
|------|--------|
| Fail-safe | covered |
""",
    )

    issues = mod.verify_reports(run_date="2026-07-01", reports_dir=reports_dir)

    assert issues == []


def test_verify_reports_rejects_uncited_p1(tmp_path: Path, monkeypatch) -> None:
    mod = _fake_repo(tmp_path, monkeypatch)
    reports_dir = tmp_path / "docs" / "audits"
    _write(
        reports_dir / "risk_engine_audit_2026-07-01.md",
        """# Risk report

Owner skill: risk-engine

## Findings

- P1: Fail-safe gap exists.

## Test gap matrix

| Item | Status |
|------|--------|
| Fail-safe | partial |
""",
    )

    issues = mod.verify_reports(run_date="2026-07-01", reports_dir=reports_dir)

    messages = [issue.message for issue in issues]
    assert any("lacks Inv-N citation" in message for message in messages)
    assert any("lacks path:line evidence" in message for message in messages)


def test_synthesize_reports_extracts_findings(tmp_path: Path, monkeypatch) -> None:
    mod = _fake_repo(tmp_path, monkeypatch)
    reports_dir = tmp_path / "docs" / "audits"
    _write(
        reports_dir / "risk_engine_audit_2026-07-01.md",
        """# Risk report

Owner skill: risk-engine

## Findings

| P0 | Inv-11 safety exit can be vetoed | src/feelies/risk/basic.py:12 |
| P2 | Add richer sizing docs | docs/prompts/audit_risk_engine.md:1 |

## Test gap matrix

| Item | Status |
|------|--------|
| Fail-safe | missing |
""",
    )
    output = reports_dir / "audit_pack_summary_2026-07-01.md"

    result = mod.synthesize_reports(
        run_date="2026-07-01",
        reports_dir=reports_dir,
        output=output,
    )

    assert result == output
    text = output.read_text(encoding="utf-8")
    assert "# Audit pack summary 2026-07-01" in text
    assert "| P0 | `risk_engine` | Inv-11 | src/feelies/risk/basic.py:12 |" in text
    assert "Add richer sizing docs" in text
