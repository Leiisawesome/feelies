"""Position-management decision layer — contracts + legacy adapter (G-1).

Phase P0/P1 of ``docs/audits/position_management_design_proposal_2026-06-08.md``.

This module introduces the *contracts* for a unified, target-based
position-management decision layer and a :class:`LegacyPositionManager`
that reproduces today's 7-intent matrix **exactly** as a
:class:`PositionPlan`.  Nothing here drives execution yet — it is the
substrate for the shadow-equivalence harness wired into the orchestrator
(default-off, parity-neutral).

Design invariants (see the proposal):
  - Inv-5 (determinism): :meth:`PositionManager.plan` is a pure function
    of ``(desired, current, market, config)``.
  - Default-off parity: the legacy adapter is byte-for-byte faithful to
    :class:`~feelies.execution.intent.SignalPositionTranslator` +
    ``_execute_reverse`` / ``_try_build_order_from_intent`` *decision
    outcomes* — no TRIM, no cost gating, full-size MARKET exits/reverses.
  - Inv-11: reducing legs (EXIT / TRIM / REVERSE_EXIT) are never
    suppressed; only additive legs (ENTRY / SCALE_UP / REVERSE_ENTRY) are
    ever cost-gated (a property exercised by later phases, not P0/P1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Protocol

from decimal import Decimal

from feelies.core.events import NBBOQuote, Side, Signal, SignalDirection
from feelies.execution.cost_model import CostModel, estimate_round_trip_cost_bps
from feelies.execution.intent import OrderIntent, TradingIntent
from feelies.portfolio.position_store import Position


class PlanLeg(Enum):
    """A classified leg of a position plan.

    ``REVERSE_EXIT`` + ``REVERSE_ENTRY`` are the two legs a flip
    decomposes into (mirrors ``_execute_reverse``).  ``TRIM`` (partial
    same-direction reduce) is reserved for Phase P3 and is never emitted
    by :class:`LegacyPositionManager`.
    """

    NO_ACTION = auto()
    ENTRY = auto()
    SCALE_UP = auto()
    TRIM = auto()
    EXIT = auto()
    REVERSE_EXIT = auto()
    REVERSE_ENTRY = auto()


class ExecStyle(Enum):
    """How a planned order should be worked.

    Phase P0/P1 only ever uses the styles the legacy path already uses
    (passive entries, MARKET exits/reverses).  ``urgency``-driven style
    selection is a Phase-P4 capability (G-3).
    """

    PASSIVE = auto()
    MARKET = auto()


# Additive legs are the only legs the economic cost gate (B4/B5) may ever
# block (locked decision 3, 2026-06-08).  Reducing legs always execute.
ADDITIVE_LEGS: frozenset[PlanLeg] = frozenset(
    {PlanLeg.ENTRY, PlanLeg.SCALE_UP, PlanLeg.REVERSE_ENTRY}
)
REDUCING_LEGS: frozenset[PlanLeg] = frozenset(
    {PlanLeg.TRIM, PlanLeg.EXIT, PlanLeg.REVERSE_EXIT}
)


@dataclass(frozen=True, kw_only=True)
class DesiredPosition:
    """A desired per-symbol book state — the planner's input.

    Generalises :class:`~feelies.core.events.TargetPosition` (the
    PORTFOLIO path's existing target model) to a signed share target with
    the edge/urgency/provenance the decision needs.

    ``target_qty`` is **signed**: ``> 0`` long, ``< 0`` short, ``0`` flat.
    ``direction`` (+1 long / -1 short / 0 flat) disambiguates the desired
    *intent* when ``target_qty == 0`` — a directional signal that sized to
    zero (hold/clamp) vs. a genuine FLAT (exit).  For non-zero targets it
    is redundant with ``sign(target_qty)``.  The forward-looking planner
    keys on ``target_qty``; only the legacy adapter consults ``direction``
    to reproduce the legacy clamp faithfully.
    ``mandatory`` marks a risk-driven desired (stop / hazard / flatten /
    session-flat) that the planner must satisfy with the cost gate forced
    open (Inv-11).
    """

    symbol: str
    target_qty: int
    direction: int = 0
    edge_bps: float = 0.0
    urgency: float = 0.5
    source: str = ""
    reason: str = ""
    mandatory: bool = False


@dataclass(frozen=True, kw_only=True)
class MarketContext:
    """Market inputs the planner prices a disturbance against.

    Optional in P0/P1 — the legacy adapter does no cost math.  Carried so
    later phases fold B4/B5 into ``plan`` without a signature change.
    """

    quote: NBBOQuote | None = None
    cost_model: CostModel | None = None


@dataclass(frozen=True, kw_only=True)
class PlannedOrder:
    """One child order proposed by the planner, with its rationale."""

    symbol: str
    side: Side
    quantity: int
    style: ExecStyle
    leg: PlanLeg
    is_short: bool = False
    rationale: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SuppressedLeg:
    """A leg the planner declined to emit (for traces / alerts)."""

    leg: PlanLeg
    reason: str
    constraints: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class PositionPlan:
    """The planner's output: child orders + suppressed-leg rationale."""

    orders: tuple[PlannedOrder, ...] = ()
    suppressed: tuple[SuppressedLeg, ...] = ()

    @property
    def primary_leg(self) -> PlanLeg:
        """The leading leg (``REVERSE_EXIT`` for a flip, else the sole leg)."""
        return self.orders[0].leg if self.orders else PlanLeg.NO_ACTION

    @property
    def total_quantity(self) -> int:
        """Sum of child-order quantities (matches the legacy intent qty)."""
        return sum(o.quantity for o in self.orders)


@dataclass(frozen=True, kw_only=True)
class PositionManagerConfig:
    """Planner feature flags.  Defaults reproduce legacy behaviour."""

    enabled: bool = False     # drive execution from the plan (Phase P2+)
    shadow: bool = False      # run alongside legacy and record divergence
    enable_trim: bool = False  # emit TRIM legs (Phase P3 / G-2)


class PositionManager(Protocol):
    """Diff a desired book against the current book into a plan."""

    def plan(
        self,
        *,
        desired: DesiredPosition,
        current: Position,
        market: MarketContext,
        config: PositionManagerConfig,
    ) -> PositionPlan: ...


# ── Legacy adapter ───────────────────────────────────────────────────


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


class LegacyPositionManager:
    """Reproduce the legacy 7-intent matrix exactly, as a ``PositionPlan``.

    Faithful to :class:`SignalPositionTranslator`:
      - over-target same-direction → ``NO_ACTION`` (**no** TRIM)
      - entries are PASSIVE-style, exits/reverse-exits are MARKET-style
        (matching ``_try_build_order_from_intent`` / ``_execute_reverse``
        decision outcomes — execution mode still governs the concrete
        order type downstream)
      - no cost gating

    The ``default_target_quantity`` mirrors the translator's default so
    the ``None`` target path resolves identically.
    """

    def __init__(self, default_target_quantity: int = 100) -> None:
        self._default_target = default_target_quantity

    def plan(
        self,
        *,
        desired: DesiredPosition,
        current: Position,
        market: MarketContext | None = None,
        config: PositionManagerConfig | None = None,
    ) -> PositionPlan:
        cur = current.quantity
        sym = desired.symbol
        d = desired.direction or _sign(desired.target_qty)
        mag = abs(desired.target_qty)

        # Legacy *effective* target — the clamp the 7-intent matrix
        # encodes: a directional signal never reduces a same-direction
        # position (max/min), so |effective| >= |current| on the same
        # side.  A FLAT desired targets 0 (exit).
        if d > 0:
            eff = max(cur, mag)
        elif d < 0:
            eff = min(cur, -mag)
        else:
            eff = 0

        delta = eff - cur
        if delta == 0:
            return PositionPlan()  # legacy NO_ACTION

        # Sign flip with a non-zero residual → REVERSE (exit + entry).
        if cur != 0 and eff != 0 and (cur > 0) != (eff > 0):
            entry_side = Side.BUY if eff > 0 else Side.SELL
            return self._reverse_plan(
                sym, exit_qty=abs(cur), entry_qty=abs(eff),
                entry_side=entry_side, is_short=eff < 0,
            )

        # Pure reduce to flat → EXIT (covers the legacy degenerate-reverse
        # whose entry leg is zero: same single flatten order).
        if eff == 0:
            return PositionPlan(orders=(
                PlannedOrder(
                    symbol=sym,
                    side=Side.SELL if cur > 0 else Side.BUY,
                    quantity=abs(cur),
                    style=ExecStyle.MARKET,
                    leg=PlanLeg.EXIT,
                ),
            ))

        # Same-direction additive (ENTRY from flat, or SCALE_UP).  The
        # legacy clamp never produces a same-direction *reduce*, so TRIM
        # is unreachable here (it arrives in Phase P3 when the clamp is
        # dropped).
        leg = PlanLeg.ENTRY if cur == 0 else PlanLeg.SCALE_UP
        side = Side.BUY if delta > 0 else Side.SELL
        return PositionPlan(orders=(self._additive(
            sym, side, abs(delta), leg, is_short=eff < 0,
        ),))

    @staticmethod
    def _additive(
        sym: str, side: Side, qty: int, leg: PlanLeg, is_short: bool,
    ) -> PlannedOrder:
        return PlannedOrder(
            symbol=sym,
            side=side,
            quantity=qty,
            style=ExecStyle.PASSIVE,
            leg=leg,
            is_short=is_short,
        )

    @staticmethod
    def _reverse_plan(
        sym: str,
        *,
        exit_qty: int,
        entry_qty: int,
        entry_side: Side,
        is_short: bool,
    ) -> PositionPlan:
        # Mirror _execute_reverse: aggressive MARKET exit + (same-side) entry.
        exit_side = Side.BUY if entry_side == Side.BUY else Side.SELL
        return PositionPlan(orders=(
            PlannedOrder(
                symbol=sym,
                side=exit_side,
                quantity=exit_qty,
                style=ExecStyle.MARKET,
                leg=PlanLeg.REVERSE_EXIT,
            ),
            PlannedOrder(
                symbol=sym,
                side=entry_side,
                quantity=entry_qty,
                style=ExecStyle.PASSIVE,
                leg=PlanLeg.REVERSE_ENTRY,
                is_short=is_short,
            ),
        ))


# ── Cost gates (B4 entry / B5 reversal) — single source of truth ─────
#
# G-1 Phase P2: the edge-vs-cost economics live with the planner.  The
# orchestrator's live gate call sites delegate here, and the future
# cost-aware planner applies the same functions when it owns the live
# decision.  These are pure — no alerts, no side effects; callers own
# provenance/alerting and the no-op (disabled / no-cost-model) fast paths.


def round_trip_cost_bps(
    cost_model: CostModel,
    *,
    symbol: str,
    entry_side: Side,
    quantity: int,
    mid_price: Decimal,
    half_spread: Decimal,
    is_taker_entry: bool,
    is_short_entry: bool,
    bid_size: int | None = None,
    ask_size: int | None = None,
    market_impact_factor: Decimal | None = None,
    max_impact_half_spreads: Decimal | None = None,
) -> float:
    """Model round-trip (entry + *taker* exit) cost in bps for one leg.

    The exit leg is always priced as a taker (``is_taker_exit=True``) —
    the conservative assumption for IBKR-style realism, since exits and
    reverse-exits reach the router aggressively even when the entry is
    passive (see ``estimate_round_trip_cost_bps``).
    """
    return estimate_round_trip_cost_bps(
        cost_model,
        symbol=symbol,
        entry_side=entry_side,
        quantity=quantity,
        mid_price=mid_price,
        half_spread=half_spread,
        is_taker=is_taker_entry,
        is_taker_exit=True,
        is_short_entry=is_short_entry,
        bid_size=bid_size,
        ask_size=ask_size,
        market_impact_factor=market_impact_factor,
        max_impact_half_spreads=max_impact_half_spreads,
    )


def entry_edge_clears_cost(
    *,
    edge_bps: float,
    rt_cost_bps: float,
    min_ratio: float,
    basis: str,
) -> bool:
    """B4: True when the entry edge clears ``min_ratio ×`` round-trip cost.

    ``basis == "round_trip"`` doubles the disclosed one-way edge so both
    sides share the round-trip basis explicitly; ``"one_way"`` keeps the
    legacy comparison.
    """
    edge_basis = edge_bps * 2.0 if basis == "round_trip" else edge_bps
    return edge_basis >= min_ratio * rt_cost_bps


def reversal_edge_gate(
    *,
    edge_bps: float,
    exit_cost_bps: float,
    entry_cost_bps: float,
    multiplier: float,
) -> tuple[float, float, bool]:
    """B5: combined exit+entry edge gate for a flip.

    Returns ``(combined_cost_bps, required_bps, passes)`` where the flip
    passes iff ``edge_bps > (exit + entry) × multiplier``.
    """
    combined = exit_cost_bps + entry_cost_bps
    required = combined * multiplier
    return combined, required, edge_bps > required


# ── Signal → DesiredPosition adapter (orchestrator SIGNAL path) ───────


def desired_from_signal(
    signal: Signal,
    target_qty: int | None,
    *,
    default_target_quantity: int = 100,
) -> DesiredPosition:
    """Map a ``Signal`` + unsigned sizer target to a signed desired.

    Resolves the ``None`` target via ``default_target_quantity`` exactly
    as :class:`SignalPositionTranslator` does, so the shadow plan sees the
    same effective magnitude the legacy translator used.
    """
    tgt = target_qty if target_qty is not None else default_target_quantity
    if tgt < 0:
        raise ValueError(f"target_quantity must be non-negative, got {tgt}")
    if signal.direction == SignalDirection.LONG:
        target_signed, direction = tgt, 1
    elif signal.direction == SignalDirection.SHORT:
        target_signed, direction = -tgt, -1
    else:  # FLAT
        target_signed, direction = 0, 0
    return DesiredPosition(
        symbol=signal.symbol,
        target_qty=target_signed,
        direction=direction,
        edge_bps=signal.edge_estimate_bps,
        source=signal.strategy_id,
        reason="signal",
    )


# ── Plan → OrderIntent (drive-from-plan flip) ────────────────────────
#
# G-1 "the flip": when the orchestrator drives from the planner, the plan
# is projected back onto the existing ``OrderIntent`` so the battle-tested
# execution machinery (risk scaling, order-id hashing, MOC/passive/borrow
# routing, the B4/B5 gates) is reused unchanged.  For the legacy planner
# this reconstruction is *byte-faithful* to the translator — proven
# exhaustively by the equivalence test — so flipping ``drive`` on is
# parity-neutral while ``enable_trim`` is off.


def order_intent_from_plan(
    plan: PositionPlan,
    *,
    signal: Signal,
    current: Position,
) -> OrderIntent:
    """Project a ``PositionPlan`` back onto a legacy ``OrderIntent``.

    The ``target_quantity`` convention matches the translator: ENTRY/
    SCALE_UP carry the leg quantity, EXIT carries ``|current|``, and a
    REVERSE carries ``exit + entry`` (== ``plan.total_quantity`` for both
    the two-leg flip and the degenerate exit-only flip).
    """
    cur = current.quantity

    def _oi(intent: TradingIntent, target: int) -> OrderIntent:
        return OrderIntent(
            intent=intent,
            symbol=signal.symbol,
            strategy_id=signal.strategy_id,
            target_quantity=target,
            current_quantity=cur,
            signal=signal,
        )

    if not plan.orders:
        return _oi(TradingIntent.NO_ACTION, 0)

    leg = plan.primary_leg
    # A flip is keyed on the *current* side: long→short when currently long.
    reverse_intent = (
        TradingIntent.REVERSE_LONG_TO_SHORT if cur > 0
        else TradingIntent.REVERSE_SHORT_TO_LONG
    )

    if leg in (PlanLeg.REVERSE_EXIT, PlanLeg.REVERSE_ENTRY):
        return _oi(reverse_intent, plan.total_quantity)
    if leg is PlanLeg.EXIT:
        # A FLAT signal is a genuine EXIT; a *directional* signal that
        # sized to zero against an opposite book is the legacy degenerate
        # REVERSE (exit-only).  Preserving that label keeps the order-id
        # hashing — and thus parity — byte-identical.
        if signal.direction == SignalDirection.FLAT:
            return _oi(TradingIntent.EXIT, plan.total_quantity)
        return _oi(reverse_intent, plan.total_quantity)
    if leg is PlanLeg.SCALE_UP:
        return _oi(TradingIntent.SCALE_UP, plan.total_quantity)
    if leg is PlanLeg.ENTRY:
        intent = (
            TradingIntent.ENTRY_LONG if plan.orders[0].side == Side.BUY
            else TradingIntent.ENTRY_SHORT
        )
        return _oi(intent, plan.total_quantity)
    if leg is PlanLeg.TRIM:
        # TRIM has no legacy OrderIntent (partial same-direction reduce).
        # It is unreachable while ``enable_trim`` is off; Phase P3 adds the
        # partial-reduce execution path.
        raise NotImplementedError(
            "TRIM legs require the Phase-P3 partial-reduce path"
        )
    return _oi(TradingIntent.NO_ACTION, 0)


# ── Shadow-equivalence comparison ────────────────────────────────────
#
# Equivalence is defined at the **order** level, not the label level:
# the plan agrees with legacy iff it would submit the same multiset of
# ``(side, quantity)`` child orders.  This is the parity-relevant notion
# (the parity hash keys on submitted orders, not intent labels) and it
# correctly treats the legacy degenerate-``REVERSE`` (a directional
# signal that sizes to 0 against an opposite position → exit-only, entry
# leg zero) as equal to the planner's ``EXIT`` — same flatten order.


def _legacy_orders(
    intent_name: str,
    target_quantity: int,
    current_quantity: int,
) -> list[tuple[Side, int]] | None:
    """Reconstruct the (side, qty) child orders the legacy path emits.

    Mirrors ``SignalPositionTranslator`` + ``_execute_reverse`` /
    ``_try_build_order_from_intent`` decomposition.  ``None`` when the
    intent name is unknown.  Sub-``min_order_shares`` filtering is an
    execution concern applied downstream and is *not* modelled here —
    zero-quantity legs are dropped by :func:`_norm`, which suffices for
    the decision-level equivalence the shadow harness asserts.
    """
    cur = current_quantity
    try:
        ti = TradingIntent[intent_name]
    except KeyError:
        return None
    if ti is TradingIntent.NO_ACTION:
        return []
    if ti is TradingIntent.ENTRY_LONG:
        return [(Side.BUY, target_quantity)]
    if ti is TradingIntent.ENTRY_SHORT:
        return [(Side.SELL, target_quantity)]
    if ti is TradingIntent.EXIT:
        return [(Side.SELL if cur > 0 else Side.BUY, target_quantity)]
    if ti is TradingIntent.SCALE_UP:
        return [(Side.BUY if cur > 0 else Side.SELL, target_quantity)]
    if ti is TradingIntent.REVERSE_LONG_TO_SHORT:
        return [(Side.SELL, abs(cur)), (Side.SELL, target_quantity - abs(cur))]
    if ti is TradingIntent.REVERSE_SHORT_TO_LONG:
        return [(Side.BUY, abs(cur)), (Side.BUY, target_quantity - abs(cur))]
    return None


def _norm(orders: list[tuple[Side, int]]) -> list[tuple[str, int]]:
    """Canonical, zero-dropped, order-independent form for comparison."""
    return sorted((s.name, q) for s, q in orders if q > 0)


@dataclass(frozen=True, kw_only=True)
class PlanDivergence:
    """A recorded mismatch between the legacy and shadow-plan order sets."""

    symbol: str
    signal_sequence: int
    legacy_intent: str
    legacy_quantity: int
    planner_leg: str
    planner_quantity: int
    detail: str


def compare_plan_to_intent(
    *,
    intent_name: str,
    intent_target_quantity: int,
    current_quantity: int,
    plan: PositionPlan,
    symbol: str,
    signal_sequence: int,
) -> PlanDivergence | None:
    """Return a :class:`PlanDivergence` iff the plan's orders disagree."""
    legacy = _legacy_orders(
        intent_name, intent_target_quantity, current_quantity,
    )
    legacy_n = _norm(legacy) if legacy is not None else None
    plan_n = _norm([(o.side, o.quantity) for o in plan.orders])
    if legacy_n == plan_n:
        return None
    return PlanDivergence(
        symbol=symbol,
        signal_sequence=signal_sequence,
        legacy_intent=intent_name,
        legacy_quantity=intent_target_quantity,
        planner_leg=plan.primary_leg.name,
        planner_quantity=plan.total_quantity,
        detail=f"legacy_orders={legacy_n} plan_orders={plan_n}",
    )
