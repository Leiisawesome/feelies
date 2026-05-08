"""Category 10 — production readiness flags."""

from __future__ import annotations

from feelies.health.config import HealthConfig
from feelies.health.context import HealthCheckContext
from feelies.health.models import HealthCheckResult, HealthStatus


_DESIRED_KEYS = (
    "deterministic_config",
    "reproducible_run_id",
    "risk_limits",
    "max_position_size",
    "max_gross_exposure",
    "max_daily_loss",
    "spread_filter",
    "liquidity_filter",
    "kill_switch",
    "data_freshness_checks",
    "replay_parity_plan",
)


def run_production_checks(ctx: HealthCheckContext, _cfg: HealthConfig) -> list[HealthCheckResult]:
    meta = dict(ctx.metadata)
    present = [k for k in _DESIRED_KEYS if meta.get(k)]
    missing = [k for k in _DESIRED_KEYS if not meta.get(k)]

    results: list[HealthCheckResult] = []

    if len(present) >= len(_DESIRED_KEYS) // 2:
        status = HealthStatus.PASS
        severity = 0
    elif len(present) == 0:
        status = HealthStatus.WARN
        severity = 2
    else:
        status = HealthStatus.WARN
        severity = 1

    results.append(
        HealthCheckResult(
            category="production_readiness",
            check_name="production_metadata_keys",
            status=status,
            metrics={"present": present, "missing": missing},
            thresholds={"desired": list(_DESIRED_KEYS)},
            message="Checklist for paper/live readiness metadata.",
            suggested_action="Document risk limits, filters, kill-switch wiring, and replay parity.",
            severity=severity,
        )
    )

    artifact_flags = {
        "saved_config_snapshot": "config_snapshot" in meta or "config_snapshot_yaml" in ctx.extra,
        "orders_logged": bool(ctx.orders),
        "fills_logged": bool(ctx.fills),
        "signals_logged": bool(ctx.signals),
    }
    if not any(artifact_flags.values()):
        results.append(
            HealthCheckResult(
                category="production_readiness",
                check_name="artifact_logging",
                status=HealthStatus.WARN,
                metrics=artifact_flags,
                thresholds={},
                message="Limited artefact coverage — replay audits will be thin.",
                suggested_action="Persist signals/orders/fills for paper trading.",
                severity=2,
            )
        )
    else:
        results.append(
            HealthCheckResult(
                category="production_readiness",
                check_name="artifact_logging",
                status=HealthStatus.PASS,
                metrics=artifact_flags,
                thresholds={},
                message="Some operational artefacts present.",
                suggested_action="",
                severity=0,
            )
        )

    return results


__all__ = ["run_production_checks"]
