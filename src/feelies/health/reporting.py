"""Serialise :class:`AlphaHealthReport` to disk."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from feelies.health.models import AlphaHealthReport, health_report_to_json_dict


def write_health_reports(
    report: AlphaHealthReport,
    out_dir: Path,
    *,
    write_json: bool = True,
    write_markdown: bool = True,
    write_csv: bool = True,
) -> dict[str, Path]:
    """Emit JSON/Markdown/CSV artefacts beneath ``out_dir``."""

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    serialisable = health_report_to_json_dict(report)

    if write_json:
        p = out_dir / "alpha_health_report.json"
        p.write_text(json.dumps(serialisable, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        paths["json"] = p

    if write_markdown:
        p = out_dir / "alpha_health_report.md"
        p.write_text(_render_markdown(report, serialisable), encoding="utf-8")
        paths["markdown"] = p

    if write_csv:
        p = out_dir / "alpha_health_checks.csv"
        with p.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(
                fh,
                fieldnames=[
                    "category",
                    "check_name",
                    "status",
                    "message",
                    "suggested_action",
                    "severity",
                ],
            )
            w.writeheader()
            for r in report.results:
                w.writerow(
                    {
                        "category": r.category,
                        "check_name": r.check_name,
                        "status": r.status.value,
                        "message": r.message,
                        "suggested_action": r.suggested_action,
                        "severity": r.severity,
                    }
                )
        paths["csv"] = p

    return paths


def _render_markdown(report: AlphaHealthReport, serialisable: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append(f"# Alpha health — {report.alpha_name}")
    lines.append("")
    lines.append(f"- **Run ID:** {report.run_id}")
    lines.append(f"- **Created (UTC):** {report.created_at.isoformat()}")
    lines.append(f"- **Git commit:** {report.repo_commit or 'unknown'}")
    lines.append(f"- **Overall status:** {report.overall_status.value}")
    lines.append(f"- **Decision:** {report.decision.value}")
    lines.append(f"- **Score:** {report.score:.4f}")
    lines.append("")

    lines.append("## Category summary")
    lines.append("")
    lines.append("| Category | Status |")
    lines.append("|---|---|")
    cat_map = report.summary.get("category_status", {})
    if isinstance(cat_map, dict):
        for k in sorted(cat_map.keys()):
            lines.append(f"| {k} | {cat_map[k]} |")
    lines.append("")

    lines.append("## Failed checks")
    lines.append("")
    fails = [r for r in report.results if r.status.value == "FAIL"]
    if not fails:
        lines.append("_None_")
    else:
        for r in fails:
            lines.append(f"- **{r.check_name}** ({r.category}): {r.message}")
    lines.append("")

    lines.append("## Warnings")
    lines.append("")
    warns = [r for r in report.results if r.status.value == "WARN"]
    if not warns:
        lines.append("_None_")
    else:
        for r in warns:
            lines.append(f"- **{r.check_name}** ({r.category}): {r.message}")
    lines.append("")

    lines.append("## Key metrics")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(serialisable.get("summary", {}), indent=2, sort_keys=True))
    lines.append("```")
    lines.append("")

    lines.append("## Recommended next action")
    lines.append("")
    lines.append(f"Decision `{report.decision.value}` at score {report.score:.4f}.")
    lines.append("")
    lines.append("## Mandatory notes")
    lines.append("")
    if report.decision.value == "KILL":
        lines.append("- **Freeze promotion** until causal and execution evidence are repaired.")
    elif report.decision.value == "RESEARCH_MORE":
        lines.append("- **Continue research** — evidence incomplete or marginal.")
    elif report.decision.value in {"PAPER_TRADE", "DEPLOY_SMALL"}:
        lines.append("- **Paper / small capital** only until live-quality telemetry confirms costs.")
    elif report.decision.value == "SCALE_CANDIDATE":
        lines.append("- **Scaling** requires sustained live/paper parity and capacity checks.")
    lines.append("")
    return "\n".join(lines)


__all__ = ["write_health_reports"]
