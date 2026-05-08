"""Composable health checks."""

from __future__ import annotations

from feelies.health.checks.capacity_checks import run_capacity_checks
from feelies.health.checks.causality_checks import run_causality_checks
from feelies.health.checks.definition_checks import run_definition_checks
from feelies.health.checks.execution_checks import run_execution_checks
from feelies.health.checks.portfolio_checks import run_portfolio_checks
from feelies.health.checks.predictive_checks import run_predictive_checks
from feelies.health.checks.production_checks import run_production_checks
from feelies.health.checks.regime_checks import run_regime_checks
from feelies.health.checks.risk_checks import run_risk_checks
from feelies.health.checks.robustness_checks import run_robustness_checks
from feelies.health.config import HealthConfig
from feelies.health.context import HealthCheckContext
from feelies.health.models import HealthCheckResult


def run_all_health_checks(ctx: HealthCheckContext, cfg: HealthConfig) -> list[HealthCheckResult]:
    """Execute every category in deterministic order."""

    results: list[HealthCheckResult] = []
    results.extend(run_definition_checks(ctx, cfg))
    results.extend(run_causality_checks(ctx, cfg))
    results.extend(run_predictive_checks(ctx, cfg))
    results.extend(run_execution_checks(ctx, cfg))
    results.extend(run_regime_checks(ctx, cfg))
    results.extend(run_robustness_checks(ctx, cfg))
    results.extend(run_risk_checks(ctx, cfg))
    results.extend(run_capacity_checks(ctx, cfg))
    results.extend(run_portfolio_checks(ctx, cfg))
    results.extend(run_production_checks(ctx, cfg))
    return results


__all__ = ["run_all_health_checks"]
