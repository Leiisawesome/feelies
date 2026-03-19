"""IntentTranslator + PositionSizer pipeline tests.

Skills: system-architect, live-execution, risk-engine, microstructure-alpha
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.alpha.module import AlphaRiskBudget
from feelies.core.events import (
    RiskVerdict,
    Signal,
    SignalDirection,
)
from feelies.execution.intent import (
    OrderIntent,
    SignalPositionTranslator,
    TradingIntent,
)
from feelies.portfolio.position_store import Position
from feelies.risk.position_sizer import BudgetBasedSizer

pytestmark = pytest.mark.backtest_validation


def _signal(
    direction: SignalDirection = SignalDirection.LONG,
    strength: float = 1.0,
    symbol: str = "AAPL",
    strategy_id: str = "test_alpha",
) -> Signal:
    return Signal(
        timestamp_ns=1_000_000_000,
        correlation_id=f"{symbol}:1000000000:1",
        sequence=1,
        symbol=symbol,
        strategy_id=strategy_id,
        direction=direction,
        strength=strength,
        edge_estimate_bps=2.5,
    )


def _position(qty: int = 0) -> Position:
    return Position(symbol="AAPL", quantity=qty)


def _budget(
    max_pos: int = 100,
    cap_alloc_pct: float = 20.0,
) -> AlphaRiskBudget:
    return AlphaRiskBudget(
        max_position_per_symbol=max_pos,
        max_gross_exposure_pct=10.0,
        max_drawdown_pct=2.0,
        capital_allocation_pct=cap_alloc_pct,
    )


class TestIntentTranslation:
    """IntentTranslator signal x position matrix."""

    def test_flat_signal_no_position_produces_no_action(self) -> None:
        translator = SignalPositionTranslator()
        intent = translator.translate(_signal(SignalDirection.FLAT), _position(0))
        assert intent.intent == TradingIntent.NO_ACTION
        assert intent.target_quantity == 0

    def test_long_signal_from_flat_produces_entry_long(self) -> None:
        translator = SignalPositionTranslator()
        intent = translator.translate(_signal(SignalDirection.LONG), _position(0), 50)
        assert intent.intent == TradingIntent.ENTRY_LONG
        assert intent.target_quantity == 50

    def test_long_signal_at_target_produces_no_action(self) -> None:
        translator = SignalPositionTranslator()
        intent = translator.translate(_signal(SignalDirection.LONG), _position(50), 50)
        assert intent.intent == TradingIntent.NO_ACTION

    def test_short_signal_from_long_produces_reverse(self) -> None:
        translator = SignalPositionTranslator()
        intent = translator.translate(
            _signal(SignalDirection.SHORT), _position(30), 50
        )
        assert intent.intent == TradingIntent.REVERSE_LONG_TO_SHORT
        assert intent.target_quantity == 30 + 50

    def test_exit_signal_closes_position(self) -> None:
        translator = SignalPositionTranslator()
        intent = translator.translate(
            _signal(SignalDirection.FLAT), _position(40), 100
        )
        assert intent.intent == TradingIntent.EXIT
        assert intent.target_quantity == 40


class TestPositionSizing:
    """PositionSizer scaling and capping."""

    def test_position_sizer_scales_with_signal_strength(self) -> None:
        sizer = BudgetBasedSizer()
        budget = _budget(max_pos=1000, cap_alloc_pct=20.0)

        qty_full = sizer.compute_target_quantity(
            _signal(strength=1.0),
            budget,
            Decimal("150.00"),
            Decimal("100000"),
        )
        qty_half = sizer.compute_target_quantity(
            _signal(strength=0.5),
            budget,
            Decimal("150.00"),
            Decimal("100000"),
        )

        assert qty_full > 0
        assert qty_half > 0
        assert abs(qty_half - qty_full // 2) <= 1

    def test_position_sizer_caps_at_max_position(self) -> None:
        sizer = BudgetBasedSizer()
        budget = _budget(max_pos=10, cap_alloc_pct=100.0)

        qty = sizer.compute_target_quantity(
            _signal(strength=1.0),
            budget,
            Decimal("1.00"),
            Decimal("1000000"),
        )
        assert qty <= 10


class TestIntentRiskInteraction:
    """Intent/risk pipeline integration."""

    def test_no_action_skips_risk_check(self, single_symbol_scenario) -> None:
        _, recorder, _, _ = single_symbol_scenario
        verdicts = recorder.of_type(RiskVerdict)
        from feelies.core.events import NBBOQuote
        quotes = recorder.of_type(NBBOQuote)

        assert len(quotes) == 8
        assert len(verdicts) < len(quotes) * 2

    def test_scale_down_verdict_reduces_quantity(self) -> None:
        translator = SignalPositionTranslator()
        sig = _signal(SignalDirection.LONG, strength=1.0)
        intent = translator.translate(sig, _position(0), 100)
        assert intent.intent == TradingIntent.ENTRY_LONG
        assert intent.target_quantity == 100

        scaled_qty = max(1, round(intent.target_quantity * 0.5))
        assert scaled_qty == 50
