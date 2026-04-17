"""Live order router — stub for live trading mode.

Implements the ``OrderRouter`` protocol for live trading with
real broker connectivity.  Not yet implemented.
"""

from __future__ import annotations

from feelies.core.events import OrderAck, OrderRequest


class LiveOrderRouter:
    """Live broker order router (stub).

    Will submit orders to a real broker API and reconcile fills.
    Requires idempotent order submission (deterministic order_id
    via SHA-256) and full OrderState SM tracking.

    Construction fails fast: wiring this in any mode before the
    live broker gateway exists is always a bug, not a runtime
    condition to handle later.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "LiveOrderRouter is not yet implemented. "
            "See live-execution skill for the specification."
        )

    def submit(self, request: OrderRequest) -> None:
        raise NotImplementedError(
            "LiveOrderRouter is not yet implemented."
        )

    def poll_acks(self) -> list[OrderAck]:
        raise NotImplementedError(
            "LiveOrderRouter is not yet implemented."
        )
