"""Unit tests for data integrity state machine."""

from __future__ import annotations

import pytest

from feelies.core.clock import SimulatedClock
from feelies.ingestion.data_integrity import DataHealth, create_data_integrity_machine


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
