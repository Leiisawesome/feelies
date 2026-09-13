"""ExecutionBackend protocol.

The Protocol lives in core so kernel can name it without importing
the execution package. The concrete facade stays in execution.backend.
"""

from __future__ import annotations

from typing import Iterator, Protocol

from feelies.core.events import NBBOQuote, OrderAck, OrderRequest, Trade


class _ExecutionMarketData(Protocol):
    """Kernel names events()."""

    def events(self) -> Iterator[NBBOQuote | Trade | object]:
        """Yield market events (and idle sentinels) in timestamp order."""
        ...


class _ExecutionOrderRouter(Protocol):
    """Kernel names submit; poll_acks is used by a helper until T-08d."""

    def submit(
        self,
        request: OrderRequest,
        triggering_quote: NBBOQuote | None = None,
    ) -> None:
        """Submit an order.  Acknowledgement arrives via poll_acks()."""
        ...

    def poll_acks(self) -> list[OrderAck]:
        """Collect any pending order acknowledgements since last poll."""
        ...


class ExecutionBackend(Protocol):
    """Facade over mode-specific data source and order router.

    Kernel names market_data.events and order_router.submit.
    cancel_order and on_trade stay getattr.
    """

    market_data: _ExecutionMarketData
    order_router: _ExecutionOrderRouter
