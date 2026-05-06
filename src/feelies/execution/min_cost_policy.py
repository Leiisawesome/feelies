"""Minimum-cost execution strategy (per-order passive vs aggressive).

Configuration-driven per-order decision policy.  Given a candidate
order's symbol / side / quantity / current quote, the policy compares
the model-computed ``cost_bps`` of a passive (maker) fill against an
aggressive (taker) fill and picks the cheaper one.  Stop-loss exits,
forced-flatten escalation, and other "must-trade" paths are forced to
aggressive regardless of cost — guaranteed-fill safety beats spread
savings (Inv-11 fail-safe).

Conservative defaults (IBKR-style, U.S. equities):

* The cost comparison uses the *same* ``DefaultCostModel`` as the
  router so backtest routing decisions cannot become more optimistic
  than the cost the simulator actually charges.
* On passive fills, the model includes the configured
  ``passive_adverse_selection_bps`` *and* the maker rebate.  Passive
  routing is therefore not a free lunch: the policy will refuse to go
  passive on tight-spread / small-order regimes where the commission
  floor + adverse-selection penalty dominates the would-be spread
  saving.
* A configurable ``prefer_passive_bias_bps`` lets operators bias the
  decision (negative = require passive to beat aggressive by a margin
  before posting a limit, the more conservative direction).
* Below ``small_order_aggressive_threshold_shares`` the policy forces
  aggressive — at small sizes the $0.35 IBKR commission floor swamps
  the spread saving and a missed passive fill that times out is more
  expensive than just crossing.

Determinism: the policy is a pure function of its inputs (cost model,
quote, order spec, config) and contains no clocks, no randomness, and
no I/O.  Replays produce identical decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from feelies.core.events import Side
from feelies.execution.cost_model import CostModel


@dataclass(frozen=True, kw_only=True)
class MinCostPolicyConfig:
    """Tunable knobs for :class:`MinimumCostExecutionPolicy`.

    ``prefer_passive_bias_bps``: subtracted from the passive-leg
        ``cost_bps`` before comparing against the aggressive leg.
        Positive values bias toward passive (operator prefers to
        chase the spread); negative values require passive to beat
        aggressive by ``|bias|`` bps before being chosen (the more
        conservative direction).  Default 0 (pure model comparison).
    ``small_order_aggressive_threshold_shares``: orders with quantity
        strictly below this threshold are forced to aggressive.
        Default 0 (disabled).  Set to e.g. 50 for a $0.35-floor IB
        Tiered profile to skip passive on noise-sized orders where
        the commission floor + adverse-selection penalty exceeds the
        spread saving.
    ``min_half_spread_for_passive``: passive routing is skipped (in
        favor of aggressive) when the current quoted half-spread is
        strictly below this threshold (in price units).  Tight
        spreads make the spread saving negligible relative to the
        adverse-selection cost.  Default 0 (disabled).  Setting this
        to e.g. ``0.005`` (one tick on a sub-$5 stock) is reasonable
        for U.S. equities.
    ``allow_passive_short_entry``: when False, short-entry orders
        always go aggressive — getting filled fast on the borrow side
        matters more than spread savings when HTB fees accrue daily.
        Default True (passive shorts allowed; HTB is modeled in the
        cost comparison so the policy can decide).
    """

    prefer_passive_bias_bps: Decimal = Decimal("0")
    small_order_aggressive_threshold_shares: int = 0
    min_half_spread_for_passive: Decimal = Decimal("0")
    allow_passive_short_entry: bool = True


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
        if (
            is_short
            and side == Side.SELL
            and not self._cfg.allow_passive_short_entry
        ):
            return "aggressive"

        # Cost comparison.  The two sides are evaluated against the
        # same notional and same model — passive uses ``half_spread=0``
        # because a maker fill rests at the BBO without crossing the
        # spread (matching the passive router's
        # ``_emit_passive_fill`` semantics).  Aggressive crosses to
        # the opposite-side BBO and pays ``half_spread``.
        passive_breakdown = self._cost_model.compute(
            symbol=symbol,
            side=side,
            quantity=quantity,
            fill_price=mid_price,
            half_spread=Decimal("0"),
            is_taker=False,
            is_short=is_short,
        )
        aggressive_breakdown = self._cost_model.compute(
            symbol=symbol,
            side=side,
            quantity=quantity,
            fill_price=mid_price,
            half_spread=half_spread,
            is_taker=True,
            is_short=is_short,
        )

        passive_cost_bps = passive_breakdown.cost_bps - self._cfg.prefer_passive_bias_bps
        if passive_cost_bps < aggressive_breakdown.cost_bps:
            return "passive"
        return "aggressive"


__all__ = [
    "MinCostPolicyConfig",
    "MinimumCostExecutionPolicy",
]
