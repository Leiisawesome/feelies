"""Reg NMS tick-size grid for simulated US equity prices (BT-14).

Sub-penny rule (simplified for the backtest book):
  - prices >= ``$1.00`` → ``$0.01`` minimum increment
  - prices < ``$1.00`` → ``$0.0001`` minimum increment

Taker fills snap *against* the trader (no invented price improvement):
  - BUY → round up (ceil to tick)
  - SELL → round down (floor to tick)

Resting LIMIT prices snap to the nearest valid tick on the passive side:
  - BUY limit → floor (cannot bid above a valid tick in sub-penny territory)
  - SELL limit → ceil
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from feelies.core.events import Side

_ONE_DOLLAR = Decimal("1")
_PENNY_TICK = Decimal("0.01")
_SUBPENNY_TICK = Decimal("0.0001")


def tick_size(price: Decimal) -> Decimal:
    """Minimum price increment for ``price`` under the Reg NMS sub-penny rule."""
    if price >= _ONE_DOLLAR:
        return _PENNY_TICK
    return _SUBPENNY_TICK


def snap_fill_price(side: Side, price: Decimal) -> Decimal:
    """Snap a simulated *fill* price conservatively for the taker."""
    tick = tick_size(price)
    rounding = ROUND_CEILING if side == Side.BUY else ROUND_FLOOR
    return price.quantize(tick, rounding=rounding)


def snap_limit_price(side: Side, price: Decimal) -> Decimal:
    """Snap a resting *limit* price to a valid tick."""
    tick = tick_size(price)
    rounding = ROUND_FLOOR if side == Side.BUY else ROUND_CEILING
    return price.quantize(tick, rounding=rounding)


def is_on_tick_grid(price: Decimal) -> bool:
    """Return True when ``price`` is an integer multiple of its tick size."""
    tick = tick_size(price)
    return price == price.quantize(tick)


__all__ = [
    "is_on_tick_grid",
    "snap_fill_price",
    "snap_limit_price",
    "tick_size",
]
