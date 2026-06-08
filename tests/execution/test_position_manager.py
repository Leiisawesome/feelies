"""Phase P0/P1 — position-manager contracts, legacy adapter, equivalence.

The critical guarantee: :class:`LegacyPositionManager` is byte-for-byte
faithful to :class:`SignalPositionTranslator`'s decision outcomes, so the
shadow harness can run it alongside the legacy path with zero divergence
(parity-neutral).  ``test_legacy_manager_matches_translator_truth_table``
is that proof.
"""

from __future__ import annotations

import pytest

from feelies.core.events import Side, Signal, SignalDirection
from feelies.execution.intent import SignalPositionTranslator, TradingIntent
from feelies.execution.position_manager import (
    ExecStyle,
    LegacyPositionManager,
    PlannedOrder,
    PlanLeg,
    PositionPlan,
    compare_plan_to_intent,
    desired_from_signal,
)
from feelies.portfolio.position_store import Position


def _signal(direction: SignalDirection, *, edge: float = 5.0) -> Signal:
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


# ── Equivalence: the legacy adapter == the translator ────────────────


class TestLegacyEquivalence:
    @pytest.mark.parametrize("direction", list(SignalDirection))
    @pytest.mark.parametrize("current", [-150, -100, -50, -1, 0, 1, 50, 100, 150])
    @pytest.mark.parametrize("target", [0, 1, 50, 100, 150])  # incl. directional-zero corner
    def test_legacy_manager_matches_translator_truth_table(
        self,
        direction: SignalDirection,
        current: int,
        target: int,
    ) -> None:
        translator = SignalPositionTranslator()
        manager = LegacyPositionManager()
        signal = _signal(direction)
        position = Position(symbol="AAPL", quantity=current)

        oi = translator.translate(signal, position, target)
        plan = manager.plan(
            desired=desired_from_signal(signal, target),
            current=position,
        )

        divergence = compare_plan_to_intent(
            intent_name=oi.intent.name,
            intent_target_quantity=oi.target_quantity,
            current_quantity=position.quantity,
            plan=plan,
            symbol=signal.symbol,
            signal_sequence=signal.sequence,
        )
        assert divergence is None, (
            f"dir={direction.name} cur={current} tgt={target}: "
            f"legacy={oi.intent.name}/{oi.target_quantity} "
            f"plan={plan.primary_leg.name}/{plan.total_quantity} ({divergence})"
        )

    def test_none_target_resolves_to_translator_default(self) -> None:
        # Both sides must apply the same default (100) on a None target.
        translator = SignalPositionTranslator(default_target_quantity=100)
        manager = LegacyPositionManager(default_target_quantity=100)
        signal = _signal(SignalDirection.LONG)
        position = Position(symbol="AAPL", quantity=0)

        oi = translator.translate(signal, position, None)
        plan = manager.plan(
            desired=desired_from_signal(signal, None),
            current=position,
        )
        assert oi.target_quantity == 100
        assert plan.total_quantity == 100
        assert compare_plan_to_intent(
            intent_name=oi.intent.name,
            intent_target_quantity=oi.target_quantity,
            current_quantity=position.quantity,
            plan=plan,
            symbol="AAPL",
            signal_sequence=signal.sequence,
        ) is None


# ── Direct plan classification ───────────────────────────────────────


class TestPlanClassification:
    def _plan(self, direction: SignalDirection, current: int, target: int) -> PositionPlan:
        return LegacyPositionManager().plan(
            desired=desired_from_signal(_signal(direction), target),
            current=Position(symbol="AAPL", quantity=current),
        )

    def test_flat_to_long_is_entry(self) -> None:
        plan = self._plan(SignalDirection.LONG, current=0, target=50)
        assert plan.primary_leg == PlanLeg.ENTRY
        assert plan.orders[0].side == Side.BUY
        assert plan.orders[0].quantity == 50
        assert plan.orders[0].style == ExecStyle.PASSIVE

    def test_scale_up_long(self) -> None:
        plan = self._plan(SignalDirection.LONG, current=30, target=80)
        assert plan.primary_leg == PlanLeg.SCALE_UP
        assert plan.total_quantity == 50

    def test_over_target_is_no_action_no_trim(self) -> None:
        # Legacy fidelity: a long already past target does NOT trim.
        plan = self._plan(SignalDirection.LONG, current=120, target=80)
        assert plan.orders == ()
        assert plan.primary_leg == PlanLeg.NO_ACTION

    def test_flat_signal_exits_full_position(self) -> None:
        plan = self._plan(SignalDirection.FLAT, current=70, target=0)
        assert plan.primary_leg == PlanLeg.EXIT
        assert plan.orders[0].side == Side.SELL
        assert plan.orders[0].quantity == 70
        assert plan.orders[0].style == ExecStyle.MARKET

    def test_reverse_long_to_short_two_legs(self) -> None:
        plan = self._plan(SignalDirection.SHORT, current=50, target=100)
        legs = [o.leg for o in plan.orders]
        assert legs == [PlanLeg.REVERSE_EXIT, PlanLeg.REVERSE_ENTRY]
        exit_leg, entry_leg = plan.orders
        assert exit_leg.side == Side.SELL and exit_leg.quantity == 50
        assert exit_leg.style == ExecStyle.MARKET
        assert entry_leg.side == Side.SELL and entry_leg.quantity == 100
        assert entry_leg.is_short is True
        # total == N + tgt, matching the legacy reverse intent quantity
        assert plan.total_quantity == 150

    def test_negative_target_rejected(self) -> None:
        with pytest.raises(ValueError):
            desired_from_signal(_signal(SignalDirection.LONG), -1)


# ── compare_plan_to_intent actually detects divergence ───────────────


class TestDivergenceDetection:
    def test_quantity_mismatch_flagged(self) -> None:
        plan = PositionPlan()  # NO_ACTION / qty 0
        div = compare_plan_to_intent(
            intent_name=TradingIntent.ENTRY_LONG.name,
            intent_target_quantity=50,
            current_quantity=0,
            plan=plan,
            symbol="AAPL",
            signal_sequence=1,
        )
        assert div is not None
        assert div.legacy_intent == "ENTRY_LONG"
        assert div.legacy_quantity == 50
        assert div.planner_quantity == 0

    def test_leg_mismatch_flagged(self) -> None:
        plan = PositionPlan(orders=(
            PlannedOrder(
                symbol="AAPL", side=Side.SELL, quantity=50,
                style=ExecStyle.MARKET, leg=PlanLeg.EXIT,
            ),
        ))
        div = compare_plan_to_intent(
            intent_name=TradingIntent.ENTRY_LONG.name,
            intent_target_quantity=50,
            current_quantity=0,
            plan=plan,
            symbol="AAPL",
            signal_sequence=1,
        )
        assert div is not None
        assert div.planner_leg == "EXIT"
