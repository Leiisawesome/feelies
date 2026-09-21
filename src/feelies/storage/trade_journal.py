"""Trade journal protocol — structured trade lifecycle records.

Distinct from EventLog: the event log is an append-only stream of
all raw events; the trade journal is a structured, queryable record
of completed trade lifecycles with computed fields (slippage, fees,
PnL per trade).

Every trade is traceable through ``correlation_id`` to its signal, risk
verdict, and fills.
"""

from __future__ import annotations

from feelies.core.trade_journal import TradeJournal as TradeJournal
from feelies.core.trade_journal import TradeRecord as TradeRecord
