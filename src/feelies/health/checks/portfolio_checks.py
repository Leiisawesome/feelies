"""Category 9 — portfolio fit vs existing strategies."""

from __future__ import annotations

from feelies.health.config import HealthConfig
from feelies.health.context import HealthCheckContext
from feelies.health.metrics import pearson_correlation, sharpe_ratio
from feelies.health.models import HealthCheckResult, HealthStatus


def _series_from_pnl(ctx: HealthCheckContext) -> list[float]:
    from feelies.health.column_utils import row_float

    out = [
        float(v)
        for v in (row_float(r, "pnl", "net_pnl", "daily_pnl") for r in ctx.pnl_series)
        if v is not None
    ]
    return out


def run_portfolio_checks(ctx: HealthCheckContext, cfg: HealthConfig) -> list[HealthCheckResult]:
    results: list[HealthCheckResult] = []

    if not ctx.existing_strategy_equity:
        results.append(
            HealthCheckResult(
                category="portfolio_fit",
                check_name="benchmark_strategies_present",
                status=HealthStatus.NOT_APPLICABLE,
                metrics={},
                thresholds={},
                message="No existing strategy PnL series supplied.",
                suggested_action="Provide portfolio_benchmarks.json with aligned return series.",
                severity=0,
            )
        )
        return results

    cand = _series_from_pnl(ctx)
    if len(cand) < 5:
        results.append(
            HealthCheckResult(
                category="portfolio_fit",
                check_name="candidate_series_length",
                status=HealthStatus.WARN,
                metrics={"len": len(cand)},
                thresholds={},
                message="Candidate series too short for stable correlation.",
                suggested_action="Align daily PnL history before portfolio diagnostics.",
                severity=2,
            )
        )
        return results

    cand_sharpe = sharpe_ratio(cand, annualization_factor=cfg.sharpe_annualization_factor)

    worst_corr = 0.0
    corr_detail: dict[str, float | None] = {}
    marginal_sharpes: dict[str, float | None] = {}

    for name, bench in ctx.existing_strategy_equity.items():
        series = list(bench)
        m = min(len(cand), len(series))
        if m < 5:
            corr_detail[name] = None
            continue
        r_val = pearson_correlation(cand[-m:], series[-m:])
        corr_detail[name] = r_val
        if r_val is not None:
            worst_corr = max(worst_corr, abs(r_val))

        combo = [cand[-m:][i] + series[-m:][i] for i in range(m)]
        marginal = sharpe_ratio(combo, annualization_factor=cfg.sharpe_annualization_factor)
        base = sharpe_ratio(series[-m:], annualization_factor=cfg.sharpe_annualization_factor)
        if marginal is not None and base is not None:
            marginal_sharpes[name] = marginal - base
        else:
            marginal_sharpes[name] = None

    status = HealthStatus.PASS
    if worst_corr > cfg.max_corr_to_existing_alpha:
        status = HealthStatus.FAIL

    min_marg = min((v for v in marginal_sharpes.values() if v is not None), default=None)
    if min_marg is not None and cand_sharpe is not None and min_marg < cfg.min_marginal_sharpe_improvement:
        status = HealthStatus.WARN if status != HealthStatus.FAIL else status

    results.append(
        HealthCheckResult(
            category="portfolio_fit",
            check_name="correlation_and_marginal_sharpe",
            status=status,
            metrics={
                "max_abs_corr": worst_corr,
                "per_strategy_corr": corr_detail,
                "marginal_sharpe_delta": marginal_sharpes,
                "candidate_sharpe": cand_sharpe,
            },
            thresholds={
                "max_corr_to_existing_alpha": cfg.max_corr_to_existing_alpha,
                "min_marginal_sharpe_improvement": cfg.min_marginal_sharpe_improvement,
            },
            message="Portfolio diversification vs recorded benchmarks.",
            suggested_action="Reject clones; favour orthogonal mechanisms.",
            severity=3 if status == HealthStatus.FAIL else 1 if status == HealthStatus.WARN else 0,
        )
    )

    return results

