"""Transaction cost model for backtest fill realism (invariant 12).

Separates cost logic from fill routing for independent stress testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from feelies.core.cost_model import CostBreakdown as CostBreakdown
from feelies.core.cost_model import CostModel as CostModel
from feelies.core.cost_model import FillType as FillType
from feelies.core.cost_model import (
    estimate_aggressive_taker_cost_bps as estimate_aggressive_taker_cost_bps,
)
from feelies.core.cost_model import (
    estimate_round_trip_cost_bps as estimate_round_trip_cost_bps,
)
from feelies.core.events import Side


@dataclass(frozen=True)
class DefaultCostModelConfig:
    """IB-style equity cost parameters.

    Per-share commission and exchange fees distinguish makers from takers.
    Through fills use a higher adverse-selection charge than queue drains.
    Sell fills add regulatory and TAF charges; short entries may add one day of
    borrow. ``stress_multiplier`` affects variable costs, not fixed floors or
    caps. By default, the commission floor applies before pass-through fees.
    """

    min_spread_cost_bps: Decimal = Decimal("0")
    commission_per_share: Decimal = Decimal("0.0035")
    taker_exchange_per_share: Decimal = Decimal("0.003")
    maker_exchange_per_share: Decimal = Decimal("0.0")
    min_commission: Decimal = Decimal("0.35")
    max_commission_pct: Decimal = Decimal("1.0")
    # Through-fills carry more adverse selection than queue-drain fills.
    passive_adverse_selection_bps: Decimal = Decimal("2.0")
    through_fill_adverse_selection_bps: Decimal = Decimal("5.0")
    adverse_selection_through_bps: Decimal = Decimal("5.0")
    adverse_selection_drain_bps: Decimal = Decimal("2.0")
    sell_regulatory_bps: Decimal = Decimal("0.5")
    finra_taf_per_share: Decimal = Decimal("0.000166")
    finra_taf_max_per_order: Decimal = Decimal("8.30")
    stress_multiplier: Decimal = Decimal("1.0")
    htb_borrow_annual_bps: Decimal = Decimal("0.0")
    # Forced exits fill against depleted depth and widened spread. Applied as a
    # multiplier on ``half_spread`` for the spread component only when
    # the caller signals a stop/forced-exit fill_type.
    stop_slippage_half_spreads: Decimal = Decimal("2.0")
    min_commission_applies_to_per_share_only: bool = True
    # Apply the spread floor only to takers; passive fills do not cross spread.
    spread_floor_taker_only: bool = True


_DEFAULT_COST_MODEL_CONFIG: DefaultCostModelConfig = DefaultCostModelConfig()


class DefaultCostModel:
    """Cost model: actual half-spread (with optional floor) + IB Tiered commission.

    Supports taker/maker fee split:
      - Taker fills (market orders, aggressive limit crosses) pay
        ``taker_exchange_per_share`` on top of commission.
      - Maker fills (passive limit orders) receive
        ``maker_exchange_per_share`` rebate (negative value) and incur
        an adverse-selection penalty selected by ``is_through_fill``
        (``adverse_selection_through_bps`` vs ``adverse_selection_drain_bps``).

    A ``stress_multiplier > 1.0`` scales all variable costs proportionally
    for worst-case scenario analysis.
    """

    def __init__(self, config: DefaultCostModelConfig | None = None) -> None:
        self._cfg = config or DefaultCostModelConfig()

    def compute(
        self,
        symbol: str,
        side: Side,
        quantity: int,
        fill_price: Decimal,
        half_spread: Decimal,
        is_taker: bool = True,
        is_short: bool = False,
        fill_type: FillType | None = None,
        adverse_notional_price: Decimal | None = None,
        is_through_fill: bool = False,
    ) -> CostBreakdown:
        notional = fill_price * quantity
        stress = self._cfg.stress_multiplier

        # Default fill_type from is_taker when not supplied.
        if fill_type is None:
            if is_taker:
                fill_type = "TAKER"
            else:
                fill_type = "THROUGH" if is_through_fill else "LEVEL"

        # Never charge a commission floor on a zero-share fill.
        if quantity <= 0:
            return CostBreakdown(
                spread_cost=Decimal("0.00"),
                commission=Decimal("0.00"),
                total_fees=Decimal("0.00"),
                cost_bps=Decimal("0.00"),
                notional=notional,
            )

        # Makers do not cross spread. Takers pay stressed spread with a floor.
        if is_taker:
            actual_spread_cost = half_spread * quantity * stress
            floor_spread_cost = (
                notional * self._cfg.min_spread_cost_bps * stress / Decimal("10000")
            )
            spread_cost = max(actual_spread_cost, floor_spread_cost)
        elif not self._cfg.spread_floor_taker_only:
            # Optional maker spread floor.
            actual_spread_cost = half_spread * quantity * stress
            floor_spread_cost = (
                notional * self._cfg.min_spread_cost_bps * stress / Decimal("10000")
            )
            spread_cost = max(actual_spread_cost, floor_spread_cost)
        else:
            spread_cost = Decimal("0")

        # Stress variable taker costs only; rebates and contractual caps stay fixed.
        stressed_commission = self._cfg.commission_per_share * stress
        if is_taker:
            exchange_per_share = self._cfg.taker_exchange_per_share * stress
        else:
            exchange_per_share = self._cfg.maker_exchange_per_share  # rebate, not stressed

        per_share_commission = stressed_commission * quantity
        exchange_fees = exchange_per_share * quantity
        if self._cfg.min_commission_applies_to_per_share_only:
            # Apply IB's minimum and maximum to commission before pass-through fees.
            per_share_commission = max(per_share_commission, self._cfg.min_commission)
            if notional > 0:
                max_ib_commission = notional * self._cfg.max_commission_pct / Decimal("100")
                per_share_commission = min(per_share_commission, max_ib_commission)
            commission = per_share_commission + exchange_fees
        else:
            # Bundled mode applies both floor and cap to commission plus exchange fees.
            commission = max(
                per_share_commission + exchange_fees,
                self._cfg.min_commission,
            )
            if notional > 0:
                max_commission = notional * self._cfg.max_commission_pct / Decimal("100")
                commission = min(commission, max_commission)

        # Maker through-fills carry the larger adverse-selection charge.
        adverse_cost = Decimal("0")
        if not is_taker:
            default_cfg = _DEFAULT_COST_MODEL_CONFIG
            through_bps = self._cfg.through_fill_adverse_selection_bps
            if (
                through_bps == default_cfg.through_fill_adverse_selection_bps
                and self._cfg.adverse_selection_through_bps
                != default_cfg.adverse_selection_through_bps
            ):
                through_bps = self._cfg.adverse_selection_through_bps
            level_bps = self._cfg.passive_adverse_selection_bps
            if (
                level_bps == default_cfg.passive_adverse_selection_bps
                and self._cfg.adverse_selection_drain_bps
                != default_cfg.adverse_selection_drain_bps
            ):
                level_bps = self._cfg.adverse_selection_drain_bps
            adverse_bps = through_bps if fill_type == "THROUGH" else level_bps
            adverse_basis_price = (
                adverse_notional_price if adverse_notional_price is not None else fill_price
            )
            adverse_notional = adverse_basis_price * quantity
            adverse_cost = adverse_notional * adverse_bps * stress / Decimal("10000")

        # Sell fees combine stressed SEC notional cost and capped FINRA TAF.
        regulatory_cost = Decimal("0")
        if side == Side.SELL:
            regulatory_cost = notional * self._cfg.sell_regulatory_bps * stress / Decimal("10000")
            if self._cfg.finra_taf_per_share > 0:
                taf = self._cfg.finra_taf_per_share * stress * quantity
                if self._cfg.finra_taf_max_per_order > 0:
                    taf = min(taf, self._cfg.finra_taf_max_per_order)
                regulatory_cost += taf

        # Charge one stressed borrow day on short entry using a 360-day year.
        htb_cost = Decimal("0")
        if is_short and side == Side.SELL and self._cfg.htb_borrow_annual_bps > 0:
            htb_cost = (
                notional
                * self._cfg.htb_borrow_annual_bps
                * stress
                / Decimal("360")
                / Decimal("10000")
            )

        total_fees = spread_cost + commission + adverse_cost + regulatory_cost + htb_cost
        cost_bps = total_fees / notional * Decimal("10000") if notional > 0 else Decimal("0")

        return CostBreakdown(
            spread_cost=spread_cost.quantize(Decimal("0.01")),
            commission=commission.quantize(Decimal("0.01")),
            total_fees=total_fees.quantize(Decimal("0.01")),
            cost_bps=cost_bps.quantize(Decimal("0.01")),
            notional=notional.quantize(Decimal("0.01")),
            raw_cost_bps=cost_bps,
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
        is_taker: bool = True,
        is_short: bool = False,
        fill_type: FillType | None = None,
        adverse_notional_price: Decimal | None = None,
        is_through_fill: bool = False,
    ) -> CostBreakdown:
        notional = fill_price * quantity
        return CostBreakdown(
            spread_cost=Decimal("0"),
            commission=Decimal("0"),
            total_fees=Decimal("0"),
            cost_bps=Decimal("0"),
            notional=notional,
        )
