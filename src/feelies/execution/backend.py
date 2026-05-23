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

from enum import StrEnum
from typing import Iterator, Protocol

from feelies.core.events import NBBOQuote, OrderAck, OrderRequest, Trade
from feelies.ingestion.idle_tick import IdleTick


class ExecutionMode(StrEnum):
    """Typed execution mode.  Subclasses ``str`` so legacy callers that
    compare against ``"BACKTEST"``/``"PAPER"``/``"LIVE"`` continue to work.
    """

    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE = "LIVE"


class MarketDataSource(Protocol):
    """Provides market events — historical replay or live feed.

    Yields NBBO quotes and trade prints in timestamp order.  Live
    feeds may also yield :class:`IdleTick` sentinels when no market
    event has arrived within the feed's internal poll timeout —
    backtest feeds (:class:`ReplayFeed`) never yield ``IdleTick`` and
    return a narrower ``Iterator[NBBOQuote | Trade]`` (a strict
    subtype of the union below, LSP-safe).

    The orchestrator dispatches by type: quotes drive the full
    signal pipeline, trades are logged and published for
    observability and feature computation, ``IdleTick`` triggers the
    async fill drain only (no micro-SM transition).
    """

    def events(self) -> Iterator[NBBOQuote | Trade | IdleTick]:
        """Yield market events (and idle sentinels) in timestamp order."""
        ...


class OrderRouter(Protocol):
    """Routes orders and returns acknowledgements.

    Backtest: simulated fill model.
    Paper: broker sandbox (IB Gateway 4002).
    Live: real broker API.

    Optional, duck-typed method::

        def cancel_order(self, order_id: str) -> bool: ...

    Implementations that support broker-initiated cancel define
    ``cancel_order``.  Absence is explicit (no ``NotImplementedError``);
    the orchestrator resolves cancels locally, emits a
    ``cancel_order_router_unsupported`` WARNING alert, and transitions
    the order SM through ``CANCEL_REQUESTED → CANCELLED`` immediately.
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
        mode: ExecutionMode | str,
    ) -> None:
        self.market_data = market_data
        self.order_router = order_router
        self.mode = ExecutionMode(mode) if not isinstance(mode, ExecutionMode) else mode
