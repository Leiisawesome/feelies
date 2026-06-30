"""Structural guards for ``docs/prompts/audit_*.md`` prompt pack.

Complements ``test_prompt_coverage_map.py`` (module ownership) with checks that
every audit prompt includes the Agent context block and the Not shipped
cross-check in Working method — see ``docs/prompts/README.md`` § Conventions.
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path("docs/prompts")
_AGENT_CONTEXT_HEADING = "## Agent context (mandatory)"
_NOT_SHIPPED_BULLET = (
    "Cross-check findings against the owning skill's **Not shipped** sections"
)


def _audit_prompt_paths() -> list[Path]:
    return sorted(_PROMPTS_DIR.glob("audit_*.md"))


def test_every_audit_prompt_has_agent_context_mandatory() -> None:
    missing = [
        p.name
        for p in _audit_prompt_paths()
        if _AGENT_CONTEXT_HEADING not in p.read_text(encoding="utf-8")
    ]
    assert not missing, (
        "audit prompts missing Agent context block — add "
        f"'{_AGENT_CONTEXT_HEADING}' per docs/prompts/_audit_agent_context.md: "
        f"{missing}"
    )


def test_every_audit_prompt_references_platform_invariants_in_agent_context() -> None:
    missing = [
        p.name
        for p in _audit_prompt_paths()
        if ".cursor/rules/platform-invariants.mdc" not in p.read_text(encoding="utf-8")
    ]
    assert not missing, (
        "audit prompts must cite platform-invariants in Agent context: " f"{missing}"
    )


def test_every_audit_prompt_references_karpathy_guidelines() -> None:
    missing = [
        p.name
        for p in _audit_prompt_paths()
        if ".cursor/rules/karpathy-guidelines.mdc" not in p.read_text(encoding="utf-8")
    ]
    assert not missing, (
        "audit prompts must cite karpathy-guidelines in Agent context: " f"{missing}"
    )


def test_every_audit_prompt_working_method_cross_checks_not_shipped() -> None:
    missing = [
        p.name
        for p in _audit_prompt_paths()
        if _NOT_SHIPPED_BULLET not in p.read_text(encoding="utf-8")
    ]
    assert not missing, (
        "audit prompts must include Not shipped cross-check in Working method: "
        f"{missing}"
    )


def test_audit_agent_context_maintenance_table_exists() -> None:
    path = _PROMPTS_DIR / "_audit_agent_context.md"
    assert path.is_file(), (
        "docs/prompts/_audit_agent_context.md must exist — per-audit read-order table"
    )
    text = path.read_text(encoding="utf-8")
    assert "| Prompt | Owner skill |" in text, "maintenance table header missing"
