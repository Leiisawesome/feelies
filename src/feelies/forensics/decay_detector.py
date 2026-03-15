"""Decay detector — stub implementation of edge decay detection.

Placeholder for the post-trade-forensics skill's decay detection
pipeline.  Will compare realized vs expected hit rate, slippage,
and net alpha over rolling windows.
"""

from __future__ import annotations

from feelies.forensics.analyzer import DecaySignal, SlippageReport
from feelies.storage.trade_journal import TradeRecord


class DecayDetector:
    """Stub decay detector (not yet implemented)."""

    def analyze_fills(self, trades: list[TradeRecord]) -> SlippageReport:
        raise NotImplementedError(
            "DecayDetector.analyze_fills is not yet implemented. "
            "See post-trade-forensics skill for specification."
        )

    def detect_edge_decay(
        self,
        strategy_id: str,
        trades: list[TradeRecord],
    ) -> list[DecaySignal]:
        raise NotImplementedError(
            "DecayDetector.detect_edge_decay is not yet implemented. "
            "See post-trade-forensics skill for specification."
        )
