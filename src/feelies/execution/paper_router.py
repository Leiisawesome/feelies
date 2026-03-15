"""Paper order router — stub for paper trading mode.

Implements the ``OrderRouter`` protocol for paper trading with
simulated fills against live market data.  Not yet implemented.
"""

from __future__ import annotations

from feelies.core.events import OrderAck, OrderRequest


class PaperOrderRouter:
    """Paper trading order router (stub).

    Will simulate fills using live market data without placing
    real orders.  Tracks virtual positions and PnL.
    """

    def submit(self, request: OrderRequest) -> None:
        raise NotImplementedError(
            "PaperOrderRouter is not yet implemented. "
            "See live-execution skill for the specification."
        )

    def poll_acks(self) -> list[OrderAck]:
        raise NotImplementedError(
            "PaperOrderRouter is not yet implemented."
        )
