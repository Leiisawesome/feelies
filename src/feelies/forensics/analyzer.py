"""Forensic analyzer protocol — post-trade analysis contracts.

Defines the interface for analyzing trade outcomes, detecting edge
decay, and generating execution quality reports.  Concrete
implementations are future work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from feelies.storage.trade_journal import TradeRecord


@dataclass(frozen=True, kw_only=True)
class SlippageReport:
    """Summary of execution quality for a time window."""

    symbol: str | None
    strategy_id: str | None
    trade_count: int
    mean_cost_bps: float
    p95_cost_bps: float
    total_fees: float


@dataclass(frozen=True, kw_only=True)
class TCAReport:
    """Full transaction cost analysis across a set of trade records.

    Extends execution quality metrics with edge-vs-cost comparison
    and order-size distribution (histogram buckets).

    ``mean_edge_bps``: realized P&L per notional in basis points,
        averaged across all trades.
    ``p95_edge_bps``: 95th-percentile edge (best trades).
    ``pct_positive_edge``: share of trades where realized edge > 0.
    ``pct_edge_covers_cost``: share of trades where edge > 2× cost
        (the B4 threshold applied retroactively).
    ``size_histogram``: order-size distribution by bucket label.
    ``rolling_50_mean_edge_bps``: mean edge over most recent 50 trades.
    ``rolling_200_mean_edge_bps``: mean edge over most recent 200 trades.
    """

    trade_count: int
    mean_cost_bps: float
    p95_cost_bps: float
    total_fees: float

    # Edge metrics (realized_pnl / notional in bps)
    mean_edge_bps: float
    p95_edge_bps: float
    pct_positive_edge: float
    pct_edge_covers_cost: float

    # Order-size histogram: bucket label → count
    size_histogram: dict[str, int]

    # Rolling window edge means
    rolling_50_mean_edge_bps: float
    rolling_200_mean_edge_bps: float


@dataclass(frozen=True, kw_only=True)
class DecaySignal:
    """Evidence of edge decay for a strategy."""

    strategy_id: str
    metric: str
    expected: float
    realized: float
    z_score: float
    recommendation: str


class ForensicAnalyzer(Protocol):
    """Analyze post-trade execution quality and detect edge decay."""

    def analyze_fills(
        self,
        trades: list[TradeRecord],
    ) -> TCAReport:
        """Compute TCA metrics from trade records."""
        ...

    def detect_edge_decay(
        self,
        strategy_id: str,
        trades: list[TradeRecord],
    ) -> list[DecaySignal]:
        """Identify statistical evidence of edge degradation."""
        ...
