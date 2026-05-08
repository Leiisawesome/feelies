"""Category 5 — regime robustness (causal proxies only)."""

from __future__ import annotations

from collections import defaultdict

from feelies.health.column_utils import row_float, row_str
from feelies.health.config import HealthConfig
from feelies.health.context import HealthCheckContext
from feelies.health.metrics import safe_mean, sharpe_ratio
from feelies.health.models import HealthCheckResult, HealthStatus


def run_regime_checks(ctx: HealthCheckContext, cfg: HealthConfig) -> list[HealthCheckResult]:
    results: list[HealthCheckResult] = []

    rows = list(ctx.trades)
    if not rows:
        results.append(
            HealthCheckResult(
                category="regime_robustness",
                check_name="regime_inputs_available",
                status=HealthStatus.WARN,
                metrics={"trade_rows": 0},
                thresholds={},
                message="No trades — regime segmentation skipped.",
                suggested_action="Export trades with spread/vol proxies or regimes.csv.",
                severity=2,
            )
        )
        return results

    spreads: list[float] = []
    for r in rows:
        sp = row_float(r, "spread_bps", "spread", "half_spread_bps")
        if sp is not None:
            spreads.append(sp)
    vols = [row_float(r, "realized_vol", "rv", "vol") for r in rows if row_float(r, "realized_vol", "rv", "vol")]
    vols_f = [float(v) for v in vols if v is not None]

    if len(spreads) < cfg.min_regime_sample_size and len(vols_f) < cfg.min_regime_sample_size:
        results.append(
            HealthCheckResult(
                category="regime_robustness",
                check_name="regime_proxy_coverage",
                status=HealthStatus.WARN,
                metrics={"spread_samples": len(spreads), "vol_samples": len(vols_f)},
                thresholds={"min_regime_sample_size": cfg.min_regime_sample_size},
                message="Insufficient spread/vol fields to bucket regimes safely.",
                suggested_action="Log spread at decision time on each trade row.",
                severity=2,
            )
        )
        return results

    # Bucket by spread terciles when possible.
    bucket_pnl: dict[str, list[float]] = defaultdict(list)
    if len(spreads) >= cfg.min_regime_sample_size:
        sorted_s = sorted(float(s) for s in spreads)
        n = len(sorted_s)
        q1 = sorted_s[n // 3]
        q2 = sorted_s[(2 * n) // 3]
        for r in rows:
            sp = row_float(r, "spread_bps", "spread", "half_spread_bps")
            pnl = row_float(r, "net_pnl", "pnl", "trade_pnl")
            if sp is None or pnl is None:
                continue
            if float(sp) <= q1:
                tag = "spread_low"
            elif float(sp) <= q2:
                tag = "spread_mid"
            else:
                tag = "spread_high"
            bucket_pnl[tag].append(float(pnl))
    else:
        for r in rows:
            pnl = row_float(r, "net_pnl", "pnl", "trade_pnl")
            vol = row_float(r, "realized_vol", "rv", "vol")
            if pnl is None or vol is None:
                continue
            bucket = "vol_bucket"
            bucket_pnl[bucket].append(float(pnl))

    totals = {k: sum(v) for k, v in bucket_pnl.items()}
    total_abs = sum(abs(v) for v in totals.values())
    max_share = None
    if total_abs > 0:
        max_share = max(abs(v) / total_abs for v in totals.values())

    status = HealthStatus.PASS
    if max_share is not None and max_share > cfg.max_single_regime_pnl_contribution:
        status = HealthStatus.WARN

    losing_common = 0
    common = 0
    for _, pnls in bucket_pnl.items():
        if len(pnls) >= cfg.min_regime_sample_size:
            common += 1
            mu = safe_mean(pnls)
            if mu is not None and mu < 0:
                losing_common += 1
    if common > 0 and (losing_common / common) > cfg.max_losing_common_regime_fraction:
        status = HealthStatus.FAIL

    sharpe_by: dict[str, float | None] = {}
    for label, pnls in bucket_pnl.items():
        sharpe_by[label] = sharpe_ratio(pnls, annualization_factor=cfg.sharpe_annualization_factor)

    results.append(
        HealthCheckResult(
            category="regime_robustness",
            check_name="regime_pnl_concentration",
            status=status,
            metrics={
                "bucket_total_pnl": totals,
                "max_abs_contribution_share": max_share,
                "per_bucket_sharpe": sharpe_by,
            },
            thresholds={
                "max_single_regime_pnl_contribution": cfg.max_single_regime_pnl_contribution,
                "max_losing_common_regime_fraction": cfg.max_losing_common_regime_fraction,
            },
            message="PnL concentration across causal spread/vol buckets.",
            suggested_action="If concentrated, document monitorable regime triggers.",
            severity=3 if status == HealthStatus.FAIL else 1 if status == HealthStatus.WARN else 0,
        )
    )

    # Time-of-day bucket (hour from timestamp if present).
    tod_pnl: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        ts = row_float(r, "timestamp", "ts_ns", "event_time_ns")
        pnl = row_float(r, "net_pnl", "pnl", "trade_pnl")
        if ts is None or pnl is None:
            continue
        hour = int((float(ts) / 1e9) % 86400 // 3600)
        bucket = f"utc_hour_{hour:02d}"
        tod_pnl[bucket].append(float(pnl))
    if len(tod_pnl) >= 2:
        tot_tod = {k: sum(v) for k, v in tod_pnl.items()}
        denom = sum(abs(v) for v in tot_tod.values())
        max_share_tod = max((abs(v) / denom) for v in tot_tod.values()) if denom > 0 else None
        results.append(
            HealthCheckResult(
                category="regime_robustness",
                check_name="time_of_day_balance",
                status=HealthStatus.PASS
                if max_share_tod is not None and max_share_tod < 0.75
                else HealthStatus.WARN,
                metrics={"tod_buckets": len(tod_pnl), "max_abs_pnl_share_by_hour_bucket": max_share_tod},
                thresholds={"informal_balance": 0.75},
                message="Time-of-day concentration proxy.",
                suggested_action="Verify execution aligns with liquidity in dominant hours.",
                severity=1,
            )
        )

    # Symbol liquidity bucket if annotated.
    liq_pnl: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        bucket = row_str(r, "liquidity_bucket", "adv_bucket", "size_bucket") or "unknown"
        pnl = row_float(r, "net_pnl", "pnl", "trade_pnl")
        if pnl is None:
            continue
        liq_pnl[bucket].append(float(pnl))
    if len(liq_pnl) > 1:
        results.append(
            HealthCheckResult(
                category="regime_robustness",
                check_name="liquidity_bucket_mix",
                status=HealthStatus.PASS,
                metrics={k: len(v) for k, v in liq_pnl.items()},
                thresholds={},
                message="Liquidity bucket coverage.",
                suggested_action="",
                severity=0,
            )
        )

    return results
