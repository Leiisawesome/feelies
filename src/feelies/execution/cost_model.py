"""Transaction cost model for backtest fill realism (invariant 12).

Separates cost logic from fill routing so models can be swapped,
stress-tested (1.5x cost, 2x latency), and audited independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from feelies.core.events import Side


class CostModel(Protocol):
    """Computes fees and slippage for a simulated fill."""

    def compute(
        self,
        symbol: str,
        side: Side,
        quantity: int,
        fill_price: Decimal,
    ) -> CostBreakdown:
        """Return cost components for a single fill."""
        ...


@dataclass(frozen=True)
class CostBreakdown:
    """Itemised cost output attached to each fill."""

    spread_cost: Decimal
    commission: Decimal
    total_fees: Decimal
    slippage_bps: Decimal


@dataclass(frozen=True)
class DefaultCostModelConfig:
    """Tunable cost parameters for the default model.

    ``spread_cost_bps``: half-spread crossing cost in basis points.
        The backtest router fills at midpoint; this re-introduces
        the cost of crossing to the bid or ask.
    ``commission_per_share``: flat per-share commission.
    ``min_commission``: minimum commission per order.
    """

    spread_cost_bps: Decimal = Decimal("0.5")
    commission_per_share: Decimal = Decimal("0.005")
    min_commission: Decimal = Decimal("1.00")


class DefaultCostModel:
    """Simple cost model: half-spread + per-share commission."""

    def __init__(self, config: DefaultCostModelConfig | None = None) -> None:
        self._cfg = config or DefaultCostModelConfig()

    def compute(
        self,
        symbol: str,
        side: Side,
        quantity: int,
        fill_price: Decimal,
    ) -> CostBreakdown:
        notional = fill_price * quantity
        spread_cost = notional * self._cfg.spread_cost_bps / Decimal("10000")

        raw_commission = self._cfg.commission_per_share * quantity
        commission = max(raw_commission, self._cfg.min_commission)

        total_fees = spread_cost + commission
        slippage_bps = (
            total_fees / notional * Decimal("10000")
            if notional > 0 else Decimal("0")
        )

        return CostBreakdown(
            spread_cost=spread_cost.quantize(Decimal("0.01")),
            commission=commission.quantize(Decimal("0.01")),
            total_fees=total_fees.quantize(Decimal("0.01")),
            slippage_bps=slippage_bps.quantize(Decimal("0.01")),
        )


class ZeroCostModel:
    """Null cost model — preserves backward compatibility for tests
    that rely on zero-cost fills."""

    def compute(
        self,
        symbol: str,
        side: Side,
        quantity: int,
        fill_price: Decimal,
    ) -> CostBreakdown:
        return CostBreakdown(
            spread_cost=Decimal("0"),
            commission=Decimal("0"),
            total_fees=Decimal("0"),
            slippage_bps=Decimal("0"),
        )
