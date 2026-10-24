"""Two resting orders at one level share one drain draw.

Front is the earlier order. Both are drain-eligible on the same quotes
(queue ahead is zero, so the hazard is the book hazard, not a queue
gate). Whenever the back order drain-fills on an event, the front order
must have drain-filled on that event. ``ticks_at_level`` is per-order
state and ``order_id`` is per-order identity, so a seed that includes
either of them can fill the back order while the front order is still
resting.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, OrderAckStatus, OrderRequest, OrderType, Side
from feelies.execution.cost_model import ZeroCostModel
from feelies.execution.passive_limit_router import PassiveLimitOrderRouter

_N_EVENTS = 1000
_FRONT = "front"
_BACK = "back"


def _quote(index: int) -> NBBOQuote:
    ts = 1_000_000_000 + index * 1_000_000
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"AAPL:{ts}:{index}",
        sequence=index,
        symbol="AAPL",
        bid=Decimal("150.00"),
        ask=Decimal("150.02"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts,
        sequence_number=50_000 + index,
    )


def _limit(order_id: str, sequence: int) -> OrderRequest:
    return OrderRequest(
        timestamp_ns=1,
        correlation_id="pair",
        sequence=sequence,
        order_id=order_id,
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        limit_price=Decimal("150.00"),
    )


def drain_violations(n_events: int = _N_EVENTS) -> int:
    """Count events where the back order drain-fills and the front does not."""
    clock = SimulatedClock(start_ns=1)
    router = PassiveLimitOrderRouter(
        clock,
        cost_model=ZeroCostModel(),
        latency_ns=0,
        fill_delay_ticks=1,
        fill_hazard_max=Decimal("0.5"),
        queue_position_shares=0,
    )
    violations = 0
    for index in range(n_events):
        front_id = f"{_FRONT}-{index}"
        back_id = f"{_BACK}-{index}"
        book = _quote(index * 2)
        clock.set_time(book.timestamp_ns)
        router.on_quote(book)
        router.submit(_limit(front_id, index * 2))
        router.submit(_limit(back_id, index * 2 + 1))
        router.poll_acks()
        assert front_id in router._resting_orders
        assert back_id in router._resting_orders
        trial = _quote(index * 2 + 1)
        clock.set_time(trial.timestamp_ns)
        router.on_quote(trial)
        filled = {
            ack.order_id
            for ack in router.poll_acks()
            if ack.status == OrderAckStatus.FILLED and ack.reason == "FILLED_BY_DRAIN"
        }
        if back_id in filled and front_id not in filled:
            violations += 1
        router.cancel_order(front_id)
        router.cancel_order(back_id)
        router.poll_acks()
    return violations


def test_back_order_does_not_drain_ahead_of_the_front_order() -> None:
    violations = drain_violations()
    assert violations == 0, (
        f"back order drain-filled ahead of the front order on {violations} of {_N_EVENTS} events"
    )
