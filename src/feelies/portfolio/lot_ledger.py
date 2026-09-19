"""Per-symbol FIFO open-lot ledger for observability.

The position store (`MemoryPositionStore`) keeps a single **average-cost**
``avg_entry_price`` and realizes PnL against it.  That is the parity-bearing
book and is intentionally left unchanged.  This ledger sits *beside* it and
tracks the individual open lots (price, open timestamp, originating
strategy/intent) with **FIFO** matching, giving:

  - per-lot holding age (the oldest open lot, FIFO front),
  - per-lot strategy/intent provenance,
  - an honest **FIFO realized PnL** view, distinct from the average-cost
    realized PnL the position store reports.

It is pure observability: it publishes nothing, touches no position/journal,
and is never read by the parity hash, so maintaining it is parity-neutral.
FIFO and average-cost realized PnL legitimately differ on partial reduces —
that difference is the point (honest per-lot accounting), not a bug.
"""

from __future__ import annotations

from feelies.core.lot_ledger import (
    Lot as Lot,
    LotLedger as LotLedger,
    _same_sign as _same_sign,
)
