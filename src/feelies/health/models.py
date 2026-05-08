"""Typed health-report schema for alpha validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class HealthStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AlphaDecision(str, Enum):
    KILL = "KILL"
    RESEARCH_MORE = "RESEARCH_MORE"
    PAPER_TRADE = "PAPER_TRADE"
    DEPLOY_SMALL = "DEPLOY_SMALL"
    SCALE_CANDIDATE = "SCALE_CANDIDATE"


@dataclass(frozen=True, kw_only=True)
class HealthCheckResult:
    """Single auditable check outcome."""

    category: str
    check_name: str
    status: HealthStatus
    metrics: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    suggested_action: str = ""
    severity: int = 0


@dataclass(frozen=True, kw_only=True)
class AlphaHealthReport:
    """Aggregate report emitted by :func:`feelies.health.runner.run_alpha_health_check`."""

    alpha_name: str
    run_id: str
    created_at: datetime
    repo_commit: str | None
    overall_status: HealthStatus
    decision: AlphaDecision
    score: float
    results: tuple[HealthCheckResult, ...]
    summary: dict[str, Any]
    artifacts: dict[str, Any]


def health_report_to_json_dict(report: AlphaHealthReport) -> dict[str, Any]:
    """Stable JSON shape for ``alpha_health_report.json``."""

    def _dt(o: datetime) -> str:
        if o.tzinfo is None:
            return o.replace(tzinfo=timezone.utc).isoformat()
        return o.isoformat()

    return {
        "alpha_name": report.alpha_name,
        "run_id": report.run_id,
        "created_at": _dt(report.created_at),
        "repo_commit": report.repo_commit,
        "overall_status": report.overall_status.value,
        "decision": report.decision.value,
        "score": report.score,
        "summary": report.summary,
        "artifacts": report.artifacts,
        "results": [
            {
                "category": r.category,
                "check_name": r.check_name,
                "status": r.status.value,
                "metrics": r.metrics,
                "thresholds": r.thresholds,
                "message": r.message,
                "suggested_action": r.suggested_action,
                "severity": r.severity,
            }
            for r in report.results
        ],
    }


__all__ = [
    "AlphaDecision",
    "AlphaHealthReport",
    "HealthCheckResult",
    "HealthStatus",
    "health_report_to_json_dict",
]
