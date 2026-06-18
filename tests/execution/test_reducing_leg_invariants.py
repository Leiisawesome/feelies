"""Audit P1.4 (2026-06-18): reducing-leg invariants in one discoverable place.

Decision-path exit coverage is otherwise scattered across
``tests/kernel/test_orchestrator*.py``.  This module concentrates the
structural contract that the audit relied on — *reducing legs are never
cost-gated and route through the never-min-lot-filtered EXIT path* — so the
guarantee is greppable and a regression is obvious.

It pins the contract at the planner / projection boundary (data-free); the
orchestrator enforces the runtime carve-out at
``orchestrator.py`` ``_try_build_order_from_intent`` (the ``is_exit_or_stop``
branch exempts ``TradingIntent.EXIT`` from both ``min_order_shares`` and the
B4 edge-cost gate).
"""

from __future__ import annotations

import random

from feelies.core.events import Side, Signal, SignalDirection
from feelies.execution.intent import TradingIntent
from feelies.execution.position_manager import (
    ADDITIVE_LEGS,
    REDUCING_LEGS,
    DesiredPosition,
    PlanLeg,
    PositionManagerConfig,
    TargetPositionManager,
    order_intent_from_plan,
)
from feelies.portfolio.position_store import Position


def _signal(direction: SignalDirection, *, edge: float = 0.0) -> Signal:
    return Signal(
        timestamp_ns=1000,
        correlation_id="c",
        sequence=7,
        symbol="AAPL",
        strategy_id="s",
        direction=direction,
        strength=0.8,
        edge_estimate_bps=edge,
    )


class TestLegClassificationDisjoint:
    def test_additive_and_reducing_are_disjoint(self) -> None:
        # The B4/B5 cost gate may only ever block an ADDITIVE leg; a leg
        # cannot be both, or a reducing leg could be cost-gated (Inv-11).
        assert ADDITIVE_LEGS.isdisjoint(REDUCING_LEGS)

    def test_reducing_legs_are_exactly_the_de_risking_set(self) -> None:
        assert REDUCING_LEGS == frozenset(
            {PlanLeg.TRIM, PlanLeg.EXIT, PlanLeg.REVERSE_EXIT}
        )

    def test_additive_legs_are_exactly_the_exposure_increasing_set(self) -> None:
        assert ADDITIVE_LEGS == frozenset(
            {PlanLeg.ENTRY, PlanLeg.SCALE_UP, PlanLeg.REVERSE_ENTRY}
        )


class TestReducingLegsProjectToExitIntent:
    """Every reducing leg projects onto the EXIT intent the orchestrator
    exempts from min-lot + B4 (so it can never be starved economically)."""

    def test_trim_projects_to_exit_intent(self) -> None:
        mgr = TargetPositionManager(trim_min_fraction=0.10)
        pos = Position(symbol="AAPL", quantity=150)
        plan = mgr.plan(
            desired=DesiredPosition(symbol="AAPL", target_qty=100, direction=1),
            current=pos,
            config=PositionManagerConfig(enable_trim=True),
        )
        assert plan.primary_leg is PlanLeg.TRIM
        oi = order_intent_from_plan(plan, signal=_signal(SignalDirection.LONG), current=pos)
        assert oi.intent is TradingIntent.EXIT

    def test_flat_exit_projects_to_exit_intent(self) -> None:
        mgr = TargetPositionManager()
        pos = Position(symbol="AAPL", quantity=150)
        plan = mgr.plan(
            desired=DesiredPosition(symbol="AAPL", target_qty=0, direction=0),
            current=pos,
        )
        assert plan.primary_leg is PlanLeg.EXIT
        oi = order_intent_from_plan(plan, signal=_signal(SignalDirection.FLAT), current=pos)
        assert oi.intent is TradingIntent.EXIT


class TestReducingLegNeverOvershoots:
    """A reduce/trim never proposes more shares than are open (it cannot
    flip the book by itself — that is a REVERSE, a two-leg plan)."""

    def test_trim_quantity_never_exceeds_open_position(self) -> None:
        rng = random.Random(20260618)
        mgr = TargetPositionManager(trim_min_fraction=0.10)
        for _ in range(500):
            cur = rng.randint(1, 500)
            sign = rng.choice((1, -1))
            current_qty = sign * cur
            # Same-direction target strictly below the open size → trim.
            target_mag = rng.randint(0, cur)
            plan = mgr.plan(
                desired=DesiredPosition(
                    symbol="AAPL",
                    target_qty=sign * target_mag,
                    direction=sign,
                ),
                current=Position(symbol="AAPL", quantity=current_qty),
                config=PositionManagerConfig(enable_trim=True),
            )
            for order in plan.orders:
                if order.leg in REDUCING_LEGS:
                    assert order.quantity <= abs(current_qty)
                    # A pure reduce is on the closing side of the book.
                    expected = Side.SELL if current_qty > 0 else Side.BUY
                    assert order.side is expected
