"""Reg-T buying-power limits for margin accounts.

Only ``margin_25k`` is implemented: **4× intraday** and **2× overnight**
multipliers on live NAV (initial equity + realized − fees + unrealized).
``margin_under_25k`` and ``cash`` are reserved for future work.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, auto

# Stable reject token consumed by the risk engine and acceptance tests.
INSUFFICIENT_BUYING_POWER = "INSUFFICIENT_BUYING_POWER"


class BuyingPowerPhase(Enum):
    """Reg-T phase controlling the equity multiplier."""

    INTRADAY = auto()
    OVERNIGHT = auto()


@dataclass(frozen=True, kw_only=True)
class BuyingPowerConfig:
    """Buying-power policy for a single account type."""

    account_type: str
    intraday_multiplier: Decimal = Decimal("4")
    overnight_multiplier: Decimal = Decimal("2")

    def __post_init__(self) -> None:
        if self.account_type != "margin_25k":
            raise NotImplementedError(
                f"buying_power for account_type={self.account_type!r} is not "
                "implemented; only 'margin_25k' is wired (BT-15)."
            )
        if self.intraday_multiplier <= 0 or self.overnight_multiplier <= 0:
            raise ValueError("buying-power multipliers must be positive")


def buying_power_limit(
    equity: Decimal,
    phase: BuyingPowerPhase,
    config: BuyingPowerConfig,
) -> Decimal:
    """Maximum gross exposure permitted under Reg-T for ``equity``."""
    if equity <= 0:
        return Decimal("0")
    multiplier = (
        config.intraday_multiplier
        if phase is BuyingPowerPhase.INTRADAY
        else config.overnight_multiplier
    )
    return equity * multiplier


__all__ = [
    "INSUFFICIENT_BUYING_POWER",
    "BuyingPowerConfig",
    "BuyingPowerPhase",
    "buying_power_limit",
]
