"""Unit tests + locked-vector replay for TradeThroughRateSensor."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.trade_through_rate import TradeThroughRateSensor
from tests.sensors.fixtures._generate import load_fixture, through_factory


def _quote(*, ts_ns: int, bid: str, ask: str, sequence: int = 0) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{sequence}",
        sequence=sequence,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts_ns,
    )


def _trade(*, ts_ns: int, price: str, sequence: int = 0) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{sequence}",
        sequence=sequence,
        symbol="AAPL",
        price=Decimal(price),
        size=100,
        exchange_timestamp_ns=ts_ns,
    )


def test_constructor_validates_arguments() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        TradeThroughRateSensor(window_seconds=0)
    with pytest.raises(ValueError, match="min_trades"):
        TradeThroughRateSensor(min_trades=-1)


def test_quote_only_no_emission() -> None:
    sensor = TradeThroughRateSensor()
    state = sensor.initial_state()
    assert sensor.update(_quote(ts_ns=1, bid="100", ask="100.01"), state, params={}) is None


def test_trade_before_quote_no_emission() -> None:
    sensor = TradeThroughRateSensor()
    state = sensor.initial_state()
    assert sensor.update(_trade(ts_ns=1, price="100"), state, params={}) is None


def test_lift_offer_counts_as_through() -> None:
    sensor = TradeThroughRateSensor(window_seconds=30, min_trades=1)
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=1, bid="100", ask="100.01"), state, params={})
    r = sensor.update(_trade(ts_ns=2, price="100.01"), state, params={})
    assert r is not None
    # 1/1 trades through the NBBO.
    assert r.value == 1.0
    assert r.warm is True


def test_midpoint_trade_not_a_through() -> None:
    sensor = TradeThroughRateSensor(window_seconds=30, min_trades=1)
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=1, bid="100.00", ask="100.02"), state, params={})
    r = sensor.update(_trade(ts_ns=2, price="100.01"), state, params={})
    assert r is not None
    assert r.value == 0.0


def test_hit_bid_counts_as_through() -> None:
    sensor = TradeThroughRateSensor(window_seconds=30, min_trades=1)
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=1, bid="100.00", ask="100.02"), state, params={})
    r = sensor.update(_trade(ts_ns=2, price="100.00"), state, params={})
    assert r is not None
    assert r.value == 1.0


def test_window_evicts_old_trades() -> None:
    sensor = TradeThroughRateSensor(window_seconds=1, min_trades=1)
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=1_000_000_000, bid="100", ask="100.01"), state, params={})
    sensor.update(_trade(ts_ns=1_000_000_000, price="100.01"), state, params={})
    sensor.update(_trade(ts_ns=1_500_000_000, price="100.005", sequence=1), state, params={})
    # 1 of 2 trades through.
    assert state["through_count"] == 1
    # Jump well past the 1s window.
    r = sensor.update(_trade(ts_ns=10_000_000_000, price="100.005", sequence=2), state, params={})
    assert r is not None
    # Both prior trades evicted, only the latest remains (mid → 0/1 = 0).
    assert r.value == 0.0
    assert state["through_count"] == 0


def test_handcomputed_mixed_trades() -> None:
    """Sequence: through, mid, through, mid → 2/4 = 0.5."""
    sensor = TradeThroughRateSensor(window_seconds=30, min_trades=4)
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=1, bid="100.00", ask="100.02"), state, params={})
    sensor.update(_trade(ts_ns=2, price="100.02", sequence=0), state, params={})
    sensor.update(_trade(ts_ns=3, price="100.01", sequence=1), state, params={})
    sensor.update(_trade(ts_ns=4, price="100.00", sequence=2), state, params={})
    r = sensor.update(_trade(ts_ns=5, price="100.01", sequence=3), state, params={})
    assert r is not None
    assert r.value == pytest.approx(0.5, rel=1e-12)
    assert r.warm is True


def test_locked_vector_replay() -> None:
    sensor = through_factory()
    state = sensor.initial_state()
    for i, (event, expected_value, expected_warm) in enumerate(
        load_fixture("trade_through_rate.jsonl")
    ):
        reading = sensor.update(event, state, params={})
        if expected_value is None:
            assert reading is None, f"record {i}: expected no emission"
            continue
        assert reading is not None, f"record {i}: expected an emission"
        assert reading.value == pytest.approx(expected_value, rel=1e-12, abs=1e-12)
        assert reading.warm is expected_warm
