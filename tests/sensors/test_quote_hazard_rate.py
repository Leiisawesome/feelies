"""Unit tests + locked-vector replay for QuoteHazardRateSensor."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.quote_hazard_rate import QuoteHazardRateSensor
from tests.sensors.fixtures._generate import hazard_factory, load_fixture


def _quote(*, ts_ns: int, sequence: int = 0) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{sequence}",
        sequence=sequence,
        symbol="AAPL",
        bid=Decimal("100"),
        ask=Decimal("100.01"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts_ns,
    )


def test_constructor_validates_arguments() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        QuoteHazardRateSensor(window_seconds=0)
    with pytest.raises(ValueError, match="min_samples"):
        QuoteHazardRateSensor(min_samples=-1)


def test_trade_events_return_none() -> None:
    sensor = QuoteHazardRateSensor()
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


def test_first_quote_emits_one_over_window() -> None:
    sensor = QuoteHazardRateSensor(window_seconds=5, min_samples=1)
    state = sensor.initial_state()
    reading = sensor.update(_quote(ts_ns=1_000_000_000), state, params={})
    assert reading is not None
    # 1 quote / 5 seconds = 0.2 events/sec.
    assert reading.value == pytest.approx(0.2, rel=1e-12)
    assert reading.warm is True


def test_handcomputed_full_window() -> None:
    """5 quotes inside a 5s window → hazard = 5/5 = 1.0/s."""
    sensor = QuoteHazardRateSensor(window_seconds=5, min_samples=5)
    state = sensor.initial_state()
    for i in range(5):
        reading = sensor.update(
            _quote(ts_ns=1_000_000_000 + i * 200_000_000, sequence=i),
            state, params={},
        )
    assert reading is not None
    assert reading.value == pytest.approx(1.0, rel=1e-12)
    assert reading.warm is True


def test_window_evicts_old_quotes() -> None:
    sensor = QuoteHazardRateSensor(window_seconds=1, min_samples=1)
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=1_000_000_000), state, params={})
    sensor.update(_quote(ts_ns=1_500_000_000), state, params={})
    # Jump 10s ahead — both are evicted.
    reading = sensor.update(_quote(ts_ns=11_000_000_000), state, params={})
    assert reading is not None
    assert reading.value == pytest.approx(1.0, rel=1e-12)
    assert len(state["timestamps"]) == 1


def test_warm_transitions_at_min_samples() -> None:
    sensor = QuoteHazardRateSensor(window_seconds=10, min_samples=3)
    state = sensor.initial_state()
    r1 = sensor.update(_quote(ts_ns=1_000_000_000, sequence=0), state, params={})
    r2 = sensor.update(_quote(ts_ns=2_000_000_000, sequence=1), state, params={})
    r3 = sensor.update(_quote(ts_ns=3_000_000_000, sequence=2), state, params={})
    assert r1 is not None and not r1.warm
    assert r2 is not None and not r2.warm
    assert r3 is not None and r3.warm


def test_locked_vector_replay() -> None:
    sensor = hazard_factory()
    state = sensor.initial_state()
    for i, (event, expected_value, expected_warm) in enumerate(
        load_fixture("quote_hazard_rate.jsonl")
    ):
        reading = sensor.update(event, state, params={})
        if expected_value is None:
            assert reading is None, f"record {i}: expected no emission"
            continue
        assert reading is not None, f"record {i}: expected an emission"
        assert reading.value == pytest.approx(expected_value, rel=1e-12, abs=1e-12)
        assert reading.warm is expected_warm
