"""Transaction cost model for backtest fill realism (invariant 12).

Separates cost logic from fill routing so models can be swapped,
stress-tested (1.5x cost, 2x latency), and audited independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from feelies.core.events import Side


FillType = Literal["TAKER", "LEVEL", "THROUGH"]


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
        fill_type: FillType | None = None,
        adverse_notional_price: Decimal | None = None,
    ) -> CostBreakdown:
        """Return cost components for a single fill.

        ``is_taker=True`` applies taker exchange fees (removing liquidity).
        ``is_taker=False`` applies maker exchange fees / rebates (adding
        liquidity) and the passive adverse-selection penalty.
        ``is_short=True`` applies the hard-to-borrow (HTB) daily fee
        on SELL-side fills when ``htb_borrow_annual_bps > 0``.

        ``fill_type`` (audit F-H-09): distinguishes through-fills from
        level (queue-drain) fills.  When ``is_taker=False`` and
        ``fill_type="THROUGH"``, the model charges
        ``through_fill_adverse_selection_bps`` rather than the gentler
        ``passive_adverse_selection_bps``.  Defaults: ``"TAKER"`` when
        ``is_taker=True``, else ``"LEVEL"``.

        ``adverse_notional_price`` (audit F-M-24): when supplied, the
        adverse-selection penalty is computed against
        ``adverse_notional_price × quantity`` rather than ``fill_price
        × quantity``.  Used by the router to bill adverse cost against
        the opposite-side BBO (the price an aggressor would have paid),
        keeping router and round-trip estimator internally consistent.
        """
        ...


@dataclass(frozen=True)
class CostBreakdown:
    """Itemised cost output attached to each fill.

    ``cost_bps`` is quantized to 0.01 for forensic stability.
    ``raw_cost_bps`` is the un-quantized value (audit F-M-20); callers
    that perform fine-grained comparisons (the minimum-cost policy
    routing decision) should use the raw value to avoid quantization-
    flip on borderline cases.
    """

    spread_cost: Decimal
    commission: Decimal
    total_fees: Decimal
    cost_bps: Decimal
    notional: Decimal
    raw_cost_bps: Decimal = Decimal("0")


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
    ``min_commission``: IB Tiered minimum per order ($0.35).  This is
        a fixed broker threshold and is NOT scaled by
        ``stress_multiplier`` (IBKR doesn't raise the per-order floor
        in volatile regimes).
    ``max_commission_pct``: IB Tiered maximum IB commission as a
        percentage of trade value (1.0%).  Per IBKR's published Tiered
        schedule the 1% cap applies to the **IB execution commission
        only** — exchange / regulatory pass-throughs are not capped
        and continue to accrue on top of the capped commission.  This
        is enforced when ``min_commission_applies_to_per_share_only=True``;
        in legacy bundled-floor mode the cap is applied to the bundled
        total (consistent with the bundled floor).
    ``passive_adverse_selection_bps``: additional cost on passive
        (maker) fills to model adverse selection risk in basis points.
        A flat per-fill proxy — real adverse selection is direction-
        and event-dependent (through-fills are typically worse than
        queue-drain fills).  See module docstring for limitations.
    ``sell_regulatory_bps``: combined SEC Section 31 fee + small
        operator-conservativeness margin, in basis points of notional,
        applied on SELL fills only.  Default 0.5 bps approximates the
        current SEC fee rate (~$27.80 per $1M = 0.278 bps at time of
        writing) with conservative headroom for rate changes.  Set to
        0 for pre-2024 backtests or to suppress entirely.
    ``finra_taf_per_share``: FINRA Trading Activity Fee per share on
        SELL fills only.  Default $0.000166 (current FINRA published
        rate).  Set to 0 to disable.
    ``finra_taf_max_per_order``: FINRA TAF cap per execution (USD).
        Default $8.30 (current FINRA published cap).
    ``stress_multiplier``: scalar applied to variable costs only
        (per-share commission, taker exchange fees, spread cost,
        adverse selection, sell-side regulatory, HTB).  Fixed
        broker thresholds (``min_commission``, ``max_commission_pct``,
        ``finra_taf_max_per_order``, maker rebate) are NOT stressed.
    ``htb_borrow_annual_bps``: annualised hard-to-borrow fee in basis
        points applied on SELL-side fills when ``is_short=True``.
        Daily cost = notional × annual_bps / 360 / 10 000 (broker
        convention: stock-loan accruals use a 360-day year, not 252
        trading days).  Default 0 = disabled.  Only the one entry-day
        accrual is charged here; multi-day holding accrual is a
        position-store concern and is out of scope for this fill-time
        model.
    ``min_commission_applies_to_per_share_only``: when True, the
        ``min_commission`` floor applies to the per-share IB execution
        fee only; exchange/regulatory pass-through fees and the maker
        rebate are added on top of the floored value.  This matches
        IBKR's published Tiered fee schedule: the $0.35 minimum is on
        the IB execution component ("Commissions"), not the bundled
        "Commission + Routing/Regulatory" total.  When False (legacy
        behavior, kept for tests and parity with the v0.1 model), the
        floor applies to the bundled total — which absorbs taker
        exchange fees inside the floor and so under-counts cost on
        small taker orders.  Default True (more conservative for
        small orders, accurate for IBKR Tiered).
    """

    min_spread_cost_bps: Decimal = Decimal("0")
    commission_per_share: Decimal = Decimal("0.0035")
    taker_exchange_per_share: Decimal = Decimal("0.003")
    maker_exchange_per_share: Decimal = Decimal("0.0")
    min_commission: Decimal = Decimal("0.35")
    max_commission_pct: Decimal = Decimal("1.0")
    # Audit F-H-09: per-fill-type passive adverse selection.
    # ``passive_adverse_selection_bps`` applies to LEVEL (queue-drain)
    # fills where the BBO never crossed our limit.  Through-fills
    # (BBO gapped through our level — textbook adverse-selection
    # scenario) carry a strictly higher charge.
    # Defaults 2.0 / 5.0 are conservative for liquid US large-caps;
    # operators should tune by symbol class.
    passive_adverse_selection_bps: Decimal = Decimal("2.0")
    through_fill_adverse_selection_bps: Decimal = Decimal("5.0")
    sell_regulatory_bps: Decimal = Decimal("0.5")
    finra_taf_per_share: Decimal = Decimal("0.000166")
    finra_taf_max_per_order: Decimal = Decimal("8.30")
    stress_multiplier: Decimal = Decimal("1.0")
    htb_borrow_annual_bps: Decimal = Decimal("0.0")
    # Audit F-H-10: forced-exit slippage multiplier.  Stop-losses /
    # hazard exits / forced-flattens fill in depleted depth and widened
    # spread that the cost model would otherwise miss.  Applied as a
    # multiplier on ``half_spread`` for the spread component only when
    # the caller signals a stop/forced-exit fill_type.
    stop_slippage_half_spreads: Decimal = Decimal("2.0")
    min_commission_applies_to_per_share_only: bool = True
    # When True (default), the spread-floor (``min_spread_cost_bps``)
    # only applies on taker fills.  Maker/passive fills don't cross
    # the spread, so charging a phantom floor on them would be a
    # categorically wrong cost attribution.  Kept as a flag so legacy
    # configs that intentionally floor passive fills can opt back in.
    spread_floor_taker_only: bool = True


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
        fill_type: FillType | None = None,
        adverse_notional_price: Decimal | None = None,
    ) -> CostBreakdown:
        notional = fill_price * quantity
        stress = self._cfg.stress_multiplier

        # Default fill_type from is_taker when not supplied.
        if fill_type is None:
            fill_type = "TAKER" if is_taker else "LEVEL"

        # Zero-quantity / zero-notional safe-no-op.  IBKR doesn't
        # commission a zero-share fill, and applying the floor in this
        # branch would charge a $0.35 phantom fee on synthetic zero
        # fills (e.g. unit-test fixtures, partial-fill remainders that
        # round to zero).  Return early; the breakdown is all zeros.
        if quantity <= 0:
            return CostBreakdown(
                spread_cost=Decimal("0.00"),
                commission=Decimal("0.00"),
                total_fees=Decimal("0.00"),
                cost_bps=Decimal("0.00"),
                notional=notional,
            )

        # Spread cost: actual half-spread (stressed — spreads widen under
        # stress) with optional BPS floor (also stressed).
        # Semantic: the spread cost models the *cost of crossing the
        # spread*.  A maker (passive) fill rests at the BBO and by
        # definition does not cross — its spread cost is therefore
        # zero regardless of the quoted half-spread.  This matches the
        # passive-limit router's real fill semantics
        # (``_emit_passive_fill`` already passes ``half_spread=0``);
        # making the cost model itself zero out the maker spread keeps
        # callers like ``estimate_round_trip_cost_bps`` honest when
        # they pass the actual half-spread for a forward-looking
        # round-trip estimate.
        # The floor is similarly taker-only by default (it models a
        # worst-case taker spread when ``half_spread`` is artificially
        # zero, e.g. locked quotes).  Set ``spread_floor_taker_only=False``
        # to opt back into legacy behavior (floor charged on every leg).
        if is_taker:
            actual_spread_cost = half_spread * quantity * stress
            floor_spread_cost = (
                notional * self._cfg.min_spread_cost_bps * stress
                / Decimal("10000")
            )
            spread_cost = max(actual_spread_cost, floor_spread_cost)
        elif not self._cfg.spread_floor_taker_only:
            # Legacy opt-in: maker fills also pay the spread floor.
            actual_spread_cost = half_spread * quantity * stress
            floor_spread_cost = (
                notional * self._cfg.min_spread_cost_bps * stress
                / Decimal("10000")
            )
            spread_cost = max(actual_spread_cost, floor_spread_cost)
        else:
            spread_cost = Decimal("0")

        # IB Tiered commission: per-share + exchange pass-through.
        # Taker pays taker_exchange_per_share; maker receives the maker rebate.
        # ``stress_multiplier`` applies only to *variable* costs (the
        # per-share rate and the taker exchange fee).  The maker rebate
        # is NOT stressed (already conservative — never inflated under
        # stress).  The fixed ``min_commission`` floor and the
        # contractual ``max_commission_pct`` cap are also NOT stressed
        # — IBKR doesn't change its per-order thresholds under
        # volatility.  Stressing them would model an implausible
        # broker-side cost shock and disconnect the gate from real-cost
        # plausibility.
        stressed_commission = self._cfg.commission_per_share * stress
        if is_taker:
            exchange_per_share = self._cfg.taker_exchange_per_share * stress
        else:
            exchange_per_share = self._cfg.maker_exchange_per_share  # rebate, not stressed

        per_share_commission = stressed_commission * quantity
        exchange_fees = exchange_per_share * quantity
        if self._cfg.min_commission_applies_to_per_share_only:
            # IBKR Tiered: $0.35 minimum and 1% maximum BOTH apply to
            # the IB execution-fee per-share component only.  Exchange
            # and regulatory pass-throughs (and the maker rebate) layer
            # on top of the floored/capped IB commission.
            #
            # Floor first, then cap (matches the IBKR billing order:
            # floor brings small orders up to $0.35, then the 1% cap
            # brings penny-stock orders back down — but exchange fees
            # are uncapped pass-throughs and continue to accrue).
            per_share_commission = max(
                per_share_commission, self._cfg.min_commission
            )
            if notional > 0:
                max_ib_commission = (
                    notional * self._cfg.max_commission_pct / Decimal("100")
                )
                per_share_commission = min(per_share_commission, max_ib_commission)
            commission = per_share_commission + exchange_fees
        else:
            # Legacy bundled-floor mode (kept for opt-in parity).
            # Floors the *total* (per-share + exchange) at ``min_commission``,
            # which absorbs taker exchange fees inside the floor and
            # under-counts commission on small orders relative to IBKR.
            # In this mode the 1% cap is also applied to the bundled
            # total — consistent with the bundled floor.
            commission = max(
                per_share_commission + exchange_fees,
                self._cfg.min_commission,
            )
            if notional > 0:
                max_commission = (
                    notional * self._cfg.max_commission_pct / Decimal("100")
                )
                commission = min(commission, max_commission)

        # Passive adverse-selection penalty (maker fills only).
        # Through-fills (BBO crossed our limit) are the textbook
        # adverse-selection scenario and carry a higher bps charge
        # (F-H-09).  Notional is computed against ``adverse_notional_price``
        # when supplied (F-M-24: routers use the worse-side BBO so the
        # gate and realised path agree on the basis); else ``fill_price``.
        adverse_cost = Decimal("0")
        if not is_taker:
            adverse_bps = (
                self._cfg.through_fill_adverse_selection_bps
                if fill_type == "THROUGH"
                else self._cfg.passive_adverse_selection_bps
            )
            adverse_basis_price = (
                adverse_notional_price
                if adverse_notional_price is not None
                else fill_price
            )
            adverse_notional = adverse_basis_price * quantity
            adverse_cost = adverse_notional * adverse_bps * stress / Decimal("10000")

        # Sell-side regulatory fees.
        #   - SEC Section 31 fee: bps of notional on sells (modeled
        #     via ``sell_regulatory_bps``, stressed).
        #   - FINRA Trading Activity Fee: per-share on sells, capped
        #     per execution.  Per-share rate is variable (stressed);
        #     the cap is a fixed FINRA threshold (NOT stressed).
        regulatory_cost = Decimal("0")
        if side == Side.SELL:
            regulatory_cost = (
                notional * self._cfg.sell_regulatory_bps * stress
                / Decimal("10000")
            )
            if self._cfg.finra_taf_per_share > 0:
                taf = self._cfg.finra_taf_per_share * stress * quantity
                if self._cfg.finra_taf_max_per_order > 0:
                    taf = min(taf, self._cfg.finra_taf_max_per_order)
                regulatory_cost += taf

        # Hard-to-borrow (HTB) daily borrow cost for short-side sells.
        # Applied only when is_short=True and htb_borrow_annual_bps > 0.
        # Daily cost = notional × annual_bps / 360 / 10 000 — broker
        # convention is a 360-day year for stock-loan accruals, not 252
        # trading days.  Stressed to model borrow-fee spikes in
        # risk-off regimes.  Note: only ONE entry-day accrual is
        # charged here; multi-day holding accrual is a position-store
        # concern documented as a remaining gap.
        htb_cost = Decimal("0")
        if is_short and side == Side.SELL and self._cfg.htb_borrow_annual_bps > 0:
            htb_cost = (
                notional * self._cfg.htb_borrow_annual_bps * stress
                / Decimal("360") / Decimal("10000")
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
    ) -> CostBreakdown:
        notional = fill_price * quantity
        return CostBreakdown(
            spread_cost=Decimal("0"),
            commission=Decimal("0"),
            total_fees=Decimal("0"),
            cost_bps=Decimal("0"),
            notional=notional,
        )


def estimate_aggressive_taker_cost_bps(
    model: CostModel,
    *,
    symbol: str,
    side: Side,
    quantity: int,
    mid_price: Decimal,
    half_spread: Decimal,
    available_depth: int,
    market_impact_factor: Decimal,
    max_impact_half_spreads: Decimal,
    is_short: bool = False,
) -> float:
    """Estimate one-way taker ``cost_bps`` including walk-the-book impact.

    Mirrors ``_fill_helpers.emit_aggressive_fill`` — splits the order
    into an L1 leg (filling at mid against ``available_depth``) and an
    excess leg (filling at impact-adjusted mid).  Returns the
    weighted-by-quantity ``cost_bps`` summed across the two legs.

    Used by the orchestrator's B4 gate and the minimum-cost policy to
    price the aggressive route depth-aware (audit F-H-04).  Without
    this helper, both consumers assume a full L1 fill and silently
    under-price large orders against thin books.
    """
    if quantity <= 0 or available_depth <= 0:
        # No fill possible — degenerate; return 0 to let the caller
        # decide (the router itself will reject on zero depth).
        return 0.0

    if quantity <= available_depth:
        breakdown = model.compute(
            symbol, side, quantity, mid_price, half_spread,
            is_taker=True, is_short=is_short,
        )
        return float(breakdown.cost_bps)

    # Walk-the-book: L1 + excess.
    partial_qty = available_depth
    excess_qty = quantity - available_depth
    raw_impact = (
        market_impact_factor
        * Decimal(str(excess_qty))
        / Decimal(str(available_depth))
        * half_spread
    )
    impact_cap = max_impact_half_spreads * half_spread
    impact = min(raw_impact, impact_cap)
    if side == Side.BUY:
        impact_price = mid_price + impact
    else:
        impact_price = max(mid_price - impact, Decimal("0.01"))

    # Both legs evaluated against mid-notional so the impact is the
    # only side-dependent cost line.  ``impact * excess_qty`` is the
    # economic slippage on the walk-the-book leg; positive cost
    # regardless of side (BUY pays more, SELL receives less).
    partial = model.compute(
        symbol, side, partial_qty, mid_price, half_spread,
        is_taker=True, is_short=is_short,
    )
    excess = model.compute(
        symbol, side, excess_qty, mid_price, half_spread,
        is_taker=True, is_short=is_short,
    )
    total_notional = mid_price * Decimal(str(quantity))
    impact_cost = impact * Decimal(str(excess_qty))
    total_fees = partial.total_fees + excess.total_fees + impact_cost
    if total_notional <= 0:
        return 0.0
    return float(total_fees / total_notional * Decimal("10000"))


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
    is_taker_exit: bool | None = None,
    bid_size: int | None = None,
    ask_size: int | None = None,
    market_impact_factor: Decimal | None = None,
    max_impact_half_spreads: Decimal | None = None,
) -> float:
    """Sum model one-way ``cost_bps`` for an entry + flat-to-flat exit leg.

    Used by the orchestrator B4 gate (Inv-12 runtime complement to load-
    time G12).  Preserves sell-side regulatory fees and HTB on short-entry
    sells while using a symmetric exit (cover / close) without HTB.

    ``is_taker`` controls the entry-leg assumption.  ``is_taker_exit``,
    when provided, controls the exit-leg assumption independently.  When
    ``is_taker_exit is None`` the legacy symmetric behavior is preserved
    (``is_taker_exit = is_taker``).

    Why an asymmetric option matters: in the platform's passive-limit
    execution mode the entry is posted as a maker (``is_taker=False``)
    but the exit leg can still reach the router as MARKET — stop-loss
    exits, forced-flatten escalation, the ``_execute_reverse`` exit
    leg, and any cross-the-book maker that gets reclassified as taker
    by the marketability guard all bypass the passive path.  Treating
    both legs as maker therefore *understates* round-trip cost in the
    very paths most likely to actually trade — the conservative gate
    (preferred for IBKR-style realism) prices the exit leg as taker
    even when the entry is passive.
    """
    if is_taker_exit is None:
        is_taker_exit = is_taker
    entry_short = bool(is_short_entry and entry_side == Side.SELL)
    exit_side = Side.SELL if entry_side == Side.BUY else Side.BUY

    # Audit F-H-04: when depth + impact knobs are supplied, taker legs
    # use the depth-aware estimator (walks the book on excess qty).
    # Otherwise fall back to the legacy single-fill model.compute path.
    use_depth_aware = (
        bid_size is not None
        and ask_size is not None
        and market_impact_factor is not None
        and max_impact_half_spreads is not None
    )

    def _entry_bps() -> float:
        if is_taker and use_depth_aware:
            depth = ask_size if entry_side == Side.BUY else bid_size
            return estimate_aggressive_taker_cost_bps(
                model,
                symbol=symbol,
                side=entry_side,
                quantity=quantity,
                mid_price=mid_price,
                half_spread=half_spread,
                available_depth=int(depth or 0),
                market_impact_factor=market_impact_factor,  # type: ignore[arg-type]
                max_impact_half_spreads=max_impact_half_spreads,  # type: ignore[arg-type]
                is_short=entry_short,
            )
        return float(model.compute(
            symbol, entry_side, quantity, mid_price, half_spread,
            is_taker=is_taker, is_short=entry_short,
        ).cost_bps)

    def _exit_bps() -> float:
        if is_taker_exit and use_depth_aware:
            depth = ask_size if exit_side == Side.BUY else bid_size
            return estimate_aggressive_taker_cost_bps(
                model,
                symbol=symbol,
                side=exit_side,
                quantity=quantity,
                mid_price=mid_price,
                half_spread=half_spread,
                available_depth=int(depth or 0),
                market_impact_factor=market_impact_factor,  # type: ignore[arg-type]
                max_impact_half_spreads=max_impact_half_spreads,  # type: ignore[arg-type]
                is_short=False,
            )
        return float(model.compute(
            symbol, exit_side, quantity, mid_price, half_spread,
            is_taker=is_taker_exit, is_short=False,
        ).cost_bps)

    return _entry_bps() + _exit_bps()
