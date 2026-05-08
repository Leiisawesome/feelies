"""Category 8 — capacity and participation."""

from __future__ import annotations

from feelies.health.column_utils import row_float, row_str
from feelies.health.config import HealthConfig
from feelies.health.context import HealthCheckContext
from feelies.health.metrics import participation_rate
from feelies.health.models import HealthCheckResult, HealthStatus


def run_capacity_checks(ctx: HealthCheckContext, cfg: HealthConfig) -> list[HealthCheckResult]:
    results: list[HealthCheckResult] = []

    rows = list(ctx.trades)
    if not rows:
        results.append(
            HealthCheckResult(
                category="capacity_liquidity",
                check_name="capacity_inputs_available",
                status=HealthStatus.WARN,
                metrics={},
                thresholds={},
                message="Capacity not evaluated — missing trades with liquidity fields.",
                suggested_action="Log ADV, top-of-book size, and order notional per fill.",
                severity=2,
            )
        )
        return results

    parts: list[float] = []
    tob_fracs: list[float] = []
    for r in rows:
        notional = row_float(r, "order_notional", "notional", "dollar_notional")
        adv = row_float(r, "adv_dollar_volume", "adv", "interval_dollar_volume")
        if notional is not None and adv is not None:
            pr = participation_rate(notional, adv)
            if pr is not None:
                parts.append(pr)
        size = row_float(r, "order_size_shares", "quantity", "qty")
        tob = row_float(r, "top_of_book_size", "tob_size", "display_qty")
        if size is not None and tob is not None and tob != 0.0:
            tob_fracs.append(abs(size) / max(1e-9, tob))

    bucket = row_str(rows[0], "liquidity_bucket", "adv_bucket") or "liquid"
    max_part = (
        cfg.max_participation_rate_illiquid
        if bucket.lower() in {"illiquid", "small", "micro"}
        else cfg.max_participation_rate_liquid
    )

    if not parts:
        results.append(
            HealthCheckResult(
                category="capacity_liquidity",
                check_name="participation_rate",
                status=HealthStatus.WARN,
                metrics={"samples": 0},
                thresholds={"max_participation": max_part},
                message="Capacity not evaluated — participation inputs missing.",
                suggested_action="Attach ADV or interval volume to each trade.",
                severity=2,
            )
        )
    else:
        worst = max(parts)
        status = HealthStatus.PASS if worst <= max_part else HealthStatus.FAIL
        results.append(
            HealthCheckResult(
                category="capacity_liquidity",
                check_name="participation_rate",
                status=status,
                metrics={"max_participation_observed": worst, "samples": len(parts)},
                thresholds={"max_participation": max_part},
                message="Participation vs ADV / interval volume.",
                suggested_action="Downsize if participation unrealistic.",
                severity=3 if status == HealthStatus.FAIL else 0,
            )
        )

    if tob_fracs:
        worst_tob = max(tob_fracs)
        status_tob = HealthStatus.PASS if worst_tob <= cfg.max_order_size_fraction_of_top_of_book else HealthStatus.WARN
        results.append(
            HealthCheckResult(
                category="capacity_liquidity",
                check_name="top_of_book_fraction",
                status=status_tob,
                metrics={"max_order_to_tob": worst_tob},
                thresholds={"max_order_size_fraction_of_top_of_book": cfg.max_order_size_fraction_of_top_of_book},
                message="Order size relative to displayed liquidity.",
                suggested_action="Use deeper book estimates if routinely breaching 25% of TOB.",
                severity=1 if status_tob == HealthStatus.WARN else 0,
            )
        )

    return results
