"""Unit tests for clock abstraction."""

from __future__ import annotations

import pytest

from feelies.core.clock import SimulatedClock, WallClock


class TestSimulatedClock:
    """Tests for SimulatedClock."""

    def test_now_ns_returns_initial_value(self) -> None:
        clock = SimulatedClock(start_ns=42)
        assert clock.now_ns() == 42

    def test_default_start_is_zero(self) -> None:
        clock = SimulatedClock()
        assert clock.now_ns() == 0

    def test_set_time_advances_clock(self) -> None:
        clock = SimulatedClock(start_ns=100)
        clock.set_time(200)
        assert clock.now_ns() == 200

    def test_set_time_backward_raises(self) -> None:
        clock = SimulatedClock(start_ns=100)
        with pytest.raises(ValueError, match="cannot move backward"):
            clock.set_time(50)

    def test_set_time_same_value_allowed(self) -> None:
        clock = SimulatedClock(start_ns=100)
        clock.set_time(100)
        assert clock.now_ns() == 100


class TestWallClock:
    """Tests for WallClock."""

    def test_now_ns_returns_positive_value(self) -> None:
        clock = WallClock()
        ts = clock.now_ns()
        assert ts > 0
        assert isinstance(ts, int)
