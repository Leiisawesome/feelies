"""Decay detector — post-trade TCA and edge decay detection.

Implements the ForensicAnalyzer protocol.  Computes execution quality
metrics (cost/edge per trade, order-size histogram, rolling means) and
detects statistical evidence of edge decay by comparing recent vs
historical realized edge using a Z-score test.
"""

from __future__ import annotations

import math
import statistics

from feelies.forensics.analyzer import DecaySignal, TCAReport
from feelies.storage.trade_journal import TradeRecord


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Return the ``pct``-th percentile from a pre-sorted list.

    ``pct`` is in [0, 100].  Returns 0.0 for an empty list.
    """
    if not sorted_vals:
        return 0.0
    idx = int(len(sorted_vals) * pct / 100)
    return sorted_vals[min(idx, len(sorted_vals) - 1)]


class DecayDetector:
    """Post-trade TCA and edge decay analyser.

    ``analyze_fills`` computes cost/edge-per-trade metrics, an
    order-size histogram, and rolling mean edge over last 50/200
    trades.

    ``detect_edge_decay`` performs a Z-score test on rolling vs
    historical edge, surfacing strategies whose recent realized edge
    has dropped significantly relative to their own history.
    """

    def analyze_fills(self, trades: list[TradeRecord]) -> TCAReport:
        """Compute TCA metrics from trade records.

        All bps values are in basis points (1 bps = 0.01%).
        Edge per trade = realized_pnl / notional × 10 000.
        """
        if not trades:
            return TCAReport(
                trade_count=0,
                mean_cost_bps=0.0,
                p95_cost_bps=0.0,
                total_fees=0.0,
                mean_edge_bps=0.0,
                p95_edge_bps=0.0,
                pct_positive_edge=0.0,
                pct_edge_covers_cost=0.0,
                size_histogram={"1-100": 0, "101-500": 0, "501-2000": 0, ">2000": 0},
                rolling_50_mean_edge_bps=0.0,
                rolling_200_mean_edge_bps=0.0,
            )

        # ── Per-trade metrics ─────────────────────────────────
        cost_bps_list: list[float] = []
        edge_bps_list: list[float] = []

        for t in trades:
            cost_bps_list.append(float(t.cost_bps))
            qty = abs(t.filled_quantity)
            if t.fill_price is not None and qty > 0:
                notional = float(t.fill_price) * qty
                edge_bps = float(t.realized_pnl) / notional * 10_000 if notional > 0 else 0.0
            else:
                edge_bps = 0.0
            edge_bps_list.append(edge_bps)

        total_fees = sum(float(t.fees) for t in trades)
        mean_cost_bps = statistics.mean(cost_bps_list)
        sorted_costs = sorted(cost_bps_list)
        p95_cost_bps = _percentile(sorted_costs, 95)

        mean_edge_bps = statistics.mean(edge_bps_list)
        sorted_edges = sorted(edge_bps_list)
        p95_edge_bps = _percentile(sorted_edges, 95)

        n = len(trades)
        pct_positive_edge = sum(1 for e in edge_bps_list if e > 0) / n * 100.0
        pct_edge_covers_cost = (
            sum(1 for e, c in zip(edge_bps_list, cost_bps_list) if e > 2 * c) / n * 100.0
        )

        # ── Order-size histogram ──────────────────────────────
        size_histogram: dict[str, int] = {
            "1-100": 0,
            "101-500": 0,
            "501-2000": 0,
            ">2000": 0,
        }
        for t in trades:
            qty = abs(t.filled_quantity)
            if qty <= 100:
                size_histogram["1-100"] += 1
            elif qty <= 500:
                size_histogram["101-500"] += 1
            elif qty <= 2000:
                size_histogram["501-2000"] += 1
            else:
                size_histogram[">2000"] += 1

        # ── Rolling window means ──────────────────────────────
        window_50 = edge_bps_list[-50:] if len(edge_bps_list) >= 50 else edge_bps_list
        window_200 = edge_bps_list[-200:] if len(edge_bps_list) >= 200 else edge_bps_list
        rolling_50 = statistics.mean(window_50) if window_50 else 0.0
        rolling_200 = statistics.mean(window_200) if window_200 else 0.0

        return TCAReport(
            trade_count=n,
            mean_cost_bps=mean_cost_bps,
            p95_cost_bps=p95_cost_bps,
            total_fees=total_fees,
            mean_edge_bps=mean_edge_bps,
            p95_edge_bps=p95_edge_bps,
            pct_positive_edge=pct_positive_edge,
            pct_edge_covers_cost=pct_edge_covers_cost,
            size_histogram=size_histogram,
            rolling_50_mean_edge_bps=rolling_50,
            rolling_200_mean_edge_bps=rolling_200,
        )

    def detect_edge_decay(
        self,
        strategy_id: str,
        trades: list[TradeRecord],
    ) -> list[DecaySignal]:
        """Detect edge decay for a strategy via Z-score test.

        Requires ≥ 100 trades to produce a signal.  Compares the mean
        **net** realized edge (PnL less fees) of the most recent 50 trades
        against the historical mean of all earlier trades, scaled by the
        standard error of a 50-trade mean.  A Z-score > 2.0 (recent edge
        significantly below history) generates a DecaySignal.

        Edge is computed net of fees so cost-driven decay — stable gross
        edge with rising costs, the crowding signature — is detectable
        rather than invisible (Inv-4).
        """
        strat_trades = [t for t in trades if t.strategy_id == strategy_id]
        if len(strat_trades) < 100:
            return []

        edge_bps: list[float] = []
        for t in strat_trades:
            qty = abs(t.filled_quantity)
            if t.fill_price is not None and qty > 0:
                notional = float(t.fill_price) * qty
                net = float(t.realized_pnl) - float(t.fees)
                edge_bps.append(net / notional * 10_000 if notional > 0 else 0.0)

        if not edge_bps:
            return []

        recent = edge_bps[-50:]
        historical = edge_bps[:-50]
        if not historical:
            return []

        hist_mean = statistics.mean(historical)
        hist_stdev = statistics.stdev(historical) if len(historical) > 1 else 0.0
        recent_mean = statistics.mean(recent)

        # Scale the mean shift by its standard error, not per-trade volatility.
        # Epsilon keeps zero-variance divergence visible.
        recent_se = hist_stdev / math.sqrt(len(recent)) if recent else 0.0
        z_score = (hist_mean - recent_mean) / (recent_se + 1e-9)

        if z_score <= 2.0:
            return []

        return [
            DecaySignal(
                strategy_id=strategy_id,
                metric="rolling_edge_bps",
                expected=round(hist_mean, 4),
                realized=round(recent_mean, 4),
                z_score=round(z_score, 2),
                recommendation=(
                    "Recent edge has decayed significantly vs history "
                    f"(z={z_score:.2f}).  Review signal quality, "
                    "check for regime change or data staleness."
                ),
            )
        ]
