"""Unit tests for reversal intent aggregation.

Covers REVERSE_LONG_TO_SHORT and REVERSE_SHORT_TO_LONG paths in
aggregate_intents(), asserting that sign convention, exit/entry bucket
splitting, and net order sides are all correct.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.alpha.aggregation import aggregate_intents
from feelies.core.events import (
    NBBOQuote,
    Side,
    Signal,
    SignalDirection,
)
from feelies.execution.intent import OrderIntent, TradingIntent


# ── helpers ─────────────────────────────────────────────────────────


def _make_signal(symbol: str = "AAPL") -> Signal:
    return Signal(
        timestamp_ns=1_000,
        correlation_id=f"test:{symbol}",
        sequence=1,
        symbol=symbol,
        strategy_id="test_strat",
        direction=SignalDirection.LONG,
        strength=1.0,
        edge_estimate_bps=5.0,
    )


def _make_intent(
    intent_type: TradingIntent,
    symbol: str = "AAPL",
    target_quantity: int = 100,
    current_quantity: int = 0,
) -> OrderIntent:
    return OrderIntent(
        intent=intent_type,
        symbol=symbol,
        strategy_id="test_strat",
        target_quantity=target_quantity,
        current_quantity=current_quantity,
        signal=_make_signal(symbol),
    )


# ── REVERSE_LONG_TO_SHORT ────────────────────────────────────────────

class TestReverseLongToShort:
    """Long position flipped to short: exit closes the long, entry opens short."""

    def test_exit_bucket_is_sell(self) -> None:
        # current_quantity is signed positive (long 50)
        intent = _make_intent(
            TradingIntent.REVERSE_LONG_TO_SHORT,
            current_quantity=50,
            target_quantity=80,   # 50 exit + 30 entry short
        )
        result = aggregate_intents((intent,))
        agg = result["AAPL"]

        # Exit closes the long → SELL
        assert agg.exit_order is not None
        exit_side, exit_qty = agg.exit_order
        assert exit_side == Side.SELL
        assert exit_qty == 50  # abs(current_quantity)

    def test_entry_bucket_is_sell(self) -> None:
        intent = _make_intent(
            TradingIntent.REVERSE_LONG_TO_SHORT,
            current_quantity=50,
            target_quantity=80,
        )
        result = aggregate_intents((intent,))
        agg = result["AAPL"]

        # Entry opens new short → SELL
        assert agg.entry_order is not None
        entry_side, entry_qty = agg.entry_order
        assert entry_side == Side.SELL
        assert entry_qty == 30  # target_quantity - current_quantity = 80 - 50

    def test_exact_reversal_no_entry(self) -> None:
        """When target == current the exit closes the position entirely, no entry."""
        intent = _make_intent(
            TradingIntent.REVERSE_LONG_TO_SHORT,
            current_quantity=100,
            target_quantity=100,
        )
        result = aggregate_intents((intent,))
        agg = result["AAPL"]

        assert agg.exit_order is not None
        assert agg.exit_order[0] == Side.SELL
        assert agg.exit_order[1] == 100
        # delta = target - current = 0 → no entry
        assert agg.entry_order is None

    def test_contributing_intents_recorded(self) -> None:
        intent = _make_intent(
            TradingIntent.REVERSE_LONG_TO_SHORT,
            current_quantity=50,
            target_quantity=80,
        )
        result = aggregate_intents((intent,))
        assert intent in result["AAPL"].contributing_intents


# ── REVERSE_SHORT_TO_LONG ────────────────────────────────────────────

class TestReverseShortToLong:
    """Short position flipped to long: exit closes the short, entry opens long."""

    def test_exit_bucket_is_buy(self) -> None:
        # current_quantity is signed negative (short -60).
        # target_quantity = abs(current) + new_long = 60 + 40 = 100 (total to buy).
        intent = _make_intent(
            TradingIntent.REVERSE_SHORT_TO_LONG,
            current_quantity=-60,
            target_quantity=100,   # abs(-60) + 40 new long
        )
        result = aggregate_intents((intent,))
        agg = result["AAPL"]

        assert agg.exit_order is not None
        exit_side, exit_qty = agg.exit_order
        assert exit_side == Side.BUY
        assert exit_qty == 60  # abs(current_quantity)

    def test_entry_bucket_is_buy(self) -> None:
        # target_quantity = abs(current) + new_long = 60 + 40 = 100.
        intent = _make_intent(
            TradingIntent.REVERSE_SHORT_TO_LONG,
            current_quantity=-60,
            target_quantity=100,
        )
        result = aggregate_intents((intent,))
        agg = result["AAPL"]

        # Entry opens new long → BUY 40 (target - abs(current) = 100 - 60)
        assert agg.entry_order is not None
        entry_side, entry_qty = agg.entry_order
        assert entry_side == Side.BUY
        assert entry_qty == 40  # target_quantity - abs(current_quantity)

    def test_exact_reversal_no_entry(self) -> None:
        """When target == abs(current) the exit closes the position, no entry."""
        intent = _make_intent(
            TradingIntent.REVERSE_SHORT_TO_LONG,
            current_quantity=-75,
            target_quantity=75,
        )
        result = aggregate_intents((intent,))
        agg = result["AAPL"]

        assert agg.exit_order is not None
        assert agg.exit_order[0] == Side.BUY
        assert agg.exit_order[1] == 75
        assert agg.entry_order is None

    def test_contributing_intents_recorded(self) -> None:
        intent = _make_intent(
            TradingIntent.REVERSE_SHORT_TO_LONG,
            current_quantity=-60,
            target_quantity=100,
        )
        result = aggregate_intents((intent,))
        assert intent in result["AAPL"].contributing_intents


# ── Multi-alpha netting across reversals ────────────────────────────

class TestReversalNetting:
    """Multiple alpha intents for the same symbol should net correctly."""

    def test_long_to_short_plus_independent_entry_nets(self) -> None:
        """A reversal exit + an independent ENTRY_SHORT should net in exit bucket."""
        reversal = _make_intent(
            TradingIntent.REVERSE_LONG_TO_SHORT,
            current_quantity=40,
            target_quantity=40,  # exit 40, delta = 0
        )
        entry = _make_intent(
            TradingIntent.ENTRY_SHORT,
            current_quantity=0,
            target_quantity=20,
        )
        result = aggregate_intents((reversal, entry))
        agg = result["AAPL"]

        # exit: SELL 40 (from reversal)
        assert agg.exit_order == (Side.SELL, 40)
        # entry: SELL 20 (from ENTRY_SHORT)
        assert agg.entry_order == (Side.SELL, 20)

    def test_opposing_reversals_cancel(self) -> None:
        """A REVERSE_LONG_TO_SHORT and REVERSE_SHORT_TO_LONG of equal size cancel."""
        # REVERSE_LONG_TO_SHORT: current=50 long, no new short entry (tgt=0 ≈ use target=50).
        long_to_short = _make_intent(
            TradingIntent.REVERSE_LONG_TO_SHORT,
            current_quantity=50,
            target_quantity=50,  # 50 + 0 new short: exit 50, entry delta 0
        )
        # REVERSE_SHORT_TO_LONG: current=-50 short, new long=50.
        # target_quantity = abs(-50) + 50 = 100 (total to buy).
        short_to_long = _make_intent(
            TradingIntent.REVERSE_SHORT_TO_LONG,
            current_quantity=-50,
            target_quantity=100,  # abs(50) + 50 new long
        )
        result = aggregate_intents((long_to_short, short_to_long))
        agg = result["AAPL"]

        # exit: SELL 50 + BUY 50 = net 0 → no exit order
        assert agg.exit_order is None
        # entry: SELL 0 + BUY 50 → BUY 50
        assert agg.entry_order == (Side.BUY, 50)
