"""Unit tests for StructuralBreakScoreSensor (v0.3 §20.4.4)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.structural_break_score import (
    StructuralBreakScoreSensor,
)


def _quote(*, ts_ns: int, mid: str, sequence: int = 0) -> NBBOQuote:
    mid_d = Decimal(mid)
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{sequence}",
        sequence=sequence,
        symbol="AAPL",
        bid=mid_d - Decimal("0.005"),
        ask=mid_d + Decimal("0.005"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts_ns,
    )


def test_constructor_validates_arguments() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        StructuralBreakScoreSensor(window_seconds=0)
    with pytest.raises(ValueError, match="alarm_threshold"):
        StructuralBreakScoreSensor(alarm_threshold=0)
    with pytest.raises(ValueError, match="drift_floor"):
        StructuralBreakScoreSensor(drift_floor=-0.01)
    with pytest.raises(ValueError, match="warm_samples"):
        StructuralBreakScoreSensor(warm_samples=-1)


def test_trade_events_return_none() -> None:
    sensor = StructuralBreakScoreSensor()
    state = sensor.initial_state()
    trade = Trade(
        timestamp_ns=1,
        correlation_id="t",
        sequence=0,
        symbol="AAPL",
        price=Decimal("100"),
        size=100,
        exchange_timestamp_ns=1,
    )
    assert sensor.update(trade, state, params={}) is None


def test_first_quote_emits_zero_no_baseline() -> None:
    sensor = StructuralBreakScoreSensor()
    state = sensor.initial_state()
    r = sensor.update(_quote(ts_ns=1, mid="100"), state, params={})
    assert r is not None
    assert r.value == 0.0
    assert r.warm is False


def test_constant_mid_no_break() -> None:
    """Identical observations after the first → score stays at 0."""
    sensor = StructuralBreakScoreSensor(
        window_seconds=10, alarm_threshold=0.1, warm_samples=3,
    )
    state = sensor.initial_state()
    r = None
    for i in range(10):
        r = sensor.update(
            _quote(ts_ns=(i + 1) * 1_000_000_000, mid="100", sequence=i),
            state, params={},
        )
    assert r is not None
    assert r.value == 0.0


def test_structural_jump_increases_score() -> None:
    """Steady mid then a sudden persistent shift → score climbs."""
    sensor = StructuralBreakScoreSensor(
        window_seconds=60, alarm_threshold=0.001, warm_samples=2,
    )
    state = sensor.initial_state()
    # Stable phase.
    for i in range(20):
        sensor.update(
            _quote(ts_ns=(i + 1) * 1_000_000_000, mid="100", sequence=i),
            state, params={},
        )
    # Sudden persistent volatility regime.
    last = None
    for i in range(20, 40):
        mid = "100" if i % 2 == 0 else "100.20"
        last = sensor.update(
            _quote(ts_ns=(i + 1) * 1_000_000_000, mid=mid, sequence=i),
            state, params={},
        )
    assert last is not None
    assert last.value > 0.0


def test_score_is_clipped_to_unit_interval() -> None:
    sensor = StructuralBreakScoreSensor(
        window_seconds=60, alarm_threshold=1e-9, warm_samples=2,
    )
    state = sensor.initial_state()
    # Tiny λ ⇒ even a small persistent observable saturates the score.
    last = None
    for i in range(10):
        mid = "100" if i % 2 == 0 else "100.10"
        last = sensor.update(
            _quote(ts_ns=(i + 1) * 1_000_000_000, mid=mid, sequence=i),
            state, params={},
        )
    assert last is not None
    assert 0.0 <= last.value <= 1.0


def test_window_evicts_old_samples() -> None:
    sensor = StructuralBreakScoreSensor(window_seconds=1, warm_samples=2)
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=1_000_000_000, mid="100"), state, params={})
    sensor.update(_quote(ts_ns=1_500_000_000, mid="100.01", sequence=1), state, params={})
    assert len(state["samples"]) == 1  # first quote bootstrapped, second is the first sample
    sensor.update(_quote(ts_ns=10_000_000_000, mid="100.02", sequence=2), state, params={})
    # The 1.5s sample is older than (10s - 1s) = 9s → evicted.
    assert len(state["samples"]) == 1
