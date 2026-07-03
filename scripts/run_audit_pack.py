#!/usr/bin/env python3
"""Prepare, verify, and synthesize audit-prompt pack runs.

This script intentionally does not automate the Claude Code UI.  It creates one
self-contained bundle per audit prompt so each bundle can be pasted into a fresh
Claude Code session, then verifies and summarizes the reports those sessions produce.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PROMPTS_DIR = _REPO_ROOT / "docs" / "prompts"
_AUDITS_DIR = _REPO_ROOT / "docs" / "audits"
_RUNNER_VERSION = 1

_BACKTICK_RE = re.compile(r"`([^`]+)`")
_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_OWNER_SKILL_RE = re.compile(r"\.cursor/skills/([^/]+)/SKILL\.md")
_SEVERITY_RE = re.compile(r"(?<![A-Z0-9])P([012])(?![A-Z0-9])")
_P01_RE = re.compile(r"(?<![A-Z0-9])P([01])(?![A-Z0-9])")
_INV_RE = re.compile(r"\bInv-\d+\b")
_CITATION_RE = re.compile(
    r"(?:src/feelies|tests|scripts|configs|docs|alphas|\.cursor)/"
    r"[A-Za-z0-9_./\\-]+:\d+|"
    r"\b(?:AGENTS|CLAUDE)\.md:\d+|"
    r"\b(?:pyproject\.toml|platform\.yaml):\d+"
)
_TEST_GAP_RE = re.compile(r"(test|coverage)[^\n]{0,80}(gap|matrix)", re.IGNORECASE)
_PROHIBITED_RE = re.compile(
    r"TODO audit later|citation needed|uncited claim|TBD\b|FIXME\b", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class AuditPrompt:
    name: str
    area: str
    path: Path
    title: str
    resources: tuple[Path, ...]
    owner_skills: tuple[str, ...]

    def report_path(self, run_date: str) -> Path:
        return _AUDITS_DIR / f"{self.area}_audit_{run_date}.md"

    def bundle_path(self, run_dir: Path) -> Path:
        return run_dir / f"{self.name}.bundle.md"


@dataclass(frozen=True, slots=True)
class VerifyIssue:
    audit: str
    severity: str
    message: str
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class ParsedFinding:
    severity: str
    audit: str
    line_number: int
    text: str
    invs: tuple[str, ...]
    citations: tuple[str, ...]


def _repo_rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _extract_agent_context(text: str) -> str:
    marker = "## Agent context (mandatory)"
    start = text.find(marker)
    if start == -1:
        return ""
    rest = text[start:]
    next_rule = rest.find("\n---", len(marker))
    if next_rule == -1:
        return rest
    return rest[:next_rule]


def _resource_path(token: str) -> Path | None:
    candidate = token.strip().split()[0].rstrip(".,;:)")
    if candidate.endswith("/"):
        return None
    if candidate in {"AGENTS.md", "CLAUDE.md", "pyproject.toml", "platform.yaml"}:
        return _REPO_ROOT / candidate
    if candidate.startswith(".cursor/"):
        return _REPO_ROOT / candidate
    return None


def _unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(path)
    return tuple(out)


def _parse_prompt(path: Path) -> AuditPrompt:
    text = _read(path)
    heading = _HEADING_RE.search(text)
    title = heading.group(1).strip() if heading else path.stem
    agent_context = _extract_agent_context(text)
    resources: list[Path] = [_REPO_ROOT / "AGENTS.md", _REPO_ROOT / "CLAUDE.md"]
    for match in _BACKTICK_RE.finditer(agent_context):
        resource = _resource_path(match.group(1))
        if resource is not None:
            resources.append(resource)

    missing = [res for res in resources if not res.exists()]
    if missing:
        missing_list = ", ".join(_repo_rel(path) for path in missing)
        raise FileNotFoundError(f"{_repo_rel(path)} references missing context: {missing_list}")

    owner_skills: list[str] = []
    for line in agent_context.splitlines():
        if "owner" not in line.lower():
            continue
        skill_match = _OWNER_SKILL_RE.search(line)
        if skill_match is not None:
            owner_skills.append(skill_match.group(1))

    name = path.stem
    area = name.removeprefix("audit_")
    return AuditPrompt(
        name=name,
        area=area,
        path=path,
        title=title,
        resources=_unique_paths(resources),
        owner_skills=tuple(dict.fromkeys(owner_skills)),
    )


def load_audits(prompts_dir: Path | None = None) -> tuple[AuditPrompt, ...]:
    root = prompts_dir or _PROMPTS_DIR
    prompts = sorted(root.glob("audit_*.md"))
    return tuple(_parse_prompt(path) for path in prompts)


def _select_audits(audits: Sequence[AuditPrompt], names: Sequence[str]) -> tuple[AuditPrompt, ...]:
    if not names:
        return tuple(audits)
    normalized = {name.removeprefix("audit_") for name in names}
    selected = tuple(a for a in audits if a.area in normalized or a.name in names)
    found = {a.area for a in selected} | {a.name for a in selected}
    missing = sorted(
        name for name in names if name.removeprefix("audit_") not in found and name not in found
    )
    if missing:
        raise ValueError(f"unknown audit prompt(s): {', '.join(missing)}")
    return selected


def render_bundle(audit: AuditPrompt, run_date: str) -> str:
    report = _repo_rel(audit.report_path(run_date))
    lines = [
        f"# Claude Code audit bundle: {audit.name}",
        "",
        f"Generated by `scripts/run_audit_pack.py` version {_RUNNER_VERSION}.",
        f"Target report: `{report}`.",
        "",
        "## Claude Code execution contract",
        "",
        "1. Start a fresh Claude Code session at the repository root.",
        "2. Paste this whole bundle as the initial task message.",
        f"3. When the prompt says `YYYY-MM-DD`, use `{run_date}`.",
        f"4. Write exactly one report to `{report}`.",
        "5. Do not modify production code, baselines, configs, or ledgers.",
        "6. If a finding is P0/P1, cite at least one `Inv-N` and `path:line` evidence.",
        "7. Treat `.cursor/rules/` and `.cursor/skills/` files as repository audit context.",
        "",
    ]
    for resource in audit.resources:
        rel = _repo_rel(resource)
        lines.extend(
            [
                f"--- BEGIN CONTEXT: {rel} ---",
                _read(resource).rstrip(),
                f"--- END CONTEXT: {rel} ---",
                "",
            ]
        )

    rel_prompt = _repo_rel(audit.path)
    lines.extend(
        [
            f"--- BEGIN AUDIT PROMPT: {rel_prompt} ---",
            _read(audit.path).rstrip(),
            f"--- END AUDIT PROMPT: {rel_prompt} ---",
            "",
        ]
    )
    return "\n".join(lines)


def prepare_run(
    *,
    run_date: str,
    run_dir: Path,
    force: bool,
    audit_names: Sequence[str] = (),
) -> Path:
    audits = _select_audits(load_audits(), audit_names)
    if run_dir.exists() and any(run_dir.iterdir()) and not force:
        raise FileExistsError(
            f"{_repo_rel(run_dir)} already exists and is not empty; pass --force"
        )
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest_entries: list[dict[str, object]] = []
    for audit in audits:
        bundle_path = audit.bundle_path(run_dir)
        _write(bundle_path, render_bundle(audit, run_date))
        manifest_entries.append(
            {
                "name": audit.name,
                "area": audit.area,
                "title": audit.title,
                "prompt": _repo_rel(audit.path),
                "bundle": _repo_rel(bundle_path),
                "report": _repo_rel(audit.report_path(run_date)),
                "resources": [_repo_rel(path) for path in audit.resources],
                "owner_skills": list(audit.owner_skills),
            }
        )

    manifest = {
        "version": _RUNNER_VERSION,
        "date": run_date,
        "bundle_count": len(manifest_entries),
        "audits": manifest_entries,
    }
    _write(run_dir / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return run_dir


def _is_generic_severity_line(line: str) -> bool:
    lower = line.lower()
    return (
        "p0/p1" in lower
        or "p0 or p1" in lower
        or "severity definitions" in lower
        or "quality bar" in lower
    )


def _severity_lines(text: str, p01_only: bool = False) -> Iterable[tuple[int, str, str]]:
    pattern = _P01_RE if p01_only else _SEVERITY_RE
    for index, line in enumerate(text.splitlines(), start=1):
        if _is_generic_severity_line(line):
            continue
        match = pattern.search(line)
        if match is None:
            continue
        yield index, f"P{match.group(1)}", line.strip()


def _verify_report(audit: AuditPrompt, run_date: str, reports_dir: Path) -> list[VerifyIssue]:
    expected_name = audit.report_path(run_date).name
    report = reports_dir / expected_name
    issues: list[VerifyIssue] = []
    if not report.exists():
        return [
            VerifyIssue(
                audit=audit.name,
                severity="ERROR",
                message=f"missing report {report.as_posix()}",
                path=report,
            )
        ]

    text = _read(report)
    if _PROHIBITED_RE.search(text):
        issues.append(
            VerifyIssue(
                audit.name, "ERROR", "report contains TODO/TBD/citation-needed text", report
            )
        )
    if not _TEST_GAP_RE.search(text):
        issues.append(
            VerifyIssue(
                audit.name, "ERROR", "report is missing a test/coverage gap matrix", report
            )
        )
    if audit.owner_skills and not any(skill in text for skill in audit.owner_skills):
        owners = ", ".join(audit.owner_skills)
        issues.append(
            VerifyIssue(
                audit.name, "ERROR", f"report does not mention owner skill(s): {owners}", report
            )
        )

    for line_number, severity, line in _severity_lines(text, p01_only=True):
        if not _INV_RE.search(line):
            issues.append(
                VerifyIssue(
                    audit.name,
                    "ERROR",
                    f"{severity} line {line_number} lacks Inv-N citation",
                    report,
                )
            )
        if not _CITATION_RE.search(line):
            issues.append(
                VerifyIssue(
                    audit.name,
                    "ERROR",
                    f"{severity} line {line_number} lacks path:line evidence",
                    report,
                )
            )
    return issues


def _changed_paths() -> tuple[str, ...]:
    proc = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=_REPO_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff --name-only failed")
    return tuple(line.strip() for line in proc.stdout.splitlines() if line.strip())


def verify_reports(
    *,
    run_date: str,
    reports_dir: Path,
    audit_names: Sequence[str] = (),
    check_worktree: bool = False,
) -> list[VerifyIssue]:
    audits = _select_audits(load_audits(), audit_names)
    issues: list[VerifyIssue] = []
    for audit in audits:
        issues.extend(_verify_report(audit, run_date, reports_dir))

    if check_worktree:
        allowed_prefixes = ("docs/audits/", "docs\\audits\\")
        unexpected = [path for path in _changed_paths() if not path.startswith(allowed_prefixes)]
        if unexpected:
            issues.append(
                VerifyIssue(
                    audit="worktree",
                    severity="ERROR",
                    message="unexpected non-audit file changes: " + ", ".join(unexpected),
                    path=None,
                )
            )
    return issues


def _parse_findings(audit: AuditPrompt, report: Path) -> tuple[ParsedFinding, ...]:
    if not report.exists():
        return ()
    findings: list[ParsedFinding] = []
    for line_number, severity, line in _severity_lines(_read(report)):
        findings.append(
            ParsedFinding(
                severity=severity,
                audit=audit.area,
                line_number=line_number,
                text=line,
                invs=tuple(dict.fromkeys(_INV_RE.findall(line))),
                citations=tuple(dict.fromkeys(_CITATION_RE.findall(line))),
            )
        )
    return tuple(findings)


def _table_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _dedupe_findings(findings: Iterable[ParsedFinding]) -> tuple[ParsedFinding, ...]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[ParsedFinding] = []
    for finding in findings:
        key = (
            finding.severity,
            finding.invs[0] if finding.invs else "",
            finding.citations[0] if finding.citations else "",
            re.sub(r"\s+", " ", finding.text.lower())[:180],
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return tuple(out)


def synthesize_reports(
    *,
    run_date: str,
    reports_dir: Path,
    output: Path,
    audit_names: Sequence[str] = (),
) -> Path:
    audits = _select_audits(load_audits(), audit_names)
    coverage_rows: list[str] = []
    all_findings: list[ParsedFinding] = []
    for audit in audits:
        report = reports_dir / audit.report_path(run_date).name
        status = "present" if report.exists() else "missing"
        coverage_rows.append(f"| `{audit.area}` | {status} | `{report.as_posix()}` |")
        all_findings.extend(_parse_findings(audit, report))

    findings = sorted(
        _dedupe_findings(all_findings),
        key=lambda item: ({"P0": 0, "P1": 1, "P2": 2}.get(item.severity, 9), item.audit),
    )

    lines = [
        f"# Audit pack summary {run_date}",
        "",
        "Generated by `scripts/run_audit_pack.py synthesize`.",
        "",
        "## Coverage",
        "",
        "| Audit | Report | Path |",
        "|-------|--------|------|",
        *coverage_rows,
        "",
        "## Parsed findings",
        "",
    ]
    if not findings:
        lines.append("No explicit P0/P1/P2 finding lines were parsed.")
    else:
        lines.extend(
            [
                "| Severity | Audit | Inv | Evidence | Finding |",
                "|----------|-------|-----|----------|---------|",
            ]
        )
        for finding in findings:
            lines.append(
                "| "
                + " | ".join(
                    (
                        finding.severity,
                        f"`{finding.audit}`",
                        _table_escape(", ".join(finding.invs) or "-"),
                        _table_escape(", ".join(finding.citations) or "-"),
                        _table_escape(finding.text),
                    )
                )
                + " |"
            )
    _write(output, "\n".join(lines) + "\n")
    return output


def _default_run_dir(run_date: str) -> Path:
    return _AUDITS_DIR / "_runs" / run_date


def _default_summary_path(run_date: str) -> Path:
    return _AUDITS_DIR / f"audit_pack_summary_{run_date}.md"


def _print_issues(issues: Sequence[VerifyIssue]) -> None:
    if not issues:
        print("verify: OK")
        return
    for issue in issues:
        path = f" ({issue.path.as_posix()})" if issue.path is not None else ""
        print(f"{issue.severity}: {issue.audit}: {issue.message}{path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="write one Claude Code-ready bundle per audit prompt")
    prepare.add_argument("--date", default=_today())
    prepare.add_argument("--run-dir", type=Path)
    prepare.add_argument("--force", action="store_true")
    prepare.add_argument("--audit", action="append", default=[], help="audit area or audit_<area>")

    verify = sub.add_parser("verify", help="verify completed audit reports")
    verify.add_argument("--date", default=_today())
    verify.add_argument("--reports-dir", type=Path, default=_AUDITS_DIR)
    verify.add_argument("--audit", action="append", default=[])
    verify.add_argument("--check-worktree", action="store_true")

    synth = sub.add_parser("synthesize", help="write a consolidated summary report")
    synth.add_argument("--date", default=_today())
    synth.add_argument("--reports-dir", type=Path, default=_AUDITS_DIR)
    synth.add_argument("--output", type=Path)
    synth.add_argument("--audit", action="append", default=[])

    all_cmd = sub.add_parser("all", help="prepare bundles, then verify and synthesize reports")
    all_cmd.add_argument("--date", default=_today())
    all_cmd.add_argument("--run-dir", type=Path)
    all_cmd.add_argument("--reports-dir", type=Path, default=_AUDITS_DIR)
    all_cmd.add_argument("--output", type=Path)
    all_cmd.add_argument("--audit", action="append", default=[])
    all_cmd.add_argument("--force", action="store_true")
    all_cmd.add_argument("--check-worktree", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "prepare":
            run_dir = args.run_dir or _default_run_dir(args.date)
            path = prepare_run(
                run_date=args.date,
                run_dir=run_dir,
                force=args.force,
                audit_names=args.audit,
            )
            print(f"prepared audit bundles in {_repo_rel(path)}")
            return 0

        if args.command == "verify":
            issues = verify_reports(
                run_date=args.date,
                reports_dir=args.reports_dir,
                audit_names=args.audit,
                check_worktree=args.check_worktree,
            )
            _print_issues(issues)
            return 1 if any(issue.severity == "ERROR" for issue in issues) else 0

        if args.command == "synthesize":
            output = args.output or _default_summary_path(args.date)
            path = synthesize_reports(
                run_date=args.date,
                reports_dir=args.reports_dir,
                output=output,
                audit_names=args.audit,
            )
            print(f"wrote summary to {_repo_rel(path)}")
            return 0

        if args.command == "all":
            run_dir = args.run_dir or _default_run_dir(args.date)
            prepare_run(
                run_date=args.date,
                run_dir=run_dir,
                force=args.force,
                audit_names=args.audit,
            )
            issues = verify_reports(
                run_date=args.date,
                reports_dir=args.reports_dir,
                audit_names=args.audit,
                check_worktree=args.check_worktree,
            )
            _print_issues(issues)
            if any(issue.severity == "ERROR" for issue in issues):
                return 1
            output = args.output or _default_summary_path(args.date)
            synthesize_reports(
                run_date=args.date,
                reports_dir=args.reports_dir,
                output=output,
                audit_names=args.audit,
            )
            print(f"prepared bundles in {_repo_rel(run_dir)}")
            print(f"wrote summary to {_repo_rel(output)}")
            return 0
    except (FileExistsError, FileNotFoundError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"error: {exc}\n")

    parser.error(f"unhandled command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
