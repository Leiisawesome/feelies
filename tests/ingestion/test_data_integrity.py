"""Unit tests for data integrity state machine."""

from __future__ import annotations

import pytest

from feelies.core.clock import SimulatedClock
from feelies.ingestion.data_integrity import (
    DataHealth,
    HaltSignal,
    classify_halt_status,
    create_data_integrity_machine,
)


class TestDataHealth:
    """Tests for DataHealth enum."""

    def test_has_expected_states(self) -> None:
        assert DataHealth.HEALTHY.value != DataHealth.GAP_DETECTED.value
        assert DataHealth.GAP_DETECTED.value != DataHealth.CORRUPTED.value

    def test_corrupted_is_terminal(self) -> None:
        from feelies.ingestion.data_integrity import _DATA_TRANSITIONS
        assert _DATA_TRANSITIONS[DataHealth.CORRUPTED] == frozenset()


class TestCreateDataIntegrityMachine:
    """Tests for create_data_integrity_machine."""

    def test_creates_machine_with_expected_name(self) -> None:
        clock = SimulatedClock(0)
        sm = create_data_integrity_machine("AAPL", clock)
        assert sm.name == "data_integrity:AAPL"

    def test_channel_suffix_in_name(self) -> None:
        clock = SimulatedClock(0)
        sm = create_data_integrity_machine("AAPL", clock, channel="quote")
        assert sm.name == "data_integrity:AAPL:quote"

    def test_initial_state_is_healthy(self) -> None:
        clock = SimulatedClock(0)
        sm = create_data_integrity_machine("MSFT", clock)
        assert sm.state == DataHealth.HEALTHY

    def test_can_transition_to_gap_detected(self) -> None:
        clock = SimulatedClock(0)
        sm = create_data_integrity_machine("AAPL", clock)
        assert sm.can_transition(DataHealth.GAP_DETECTED)
        sm.transition(DataHealth.GAP_DETECTED, trigger="seq_gap:1->5")
        assert sm.state == DataHealth.GAP_DETECTED

    def test_healthy_cannot_transition_directly_to_corrupted(self) -> None:
        clock = SimulatedClock(0)
        sm = create_data_integrity_machine("AAPL", clock)
        # HEALTHY can transition to CORRUPTED per the transition table
        assert sm.can_transition(DataHealth.CORRUPTED)

    def test_gap_detected_can_transition_back_to_healthy(self) -> None:
        clock = SimulatedClock(0)
        sm = create_data_integrity_machine("AAPL", clock)
        sm.transition(DataHealth.GAP_DETECTED, trigger="gap")
        sm.transition(DataHealth.HEALTHY, trigger="gap_resolved")
        assert sm.state == DataHealth.HEALTHY


class TestHaltedState:
    """BT-5: DataHealth.HALTED transitions."""

    def test_healthy_to_halted_and_back(self) -> None:
        clock = SimulatedClock(0)
        sm = create_data_integrity_machine("AAPL", clock)
        assert sm.can_transition(DataHealth.HALTED)
        sm.transition(DataHealth.HALTED, trigger="luld_halt_on")
        assert sm.state == DataHealth.HALTED
        # Resume back to HEALTHY (recoverable, unlike CORRUPTED).
        assert sm.can_transition(DataHealth.HEALTHY)
        sm.transition(DataHealth.HEALTHY, trigger="luld_halt_off")
        assert sm.state == DataHealth.HEALTHY

    def test_halted_cannot_be_terminal(self) -> None:
        clock = SimulatedClock(0)
        sm = create_data_integrity_machine("AAPL", clock)
        sm.transition(DataHealth.HALTED, trigger="halt")
        # HALTED is recoverable to HEALTHY and escalatable to CORRUPTED,
        # but never directly to GAP_DETECTED.
        assert sm.can_transition(DataHealth.HEALTHY)
        assert sm.can_transition(DataHealth.CORRUPTED)
        assert not sm.can_transition(DataHealth.GAP_DETECTED)


class TestClassifyHaltStatus:
    """BT-5: shared condition-code classifier."""

    def test_no_codes_configured_is_inert(self) -> None:
        assert classify_halt_status((1, 2, 3), frozenset(), frozenset()) is None

    def test_halt_on_code_detected(self) -> None:
        assert classify_halt_status(
            (5,), frozenset({5}), frozenset({6}),
        ) is HaltSignal.HALT_ON

    def test_halt_off_code_detected(self) -> None:
        assert classify_halt_status(
            (6,), frozenset({5}), frozenset({6}),
        ) is HaltSignal.HALT_OFF

    def test_no_matching_code(self) -> None:
        assert classify_halt_status(
            (9,), frozenset({5}), frozenset({6}),
        ) is None

    def test_both_present_prefers_halt_on_failsafe(self) -> None:
        assert classify_halt_status(
            (5, 6), frozenset({5}), frozenset({6}),
        ) is HaltSignal.HALT_ON
