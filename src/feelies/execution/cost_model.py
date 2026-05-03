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
        is_taker: bool = True,
        is_short: bool = False,
    ) -> CostBreakdown:
        """Return cost components for a single fill.

        ``is_taker=True`` applies taker exchange fees (removing liquidity).
        ``is_taker=False`` applies maker exchange fees / rebates (adding
        liquidity) and the passive adverse-selection penalty.
        ``is_short=True`` applies the hard-to-borrow (HTB) daily fee
        on SELL-side fills when ``htb_borrow_annual_bps > 0``.
        """
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
    ``taker_exchange_per_share``: IB pass-through fee for removing
        liquidity (~$0.003 per share).
    ``maker_exchange_per_share``: IB maker rebate for adding liquidity
        (negative, ~−$0.002 per share).
    ``min_commission``: IB Tiered minimum per order ($0.35).
    ``max_commission_pct``: IB Tiered maximum commission as a
        percentage of trade value (1.0%).
    ``passive_adverse_selection_bps``: additional cost on passive
        (maker) fills to model adverse selection risk in basis points.
    ``sell_regulatory_bps``: SEC/FINRA regulatory fee on sell-side
        fills in basis points (0 = disabled by default).
    ``stress_multiplier``: scalar applied to all variable costs for
        stress-testing (1.0 = baseline, 1.5 = 50% cost stress).
    ``htb_borrow_annual_bps``: annualised hard-to-borrow fee in basis
        points applied on SELL-side fills when ``is_short=True``.
        Daily cost = notional × annual_bps / 252 / 10 000.
        Default 0 = disabled.  Set only for short-selling strategies.
    ``min_commission_applies_to_per_share_only``: when True, the
        ``min_commission`` floor applies only to the per-share
        component before the exchange pass-through/rebate is added.
        Default False matches IB Tiered behavior (min applies to
        the total, so rebates don't show on small orders).  Set to
        True for advanced passive strategies that need to model the
        rebate net of commission on small orders.
    """

    min_spread_cost_bps: Decimal = Decimal("0")
    commission_per_share: Decimal = Decimal("0.0035")
    taker_exchange_per_share: Decimal = Decimal("0.003")
    maker_exchange_per_share: Decimal = Decimal("-0.002")
    min_commission: Decimal = Decimal("0.35")
    max_commission_pct: Decimal = Decimal("1.0")
    passive_adverse_selection_bps: Decimal = Decimal("0.5")
    sell_regulatory_bps: Decimal = Decimal("0.0")
    stress_multiplier: Decimal = Decimal("1.0")
    htb_borrow_annual_bps: Decimal = Decimal("0.0")
    min_commission_applies_to_per_share_only: bool = False


class DefaultCostModel:
    """Cost model: actual half-spread (with optional floor) + IB Tiered commission.

    Supports taker/maker fee split:
      - Taker fills (market orders, aggressive limit crosses) pay
        ``taker_exchange_per_share`` on top of commission.
      - Maker fills (passive limit orders) receive
        ``maker_exchange_per_share`` rebate (negative value) and incur
        ``passive_adverse_selection_bps`` for adverse selection risk.

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
    ) -> CostBreakdown:
        notional = fill_price * quantity
        stress = self._cfg.stress_multiplier

        # Spread cost: actual half-spread (stressed — spreads widen under
        # stress) with optional BPS floor (also stressed).
        actual_spread_cost = half_spread * quantity * stress
        floor_spread_cost = notional * self._cfg.min_spread_cost_bps * stress / Decimal("10000")
        spread_cost = max(actual_spread_cost, floor_spread_cost)

        # IB Tiered commission: per-share + exchange pass-through.
        # Taker pays taker_exchange_per_share; maker receives the maker rebate.
        # Stress multiplier applies to commission and taker exchange fee; the
        # maker rebate is not stressed (already a conservative assumption).
        stressed_commission = self._cfg.commission_per_share * stress
        if is_taker:
            exchange_per_share = self._cfg.taker_exchange_per_share * stress
        else:
            exchange_per_share = self._cfg.maker_exchange_per_share  # rebate, not stressed

        per_share_commission = stressed_commission * quantity
        exchange_fees = exchange_per_share * quantity
        if self._cfg.min_commission_applies_to_per_share_only:
            # Advanced mode: floor the per-share part only; rebates can
            # produce a net credit on small maker orders.
            per_share_commission = max(
                per_share_commission, self._cfg.min_commission * stress
            )
            commission = per_share_commission + exchange_fees
        else:
            # IB Tiered default: floor the total (commission + exchange).
            commission = max(
                per_share_commission + exchange_fees,
                self._cfg.min_commission * stress,
            )
        if notional > 0:
            max_commission = notional * self._cfg.max_commission_pct / Decimal("100")
            commission = min(commission, max_commission)

        # Passive adverse-selection penalty (maker fills only)
        adverse_cost = Decimal("0")
        if not is_taker:
            adverse_cost = notional * self._cfg.passive_adverse_selection_bps * stress / Decimal("10000")

        # Sell-side regulatory fee (e.g. SEC fee, default 0)
        regulatory_cost = Decimal("0")
        if side == Side.SELL:
            regulatory_cost = notional * self._cfg.sell_regulatory_bps * stress / Decimal("10000")

        # Hard-to-borrow (HTB) daily borrow cost for short-side sells (2g).
        # Applied only when is_short=True and htb_borrow_annual_bps > 0.
        # Daily cost = notional × annual_bps / 252 / 10 000 (one trading day).
        # Stressed to model borrow-fee spikes in risk-off regimes.
        htb_cost = Decimal("0")
        if is_short and side == Side.SELL and self._cfg.htb_borrow_annual_bps > 0:
            htb_cost = (
                notional * self._cfg.htb_borrow_annual_bps * stress
                / Decimal("252") / Decimal("10000")
            )

        total_fees = spread_cost + commission + adverse_cost + regulatory_cost + htb_cost
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
        is_taker: bool = True,
        is_short: bool = False,
    ) -> CostBreakdown:
        notional = fill_price * quantity
        return CostBreakdown(
            spread_cost=Decimal("0"),
            commission=Decimal("0"),
            total_fees=Decimal("0"),
            cost_bps=Decimal("0"),
            notional=notional,
        )


def estimate_round_trip_cost_bps(
    model: CostModel,
    *,
    symbol: str,
    entry_side: Side,
    quantity: int,
    mid_price: Decimal,
    half_spread: Decimal,
    is_taker: bool,
    is_short_entry: bool,
) -> float:
    """Sum model one-way ``cost_bps`` for an entry + flat-to-flat exit leg.

    Used by the orchestrator B4 gate (Inv-12 runtime complement to load-
    time G12).  Preserves sell-side regulatory fees and HTB on short-entry
    sells while using a symmetric exit (cover / close) without HTB.

    Both legs share the same ``is_taker`` assumption — matching the legacy
    ``cost_bps * 2`` heuristic when costs are symmetric.
    """
    entry_short = bool(is_short_entry and entry_side == Side.SELL)
    entry = model.compute(
        symbol,
        entry_side,
        quantity,
        mid_price,
        half_spread,
        is_taker=is_taker,
        is_short=entry_short,
    )
    exit_side = Side.SELL if entry_side == Side.BUY else Side.BUY
    exit_leg = model.compute(
        symbol,
        exit_side,
        quantity,
        mid_price,
        half_spread,
        is_taker=is_taker,
        is_short=False,
    )
    return float(entry.cost_bps + exit_leg.cost_bps)
