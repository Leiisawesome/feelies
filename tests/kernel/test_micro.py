"""Tests for the micro (tick pipeline) state machine."""

from __future__ import annotations

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.state_machine import IllegalTransition
from feelies.kernel.micro import MicroState, create_micro_state_machine


@pytest.fixture
def clock() -> SimulatedClock:
    return SimulatedClock(start_ns=0)


class TestMicroInitialState:
    def test_starts_in_waiting(self, clock: SimulatedClock) -> None:
        sm = create_micro_state_machine(clock)
        assert sm.state == MicroState.WAITING_FOR_MARKET_EVENT

    def test_machine_name(self, clock: SimulatedClock) -> None:
        sm = create_micro_state_machine(clock)
        assert sm.name == "tick_pipeline"


class TestMicroFullPipeline:
    """M0→M1→M2→M3→M4→M5→M6→M7→M8→M9→M10→M0 (full order path)."""

    def test_full_pipeline_returns_to_waiting(self, clock: SimulatedClock) -> None:
        sm = create_micro_state_machine(clock)
        transitions = [
            (MicroState.MARKET_EVENT_RECEIVED, "tick_arrived"),
            (MicroState.STATE_UPDATE, "event_logged"),
            (MicroState.FEATURE_COMPUTE, "state_updated"),
            (MicroState.SIGNAL_EVALUATE, "features_computed"),
            (MicroState.RISK_CHECK, "signal_evaluated"),
            (MicroState.ORDER_DECISION, "risk_pass"),
            (MicroState.ORDER_SUBMIT, "order_constructed"),
            (MicroState.ORDER_ACK, "order_submitted"),
            (MicroState.POSITION_UPDATE, "order_acknowledged"),
            (MicroState.LOG_AND_METRICS, "position_updated"),
            (MicroState.WAITING_FOR_MARKET_EVENT, "tick_complete"),
        ]
        for target, trigger in transitions:
            sm.transition(target, trigger=trigger)
        assert sm.state == MicroState.WAITING_FOR_MARKET_EVENT

    def test_full_pipeline_history_length(self, clock: SimulatedClock) -> None:
        sm = create_micro_state_machine(clock)
        states = [
            MicroState.MARKET_EVENT_RECEIVED,
            MicroState.STATE_UPDATE,
            MicroState.FEATURE_COMPUTE,
            MicroState.SIGNAL_EVALUATE,
            MicroState.RISK_CHECK,
            MicroState.ORDER_DECISION,
            MicroState.ORDER_SUBMIT,
            MicroState.ORDER_ACK,
            MicroState.POSITION_UPDATE,
            MicroState.LOG_AND_METRICS,
            MicroState.WAITING_FOR_MARKET_EVENT,
        ]
        for s in states:
            sm.transition(s, trigger="t")
        assert len(sm.history) == 11

    def test_two_consecutive_ticks(self, clock: SimulatedClock) -> None:
        """Verify the pipeline can loop: M0→...→M10→M0→M1→...→M10→M0."""
        sm = create_micro_state_machine(clock)
        no_signal_path = [
            MicroState.MARKET_EVENT_RECEIVED,
            MicroState.STATE_UPDATE,
            MicroState.FEATURE_COMPUTE,
            MicroState.SIGNAL_EVALUATE,
            MicroState.LOG_AND_METRICS,
            MicroState.WAITING_FOR_MARKET_EVENT,
        ]
        for s in no_signal_path:
            sm.transition(s, trigger="t")
        assert sm.state == MicroState.WAITING_FOR_MARKET_EVENT

        for s in no_signal_path:
            sm.transition(s, trigger="t")
        assert sm.state == MicroState.WAITING_FOR_MARKET_EVENT


class TestMicroEarlyExitNoSignal:
    """M4 → M10 when no signal is produced."""

    def test_no_signal_exits_to_log(self, clock: SimulatedClock) -> None:
        sm = create_micro_state_machine(clock)
        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick_arrived")
        sm.transition(MicroState.STATE_UPDATE, trigger="event_logged")
        sm.transition(MicroState.FEATURE_COMPUTE, trigger="state_updated")
        sm.transition(MicroState.SIGNAL_EVALUATE, trigger="features_computed")
        sm.transition(MicroState.LOG_AND_METRICS, trigger="no_signal")
        assert sm.state == MicroState.LOG_AND_METRICS

        sm.transition(MicroState.WAITING_FOR_MARKET_EVENT, trigger="tick_complete")
        assert sm.state == MicroState.WAITING_FOR_MARKET_EVENT


class TestMicroEarlyExitRiskReject:
    """M5 → M10 when risk rejects."""

    def test_risk_reject_exits_to_log(self, clock: SimulatedClock) -> None:
        sm = create_micro_state_machine(clock)
        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick_arrived")
        sm.transition(MicroState.STATE_UPDATE, trigger="event_logged")
        sm.transition(MicroState.FEATURE_COMPUTE, trigger="state_updated")
        sm.transition(MicroState.SIGNAL_EVALUATE, trigger="features_computed")
        sm.transition(MicroState.RISK_CHECK, trigger="signal_evaluated")
        sm.transition(MicroState.LOG_AND_METRICS, trigger="risk_reject")
        assert sm.state == MicroState.LOG_AND_METRICS


class TestMicroEarlyExitOrderDecision:
    """M6 → M10 when check_order rejects (pre-submission veto)."""

    def test_order_decision_reject_exits_to_log(self, clock: SimulatedClock) -> None:
        sm = create_micro_state_machine(clock)
        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick_arrived")
        sm.transition(MicroState.STATE_UPDATE, trigger="event_logged")
        sm.transition(MicroState.FEATURE_COMPUTE, trigger="state_updated")
        sm.transition(MicroState.SIGNAL_EVALUATE, trigger="features_computed")
        sm.transition(MicroState.RISK_CHECK, trigger="signal_evaluated")
        sm.transition(MicroState.ORDER_DECISION, trigger="risk_pass")
        sm.transition(MicroState.LOG_AND_METRICS, trigger="check_order_rejected")
        assert sm.state == MicroState.LOG_AND_METRICS


class TestMicroReset:
    def test_reset_returns_to_waiting(self, clock: SimulatedClock) -> None:
        sm = create_micro_state_machine(clock)
        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick_arrived")
        sm.transition(MicroState.STATE_UPDATE, trigger="event_logged")
        sm.reset(trigger="abort")
        assert sm.state == MicroState.WAITING_FOR_MARKET_EVENT

    def test_reset_mid_pipeline_preserves_history(self, clock: SimulatedClock) -> None:
        sm = create_micro_state_machine(clock)
        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick_arrived")
        sm.reset(trigger="abort")
        assert len(sm.history) == 2  # transition + reset


class TestMicroIllegalTransitions:
    def test_cannot_skip_waiting_to_feature_compute(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        with pytest.raises(IllegalTransition):
            sm.transition(MicroState.FEATURE_COMPUTE, trigger="skip")

    def test_cannot_skip_waiting_to_order_submit(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        with pytest.raises(IllegalTransition):
            sm.transition(MicroState.ORDER_SUBMIT, trigger="skip")

    def test_cannot_go_backward(self, clock: SimulatedClock) -> None:
        sm = create_micro_state_machine(clock)
        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick_arrived")
        sm.transition(MicroState.STATE_UPDATE, trigger="event_logged")
        with pytest.raises(IllegalTransition):
            sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="backward")

    def test_cannot_skip_from_feature_to_order(self, clock: SimulatedClock) -> None:
        sm = create_micro_state_machine(clock)
        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick_arrived")
        sm.transition(MicroState.STATE_UPDATE, trigger="event_logged")
        sm.transition(MicroState.FEATURE_COMPUTE, trigger="state_updated")
        with pytest.raises(IllegalTransition):
            sm.transition(MicroState.ORDER_SUBMIT, trigger="skip_to_order")

    def test_log_and_metrics_cannot_go_to_order_submit(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick_arrived")
        sm.transition(MicroState.STATE_UPDATE, trigger="event_logged")
        sm.transition(MicroState.FEATURE_COMPUTE, trigger="state_updated")
        sm.transition(MicroState.SIGNAL_EVALUATE, trigger="features_computed")
        sm.transition(MicroState.LOG_AND_METRICS, trigger="no_signal")
        with pytest.raises(IllegalTransition):
            sm.transition(MicroState.ORDER_SUBMIT, trigger="illegal")
