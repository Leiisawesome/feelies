"""Unit tests for IBOrderRouter MARKET order mapping."""

from __future__ import annotations

from feelies.broker.ib.router import IBOrderRouter
from feelies.core.clock import WallClock
from feelies.core.events import OrderRequest, OrderType, Side


class _Conn:
    def next_order_id(self) -> int:
        return 1

    def enqueue_order(self, ib_order_id: int, contract: object, order: object) -> None:
        self.last_order = order


def test_market_order_maps_to_mkt_without_limit_price() -> None:
    conn = _Conn()
    router = IBOrderRouter(connection=conn, clock=WallClock())  # type: ignore[arg-type]
    req = OrderRequest(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        order_id="mkt-1",
        symbol="SPY",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=1,
        strategy_id="test",
    )
    router.submit(req)
    order = conn.last_order
    assert order.orderType == "MKT"
