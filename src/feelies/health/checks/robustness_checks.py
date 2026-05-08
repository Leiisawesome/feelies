"""Category 6 — robustness and overfit proxies."""

from __future__ import annotations

from feelies.health.config import HealthConfig
from feelies.health.context import HealthCheckContext
from feelies.health.models import HealthCheckResult, HealthStatus


def run_robustness_checks(ctx: HealthCheckContext, cfg: HealthConfig) -> list[HealthCheckResult]:
    results: list[HealthCheckResult] = []
    rs = dict(ctx.robustness_summary)
    if not rs:
        results.append(
            HealthCheckResult(
                category="robustness_overfit",
                check_name="robustness_artifacts_present",
                status=HealthStatus.WARN,
                metrics={},
                thresholds={},
                message="Robustness not demonstrated — no robustness_summary.json loaded.",
                suggested_action="Run parameter perturbation sweeps and store summary stats.",
                severity=2,
            )
        )
        return results

    best = float(rs.get("best_sharpe", 0.0) or 0.0)
    median = float(rs.get("median_sharpe", 0.0) or 0.0)
    oos = rs.get("oos_sharpe")
    is_sharpe = rs.get("is_sharpe")
    neighbor_frac = float(rs.get("profitable_neighbor_fraction", 0.0) or 0.0)
    ratio = None
    if median == median and abs(median) > 1e-12:
        ratio = best / median

    status = HealthStatus.PASS
    if neighbor_frac and neighbor_frac < cfg.min_profitable_neighbor_fraction:
        status = HealthStatus.WARN
    if ratio is not None and ratio > cfg.max_best_to_median_sharpe_ratio:
        status = HealthStatus.FAIL
    if oos is not None and is_sharpe is not None:
        try:
            oos_f = float(oos)
            is_f = float(is_sharpe)
            if is_f > 0 and (is_f - oos_f) / is_f > cfg.max_oos_sharpe_degradation:
                status = HealthStatus.FAIL
        except (TypeError, ValueError):
            status = HealthStatus.WARN

    results.append(
        HealthCheckResult(
            category="robustness_overfit",
            check_name="robustness_stress_summary",
            status=status,
            metrics={
                "best_sharpe": best,
                "median_sharpe": median,
                "best_to_median": ratio,
                "profitable_neighbor_fraction": neighbor_frac,
                "is_sharpe": is_sharpe,
                "oos_sharpe": oos,
            },
            thresholds={
                "min_profitable_neighbor_fraction": cfg.min_profitable_neighbor_fraction,
                "max_best_to_median_sharpe_ratio": cfg.max_best_to_median_sharpe_ratio,
                "max_oos_sharpe_degradation": cfg.max_oos_sharpe_degradation,
            },
            message="Robustness summary evaluation.",
            suggested_action="Avoid single peak parameter islands; require OOS stability.",
            severity=3 if status == HealthStatus.FAIL else 1 if status == HealthStatus.WARN else 0,
        )
    )

    placebo = rs.get("placebo_sharpe")
    live = rs.get("alpha_sharpe")
    if placebo is not None and live is not None:
        try:
            p = float(placebo)
            l = float(live)
            if l - p < 0.05 * max(1e-6, abs(l)):
                results.append(
                    HealthCheckResult(
                        category="robustness_overfit",
                        check_name="placebo_comparison",
                        status=HealthStatus.FAIL,
                        metrics={"placebo_sharpe": p, "alpha_sharpe": l},
                        thresholds={"min_gap": 0.05},
                        message="Placebo / randomized control matches candidate performance.",
                        suggested_action="Redesign features — likely spurious correlation.",
                        severity=3,
                    )
                )
        except (TypeError, ValueError):
            pass

    return results
