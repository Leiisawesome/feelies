"""Trading intent translator — Signal x Position -> OrderAction.

Bridges the gap between a stateless signal ("the market looks long")
and a stateful trading action ("given my current position, here's
what I need to do").  The signal engine is pure and position-unaware;
the intent translator injects position awareness.

The orchestrator calls the translator between M4 (signal evaluate)
and M6 (order decision).  The translator determines whether to
enter, exit, reverse, scale up, or do nothing.

Invariants preserved:
  - Inv 5 (deterministic): same signal + position → same intent
  - Inv 8 (layer separation): translator is injectable, not embedded
    in the orchestrator
  - Inv 11 (fail-safe): unknown states → NO_ACTION
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

from feelies.core.events import Signal, SignalDirection
from feelies.portfolio.position_store import Position


class TradingIntent(Enum):
    ENTRY_LONG = auto()
    ENTRY_SHORT = auto()
    EXIT = auto()
    REVERSE_LONG_TO_SHORT = auto()
    REVERSE_SHORT_TO_LONG = auto()
    SCALE_UP = auto()
    NO_ACTION = auto()


@dataclass(frozen=True, kw_only=True)
class OrderIntent:
    """Computed trading action from signal + current position."""

    intent: TradingIntent
    symbol: str
    strategy_id: str
    target_quantity: int
    current_quantity: int
    signal: Signal


class IntentTranslator(Protocol):
    """Maps a signal and current position to a concrete trading intent."""

    def translate(
        self,
        signal: Signal,
        position: Position,
        target_quantity: int | None = None,
    ) -> OrderIntent:
        """Determine trading action from signal direction + current position.

        ``target_quantity`` overrides the default sizing when provided
        (typically computed by a PositionSizer).  When None, the
        implementation falls back to its own default.

        The returned ``target_quantity`` in OrderIntent is unsigned
        (absolute shares to trade).  The caller derives ``Side``
        from the ``TradingIntent`` enum.
        """
        ...


class SignalPositionTranslator:
    """Default intent translator using the signal x position matrix.

    | Signal    | Position  | Intent                  | Quantity            |
    |-----------|-----------|-------------------------|---------------------|
    | LONG      | 0         | ENTRY_LONG              | target_qty          |
    | LONG      | +N (>=tgt)| NO_ACTION               | 0                   |
    | LONG      | +N (<tgt) | SCALE_UP                | target_qty - N      |
    | LONG      | -N        | REVERSE_SHORT_TO_LONG   | N + target_qty      |
    | SHORT     | 0         | ENTRY_SHORT             | target_qty          |
    | SHORT     | -N (>=tgt)| NO_ACTION               | 0                   |
    | SHORT     | -N (<tgt) | SCALE_UP                | target_qty - |N|    |
    | SHORT     | +N        | REVERSE_LONG_TO_SHORT   | N + target_qty      |
    | FLAT      | +N        | EXIT                    | N                   |
    | FLAT      | -N        | EXIT                    | |N|                 |
    | FLAT      | 0         | NO_ACTION               | 0                   |
    """

    def __init__(self, default_target_quantity: int = 100) -> None:
        self._default_target = default_target_quantity

    def translate(
        self,
        signal: Signal,
        position: Position,
        target_quantity: int | None = None,
    ) -> OrderIntent:
        tgt = target_quantity if target_quantity is not None else self._default_target
        qty = position.quantity

        if signal.direction == SignalDirection.FLAT:
            return self._handle_flat(signal, qty, tgt)
        if signal.direction == SignalDirection.LONG:
            return self._handle_long(signal, qty, tgt)
        if signal.direction == SignalDirection.SHORT:
            return self._handle_short(signal, qty, tgt)

        return OrderIntent(
            intent=TradingIntent.NO_ACTION,
            symbol=signal.symbol,
            strategy_id=signal.strategy_id,
            target_quantity=0,
            current_quantity=qty,
            signal=signal,
        )

    def _handle_flat(self, signal: Signal, qty: int, tgt: int) -> OrderIntent:
        if qty == 0:
            return OrderIntent(
                intent=TradingIntent.NO_ACTION,
                symbol=signal.symbol,
                strategy_id=signal.strategy_id,
                target_quantity=0,
                current_quantity=qty,
                signal=signal,
            )
        return OrderIntent(
            intent=TradingIntent.EXIT,
            symbol=signal.symbol,
            strategy_id=signal.strategy_id,
            target_quantity=abs(qty),
            current_quantity=qty,
            signal=signal,
        )

    def _handle_long(self, signal: Signal, qty: int, tgt: int) -> OrderIntent:
        if qty < 0:
            return OrderIntent(
                intent=TradingIntent.REVERSE_SHORT_TO_LONG,
                symbol=signal.symbol,
                strategy_id=signal.strategy_id,
                target_quantity=abs(qty) + tgt,
                current_quantity=qty,
                signal=signal,
            )
        if qty >= tgt:
            return OrderIntent(
                intent=TradingIntent.NO_ACTION,
                symbol=signal.symbol,
                strategy_id=signal.strategy_id,
                target_quantity=0,
                current_quantity=qty,
                signal=signal,
            )
        if qty > 0:
            return OrderIntent(
                intent=TradingIntent.SCALE_UP,
                symbol=signal.symbol,
                strategy_id=signal.strategy_id,
                target_quantity=tgt - qty,
                current_quantity=qty,
                signal=signal,
            )
        return OrderIntent(
            intent=TradingIntent.ENTRY_LONG,
            symbol=signal.symbol,
            strategy_id=signal.strategy_id,
            target_quantity=tgt,
            current_quantity=qty,
            signal=signal,
        )

    def _handle_short(self, signal: Signal, qty: int, tgt: int) -> OrderIntent:
        if qty > 0:
            return OrderIntent(
                intent=TradingIntent.REVERSE_LONG_TO_SHORT,
                symbol=signal.symbol,
                strategy_id=signal.strategy_id,
                target_quantity=qty + tgt,
                current_quantity=qty,
                signal=signal,
            )
        if qty <= -tgt:
            return OrderIntent(
                intent=TradingIntent.NO_ACTION,
                symbol=signal.symbol,
                strategy_id=signal.strategy_id,
                target_quantity=0,
                current_quantity=qty,
                signal=signal,
            )
        if qty < 0:
            return OrderIntent(
                intent=TradingIntent.SCALE_UP,
                symbol=signal.symbol,
                strategy_id=signal.strategy_id,
                target_quantity=tgt - abs(qty),
                current_quantity=qty,
                signal=signal,
            )
        return OrderIntent(
            intent=TradingIntent.ENTRY_SHORT,
            symbol=signal.symbol,
            strategy_id=signal.strategy_id,
            target_quantity=tgt,
            current_quantity=qty,
            signal=signal,
        )
