"""Trade journal protocol — structured trade lifecycle records.

Distinct from EventLog: the event log is an append-only stream of
all raw events; the trade journal is a structured, queryable record
of completed trade lifecycles with computed fields (slippage, fees,
PnL per trade).

Supports audit (invariant 13) and post-trade forensics.  Every
trade is traceable to the signal, risk verdict, and fill events
that produced it via correlation_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterator, Protocol

from feelies.core.events import Side


@dataclass(frozen=True, kw_only=True)
class TradeRecord:
    """Complete lifecycle record for a single trade.

    Captures the full decision chain from signal through fill,
    with computed execution quality fields.

    ``realized_pnl`` is **per-trade differential** — the PnL realized
    by this specific fill only.  Computed as the change in the
    position's cumulative realized PnL across this fill.  Contrast
    with ``PositionUpdate.realized_pnl``, which is cumulative.
    """

    order_id: str
    symbol: str
    strategy_id: str
    side: Side
    requested_quantity: int
    filled_quantity: int
    fill_price: Decimal | None
    signal_timestamp_ns: int
    submit_timestamp_ns: int
    fill_timestamp_ns: int | None
    cost_bps: Decimal
    fees: Decimal
    realized_pnl: Decimal
    correlation_id: str
    metadata: dict[str, str] = field(default_factory=dict)


class TradeJournal(Protocol):
    """Structured, queryable trade lifecycle store.

    Failure mode: degrade.  If journal write fails, the event log
    still has the raw events — the journal can be rebuilt from it.
    Journal unavailability does not halt trading.
    """

    def record(self, trade: TradeRecord) -> None:
        """Record a completed trade.  Must be durable before returning."""
        ...

    def query(
        self,
        *,
        symbol: str | None = None,
        strategy_id: str | None = None,
        start_ns: int | None = None,
        end_ns: int | None = None,
    ) -> Iterator[TradeRecord]:
        """Query trade records with optional filters.

        Results ordered by fill_timestamp_ns ascending.
        """
        ...
