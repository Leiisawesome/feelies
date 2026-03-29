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
    ) -> SlippageReport:
        """Compute execution quality metrics from trade records."""
        ...

    def detect_edge_decay(
        self,
        strategy_id: str,
        trades: list[TradeRecord],
    ) -> list[DecaySignal]:
        """Identify statistical evidence of edge degradation."""
        ...
