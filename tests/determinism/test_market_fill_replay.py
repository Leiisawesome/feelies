"""Golden fill-replay parity for ``market_fill`` (audit P1.5).

The locked Inv-5 parity baselines in this package hash pre-router event
streams (signals, intents, ``OrderRequest``s) and never route through
``append_market_fill_acks`` — so the aggressive fill model's realized
``OrderAck`` economics (cross price, walk-the-book split, stop slippage,
cost_bps) were previously unlocked in CI.  This module closes that gap: a
scripted MARKET-fill scenario is replayed through
:class:`feelies.execution.backtest_router.BacktestOrderRouter` with the
default cost model, and the resulting ack stream is pinned by SHA-256.

Any change to the default fill economics now fails here and must be
re-baselined in the same commit with a rationale (mirrors the parity-hash
re-baseline workflow).
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    NBBOQuote,
    OrderAck,
    OrderRequest,
    OrderType,
    Side,
)
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.execution.cost_model import DefaultCostModel, DefaultCostModelConfig


def _quote(bid: str, ask: str, bid_size: int, ask_size: int, ts: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id="q",
        sequence=ts,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts,
        sequence_number=ts,
    )


def _order(side: Side, qty: int, oid: str, seq: int, reason: str = "") -> OrderRequest:
    return OrderRequest(
        timestamp_ns=0,
        correlation_id="c",
        sequence=seq,
        order_id=oid,
        symbol="AAPL",
        side=side,
        order_type=OrderType.MARKET,
        quantity=qty,
        reason=reason,
    )


def _replay() -> tuple[str, int]:
    router = BacktestOrderRouter(
        SimulatedClock(start_ns=0),
        cost_model=DefaultCostModel(DefaultCostModelConfig()),
        stop_slippage_half_spreads=Decimal("2.0"),
    )
    acks: list[OrderAck] = []

    # 1. Plain buy/sell within L1 depth.
    router.on_quote(_quote("100.00", "100.10", 500, 500, 1000))
    router.submit(_order(Side.BUY, 100, "o1", 1))
    router.submit(_order(Side.SELL, 100, "o2", 2))
    acks.extend(router.poll_acks())

    # 2. Large buy walks the book (qty 200 > ask depth 50).
    router.on_quote(_quote("99.50", "99.60", 50, 50, 2000))
    router.submit(_order(Side.BUY, 200, "o3", 3))
    acks.extend(router.poll_acks())

    # 3. Forced-exit stop sells into widened spread.
    router.on_quote(_quote("99.40", "99.55", 300, 300, 3000))
    router.submit(_order(Side.SELL, 100, "o4", 4, reason="STOP_EXIT"))
    acks.extend(router.poll_acks())

    return _hash_acks(acks), len(acks)


def _hash_acks(acks: list[OrderAck]) -> str:
    lines = [
        f"{a.order_id}|{a.status.name}|{a.filled_quantity}|{a.fill_price}|"
        f"{a.fees}|{a.cost_bps}|{a.timestamp_ns}"
        for a in acks
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# Locked golden fill-replay baseline (default market-fill economics).
# Count includes the per-order ACKNOWLEDGED acks (Inv-9 parity): o1/o2/o4
# emit ACK + FILLED (2 each); o3 walks the book → ACK + PARTIALLY_FILLED +
# FILLED (3).  2 + 2 + 3 + 2 = 9.
EXPECTED_MARKET_FILL_HASH = "d3a7658b581622f8bc6594e2f346c0c8bd2566d5c5dcd79cfba8cf0e16df174d"
EXPECTED_MARKET_FILL_ACK_COUNT = 9


def test_market_fill_replay_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay()
    assert actual_count == EXPECTED_MARKET_FILL_ACK_COUNT, (
        f"market_fill ack count drift: expected {EXPECTED_MARKET_FILL_ACK_COUNT}, "
        f"got {actual_count}"
    )
    assert actual_hash == EXPECTED_MARKET_FILL_HASH, (
        "Golden market_fill ack-stream hash drift!\n"
        f"  Expected: {EXPECTED_MARKET_FILL_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional (fill-model change), update the constant in the same "
        "commit and justify in the commit message."
    )


def test_market_fill_replay_is_deterministic() -> None:
    hash_a, count_a = _replay()
    hash_b, count_b = _replay()
    assert (hash_a, count_a) == (hash_b, count_b)
