"""Trade journal protocol — structured trade lifecycle records.

Distinct from EventLog: the event log is an append-only stream of
all raw events; the trade journal is a structured, queryable record
of completed trade lifecycles with computed fields (slippage, fees,
PnL per trade).

Every trade is traceable through ``correlation_id`` to its signal, risk
verdict, and fills.
"""

from __future__ import annotations

from typing import Iterator, Protocol

from feelies.core.trade_journal import TradeRecord as TradeRecord


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
