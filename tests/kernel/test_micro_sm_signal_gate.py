"""Phase-3-α micro state-machine tests for ``SIGNAL_GATE``.

Verifies the new transitions slotted in by P3-α:

- ``HORIZON_AGGREGATE → SIGNAL_GATE`` is legal (with at least one
  SIGNAL alpha registered).
- ``SIGNAL_GATE → FEATURE_COMPUTE`` is the only valid exit.
- ``HORIZON_AGGREGATE → FEATURE_COMPUTE`` (Phase-2 fast-path) remains
  legal so SIGNAL-only deployments without a portfolio layer take the
  short path through the orchestrator.
- ``SIGNAL_GATE`` cannot be entered from any non-aggregate state.
- The full sensor-enabled + SIGNAL-loaded pipeline reaches
  ``WAITING_FOR_MARKET_EVENT`` cleanly.
"""

from __future__ import annotations

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.state_machine import IllegalTransition
from feelies.kernel.micro import MicroState, create_micro_state_machine


@pytest.fixture
def clock() -> SimulatedClock:
    return SimulatedClock(start_ns=0)


# ── New transitions ─────────────────────────────────────────────────────


class TestSignalGateTransitions:
    def test_horizon_aggregate_to_signal_gate_legal(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        for target, trig in [
            (MicroState.MARKET_EVENT_RECEIVED, "tick_arrived"),
            (MicroState.STATE_UPDATE, "event_logged"),
            (MicroState.SENSOR_UPDATE, "state_updated"),
            (MicroState.HORIZON_CHECK, "sensors_updated"),
            (MicroState.HORIZON_AGGREGATE, "horizon_crossed"),
            (MicroState.SIGNAL_GATE, "snapshot_emitted"),
        ]:
            sm.transition(target, trigger=trig)
        assert sm.state == MicroState.SIGNAL_GATE

    def test_signal_gate_to_feature_compute(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        for target, trig in [
            (MicroState.MARKET_EVENT_RECEIVED, "tick_arrived"),
            (MicroState.STATE_UPDATE, "event_logged"),
            (MicroState.SENSOR_UPDATE, "state_updated"),
            (MicroState.HORIZON_CHECK, "sensors_updated"),
            (MicroState.HORIZON_AGGREGATE, "horizon_crossed"),
            (MicroState.SIGNAL_GATE, "snapshot_emitted"),
            (MicroState.FEATURE_COMPUTE, "signals_emitted"),
        ]:
            sm.transition(target, trigger=trig)
        assert sm.state == MicroState.FEATURE_COMPUTE


class TestPhase2FastPathPreserved:
    def test_horizon_aggregate_can_still_skip_signal_gate(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        for target, trig in [
            (MicroState.MARKET_EVENT_RECEIVED, "tick_arrived"),
            (MicroState.STATE_UPDATE, "event_logged"),
            (MicroState.SENSOR_UPDATE, "state_updated"),
            (MicroState.HORIZON_CHECK, "sensors_updated"),
            (MicroState.HORIZON_AGGREGATE, "horizon_crossed"),
            (MicroState.FEATURE_COMPUTE, "snapshot_emitted_no_signal_alpha"),
        ]:
            sm.transition(target, trigger=trig)
        assert sm.state == MicroState.FEATURE_COMPUTE


class TestSignalGateIsolation:
    def test_signal_gate_unreachable_from_state_update(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        sm.transition(MicroState.MARKET_EVENT_RECEIVED, trigger="tick_arrived")
        sm.transition(MicroState.STATE_UPDATE, trigger="event_logged")
        with pytest.raises(IllegalTransition):
            sm.transition(MicroState.SIGNAL_GATE, trigger="cant_skip")

    def test_signal_gate_cannot_loop_back_to_horizon_aggregate(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        for target, trig in [
            (MicroState.MARKET_EVENT_RECEIVED, "tick_arrived"),
            (MicroState.STATE_UPDATE, "event_logged"),
            (MicroState.SENSOR_UPDATE, "state_updated"),
            (MicroState.HORIZON_CHECK, "sensors_updated"),
            (MicroState.HORIZON_AGGREGATE, "horizon_crossed"),
            (MicroState.SIGNAL_GATE, "snapshot_emitted"),
        ]:
            sm.transition(target, trigger=trig)
        with pytest.raises(IllegalTransition):
            sm.transition(MicroState.HORIZON_AGGREGATE, trigger="cant_loop_back")

    def test_signal_gate_cannot_skip_to_signal_evaluate(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        for target, trig in [
            (MicroState.MARKET_EVENT_RECEIVED, "tick_arrived"),
            (MicroState.STATE_UPDATE, "event_logged"),
            (MicroState.SENSOR_UPDATE, "state_updated"),
            (MicroState.HORIZON_CHECK, "sensors_updated"),
            (MicroState.HORIZON_AGGREGATE, "horizon_crossed"),
            (MicroState.SIGNAL_GATE, "snapshot_emitted"),
        ]:
            sm.transition(target, trigger=trig)
        with pytest.raises(IllegalTransition):
            sm.transition(
                MicroState.SIGNAL_EVALUATE, trigger="cant_skip_features",
            )


class TestSignalGateFullPipeline:
    def test_full_pipeline_with_signal_gate_reaches_waiting(
        self, clock: SimulatedClock
    ) -> None:
        sm = create_micro_state_machine(clock)
        for target, trig in [
            (MicroState.MARKET_EVENT_RECEIVED, "tick_arrived"),
            (MicroState.STATE_UPDATE, "event_logged"),
            (MicroState.SENSOR_UPDATE, "state_updated"),
            (MicroState.HORIZON_CHECK, "sensors_updated"),
            (MicroState.HORIZON_AGGREGATE, "horizon_crossed"),
            (MicroState.SIGNAL_GATE, "snapshot_emitted"),
            (MicroState.FEATURE_COMPUTE, "signals_emitted"),
            (MicroState.SIGNAL_EVALUATE, "features_computed"),
            (MicroState.LOG_AND_METRICS, "no_legacy_signal"),
            (MicroState.WAITING_FOR_MARKET_EVENT, "tick_complete"),
        ]:
            sm.transition(target, trigger=trig)
        assert sm.state == MicroState.WAITING_FOR_MARKET_EVENT
