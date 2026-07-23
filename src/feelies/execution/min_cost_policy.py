"""Choose passive or aggressive execution from modeled per-order cost.

The policy uses the router's cost model, including rebates, adverse selection,
commission floors, and non-fill risk. Must-trade orders always use aggressive
execution. Decisions depend only on the supplied order, quote, and config.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from feelies.core.events import Side
from feelies.execution.cost_model import (
    CostModel,
    estimate_aggressive_taker_cost_bps,
)


@dataclass(frozen=True, kw_only=True)
class MinCostPolicyConfig:
    """Configuration for :class:`MinimumCostExecutionPolicy`.

    Positive ``prefer_passive_bias_bps`` favors passive orders; negative values
    require passive execution to win by that margin. Share and spread thresholds
    can force aggressive execution. ``allow_passive_short_entry`` controls short
    entries independently.
    """

    prefer_passive_bias_bps: Decimal = Decimal("0")
    small_order_aggressive_threshold_shares: int = 0
    min_half_spread_for_passive: Decimal = Decimal("0")
    allow_passive_short_entry: bool = True
    # Match the router's depth-aware aggressive cost.
    market_impact_factor: Decimal = Decimal("0.5")
    max_impact_half_spreads: Decimal = Decimal("10")
    # Mirror the router's within-L1 and permanent-impact charges.
    within_l1_impact_factor: Decimal = Decimal("0")
    permanent_impact_coefficient: Decimal = Decimal("0")
    # Price non-fill risk as probability × forgone edge.
    passive_non_fill_probability: Decimal = Decimal("0.30")


class MinimumCostExecutionPolicy:
    """Decides per-order whether to use a passive limit or aggressive market.

    The policy compares :class:`CostModel`\\-computed ``cost_bps`` of a
    notional fill on each side and picks the cheaper one, with the
    configured bias and forced-aggressive carve-outs.  It does not
    submit any orders — the orchestrator constructs the resulting
    ``OrderRequest`` with the chosen ``order_type``.

    Returned decisions are one of:

    * ``"passive"`` — caller posts a LIMIT order at the near-side BBO
      (BUY @ bid, SELL @ ask).  Falls through to aggressive at the
      router level if the limit becomes marketable.
    * ``"aggressive"`` — caller submits a MARKET order.

    The policy never returns ``None``: every order has a routing
    decision.  Forced-aggressive paths (stop, force-flatten) bypass
    the cost comparison and emit ``"aggressive"`` directly.
    """

    def __init__(
        self,
        cost_model: CostModel,
        config: MinCostPolicyConfig | None = None,
    ) -> None:
        self._cost_model = cost_model
        self._cfg = config or MinCostPolicyConfig()

    @property
    def config(self) -> MinCostPolicyConfig:
        return self._cfg

    def decide(
        self,
        *,
        symbol: str,
        side: Side,
        quantity: int,
        mid_price: Decimal,
        half_spread: Decimal,
        is_short: bool = False,
        force_aggressive: bool = False,
        bid_size: int | None = None,
        ask_size: int | None = None,
        edge_bps: float = 0.0,
    ) -> str:
        """Return ``"passive"`` or ``"aggressive"`` for this order.

        ``force_aggressive`` is the caller-supplied safety override
        for stop-loss exits, forced-flatten escalation, and the EXIT
        leg of REVERSE intents — paths that must trade now and not
        risk a passive cancel.  Even a positive cost model verdict
        cannot override it.
        """
        if force_aggressive:
            return "aggressive"

        if quantity <= 0:
            return "aggressive"

        # Small-order carve-out: commission floor swamps the spread
        # saving below this threshold (IBKR Tiered $0.35 floor).
        if (
            self._cfg.small_order_aggressive_threshold_shares > 0
            and quantity < self._cfg.small_order_aggressive_threshold_shares
        ):
            return "aggressive"

        # Tight-spread carve-out: half-spread too narrow for passive
        # to be meaningfully cheaper after adverse selection.
        if (
            self._cfg.min_half_spread_for_passive > 0
            and half_spread < self._cfg.min_half_spread_for_passive
        ):
            return "aggressive"

        # Short-entry carve-out: HTB cost accrues daily.  When the
        # operator opts out of passive shorts, all sells with
        # ``is_short=True`` go aggressive.  When opted in (default),
        # the cost comparison itself handles HTB on the SELL leg.
        if is_short and side == Side.SELL and not self._cfg.allow_passive_short_entry:
            return "aggressive"

        # Compare raw costs on one notional; makers do not cross the spread.
        passive_breakdown = self._cost_model.compute(
            symbol=symbol,
            side=side,
            quantity=quantity,
            fill_price=mid_price,
            half_spread=Decimal("0"),
            is_taker=False,
            is_short=is_short,
        )

        # Use walk-the-book pricing when both BBO depths are available.
        if bid_size is not None and ask_size is not None:
            depth = ask_size if side == Side.BUY else bid_size
            aggressive_cost_bps = Decimal(
                str(
                    estimate_aggressive_taker_cost_bps(
                        self._cost_model,
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        mid_price=mid_price,
                        half_spread=half_spread,
                        available_depth=int(depth),
                        market_impact_factor=self._cfg.market_impact_factor,
                        max_impact_half_spreads=self._cfg.max_impact_half_spreads,
                        within_l1_impact_factor=self._cfg.within_l1_impact_factor,
                        permanent_impact_coefficient=self._cfg.permanent_impact_coefficient,
                        is_short=is_short,
                    )
                )
            )
        else:
            aggressive_breakdown = self._cost_model.compute(
                symbol=symbol,
                side=side,
                quantity=quantity,
                fill_price=mid_price,
                half_spread=half_spread,
                is_taker=True,
                is_short=is_short,
            )
            aggressive_cost_bps = aggressive_breakdown.raw_cost_bps

        # Add expected forgone edge to the passive route.
        passive_raw = passive_breakdown.raw_cost_bps
        opportunity_cost = self._cfg.passive_non_fill_probability * Decimal(str(edge_bps))
        passive_cost_bps = passive_raw - self._cfg.prefer_passive_bias_bps + opportunity_cost
        if passive_cost_bps < aggressive_cost_bps:
            return "passive"
        return "aggressive"


__all__ = [
    "MinCostPolicyConfig",
    "MinimumCostExecutionPolicy",
]
