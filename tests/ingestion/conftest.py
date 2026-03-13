"""Shared fixtures for ingestion tests."""

from __future__ import annotations

import pytest

from feelies.core.clock import SimulatedClock
from feelies.ingestion.polygon_normalizer import PolygonNormalizer
from feelies.storage.memory_event_log import InMemoryEventLog


@pytest.fixture
def clock() -> SimulatedClock:
    """Deterministic clock for tests."""
    return SimulatedClock(start_ns=1_000_000_000)


@pytest.fixture
def normalizer(clock: SimulatedClock) -> PolygonNormalizer:
    """Polygon normalizer with deterministic clock."""
    return PolygonNormalizer(clock=clock)


@pytest.fixture
def event_log() -> InMemoryEventLog:
    """In-memory event log for tests."""
    return InMemoryEventLog()
