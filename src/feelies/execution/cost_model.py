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
    notional: Decimal


@dataclass(frozen=True)
class DefaultCostModelConfig:
    """Tunable cost parameters matching IB US Equity Tiered pricing.

    ``min_spread_cost_bps``: minimum half-spread crossing cost in basis
        points.  Set to 0 for IB (no phantom spread floor).
    ``commission_per_share``: IB Tiered commission component ($0.0035).
    ``exchange_per_share``: IB pass-through exchange, clearing, and
        regulatory fees (~$0.0005 conservative estimate for adding
        liquidity; up to ~$0.003 for removing).
    ``min_commission``: IB Tiered minimum per order ($0.35).
    ``max_commission_pct``: IB Tiered maximum commission as a
        percentage of trade value (1.0%).
    """

    min_spread_cost_bps: Decimal = Decimal("0")
    commission_per_share: Decimal = Decimal("0.0035")
    exchange_per_share: Decimal = Decimal("0.0005")
    min_commission: Decimal = Decimal("0.35")
    max_commission_pct: Decimal = Decimal("1.0")


class DefaultCostModel:
    """Cost model: actual half-spread (with optional floor) + IB Tiered commission."""

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

        # Spread cost: actual half-spread with optional BPS floor
        actual_spread_cost = half_spread * quantity
        floor_spread_cost = notional * self._cfg.min_spread_cost_bps / Decimal("10000")
        spread_cost = max(actual_spread_cost, floor_spread_cost)

        # IB Tiered commission: per-share + exchange pass-through, with min/max
        raw_commission = (
            self._cfg.commission_per_share + self._cfg.exchange_per_share
        ) * quantity
        commission = max(raw_commission, self._cfg.min_commission)
        # IB caps commission at max_commission_pct of trade value
        if notional > 0:
            max_commission = notional * self._cfg.max_commission_pct / Decimal("100")
            commission = min(commission, max_commission)

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
            notional=notional,
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
        notional = fill_price * quantity
        return CostBreakdown(
            spread_cost=Decimal("0"),
            commission=Decimal("0"),
            total_fees=Decimal("0"),
            cost_bps=Decimal("0"),
            notional=notional,
        )
