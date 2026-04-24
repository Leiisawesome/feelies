"""Tests for the Phase-2 sensor / horizon micro-states.

These exercise the new transitions added by P2-α
(``SENSOR_UPDATE``, ``HORIZON_CHECK``, ``HORIZON_AGGREGATE``) and
verify the legacy fast-path (``STATE_UPDATE → FEATURE_COMPUTE``)
still works bit-for-bit when sensors are absent.
"""

from __future__ import annotations

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.state_machine import IllegalTransition
from feelies.kernel.micro import MicroState, create_micro_state_machine


@pytest.fixture
def clock() -> SimulatedClock:
    return SimulatedClock(start_ns=0)


class TestLegacyPathPreserved:
    def test_state_update_can_still_go_directly_to_feature_compute(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick_arrived")
        sm.transition(MicroState.STATE_UPDATE, trigger="event_logged")
        sm.transition(MicroState.FEATURE_COMPUTE, trigger="state_updated")
        assert sm.state == MicroState.FEATURE_COMPUTE


class TestSensorEnabledPath:
    def test_full_sensor_path_with_horizon_aggregate(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        for target, trigger in [
            (MicroState.MARKET_EVENT_RECEIVED, "tick_arrived"),
            (MicroState.STATE_UPDATE, "event_logged"),
            (MicroState.SENSOR_UPDATE, "state_updated"),
            (MicroState.HORIZON_CHECK, "sensors_updated"),
            (MicroState.HORIZON_AGGREGATE, "horizon_crossed"),
            (MicroState.FEATURE_COMPUTE, "snapshot_emitted"),
            (MicroState.SIGNAL_EVALUATE, "features_computed"),
            (MicroState.LOG_AND_METRICS, "no_signal"),
            (MicroState.WAITING_FOR_MARKET_EVENT, "tick_complete"),
        ]:
            sm.transition(target, trigger=trigger)
        assert sm.state == MicroState.WAITING_FOR_MARKET_EVENT

    def test_horizon_check_can_skip_aggregate_when_no_tick_crossed(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick_arrived")
        sm.transition(MicroState.STATE_UPDATE, trigger="event_logged")
        sm.transition(MicroState.SENSOR_UPDATE, trigger="state_updated")
        sm.transition(MicroState.HORIZON_CHECK, trigger="sensors_updated")
        sm.transition(MicroState.FEATURE_COMPUTE, trigger="no_horizon_crossed")
        assert sm.state == MicroState.FEATURE_COMPUTE


class TestIllegalTransitions:
    def test_sensor_update_cannot_skip_horizon_check(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick_arrived")
        sm.transition(MicroState.STATE_UPDATE, trigger="event_logged")
        sm.transition(MicroState.SENSOR_UPDATE, trigger="state_updated")
        with pytest.raises(IllegalTransition):
            sm.transition(MicroState.FEATURE_COMPUTE, trigger="invalid_skip")

    def test_state_update_cannot_jump_to_horizon_check(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick_arrived")
        sm.transition(MicroState.STATE_UPDATE, trigger="event_logged")
        with pytest.raises(IllegalTransition):
            sm.transition(MicroState.HORIZON_CHECK, trigger="invalid_skip")

    def test_horizon_aggregate_only_reaches_feature_compute(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        for target, trigger in [
            (MicroState.MARKET_EVENT_RECEIVED, "tick_arrived"),
            (MicroState.STATE_UPDATE, "event_logged"),
            (MicroState.SENSOR_UPDATE, "state_updated"),
            (MicroState.HORIZON_CHECK, "sensors_updated"),
            (MicroState.HORIZON_AGGREGATE, "horizon_crossed"),
        ]:
            sm.transition(target, trigger=trigger)
        with pytest.raises(IllegalTransition):
            sm.transition(MicroState.SIGNAL_EVALUATE, trigger="invalid_skip")
