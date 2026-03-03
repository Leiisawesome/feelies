"""ExecutionBackend — the ONLY mode-specific abstraction (invariant 9).

If any logic branches on "if live then..." outside of ExecutionBackend
implementations, the architecture is broken.

Mode-specific behavior is confined to two interfaces:
  - MarketDataSource: historical replay (backtest) vs live feed
  - OrderRouter: simulated fills (backtest) vs broker API (live)

Section VIII of the system diagram: the micro-state machine is identical
across BACKTEST_MODE, PAPER_TRADING_MODE, and LIVE_TRADING_MODE.
Only the source of MARKET_EVENT and ORDER_ACK differs.
"""

from __future__ import annotations

from typing import Iterator, Protocol

from feelies.core.events import NBBOQuote, OrderAck, OrderRequest, Trade


class MarketDataSource(Protocol):
    """Provides market events — historical replay or live feed.

    Yields both NBBO quotes and trade prints in timestamp order.
    The orchestrator dispatches by type: quotes drive the full
    signal pipeline; trades are logged and published for
    observability and feature computation.
    """

    def events(self) -> Iterator[NBBOQuote | Trade]:
        """Yield market events in timestamp order."""
        ...


class OrderRouter(Protocol):
    """Routes orders and returns acknowledgements.

    Backtest: simulated fill model.
    Paper: broker sandbox.
    Live: real broker API.
    """

    def submit(self, request: OrderRequest) -> None:
        """Submit an order.  Acknowledgement arrives via poll_acks()."""
        ...

    def poll_acks(self) -> list[OrderAck]:
        """Collect any pending order acknowledgements since last poll."""
        ...


class ExecutionBackend:
    """Facade over mode-specific data source and order router.

    The orchestrator interacts with this facade exclusively.
    It does not know whether it is in backtest, paper, or live mode.
    """

    __slots__ = ("market_data", "order_router", "mode")

    def __init__(
        self,
        market_data: MarketDataSource,
        order_router: OrderRouter,
        mode: str,
    ) -> None:
        self.market_data = market_data
        self.order_router = order_router
        self.mode = mode
