from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import Signal, SignalDirection
from feelies.execution.intent import (
    OrderIntent,
    SignalPositionTranslator,
    TradingIntent,
)
from feelies.portfolio.position_store import Position


def _signal(direction: SignalDirection) -> Signal:
    return Signal(
        timestamp_ns=1000,
        correlation_id="test",
        sequence=1,
        symbol="AAPL",
        strategy_id="alpha1",
        direction=direction,
        strength=0.8,
        edge_estimate_bps=5.0,
    )


def _position(quantity: int) -> Position:
    return Position(
        symbol="AAPL",
        quantity=quantity,
        avg_entry_price=Decimal("150.00"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
    )


TARGET = 100


class TestSignalPositionTranslator:
    @pytest.fixture()
    def translator(self) -> SignalPositionTranslator:
        return SignalPositionTranslator(default_target_quantity=TARGET)

    # ── LONG signal ──────────────────────────────────────────────

    def test_long_flat_position_entry(self, translator: SignalPositionTranslator):
        result = translator.translate(_signal(SignalDirection.LONG), _position(0), TARGET)
        assert result.intent == TradingIntent.ENTRY_LONG
        assert result.target_quantity == TARGET

    def test_long_at_target_no_action(self, translator: SignalPositionTranslator):
        result = translator.translate(_signal(SignalDirection.LONG), _position(100), TARGET)
        assert result.intent == TradingIntent.NO_ACTION
        assert result.target_quantity == 0

    def test_long_above_target_no_action(self, translator: SignalPositionTranslator):
        result = translator.translate(_signal(SignalDirection.LONG), _position(150), TARGET)
        assert result.intent == TradingIntent.NO_ACTION
        assert result.target_quantity == 0

    def test_long_partial_position_scale_up(self, translator: SignalPositionTranslator):
        result = translator.translate(_signal(SignalDirection.LONG), _position(40), TARGET)
        assert result.intent == TradingIntent.SCALE_UP
        assert result.target_quantity == 60

    def test_long_short_position_reverse(self, translator: SignalPositionTranslator):
        result = translator.translate(_signal(SignalDirection.LONG), _position(-50), TARGET)
        assert result.intent == TradingIntent.REVERSE_SHORT_TO_LONG
        assert result.target_quantity == 150  # 50 + 100

    # ── SHORT signal ─────────────────────────────────────────────

    def test_short_flat_position_entry(self, translator: SignalPositionTranslator):
        result = translator.translate(_signal(SignalDirection.SHORT), _position(0), TARGET)
        assert result.intent == TradingIntent.ENTRY_SHORT
        assert result.target_quantity == TARGET

    def test_short_at_target_no_action(self, translator: SignalPositionTranslator):
        result = translator.translate(_signal(SignalDirection.SHORT), _position(-100), TARGET)
        assert result.intent == TradingIntent.NO_ACTION
        assert result.target_quantity == 0

    def test_short_beyond_target_no_action(self, translator: SignalPositionTranslator):
        result = translator.translate(_signal(SignalDirection.SHORT), _position(-150), TARGET)
        assert result.intent == TradingIntent.NO_ACTION
        assert result.target_quantity == 0

    def test_short_partial_position_scale_up(self, translator: SignalPositionTranslator):
        result = translator.translate(_signal(SignalDirection.SHORT), _position(-30), TARGET)
        assert result.intent == TradingIntent.SCALE_UP
        assert result.target_quantity == 70  # 100 - 30

    def test_short_long_position_reverse(self, translator: SignalPositionTranslator):
        result = translator.translate(_signal(SignalDirection.SHORT), _position(60), TARGET)
        assert result.intent == TradingIntent.REVERSE_LONG_TO_SHORT
        assert result.target_quantity == 160  # 60 + 100

    # ── FLAT signal ──────────────────────────────────────────────

    def test_flat_long_position_exit(self, translator: SignalPositionTranslator):
        result = translator.translate(_signal(SignalDirection.FLAT), _position(75), TARGET)
        assert result.intent == TradingIntent.EXIT
        assert result.target_quantity == 75

    def test_flat_short_position_exit(self, translator: SignalPositionTranslator):
        result = translator.translate(_signal(SignalDirection.FLAT), _position(-80), TARGET)
        assert result.intent == TradingIntent.EXIT
        assert result.target_quantity == 80

    def test_flat_no_position_no_action(self, translator: SignalPositionTranslator):
        result = translator.translate(_signal(SignalDirection.FLAT), _position(0), TARGET)
        assert result.intent == TradingIntent.NO_ACTION
        assert result.target_quantity == 0

    # ── Default target quantity ──────────────────────────────────

    def test_none_target_uses_default(self, translator: SignalPositionTranslator):
        result = translator.translate(_signal(SignalDirection.LONG), _position(0), None)
        assert result.intent == TradingIntent.ENTRY_LONG
        assert result.target_quantity == TARGET

    # ── Common fields ────────────────────────────────────────────

    def test_result_carries_symbol_and_strategy(self, translator: SignalPositionTranslator):
        sig = _signal(SignalDirection.LONG)
        result = translator.translate(sig, _position(0), TARGET)
        assert result.symbol == "AAPL"
        assert result.strategy_id == "alpha1"
        assert result.signal is sig
        assert result.current_quantity == 0
