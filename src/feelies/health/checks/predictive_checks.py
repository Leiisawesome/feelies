"""Category 3 — raw predictive power."""

from __future__ import annotations

from collections import defaultdict

from feelies.health.column_utils import row_float, row_str
from feelies.health.config import HealthConfig
from feelies.health.context import HealthCheckContext
from feelies.health.metrics import (
    hit_rate,
    ic_t_statistic,
    monotonicity_score,
    quantile_bucket_returns,
    safe_mean,
    spearman_correlation,
    signal_autocorrelation,
)
from feelies.health.models import HealthCheckResult, HealthStatus


def run_predictive_checks(ctx: HealthCheckContext, cfg: HealthConfig) -> list[HealthCheckResult]:
    results: list[HealthCheckResult] = []
    rows = list(ctx.signals)
    xs: list[float] = []
    ys: list[float] = []
    day_keys: set[str] = set()
    syms: set[str] = set()
    for row in rows:
        s = row_float(row, "signal", "alpha_signal", "score", "forecast")
        y = row_float(row, "forward_return", "fwd_return", "label", "y")
        if s is None or y is None:
            continue
        xs.append(s)
        ys.append(y)
        sym = row_str(row, "symbol", "ticker")
        if sym:
            syms.add(sym)
        day = row_str(row, "date", "session_date", "trading_day")
        if day:
            day_keys.add(day)
        else:
            ts = row_float(row, "timestamp", "ts", "event_time_ns")
            if ts is not None:
                day_keys.add(str(int(ts) // 86_400_000_000_000))  # coarse day bucket in ns

    n = len(xs)
    if n < cfg.min_observations:
        results.append(
            HealthCheckResult(
                category="raw_predictive_power",
                check_name="sample_size",
                status=HealthStatus.FAIL,
                metrics={"n_observations": n, "n_trading_days": len(day_keys), "n_symbols": len(syms)},
                thresholds={"min_observations": cfg.min_observations, "min_trading_days": cfg.min_trading_days},
                message="Insufficient paired signal / forward-return observations.",
                suggested_action="Collect more history or lower thresholds only with justification.",
                severity=3,
            )
        )
        return results

    results.append(
        HealthCheckResult(
            category="raw_predictive_power",
            check_name="sample_size",
            status=HealthStatus.PASS,
            metrics={"n_observations": n, "n_trading_days": len(day_keys), "n_symbols": len(syms)},
            thresholds={"min_observations": cfg.min_observations, "min_trading_days": cfg.min_trading_days},
            message="Observation count meets minimum.",
            suggested_action="",
            severity=0,
        )
    )

    if len(day_keys) < cfg.min_trading_days:
        results.append(
            HealthCheckResult(
                category="raw_predictive_power",
                check_name="trading_day_coverage",
                status=HealthStatus.WARN,
                metrics={"n_trading_days": len(day_keys)},
                thresholds={"min_trading_days": cfg.min_trading_days},
                message="Few distinct trading days — time diversity is limited.",
                suggested_action="Bucket timestamps into sessions or widen calendar coverage.",
                severity=2,
            )
        )
    else:
        results.append(
            HealthCheckResult(
                category="raw_predictive_power",
                check_name="trading_day_coverage",
                status=HealthStatus.PASS,
                metrics={"n_trading_days": len(day_keys)},
                thresholds={"min_trading_days": cfg.min_trading_days},
                message="Trading-day coverage acceptable.",
                suggested_action="",
                severity=0,
            )
        )

    ic = spearman_correlation(xs, ys)
    ic_t = ic_t_statistic(ic, n) if ic is not None else None
    status_ic = HealthStatus.PASS
    if ic is None:
        status_ic = HealthStatus.FAIL
    else:
        if abs(ic) < cfg.min_abs_ic or (ic_t is not None and abs(ic_t) < cfg.min_ic_t_stat):
            status_ic = HealthStatus.WARN
        if ic < 0:
            status_ic = HealthStatus.FAIL
    results.append(
        HealthCheckResult(
            category="raw_predictive_power",
            check_name="information_coefficient",
            status=status_ic,
            metrics={"ic_spearman": ic, "ic_t_stat": ic_t},
            thresholds={"min_abs_ic": cfg.min_abs_ic, "min_ic_t_stat": cfg.min_ic_t_stat},
            message="Spearman IC diagnostics on signal vs forward return.",
            suggested_action="Strengthen signal construction if IC is weak or negative.",
            severity=2 if status_ic == HealthStatus.WARN else 3 if status_ic == HealthStatus.FAIL else 0,
        )
    )

    buckets = quantile_bucket_returns(xs, ys, quantiles=5)
    spread = None
    mono = None
    if buckets:
        spread = buckets[-1] - buckets[0]
        mono = monotonicity_score(buckets)
    status_q = HealthStatus.WARN
    if spread is not None and spread > 0 and (mono is None or mono >= cfg.min_monotonicity_score):
        status_q = HealthStatus.PASS
    if spread is not None and spread <= 0:
        status_q = HealthStatus.FAIL
    results.append(
        HealthCheckResult(
            category="raw_predictive_power",
            check_name="quantile_monotonicity",
            status=status_q,
            metrics={"bucket_mean_returns": buckets, "top_minus_bottom": spread, "monotonicity": mono},
            thresholds={"min_monotonicity_score": cfg.min_monotonicity_score},
            message="Quantile spread / monotonicity diagnostic.",
            suggested_action="Inspect bucket drift — flat buckets imply weak ranking power.",
            severity=3 if status_q == HealthStatus.FAIL else 1 if status_q == HealthStatus.WARN else 0,
        )
    )

    hits = [xs[i] * ys[i] > 0 for i in range(n)]
    hr = hit_rate(hits)
    results.append(
        HealthCheckResult(
            category="raw_predictive_power",
            check_name="directional_hit_rate",
            status=HealthStatus.PASS if hr is not None and hr >= 0.5 else HealthStatus.WARN,
            metrics={"hit_rate": hr},
            thresholds={"reference": 0.5},
            message="Hit-rate vs directional forward returns.",
            suggested_action="",
            severity=1,
        )
    )

    coverage = n / max(1, len(rows))
    cov_status = HealthStatus.PASS if coverage >= cfg.min_signal_coverage else HealthStatus.WARN
    results.append(
        HealthCheckResult(
            category="raw_predictive_power",
            check_name="signal_coverage",
            status=cov_status,
            metrics={"paired_fraction_of_rows": coverage},
            thresholds={"min_signal_coverage": cfg.min_signal_coverage},
            message="Share of signal rows with usable forward returns.",
            suggested_action="Align labels to signals to avoid sparse evaluation.",
            severity=1 if cov_status == HealthStatus.WARN else 0,
        )
    )

    xs_by_sym: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        sym = row_str(row, "symbol", "ticker") or "_all"
        s = row_float(row, "signal", "alpha_signal", "score", "forecast")
        if s is not None:
            xs_by_sym[sym].append(s)
    autocorrs: dict[str, float | None] = {}
    for sym, series in xs_by_sym.items():
        if len(series) > 5:
            autocorrs[sym] = signal_autocorrelation(series, lag=1)
    results.append(
        HealthCheckResult(
            category="raw_predictive_power",
            check_name="signal_autocorrelation",
            status=HealthStatus.PASS,
            metrics={"per_symbol_lag1": autocorrs},
            thresholds={},
            message="Signal persistence diagnostic (lag-1 autocorrelation).",
            suggested_action="High autocorrelation may inflate naive IC — consider Newey-West style "
            "controls offline.",
            severity=0,
        )
    )

    return results
