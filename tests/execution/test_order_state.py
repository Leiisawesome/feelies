from __future__ import annotations

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.state_machine import IllegalTransition
from feelies.execution.order_state import OrderState, create_order_state_machine


@pytest.fixture()
def clock() -> SimulatedClock:
    return SimulatedClock(start_ns=0)


class TestOrderStateMachine:
    def test_happy_path_created_to_filled(self, clock: SimulatedClock):
        sm = create_order_state_machine("o1", clock)
        assert sm.state == OrderState.CREATED

        sm.transition(OrderState.SUBMITTED, trigger="send")
        assert sm.state == OrderState.SUBMITTED

        sm.transition(OrderState.ACKNOWLEDGED, trigger="broker_ack")
        assert sm.state == OrderState.ACKNOWLEDGED

        sm.transition(OrderState.FILLED, trigger="fill")
        assert sm.state == OrderState.FILLED

    def test_rejection_path(self, clock: SimulatedClock):
        sm = create_order_state_machine("o2", clock)
        sm.transition(OrderState.SUBMITTED, trigger="send")
        sm.transition(OrderState.REJECTED, trigger="broker_reject")
        assert sm.state == OrderState.REJECTED

    def test_cancel_path(self, clock: SimulatedClock):
        sm = create_order_state_machine("o3", clock)
        sm.transition(OrderState.SUBMITTED, trigger="send")
        sm.transition(OrderState.ACKNOWLEDGED, trigger="broker_ack")
        sm.transition(OrderState.CANCEL_REQUESTED, trigger="user_cancel")
        sm.transition(OrderState.CANCELLED, trigger="cancel_confirmed")
        assert sm.state == OrderState.CANCELLED

    def test_fill_beats_cancel(self, clock: SimulatedClock):
        sm = create_order_state_machine("o4", clock)
        sm.transition(OrderState.SUBMITTED, trigger="send")
        sm.transition(OrderState.ACKNOWLEDGED, trigger="broker_ack")
        sm.transition(OrderState.CANCEL_REQUESTED, trigger="user_cancel")
        sm.transition(OrderState.FILLED, trigger="fill_before_cancel")
        assert sm.state == OrderState.FILLED

    def test_partial_fills_then_filled(self, clock: SimulatedClock):
        sm = create_order_state_machine("o5", clock)
        sm.transition(OrderState.SUBMITTED, trigger="send")
        sm.transition(OrderState.ACKNOWLEDGED, trigger="broker_ack")
        sm.transition(OrderState.PARTIALLY_FILLED, trigger="partial1")
        sm.transition(OrderState.PARTIALLY_FILLED, trigger="partial2")
        sm.transition(OrderState.FILLED, trigger="final_fill")
        assert sm.state == OrderState.FILLED

    def test_illegal_transition_created_to_filled(self, clock: SimulatedClock):
        sm = create_order_state_machine("o6", clock)
        with pytest.raises(IllegalTransition):
            sm.transition(OrderState.FILLED, trigger="skip")

    def test_illegal_transition_created_to_acknowledged(self, clock: SimulatedClock):
        sm = create_order_state_machine("o7", clock)
        with pytest.raises(IllegalTransition):
            sm.transition(OrderState.ACKNOWLEDGED, trigger="skip")

    @pytest.mark.parametrize("terminal_state", [
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
    ])
    def test_terminal_states_have_no_outbound(
        self, clock: SimulatedClock, terminal_state: OrderState
    ):
        sm = create_order_state_machine("term", clock)

        paths: dict[OrderState, list[tuple[OrderState, str]]] = {
            OrderState.FILLED: [
                (OrderState.SUBMITTED, "send"),
                (OrderState.ACKNOWLEDGED, "ack"),
                (OrderState.FILLED, "fill"),
            ],
            OrderState.CANCELLED: [
                (OrderState.SUBMITTED, "send"),
                (OrderState.ACKNOWLEDGED, "ack"),
                (OrderState.CANCEL_REQUESTED, "cancel"),
                (OrderState.CANCELLED, "confirmed"),
            ],
            OrderState.REJECTED: [
                (OrderState.SUBMITTED, "send"),
                (OrderState.REJECTED, "reject"),
            ],
            OrderState.EXPIRED: [
                (OrderState.SUBMITTED, "send"),
                (OrderState.ACKNOWLEDGED, "ack"),
                (OrderState.EXPIRED, "expire"),
            ],
        }

        for target, trigger in paths[terminal_state]:
            sm.transition(target, trigger=trigger)

        assert sm.state == terminal_state
        for candidate in OrderState:
            assert not sm.can_transition(candidate)

    def test_transition_records_history(self, clock: SimulatedClock):
        sm = create_order_state_machine("o8", clock)
        sm.transition(OrderState.SUBMITTED, trigger="send")
        sm.transition(OrderState.ACKNOWLEDGED, trigger="ack")

        history = sm.history
        assert len(history) == 2
        assert history[0].from_state == "CREATED"
        assert history[0].to_state == "SUBMITTED"
        assert history[1].from_state == "SUBMITTED"
        assert history[1].to_state == "ACKNOWLEDGED"

    def test_acknowledged_to_expired(self, clock: SimulatedClock):
        sm = create_order_state_machine("o9", clock)
        sm.transition(OrderState.SUBMITTED, trigger="send")
        sm.transition(OrderState.ACKNOWLEDGED, trigger="ack")
        sm.transition(OrderState.EXPIRED, trigger="timeout")
        assert sm.state == OrderState.EXPIRED
