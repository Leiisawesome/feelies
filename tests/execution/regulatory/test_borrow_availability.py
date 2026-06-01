"""Unit tests for BT-7 borrow-availability tiers."""

from __future__ import annotations

import pytest

from feelies.core.events import Signal, SignalDirection
from feelies.execution.intent import OrderIntent, TradingIntent
from feelies.execution.regulatory.borrow_availability import (
    BorrowTier,
    build_borrow_table,
    htb_fee_applies,
    is_short_sale_intent,
    parse_borrow_tier,
)


def _intent(
    trading_intent: TradingIntent,
    direction: SignalDirection,
    *,
    current_quantity: int = 0,
) -> OrderIntent:
    sig = Signal(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        strategy_id="s",
        direction=direction,
        strength=0.8,
        edge_estimate_bps=5.0,
    )
    return OrderIntent(
        intent=trading_intent,
        symbol="AAPL",
        strategy_id="s",
        target_quantity=10,
        current_quantity=current_quantity,
        signal=sig,
    )


class TestParseBorrowTier:
    def test_available(self) -> None:
        assert parse_borrow_tier("available") is BorrowTier.AVAILABLE

    def test_hard_case_insensitive(self) -> None:
        assert parse_borrow_tier("HARD") is BorrowTier.HARD

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid borrow tier"):
            parse_borrow_tier("maybe")


class TestBuildBorrowTable:
    def test_normalizes_symbols(self) -> None:
        table = build_borrow_table({"aapl": "available", "xyz": "hard"})
        assert table == {"AAPL": BorrowTier.AVAILABLE, "XYZ": BorrowTier.HARD}


class TestIsShortSaleIntent:
    def test_entry_short(self) -> None:
        assert is_short_sale_intent(
            _intent(TradingIntent.ENTRY_SHORT, SignalDirection.SHORT),
        )

    def test_entry_long_not_short_sale(self) -> None:
        assert not is_short_sale_intent(
            _intent(TradingIntent.ENTRY_LONG, SignalDirection.LONG),
        )

    def test_scale_up_short(self) -> None:
        assert is_short_sale_intent(
            _intent(
                TradingIntent.SCALE_UP,
                SignalDirection.SHORT,
                current_quantity=-50,
            ),
        )


class TestHtbFeeApplies:
    def test_hard_short_sale(self) -> None:
        assert htb_fee_applies(BorrowTier.HARD, True)

    def test_available_short_sale_no_htb(self) -> None:
        assert not htb_fee_applies(BorrowTier.AVAILABLE, True)

    def test_hard_buy_not_htb(self) -> None:
        assert not htb_fee_applies(BorrowTier.HARD, False)
