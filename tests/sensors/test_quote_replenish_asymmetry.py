"""Unit tests + locked-vector replay for QuoteReplenishAsymmetrySensor."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.quote_replenish_asymmetry import (
    QuoteReplenishAsymmetrySensor,
)
from tests.sensors.fixtures._generate import load_fixture, replenish_factory


def _quote(*, ts_ns: int, bid_size: int, ask_size: int, sequence: int = 0) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{sequence}",
        sequence=sequence,
        symbol="AAPL",
        bid=Decimal("100"),
        ask=Decimal("100.01"),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts_ns,
    )


def test_constructor_validates_arguments() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        QuoteReplenishAsymmetrySensor(window_seconds=0)
    with pytest.raises(ValueError, match="min_observations"):
        QuoteReplenishAsymmetrySensor(min_observations=-1)


def test_trade_events_return_none() -> None:
    sensor = QuoteReplenishAsymmetrySensor()
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


def test_first_quote_emits_zero_no_history() -> None:
    """First quote has no prior — no additions recorded; value=0."""
    sensor = QuoteReplenishAsymmetrySensor(window_seconds=5, min_observations=1)
    state = sensor.initial_state()
    r = sensor.update(_quote(ts_ns=1, bid_size=100, ask_size=100), state, params={})
    assert r is not None
    assert r.value == 0.0
    assert r.warm is False  # need adds on both sides


def test_pure_bid_replenishment_yields_plus_one() -> None:
    """Bid grows, ask shrinks → only bid additions → asymmetry=+1."""
    sensor = QuoteReplenishAsymmetrySensor(window_seconds=5, min_observations=1)
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=1, bid_size=100, ask_size=100), state, params={})
    r = sensor.update(_quote(ts_ns=2, bid_size=200, ask_size=50, sequence=1), state, params={})
    assert r is not None
    # bid_sum=100, ask_sum=0 → asymmetry = (100/5 - 0)/(100/5 + 0) = 1.
    assert r.value == 1.0
    assert r.warm is False  # ask_adds is empty


def test_balanced_replenishment_yields_zero() -> None:
    """Equal additions on both sides → asymmetry=0."""
    sensor = QuoteReplenishAsymmetrySensor(window_seconds=5, min_observations=1)
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=1, bid_size=100, ask_size=100), state, params={})
    r = sensor.update(
        _quote(ts_ns=2, bid_size=200, ask_size=200, sequence=1), state, params={},
    )
    assert r is not None
    assert r.value == 0.0
    assert r.warm is True  # 2 obs ≥ min_observations and adds on both sides


def test_window_evicts_old_additions() -> None:
    sensor = QuoteReplenishAsymmetrySensor(window_seconds=1, min_observations=1)
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=1_000_000_000, bid_size=100, ask_size=100), state, params={})
    sensor.update(
        _quote(ts_ns=1_500_000_000, bid_size=200, ask_size=100, sequence=1),
        state, params={},
    )
    # +100 bid recorded inside the 1s window.
    assert state["bid_sum"] == 100
    sensor.update(
        _quote(ts_ns=10_000_000_000, bid_size=200, ask_size=100, sequence=2),
        state, params={},
    )
    # The earlier addition is evicted; the latest tick had Δbid=0 (200→200).
    assert state["bid_sum"] == 0


def test_warm_requires_both_sides_with_adds() -> None:
    sensor = QuoteReplenishAsymmetrySensor(window_seconds=10, min_observations=2)
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=1, bid_size=100, ask_size=100, sequence=0), state, params={})
    r = sensor.update(
        _quote(ts_ns=2, bid_size=150, ask_size=120, sequence=1), state, params={},
    )
    assert r is not None and r.warm is True  # 2 obs, both sides have adds


def test_locked_vector_replay() -> None:
    sensor = replenish_factory()
    state = sensor.initial_state()
    for i, (event, expected_value, expected_warm) in enumerate(
        load_fixture("quote_replenish_asymmetry.jsonl")
    ):
        reading = sensor.update(event, state, params={})
        if expected_value is None:
            assert reading is None, f"record {i}: expected no emission"
            continue
        assert reading is not None, f"record {i}: expected an emission"
        assert reading.value == pytest.approx(expected_value, rel=1e-12, abs=1e-12)
        assert reading.warm is expected_warm
