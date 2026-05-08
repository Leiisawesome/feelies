"""Category 4 — cost and execution survival."""

from __future__ import annotations

from feelies.health.column_utils import row_float
from feelies.health.config import HealthConfig
from feelies.health.context import HealthCheckContext
from feelies.health.metrics import safe_mean, sharpe_ratio
from feelies.health.models import HealthCheckResult, HealthStatus


def _variant_metrics(variant: dict[str, float]) -> dict[str, float | None]:
    return {
        "gross_pnl": variant.get("gross_pnl"),
        "net_pnl": variant.get("net_pnl"),
        "gross_sharpe": variant.get("gross_sharpe"),
        "net_sharpe": variant.get("net_sharpe"),
        "avg_gross_edge_per_trade": variant.get("avg_gross_edge_per_trade"),
        "avg_net_edge_per_trade": variant.get("avg_net_edge_per_trade"),
        "avg_cost_per_trade": variant.get("avg_cost_per_trade"),
        "turnover": variant.get("turnover"),
        "avg_spread_paid_bps": variant.get("avg_spread_paid_bps"),
        "slippage_bps": variant.get("slippage_bps"),
        "fee_bps": variant.get("fee_bps"),
    }


def _infer_from_pnl_series(ctx: HealthCheckContext) -> dict[str, float]:
    pnls: list[float] = []
    for r in ctx.pnl_series:
        v = row_float(r, "pnl", "net_pnl", "daily_pnl")
        if v is not None:
            pnls.append(v)
    floats = pnls
    gross_f: list[float] = []
    for r in ctx.pnl_series:
        g = row_float(r, "gross_pnl")
        if g is not None:
            gross_f.append(g)
    if not floats:
        return {}
    total_net = sum(floats)
    total_gross = sum(gross_f) if gross_f else total_net
    costs = max(0.0, total_gross - total_net)
    sh = sharpe_ratio(floats, annualization_factor=252.0)  # default; cfg applied later
    avg_cost = costs / max(1, len(floats))
    edge = (total_gross / max(1, len(floats))) - (total_net / max(1, len(floats)))
    return {
        "net_pnl": total_net,
        "gross_pnl": total_gross,
        "net_sharpe": sh if sh is not None else 0.0,
        "gross_sharpe": sh if sh is not None else 0.0,
        "avg_cost_per_trade": avg_cost,
        "avg_gross_edge_per_trade": total_gross / max(1, len(floats)),
        "avg_net_edge_per_trade": total_net / max(1, len(floats)),
    }


def _infer_from_trades(ctx: HealthCheckContext) -> dict[str, float]:
    edges = []
    costs = []
    for r in ctx.trades:
        g = row_float(r, "gross_edge", "gross_pnl", "edge_gross")
        n = row_float(r, "net_edge", "net_pnl", "edge_net")
        c = row_float(r, "fees", "fee", "cost", "slippage", "total_cost")
        if g is not None and n is not None:
            edges.append(g - n)
        elif c is not None:
            costs.append(c)
    if not edges and not costs:
        return {}
    avg_cost = safe_mean(costs) if costs else safe_mean(edges)
    gross_vals: list[float] = []
    net_vals: list[float] = []
    for r in ctx.trades:
        g = row_float(r, "gross_edge")
        if g is not None:
            gross_vals.append(g)
        n = row_float(r, "net_edge")
        if n is not None:
            net_vals.append(n)
    avg_gross = safe_mean(gross_vals)
    avg_net = safe_mean(net_vals)
    ratio = None
    if avg_cost is not None and avg_cost != 0.0 and avg_gross is not None:
        ratio = abs(avg_gross) / max(1e-12, abs(avg_cost))
    out: dict[str, float] = {}
    if avg_gross is not None:
        out["avg_gross_edge_per_trade"] = float(avg_gross)
    if avg_net is not None:
        out["avg_net_edge_per_trade"] = float(avg_net)
    if avg_cost is not None:
        out["avg_cost_per_trade"] = float(avg_cost)
    if ratio is not None:
        out["gross_edge_to_cost_ratio"] = float(ratio)
    return out


def run_execution_checks(ctx: HealthCheckContext, cfg: HealthConfig) -> list[HealthCheckResult]:
    results: list[HealthCheckResult] = []
    variants = dict(ctx.execution_variants)

    inferred_only = False
    if not variants:
        pnl_metrics = _infer_from_pnl_series(ctx)
        trade_metrics = _infer_from_trades(ctx)
        if pnl_metrics:
            rets: list[float] = []
            for r in ctx.pnl_series:
                v = row_float(r, "pnl", "net_pnl", "daily_pnl")
                if v is not None:
                    rets.append(v)
            sh = sharpe_ratio(rets, annualization_factor=cfg.sharpe_annualization_factor)
            if sh is not None:
                pnl_metrics["net_sharpe"] = sh
                pnl_metrics["gross_sharpe"] = sh
            variants["inferred_from_pnl"] = {k: float(v) for k, v in pnl_metrics.items() if v is not None}
            inferred_only = True
        if trade_metrics:
            merged: dict[str, float] = dict(variants.get("inferred_from_pnl", {}))
            merged.update({k: float(v) for k, v in trade_metrics.items()})
            variants["inferred_from_pnl"] = merged
            inferred_only = True

    proven_lens = {"conservative", "executable", "bid_ask", "delayed", "realistic", "with_costs"}
    has_proven_lens = any(k in proven_lens for k in variants)
    mid_only = ("mid" in variants and not has_proven_lens) or (
        inferred_only and not has_proven_lens and set(variants.keys()) <= {"inferred_from_pnl"}
    )

    if not variants:
        results.append(
            HealthCheckResult(
                category="cost_execution_survival",
                check_name="execution_variants_present",
                status=HealthStatus.WARN,
                metrics={"variants": []},
                thresholds={},
                message="No execution variants or inferable PnL — tradability is unproven.",
                suggested_action="Export execution_variants.json with mid/executable/conservative "
                "summaries or trades with costs.",
                severity=2,
            )
        )
        results.append(
            HealthCheckResult(
                category="cost_execution_survival",
                check_name="primary_lens_economics",
                status=HealthStatus.NOT_APPLICABLE,
                metrics={"reason": "no_execution_lenses"},
                thresholds={},
                message="Skipped — no primary execution lens available.",
                suggested_action="Provide PnL or execution variant summaries.",
                severity=0,
            )
        )
        return results

    results.append(
        HealthCheckResult(
            category="cost_execution_survival",
            check_name="execution_variants_present",
            status=HealthStatus.WARN if mid_only else HealthStatus.PASS,
            metrics={"variant_keys": sorted(variants.keys()), "mid_only": mid_only},
            thresholds={},
            message="Execution survival not proven; only mid-price results available."
            if mid_only
            else "Multiple execution lenses present.",
            suggested_action="Add bid/ask executable and conservative cost scenarios.",
            severity=2 if mid_only else 0,
        )
    )

    primary_key = next(iter(variants))
    for cand in (
        "conservative",
        "executable",
        "realistic",
        "bid_ask",
        "delayed",
        "with_costs",
        "inferred_from_pnl",
        "mid",
    ):
        if cand in variants:
            primary_key = cand
            break
    primary = {k: float(v) for k, v in variants[primary_key].items() if _is_float(v)}
    net_pnl = primary.get("net_pnl")
    net_sharpe = primary.get("net_sharpe")
    gross_edge = primary.get("avg_gross_edge_per_trade")
    cost = primary.get("avg_cost_per_trade")
    ratio = primary.get("gross_edge_to_cost_ratio")
    if ratio is None and gross_edge is not None and cost is not None and cost != 0.0:
        ratio = abs(gross_edge) / max(1e-12, abs(cost))

    share = None
    if gross_edge is not None and gross_edge != 0.0 and cost is not None:
        share = abs(cost) / max(1e-12, abs(gross_edge))

    status = HealthStatus.PASS
    messages: list[str] = []

    if net_pnl is not None and net_pnl < cfg.min_net_pnl:
        status = HealthStatus.FAIL
        messages.append("Net PnL negative under primary execution lens.")
    if net_sharpe is not None and net_sharpe < cfg.min_net_sharpe:
        status = HealthStatus.WARN if status != HealthStatus.FAIL else status
        messages.append("Net Sharpe below threshold.")

    if ratio is not None:
        if ratio < cfg.min_gross_edge_to_cost_ratio:
            status = HealthStatus.FAIL
            messages.append("Gross-edge to cost ratio fails structural margin.")
        elif ratio < cfg.warn_gross_edge_to_cost_ratio:
            status = HealthStatus.WARN if status == HealthStatus.PASS else status
            messages.append("Gross-edge to cost ratio only marginally above minimum.")

    if share is not None and share > cfg.max_cost_share_of_gross_edge:
        status = HealthStatus.FAIL if status != HealthStatus.FAIL else HealthStatus.FAIL
        messages.append("Costs consume excessive share of gross edge.")

    mid_penalty = mid_only
    if mid_only:
        status = HealthStatus.FAIL if status == HealthStatus.PASS else status
        messages.append("Mid-only path cannot PASS execution survival.")

    results.append(
        HealthCheckResult(
            category="cost_execution_survival",
            check_name="primary_lens_economics",
            status=status,
            metrics={
                "primary_lens": primary_key,
                **_variant_metrics(primary),
                "gross_edge_to_cost_ratio": ratio,
                "cost_share_of_gross_edge": share,
                "mid_only_execution": mid_penalty,
            },
            thresholds={
                "min_net_pnl": cfg.min_net_pnl,
                "min_net_sharpe": cfg.min_net_sharpe,
                "min_gross_edge_to_cost_ratio": cfg.min_gross_edge_to_cost_ratio,
                "warn_gross_edge_to_cost_ratio": cfg.warn_gross_edge_to_cost_ratio,
                "max_cost_share_of_gross_edge": cfg.max_cost_share_of_gross_edge,
            },
            message="; ".join(messages) or "Primary execution lens passes economics thresholds.",
            suggested_action="Stress costs and latency before allocating capital.",
            severity=3 if status == HealthStatus.FAIL else 1 if status == HealthStatus.WARN else 0,
        )
    )

    return results


def _is_float(v: object) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v)
        except ValueError:
            return False
        return True
    return False
