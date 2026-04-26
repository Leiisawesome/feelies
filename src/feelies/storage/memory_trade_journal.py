"""In-memory trade journal for backtesting and testing.

Implements the ``TradeJournal`` protocol with a simple list store.
Not durable — data is lost on process exit.  Suitable for backtest
mode where trade records are consumed within the same process.
"""

from __future__ import annotations

from typing import Iterator

from feelies.storage.trade_journal import TradeRecord


class InMemoryTradeJournal:
    """In-memory TradeJournal implementation."""

    def __init__(self) -> None:
        self._records: list[TradeRecord] = []

    def record(self, trade: TradeRecord) -> None:
        self._records.append(trade)

    def query(
        self,
        *,
        symbol: str | None = None,
        strategy_id: str | None = None,
        start_ns: int | None = None,
        end_ns: int | None = None,
    ) -> Iterator[TradeRecord]:
        def _ts(r: TradeRecord) -> float:
            return float(r.fill_timestamp_ns) if r.fill_timestamp_ns is not None else float("inf")

        for rec in sorted(self._records, key=_ts):
            if symbol is not None and rec.symbol != symbol:
                continue
            if strategy_id is not None and rec.strategy_id != strategy_id:
                continue
            ts = _ts(rec)
            if start_ns is not None and ts < start_ns:
                continue
            if end_ns is not None and ts > end_ns:
                continue
            yield rec

    def __len__(self) -> int:
        return len(self._records)
