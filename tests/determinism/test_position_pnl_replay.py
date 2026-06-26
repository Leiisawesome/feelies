"""PnL baseline — ``PositionUpdate`` replay parity (determinism-audit P1 #5).

Inv-5 promises "same event log + params → bit-identical signals, **orders,
PnL**", but no locked baseline reached PnL: the ``market_fill_acks`` baseline
pins fill *economics* (``fill_price`` / ``fees`` / ``cost_bps``) and stops at
the ``OrderAck``; nothing pinned the position/PnL reconciliation downstream.

This baseline closes that gap.  It drives a deterministic fill + mark
sequence through :class:`MemoryPositionStore` — the FIFO cost-basis engine
the backtest path uses — and hashes the ``PositionUpdate`` stream the
orchestrator emits from the resulting :class:`Position` (the field mapping
mirrors ``orchestrator.py`` exactly: ``avg_price`` ← ``avg_entry_price``,
``cost_bps`` ← the fill's disclosed cost).  The scenario exercises every PnL
branch:

* open long, add to long (weighted-average entry),
* partial close (realized PnL on a long reduce),
* open short, cover short (realized PnL on a short close),
* a sign-flip fill (close-through + re-open on the opposite side),
* long and short mark-to-market (spread-aware: longs mark to bid, shorts to
  ask).

Decimal fields are serialized at fixed precision so the hash is invariant to
the working Decimal context's trailing-digit choices while still flipping on
any cent-level PnL drift.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from feelies.core.events import PositionUpdate
from feelies.core.identifiers import SequenceGenerator
from feelies.portfolio.memory_position_store import MemoryPositionStore


@dataclass(frozen=True)
class _Fill:
    symbol: str
    qty_delta: int
    fill_price: Decimal
    fees: Decimal
    cost_bps: Decimal


@dataclass(frozen=True)
class _Mark:
    symbol: str
    bid: Decimal
    ask: Decimal


def _d(value: str) -> Decimal:
    return Decimal(value)


# Deterministic fill/mark script.  Clean numbers so the cost-basis divisions
# terminate; marks precede the fills that should reflect them so each emitted
# snapshot carries a non-trivial unrealized PnL.
_SCENARIO: tuple[_Fill | _Mark, ...] = (
    _Fill("AAPL", 100, _d("180.00"), _d("1.00"), _d("1.5")),
    _Mark("AAPL", _d("184.00"), _d("184.10")),
    _Fill("AAPL", 100, _d("184.00"), _d("1.00"), _d("1.5")),  # avg → 182.00
    _Fill("AAPL", -50, _d("190.00"), _d("0.50"), _d("2.0")),  # realized += 400
    _Mark("AAPL", _d("188.00"), _d("188.10")),
    _Fill("MSFT", -100, _d("370.00"), _d("1.00"), _d("1.5")),  # open short
    _Mark("MSFT", _d("365.90"), _d("366.00")),
    _Fill("MSFT", 100, _d("366.00"), _d("1.00"), _d("1.5")),  # cover, realized += 400
    _Fill("AAPL", -200, _d("191.00"), _d("2.00"), _d("2.5")),  # close 150 + flip short 50
)


def _hash_position_stream(updates: list[PositionUpdate]) -> str:
    lines: list[str] = []
    for u in updates:
        lines.append(
            f"{u.sequence}|{u.symbol}|{u.quantity}|"
            f"{u.avg_price:.6f}|{u.realized_pnl:.6f}|{u.unrealized_pnl:.6f}|"
            f"{u.cumulative_fees:.6f}|{u.cost_bps:.6f}|{u.timestamp_ns}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _replay() -> tuple[str, int]:
    store = MemoryPositionStore()
    seq = SequenceGenerator()
    base_ts = 1_700_000_000_000_000_000
    updates: list[PositionUpdate] = []
    for step, event in enumerate(_SCENARIO):
        ts = base_ts + step * 1_000_000_000
        if isinstance(event, _Mark):
            store.update_mark(
                event.symbol, (event.bid + event.ask) / 2, bid=event.bid, ask=event.ask
            )
            continue
        pos = store.update(
            symbol=event.symbol,
            quantity_delta=event.qty_delta,
            fill_price=event.fill_price,
            fees=event.fees,
            timestamp_ns=ts,
        )
        # Mirror orchestrator.py's PositionUpdate construction.
        updates.append(
            PositionUpdate(
                timestamp_ns=ts,
                correlation_id=f"fill:{event.symbol}:{step}",
                sequence=seq.next(),
                symbol=event.symbol,
                quantity=pos.quantity,
                avg_price=pos.avg_entry_price,
                realized_pnl=pos.realized_pnl,
                unrealized_pnl=pos.unrealized_pnl,
                cumulative_fees=pos.cumulative_fees,
                cost_bps=event.cost_bps,
            )
        )
    return _hash_position_stream(updates), len(updates)


# Locked PnL baseline.  Re-baseline only with an intentional change to the
# MemoryPositionStore cost-basis math, justified in the commit message.
EXPECTED_POSITION_PNL_HASH = "7add366c6db014c0d20d0c4900f3bf192ab20d96738a0d28670ba003afdd6a05"
EXPECTED_POSITION_PNL_COUNT = 6


def test_position_pnl_stream_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay()
    assert actual_count == EXPECTED_POSITION_PNL_COUNT, (
        f"PositionUpdate count drift: expected {EXPECTED_POSITION_PNL_COUNT}, got {actual_count}"
    )
    assert actual_hash == EXPECTED_POSITION_PNL_HASH, (
        "PnL (PositionUpdate) hash drift!\n"
        f"  Expected: {EXPECTED_POSITION_PNL_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional (cost-basis / PnL change), update the constant in the "
        "same commit and justify in the commit message."
    )


def test_two_replays_produce_identical_pnl_hash() -> None:
    hash_a, count_a = _replay()
    hash_b, count_b = _replay()
    assert count_a == count_b
    assert hash_a == hash_b


def test_realized_and_unrealized_pnl_are_nonzero_somewhere() -> None:
    """Guard against a vacuous baseline: the scenario must exercise PnL."""
    store = MemoryPositionStore()
    saw_realized = False
    saw_unrealized = False
    base_ts = 1_700_000_000_000_000_000
    for step, event in enumerate(_SCENARIO):
        if isinstance(event, _Mark):
            store.update_mark(
                event.symbol, (event.bid + event.ask) / 2, bid=event.bid, ask=event.ask
            )
            continue
        pos = store.update(
            symbol=event.symbol,
            quantity_delta=event.qty_delta,
            fill_price=event.fill_price,
            fees=event.fees,
            timestamp_ns=base_ts + step * 1_000_000_000,
        )
        saw_realized = saw_realized or pos.realized_pnl != 0
        saw_unrealized = saw_unrealized or pos.unrealized_pnl != 0
    assert saw_realized, "scenario never realized PnL — not a meaningful baseline"
    assert saw_unrealized, "scenario never marked an open position — unrealized PnL unpinned"
