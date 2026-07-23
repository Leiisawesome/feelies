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
        _trade(ts_ns=2, price="99.99", size=500),
        state,
        params={},
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
        _trade(ts_ns=2, price="100", size=600),
        state,
        params={},
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


# ── F5 (sensor_review_2026-07-02): O(1) block-trade fill ───────────


def _naive_reference_fill(
    *, trades: list[tuple[int, int]], bucket_volume: int, window_buckets: int
) -> tuple[list[float], int, int]:
    """A from-scratch re-implementation of the original per-share spill loop,
    used to lock the O(1) rewrite's byte-for-byte equivalence on inputs the
    fixture does not exercise (multi-bucket-spanning trades).

    ``trades`` is a list of ``(side, size)`` with side in {+1, -1}.
    Returns ``(bucket_imbalances, buy_vol, sell_vol)`` after all trades.
    """
    from collections import deque

    buckets: deque[float] = deque(maxlen=window_buckets)
    buy_vol = sell_vol = 0
    for side, size in trades:
        remaining = size
        while remaining > 0:
            cur_total = buy_vol + sell_vol
            room = bucket_volume - cur_total
            take = remaining if remaining <= room else room
            if side > 0:
                buy_vol += take
            else:
                sell_vol += take
            remaining -= take
            if buy_vol + sell_vol >= bucket_volume:
                buckets.append(abs(buy_vol - sell_vol) / float(bucket_volume))
                buy_vol = sell_vol = 0
    return list(buckets), buy_vol, sell_vol


def test_block_trade_matches_naive_reference_no_window_overflow() -> None:
    """A single block trade spanning several (but < window) buckets must
    produce the exact same bucket deque and residual volumes as the original
    per-share loop."""
    bucket_volume, window = 1_000, 50
    sensor = VPIN50BucketSensor(bucket_volume=bucket_volume, window_buckets=window, min_buckets=1)
    state = sensor.initial_state()
    # First trade: 300 buys → partial bucket. Second: a 7_450-share buy block
    # → completes bucket1 (700 more), 7 full 1.0 buckets, 450 remainder.
    sensor.update(_trade(ts_ns=1, price="100", size=300), state, params={})
    sensor.update(_trade(ts_ns=2, price="100", size=7_450), state, params={})

    ref_buckets, ref_buy, ref_sell = _naive_reference_fill(
        trades=[(+1, 300), (+1, 7_450)],
        bucket_volume=bucket_volume,
        window_buckets=window,
    )
    assert list(state["buckets"]) == ref_buckets
    assert state["buy_vol"] == ref_buy
    assert state["sell_vol"] == ref_sell
    # 300 + 7450 = 7750 shares: bucket1 completes with 700 (300+700), leaving
    # 6750 → 6 full 1.0 buckets (6000) + 750 residual. 7 buckets, 750 open.
    assert len(state["buckets"]) == 7
    assert state["buy_vol"] + state["sell_vol"] == 750


def test_giant_trade_overwrites_whole_window_with_ones() -> None:
    """A trade whose whole-bucket count exceeds the window fills the entire
    window with 1.0 imbalances and reports VPIN == 1.0, in O(1)."""
    bucket_volume, window = 1_000, 50
    sensor = VPIN50BucketSensor(bucket_volume=bucket_volume, window_buckets=window, min_buckets=1)
    state = sensor.initial_state()
    # 1_000_000 buy shares = 1000 full buckets ≫ window of 50.
    reading = sensor.update(_trade(ts_ns=1, price="100", size=1_000_000), state, params={})
    assert reading is not None
    assert list(state["buckets"]) == [1.0] * window
    assert state["buckets_sum"] == float(window)
    assert reading.value == 1.0
    # Residual: 1_000_000 % 1000 == 0, so no partial bucket is open.
    assert state["buy_vol"] + state["sell_vol"] == 0


def test_block_trade_then_normal_trades_stay_consistent() -> None:
    """After a window-overflowing block trade, subsequent normal trades must
    keep buckets_sum in exact agreement with the deque contents."""
    bucket_volume, window = 500, 10
    sensor = VPIN50BucketSensor(bucket_volume=bucket_volume, window_buckets=window, min_buckets=1)
    state = sensor.initial_state()
    sensor.update(_trade(ts_ns=1, price="100", size=100_000), state, params={})  # block
    # A few normal alternating trades.
    sensor.update(_trade(ts_ns=2, price="100.01", size=500), state, params={})  # buy bucket
    sensor.update(_trade(ts_ns=3, price="99.99", size=500), state, params={})  # sell bucket
    assert state["buckets_sum"] == pytest.approx(sum(state["buckets"]), rel=1e-12)


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
