"""Market data normalizer protocol — the ingestion layer's core contract.

Transforms raw feed data from external sources (Polygon.io WebSocket,
REST) into validated canonical events (NBBOQuote, Trade).  Assigns
correlation IDs at the system boundary.  Validates data integrity:
detects gaps, duplicates, and schema violations.  Drives per-symbol
DataHealth state machines.

Uses Protocol (structural subtyping) so that implementations for
different feed sources need not inherit from this module.

This protocol is the system boundary — all market data enters the
platform through it.  Upstream of the normalizer is external;
downstream is canonical.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from feelies.core.events import NBBOQuote, Trade
from feelies.ingestion.data_integrity import DataHealth


class MarketDataNormalizer(Protocol):
    """Transforms raw feed data into validated canonical market events.

    Responsibilities:
      - Parse raw wire-format data into typed NBBOQuote / Trade events
      - Assign correlation IDs at the ingestion boundary (invariant 13)
      - Validate timestamp monotonicity and field integrity
      - Detect gaps, duplicates, and corrupted messages
      - Track per-symbol DataHealth state

    Failure mode: degrade.  Parse errors and corrupt messages are
    filtered (returned as empty list) and surfaced via DataHealth
    transitions and metric events — never silently consumed, never
    crash the pipeline.
    """

    def on_message(
        self,
        raw: bytes,
        received_ns: int,
        source: str,
    ) -> Sequence[NBBOQuote | Trade]:
        """Normalize a raw feed message into canonical events.

        Args:
            raw: Raw message bytes from the feed.
            received_ns: Nanosecond timestamp when the message was
                received (from injectable clock, not wall time).
            source: Feed identifier (e.g., ``"polygon_ws"``).

        Returns:
            Zero or more canonical events.  Empty if the message is
            filtered (duplicate, corrupt, non-market-data).
        """
        ...

    def health(self, symbol: str) -> DataHealth:
        """Current data integrity state for a symbol."""
        ...

    def all_health(self) -> dict[str, DataHealth]:
        """Data integrity state for all tracked symbols."""
        ...
