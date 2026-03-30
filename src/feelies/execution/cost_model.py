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
    """Computes fees and cost breakdown for a simulated fill."""

    def compute(
        self,
        symbol: str,
        side: Side,
        quantity: int,
        fill_price: Decimal,
        half_spread: Decimal,
    ) -> CostBreakdown:
        """Return cost components for a single fill."""
        ...


@dataclass(frozen=True)
class CostBreakdown:
    """Itemised cost output attached to each fill."""

    spread_cost: Decimal
    commission: Decimal
    total_fees: Decimal
    cost_bps: Decimal


@dataclass(frozen=True)
class DefaultCostModelConfig:
    """Tunable cost parameters for the default model.

    ``min_spread_cost_bps``: minimum half-spread crossing cost in basis
        points.  Acts as a floor when the actual quote spread is narrower
        (e.g. locked/crossed markets or sub-penny spreads).
    ``commission_per_share``: flat per-share commission.
    ``min_commission``: minimum commission per order.
    """

    min_spread_cost_bps: Decimal = Decimal("0.5")
    commission_per_share: Decimal = Decimal("0.005")
    min_commission: Decimal = Decimal("1.00")


class DefaultCostModel:
    """Cost model: actual half-spread (with floor) + per-share commission."""

    def __init__(self, config: DefaultCostModelConfig | None = None) -> None:
        self._cfg = config or DefaultCostModelConfig()

    def compute(
        self,
        symbol: str,
        side: Side,
        quantity: int,
        fill_price: Decimal,
        half_spread: Decimal,
    ) -> CostBreakdown:
        notional = fill_price * quantity

        actual_spread_cost = half_spread * quantity
        floor_spread_cost = notional * self._cfg.min_spread_cost_bps / Decimal("10000")
        spread_cost = max(actual_spread_cost, floor_spread_cost)

        raw_commission = self._cfg.commission_per_share * quantity
        commission = max(raw_commission, self._cfg.min_commission)

        total_fees = spread_cost + commission
        cost_bps = (
            total_fees / notional * Decimal("10000")
            if notional > 0 else Decimal("0")
        )

        return CostBreakdown(
            spread_cost=spread_cost.quantize(Decimal("0.01")),
            commission=commission.quantize(Decimal("0.01")),
            total_fees=total_fees.quantize(Decimal("0.01")),
            cost_bps=cost_bps.quantize(Decimal("0.01")),
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
        half_spread: Decimal,
    ) -> CostBreakdown:
        return CostBreakdown(
            spread_cost=Decimal("0"),
            commission=Decimal("0"),
            total_fees=Decimal("0"),
            cost_bps=Decimal("0"),
        )
