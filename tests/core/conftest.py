"""Shared fixtures for core tests."""

from __future__ import annotations

import pytest

from feelies.core.clock import SimulatedClock


@pytest.fixture
def clock() -> SimulatedClock:
    """Deterministic clock for tests."""
    return SimulatedClock(start_ns=1_000_000_000)
