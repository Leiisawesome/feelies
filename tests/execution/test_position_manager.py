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
    order_intent_from_plan,
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


# ── The flip: plan → OrderIntent is byte-faithful to the translator ──


class TestOrderIntentFromPlan:
    @pytest.mark.parametrize("direction", list(SignalDirection))
    @pytest.mark.parametrize("current", [-150, -100, -50, -1, 0, 1, 50, 100, 150])
    @pytest.mark.parametrize("target", [0, 1, 50, 100, 150])
    def test_reconstructed_intent_equals_translator(
        self,
        direction: SignalDirection,
        current: int,
        target: int,
    ) -> None:
        # The drive path (plan -> OrderIntent) must reproduce the exact
        # OrderIntent the legacy translator produces — the parity proof for
        # flipping `drive` on while `enable_trim` is off.
        translator = SignalPositionTranslator()
        manager = LegacyPositionManager()
        signal = _signal(direction)
        position = Position(symbol="AAPL", quantity=current)

        legacy = translator.translate(signal, position, target)
        plan = manager.plan(
            desired=desired_from_signal(signal, target),
            current=position,
        )
        reconstructed = order_intent_from_plan(
            plan, signal=signal, current=position,
        )

        assert reconstructed == legacy, (
            f"dir={direction.name} cur={current} tgt={target}: "
            f"legacy={legacy.intent.name}/{legacy.target_quantity} "
            f"recon={reconstructed.intent.name}/{reconstructed.target_quantity}"
        )

    def test_none_target_reconstructs_identically(self) -> None:
        translator = SignalPositionTranslator(default_target_quantity=100)
        manager = LegacyPositionManager(default_target_quantity=100)
        signal = _signal(SignalDirection.SHORT)
        position = Position(symbol="AAPL", quantity=0)
        legacy = translator.translate(signal, position, None)
        plan = manager.plan(
            desired=desired_from_signal(signal, None), current=position,
        )
        assert order_intent_from_plan(
            plan, signal=signal, current=position,
        ) == legacy


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


# ── Cost gates (B4/B5) — single source of truth ──────────────────────


class TestCostGates:
    def test_entry_edge_clears_cost_boundary_and_basis(self) -> None:
        from feelies.execution.position_manager import entry_edge_clears_cost
        # one_way: clears when edge >= ratio * cost (boundary inclusive).
        assert entry_edge_clears_cost(
            edge_bps=20.0, rt_cost_bps=10.0, min_ratio=2.0, basis="one_way",
        )
        assert not entry_edge_clears_cost(
            edge_bps=19.9, rt_cost_bps=10.0, min_ratio=2.0, basis="one_way",
        )
        # round_trip basis doubles the one-way edge before comparing.
        assert entry_edge_clears_cost(
            edge_bps=10.0, rt_cost_bps=10.0, min_ratio=2.0, basis="round_trip",
        )

    def test_reversal_edge_gate_math(self) -> None:
        from feelies.execution.position_manager import reversal_edge_gate
        combined, required, passes = reversal_edge_gate(
            edge_bps=30.0, exit_cost_bps=4.0, entry_cost_bps=4.0, multiplier=2.0,
        )
        assert combined == 8.0
        assert required == 16.0
        assert passes is True  # 30 > 16
        _, _, blocked = reversal_edge_gate(
            edge_bps=5.0, exit_cost_bps=4.0, entry_cost_bps=4.0, multiplier=2.0,
        )
        assert blocked is False  # 5 !> 16

    def test_round_trip_cost_bps_is_positive_taker_exit(self) -> None:
        from decimal import Decimal

        from feelies.execution.cost_model import (
            DefaultCostModel,
            DefaultCostModelConfig,
            estimate_round_trip_cost_bps,
        )
        from feelies.execution.position_manager import round_trip_cost_bps
        model = DefaultCostModel(DefaultCostModelConfig())
        kw = dict(
            symbol="AAPL", entry_side=Side.BUY, quantity=100,
            mid_price=Decimal("100"), half_spread=Decimal("0.05"),
            is_short_entry=False, bid_size=100, ask_size=200,
            market_impact_factor=Decimal("0.5"),
            max_impact_half_spreads=Decimal("10"),
        )
        got = round_trip_cost_bps(model, is_taker_entry=True, **kw)
        assert got > 0
        # Equivalent to the cost-model helper with a forced taker exit.
        expected = estimate_round_trip_cost_bps(
            model, is_taker=True, is_taker_exit=True, **kw,
        )
        assert got == expected


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
