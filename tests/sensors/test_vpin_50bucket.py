"""Unit tests + locked-vector replay for VPIN50BucketSensor."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.vpin_50bucket import VPIN50BucketSensor
from tests.sensors.fixtures._generate import load_fixture, vpin_factory


# ── Hand-computed unit tests ───────────────────────────────────────


def _trade(*, ts_ns: int, price: str, size: int, sequence: int = 0) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{sequence}",
        sequence=sequence,
        symbol="AAPL",
        price=Decimal(price),
        size=size,
        exchange_timestamp_ns=ts_ns,
    )


def test_constructor_validates_arguments() -> None:
    with pytest.raises(ValueError, match="bucket_volume"):
        VPIN50BucketSensor(bucket_volume=0)
    with pytest.raises(ValueError, match="window_buckets"):
        VPIN50BucketSensor(window_buckets=0)
    with pytest.raises(ValueError, match="min_buckets"):
        VPIN50BucketSensor(window_buckets=10, min_buckets=20)


def test_quote_events_return_none() -> None:
    sensor = VPIN50BucketSensor()
    state = sensor.initial_state()
    quote = NBBOQuote(
        timestamp_ns=1,
        correlation_id="q",
        sequence=0,
        symbol="AAPL",
        bid=Decimal("100"),
        ask=Decimal("100.01"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=1,
    )
    assert sensor.update(quote, state, params={}) is None


def test_zero_size_trade_returns_none() -> None:
    sensor = VPIN50BucketSensor()
    state = sensor.initial_state()
    trade = _trade(ts_ns=1, price="100", size=0)
    assert sensor.update(trade, state, params={}) is None


def test_single_bucket_full_buy_imbalance_is_one() -> None:
    """All buy-initiated trades fill one bucket → imbalance=1."""
    sensor = VPIN50BucketSensor(bucket_volume=1_000, window_buckets=5, min_buckets=1)
    state = sensor.initial_state()
    # Force the very first trade to be tagged as 'buy' by giving the
    # initial trade a higher price than the synthetic last_price=None
    # default; since last_price=None inherits last_side=+1, the first
    # trade is buy.  Subsequent trades at the *same* price keep that
    # side (tick rule: equal price ⇒ inherit prior side).
    for i in range(2):
        reading = sensor.update(
            _trade(ts_ns=i + 1, price="100", size=500, sequence=i),
            state,
            params={},
        )
        assert reading is not None
    # Bucket is now full (1000 / 1000); imbalance = |1000-0|/1000 = 1.
    assert reading.value == 1.0
    assert reading.warm is True


def test_balanced_buy_sell_yields_zero_imbalance() -> None:
    sensor = VPIN50BucketSensor(bucket_volume=1_000, window_buckets=5, min_buckets=1)
    state = sensor.initial_state()
    # Buy 500, then drop the price → tick rule sells the next one.
    sensor.update(_trade(ts_ns=1, price="100.01", size=500), state, params={})
    reading = sensor.update(
        _trade(ts_ns=2, price="99.99", size=500), state, params={},
    )
    assert reading is not None
    assert reading.value == 0.0
    assert reading.warm is True


def test_overflow_spills_into_next_bucket() -> None:
    """A trade larger than remaining bucket room must fill exactly."""
    sensor = VPIN50BucketSensor(bucket_volume=1_000, window_buckets=5, min_buckets=1)
    state = sensor.initial_state()
    # 700 buys then 600 buys: bucket1 = 1000 (700+300 spillover),
    # bucket2 starts at 300 buys.
    sensor.update(_trade(ts_ns=1, price="100", size=700), state, params={})
    reading = sensor.update(
        _trade(ts_ns=2, price="100", size=600), state, params={},
    )
    assert reading is not None
    assert reading.value == 1.0
    # Total volume is conserved: 700 + 600 = 1300 = 1000 (bucket1) + 300 (bucket2).
    assert state["buy_vol"] + state["sell_vol"] == 300


def test_warm_only_after_min_buckets() -> None:
    sensor = VPIN50BucketSensor(bucket_volume=200, window_buckets=10, min_buckets=3)
    state = sensor.initial_state()
    # Bucket 1: two 100-size trades fill the 200-share bucket.
    sensor.update(_trade(ts_ns=1, price="100", size=100, sequence=0), state, params={})
    r = sensor.update(_trade(ts_ns=2, price="100", size=100, sequence=1), state, params={})
    assert r is not None and r.warm is False  # 1 bucket complete
    # Bucket 2.
    sensor.update(_trade(ts_ns=3, price="100", size=100, sequence=2), state, params={})
    r = sensor.update(_trade(ts_ns=4, price="100", size=100, sequence=3), state, params={})
    assert r is not None and r.warm is False  # 2 buckets complete
    # Bucket 3 completes → warm.
    sensor.update(_trade(ts_ns=5, price="100", size=100, sequence=4), state, params={})
    r = sensor.update(_trade(ts_ns=6, price="100", size=100, sequence=5), state, params={})
    assert r is not None and r.warm is True  # 3 buckets complete


# ── Locked-vector replay ──────────────────────────────────────────


def test_locked_vector_replay() -> None:
    sensor = vpin_factory()
    state = sensor.initial_state()
    for i, (event, expected_value, expected_warm) in enumerate(
        load_fixture("vpin_50bucket.jsonl")
    ):
        reading = sensor.update(event, state, params={})
        if expected_value is None:
            assert reading is None, f"record {i}: expected no emission"
            continue
        assert reading is not None, f"record {i}: expected an emission"
        assert reading.value == pytest.approx(expected_value, rel=1e-12, abs=1e-12), (
            f"record {i}: value drift"
        )
        assert reading.warm is expected_warm, f"record {i}: warm drift"
