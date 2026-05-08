"""Category 7 — risk and drawdown diagnostics."""

from __future__ import annotations

from collections import defaultdict

from feelies.health.column_utils import row_float, row_str
from feelies.health.config import HealthConfig
from feelies.health.context import HealthCheckContext
from feelies.health.metrics import max_drawdown_from_equity, skew_kurtosis, summarize_trade_pnls
from feelies.health.models import HealthCheckResult, HealthStatus


def run_risk_checks(ctx: HealthCheckContext, cfg: HealthConfig) -> list[HealthCheckResult]:
    results: list[HealthCheckResult] = []

    trade_pnls = [
        float(v)
        for v in (
            row_float(r, "net_pnl", "pnl", "trade_pnl") for r in ctx.trades
        )
        if v is not None
    ]
    if trade_pnls:
        stats = summarize_trade_pnls(trade_pnls)
        skew, kurt = skew_kurtosis(trade_pnls)
        wins = sum(1 for x in trade_pnls if x > 0)
        losses = sum(1 for x in trade_pnls if x < 0)
        win_rate = wins / max(1, len(trade_pnls))
        pos_sum = sum(x for x in trade_pnls if x > 0)
        neg_sum = abs(sum(x for x in trade_pnls if x < 0))
        payoff = (pos_sum / wins / (neg_sum / losses)) if wins and losses and neg_sum else None
        results.append(
            HealthCheckResult(
                category="risk_drawdown",
                check_name="trade_distribution",
                status=HealthStatus.PASS,
                metrics={
                    **stats,
                    "skew": skew,
                    "excess_kurtosis": kurt,
                    "win_rate": win_rate,
                    "payoff_ratio": payoff,
                },
                thresholds={},
                message="Trade-level PnL distribution snapshot.",
                suggested_action="Inspect tails if kurtosis extreme.",
                severity=0,
            )
        )

    # Equity curve / drawdown from pnl series.
    equity: list[float] = []
    cum = 0.0
    daily_pnls: dict[str, float] = defaultdict(float)
    for r in ctx.pnl_series:
        pnl = row_float(r, "pnl", "net_pnl", "daily_pnl")
        day = row_str(r, "date", "session_date", "day")
        if pnl is None:
            continue
        cum += float(pnl)
        equity.append(cum)
        if day:
            daily_pnls[day] += float(pnl)

    if len(equity) >= 2:
        dd_info = max_drawdown_from_equity(equity)
        total_profit = max(equity[-1], 1e-9)
        dd_frac = dd_info[0] / max(1e-9, total_profit) if dd_info else None
        status_dd = HealthStatus.PASS
        if dd_frac is not None and dd_frac > cfg.max_drawdown_fraction_of_total_profit:
            status_dd = HealthStatus.WARN
        results.append(
            HealthCheckResult(
                category="risk_drawdown",
                check_name="max_drawdown_vs_profit",
                status=status_dd,
                metrics={"max_drawdown_fraction": dd_info[0] if dd_info else None, "ratio_to_profit": dd_frac},
                thresholds={"max_drawdown_fraction_of_total_profit": cfg.max_drawdown_fraction_of_total_profit},
                message="Drawdown scaled by terminal cumulative PnL.",
                suggested_action="Cap leverage if drawdown dominates payoff.",
                severity=2 if status_dd == HealthStatus.WARN else 0,
            )
        )

    if daily_pnls:
        totals = dict(daily_pnls)
        sum_abs = sum(abs(v) for v in totals.values())
        pos_total = sum(v for v in totals.values() if v > 0)
        max_day_share = max((abs(v) / sum_abs) for v in totals.values()) if sum_abs > 0 else None
        max_day_gain_share = max((v / pos_total) for v in totals.values() if v > 0) if pos_total > 0 else None
        worst_day = min(totals.values())
        status_day = HealthStatus.PASS
        if max_day_share is not None and max_day_share > cfg.max_single_day_profit_contribution:
            status_day = HealthStatus.WARN
        if pos_total > 0 and abs(worst_day) / pos_total > cfg.max_single_day_loss_fraction_of_total_profit:
            status_day = HealthStatus.FAIL
        results.append(
            HealthCheckResult(
                category="risk_drawdown",
                check_name="daily_concentration",
                status=status_day,
                metrics={
                    "max_abs_daily_share": max_day_share,
                    "max_daily_gain_share_of_positive_total": max_day_gain_share,
                    "worst_day_pnl": worst_day,
                },
                thresholds={
                    "max_single_day_profit_contribution": cfg.max_single_day_profit_contribution,
                    "max_single_day_loss_fraction_of_total_profit": cfg.max_single_day_loss_fraction_of_total_profit,
                },
                message="Daily PnL concentration diagnostics.",
                suggested_action="Investigate single-session dominance / cliff risk.",
                severity=3 if status_day == HealthStatus.FAIL else 1 if status_day == HealthStatus.WARN else 0,
            )
        )

    sym_pnls: dict[str, float] = defaultdict(float)
    for r in ctx.trades:
        sym = row_str(r, "symbol", "ticker")
        pnl = row_float(r, "net_pnl", "pnl", "trade_pnl")
        if sym and pnl is not None:
            sym_pnls[sym] += float(pnl)

    if sym_pnls:
        total = sum(abs(v) for v in sym_pnls.values())
        max_sym_share = max(abs(v) / total for v in sym_pnls.values()) if total > 0 else None
        status_sym = HealthStatus.PASS
        if max_sym_share is not None and max_sym_share > cfg.max_single_symbol_pnl_contribution:
            status_sym = HealthStatus.WARN
        results.append(
            HealthCheckResult(
                category="risk_drawdown",
                check_name="symbol_concentration",
                status=status_sym,
                metrics={"max_symbol_abs_share": max_sym_share, "n_symbols": len(sym_pnls)},
                thresholds={"max_single_symbol_pnl_contribution": cfg.max_single_symbol_pnl_contribution},
                message="PnL concentration across symbols.",
                suggested_action="Diversify or cap single-name risk.",
                severity=2 if status_sym == HealthStatus.WARN else 0,
            )
        )

    if not results:
        results.append(
            HealthCheckResult(
                category="risk_drawdown",
                check_name="risk_inputs_available",
                status=HealthStatus.WARN,
                metrics={},
                thresholds={},
                message="No trades or PnL series for risk analytics.",
                suggested_action="Export trades.csv / pnl.csv with per-trade and daily PnL.",
                severity=2,
            )
        )

    return results
