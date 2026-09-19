"""Reg-T buying-power phase.

The enum lives in core so kernel can name it without importing the
risk package. ``buying_power_limit`` stays in risk.
"""

from __future__ import annotations

from enum import Enum, auto


class BuyingPowerPhase(Enum):
    """Reg-T phase controlling the equity multiplier."""

    INTRADAY = auto()
    OVERNIGHT = auto()
