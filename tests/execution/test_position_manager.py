"""Phase P0/P1 — position-manager contracts, translator adapter, equivalence.

The critical guarantee: :class:`LegacyPositionManager` is byte-for-byte
faithful to :class:`SignalPositionTranslator`'s decision outcomes, so the
shadow harness can run it alongside the translator path with zero
divergence (parity-neutral).
``test_legacy_manager_matches_translator_truth_table`` is that proof.
"""

from __future__ import annotations

import pytest

from feelies.core.events import Side, Signal, SignalDirection
from feelies.execution.intent import SignalPositionTranslator, TradingIntent
from feelies.execution.position_manager import (
    DesiredPosition,
    ExecStyle,
    LegacyPositionManager,
    PlannedOrder,
    PlanLeg,
    PositionManagerConfig,
    PositionPlan,
    TargetPositionManager,
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
        assert (
            compare_plan_to_intent(
                intent_name=oi.intent.name,
                intent_target_quantity=oi.target_quantity,
                current_quantity=position.quantity,
                plan=plan,
                symbol="AAPL",
                signal_sequence=signal.sequence,
            )
            is None
        )


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
            plan,
            signal=signal,
            current=position,
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
            desired=desired_from_signal(signal, None),
            current=position,
        )
        assert (
            order_intent_from_plan(
                plan,
                signal=signal,
                current=position,
            )
            == legacy
        )


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
        # Translator fidelity: a long already past target does NOT trim.
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
            edge_bps=20.0,
            rt_cost_bps=10.0,
            min_ratio=2.0,
            basis="one_way",
        )
        assert not entry_edge_clears_cost(
            edge_bps=19.9,
            rt_cost_bps=10.0,
            min_ratio=2.0,
            basis="one_way",
        )
        # round_trip basis doubles the one-way edge before comparing.
        assert entry_edge_clears_cost(
            edge_bps=10.0,
            rt_cost_bps=10.0,
            min_ratio=2.0,
            basis="round_trip",
        )

    def test_reversal_edge_gate_math(self) -> None:
        from feelies.execution.position_manager import reversal_edge_gate

        combined, required, passes = reversal_edge_gate(
            edge_bps=30.0,
            exit_cost_bps=4.0,
            entry_cost_bps=4.0,
            multiplier=2.0,
        )
        assert combined == 8.0
        assert required == 16.0
        assert passes is True  # 30 > 16
        _, _, blocked = reversal_edge_gate(
            edge_bps=5.0,
            exit_cost_bps=4.0,
            entry_cost_bps=4.0,
            multiplier=2.0,
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
            symbol="AAPL",
            entry_side=Side.BUY,
            quantity=100,
            mid_price=Decimal("100"),
            half_spread=Decimal("0.05"),
            is_short_entry=False,
            bid_size=100,
            ask_size=200,
            market_impact_factor=Decimal("0.5"),
            max_impact_half_spreads=Decimal("10"),
        )
        got = round_trip_cost_bps(model, is_taker_entry=True, **kw)
        assert got > 0
        # Equivalent to the cost-model helper with a forced taker exit.
        expected = estimate_round_trip_cost_bps(
            model,
            is_taker=True,
            is_taker_exit=True,
            **kw,
        )
        assert got == expected


# ── P3: cost-aware TRIM ──────────────────────────────────────────────


class TestTargetPositionManagerTrim:
    @pytest.mark.parametrize("direction", list(SignalDirection))
    @pytest.mark.parametrize("current", [-150, -50, 0, 50, 150])
    @pytest.mark.parametrize("target", [0, 50, 100, 150])
    def test_trim_off_is_byte_identical_to_legacy(
        self,
        direction: SignalDirection,
        current: int,
        target: int,
    ) -> None:
        legacy = LegacyPositionManager()
        tgt = TargetPositionManager()
        signal = _signal(direction)
        pos = Position(symbol="AAPL", quantity=current)
        desired = desired_from_signal(signal, target)
        # No config / trim disabled → identical plans.
        a = legacy.plan(desired=desired, current=pos)
        b = tgt.plan(
            desired=desired,
            current=pos,
            config=PositionManagerConfig(enable_trim=False),
        )
        assert [(o.side, o.quantity, o.leg) for o in a.orders] == [
            (o.side, o.quantity, o.leg) for o in b.orders
        ]

    def test_trim_emitted_on_same_direction_shrink(self) -> None:
        mgr = TargetPositionManager(trim_min_fraction=0.10)
        pos = Position(symbol="AAPL", quantity=150)  # long 150
        desired = DesiredPosition(symbol="AAPL", target_qty=100, direction=1)
        plan = mgr.plan(
            desired=desired,
            current=pos,
            config=PositionManagerConfig(enable_trim=True),
        )
        assert len(plan.orders) == 1
        leg = plan.orders[0]
        assert leg.leg == PlanLeg.TRIM
        assert leg.side == Side.SELL
        assert leg.quantity == 50  # 150 → 100
        # LegacyPositionManager (translator-equivalent) would hold (NO_ACTION).
        assert (
            LegacyPositionManager()
            .plan(
                desired=desired,
                current=pos,
            )
            .orders
            == ()
        )

    def test_short_trim_covers_partially(self) -> None:
        mgr = TargetPositionManager(trim_min_fraction=0.10)
        pos = Position(symbol="AAPL", quantity=-150)  # short 150
        desired = DesiredPosition(symbol="AAPL", target_qty=-100, direction=-1)
        plan = mgr.plan(
            desired=desired,
            current=pos,
            config=PositionManagerConfig(enable_trim=True),
        )
        leg = plan.orders[0]
        assert leg.leg == PlanLeg.TRIM
        assert leg.side == Side.BUY  # reduce a short = buy to cover
        assert leg.quantity == 50

    def test_churn_guard_suppresses_tiny_trim(self) -> None:
        mgr = TargetPositionManager(trim_min_fraction=0.10)
        pos = Position(symbol="AAPL", quantity=150)
        # 150 → 145 is a 5-share trim; threshold = ceil(0.10*150)=15 → hold.
        desired = DesiredPosition(symbol="AAPL", target_qty=145, direction=1)
        plan = mgr.plan(
            desired=desired,
            current=pos,
            config=PositionManagerConfig(enable_trim=True),
        )
        assert plan.orders == ()
        assert plan.suppressed and plan.suppressed[0].reason == "trim_below_churn_threshold"

    def test_trim_does_not_touch_entry_or_reverse(self) -> None:
        mgr = TargetPositionManager()
        cfg = PositionManagerConfig(enable_trim=True)
        # entry from flat
        entry = mgr.plan(
            desired=DesiredPosition(symbol="AAPL", target_qty=100, direction=1),
            current=Position(symbol="AAPL", quantity=0),
            config=cfg,
        )
        assert entry.primary_leg == PlanLeg.ENTRY
        # reverse (opposite-side target)
        rev = mgr.plan(
            desired=DesiredPosition(symbol="AAPL", target_qty=-100, direction=-1),
            current=Position(symbol="AAPL", quantity=50),
            config=cfg,
        )
        assert rev.primary_leg == PlanLeg.REVERSE_EXIT

    def _market_ctx(self):
        from decimal import Decimal

        from feelies.core.events import NBBOQuote
        from feelies.execution.cost_model import (
            DefaultCostModel,
            DefaultCostModelConfig,
        )
        from feelies.execution.position_manager import MarketContext

        quote = NBBOQuote(
            timestamp_ns=1000,
            correlation_id="c",
            sequence=1,
            symbol="AAPL",
            bid=Decimal("99.95"),
            ask=Decimal("100.05"),
            bid_size=100,
            ask_size=200,
            exchange_timestamp_ns=900,
        )
        return MarketContext(
            quote=quote,
            cost_model=DefaultCostModel(DefaultCostModelConfig()),
        )

    def test_edge_gate_holds_when_edge_still_clears_cost(self) -> None:
        # High forward edge → the target dip is noise → hold (no trim).
        mgr = TargetPositionManager(trim_min_fraction=0.10)
        pos = Position(symbol="AAPL", quantity=150)
        desired = DesiredPosition(
            symbol="AAPL",
            target_qty=100,
            direction=1,
            edge_bps=10_000.0,
        )
        plan = mgr.plan(
            desired=desired,
            current=pos,
            market=self._market_ctx(),
            config=PositionManagerConfig(
                enable_trim=True,
                trim_edge_gate_multiplier=1.0,
            ),
        )
        assert plan.orders == ()
        assert plan.suppressed[0].reason == "trim_edge_above_gate"

    def test_edge_gate_trims_when_edge_below_cost(self) -> None:
        # Negligible forward edge → the excess is dead weight → trim.
        mgr = TargetPositionManager(trim_min_fraction=0.10)
        pos = Position(symbol="AAPL", quantity=150)
        desired = DesiredPosition(
            symbol="AAPL",
            target_qty=100,
            direction=1,
            edge_bps=0.0,
        )
        plan = mgr.plan(
            desired=desired,
            current=pos,
            market=self._market_ctx(),
            config=PositionManagerConfig(
                enable_trim=True,
                trim_edge_gate_multiplier=1.0,
            ),
        )
        assert plan.primary_leg == PlanLeg.TRIM
        assert plan.orders[0].quantity == 50

    def test_edge_gate_off_trims_regardless_of_edge(self) -> None:
        # multiplier 0 → gate inert → churn-guard-only trim even on high edge.
        mgr = TargetPositionManager(trim_min_fraction=0.10)
        pos = Position(symbol="AAPL", quantity=150)
        desired = DesiredPosition(
            symbol="AAPL",
            target_qty=100,
            direction=1,
            edge_bps=10_000.0,
        )
        plan = mgr.plan(
            desired=desired,
            current=pos,
            market=self._market_ctx(),
            config=PositionManagerConfig(
                enable_trim=True,
                trim_edge_gate_multiplier=0.0,
            ),
        )
        assert plan.primary_leg == PlanLeg.TRIM

    def test_edge_gate_inert_without_cost_model(self) -> None:
        # No cost model → gate cannot price → trim on churn guard (fail-safe).
        mgr = TargetPositionManager(trim_min_fraction=0.10)
        pos = Position(symbol="AAPL", quantity=150)
        desired = DesiredPosition(
            symbol="AAPL",
            target_qty=100,
            direction=1,
            edge_bps=10_000.0,
        )
        plan = mgr.plan(
            desired=desired,
            current=pos,
            config=PositionManagerConfig(
                enable_trim=True,
                trim_edge_gate_multiplier=1.0,
            ),
        )
        assert plan.primary_leg == PlanLeg.TRIM

    def test_urgency_exec_makes_trim_passive(self) -> None:
        mgr = TargetPositionManager(trim_min_fraction=0.10)
        pos = Position(symbol="AAPL", quantity=150)
        desired = DesiredPosition(symbol="AAPL", target_qty=100, direction=1)
        passive = mgr.plan(
            desired=desired,
            current=pos,
            config=PositionManagerConfig(enable_trim=True, urgency_exec=True),
        )
        assert passive.orders[0].style == ExecStyle.PASSIVE
        aggressive = mgr.plan(
            desired=desired,
            current=pos,
            config=PositionManagerConfig(enable_trim=True, urgency_exec=False),
        )
        assert aggressive.orders[0].style == ExecStyle.MARKET

    def test_trim_leg_maps_to_partial_exit_intent(self) -> None:
        from feelies.execution.intent import TradingIntent

        signal = _signal(SignalDirection.LONG)
        pos = Position(symbol="AAPL", quantity=150)
        plan = TargetPositionManager(trim_min_fraction=0.10).plan(
            desired=DesiredPosition(symbol="AAPL", target_qty=100, direction=1),
            current=pos,
            config=PositionManagerConfig(enable_trim=True),
        )
        oi = order_intent_from_plan(plan, signal=signal, current=pos)
        assert oi.intent == TradingIntent.EXIT  # executes via the EXIT path
        assert oi.target_quantity == 50  # partial, not |current|


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
        plan = PositionPlan(
            orders=(
                PlannedOrder(
                    symbol="AAPL",
                    side=Side.SELL,
                    quantity=50,
                    style=ExecStyle.MARKET,
                    leg=PlanLeg.EXIT,
                ),
            )
        )
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
