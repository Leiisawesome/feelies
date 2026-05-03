"""Unit tests + locked-vector replay for KyleLambda60sSensor."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor
from tests.sensors.fixtures._generate import kyle_factory, load_fixture


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


def _quote(
    *, ts_ns: int, bid: str, ask: str, sequence: int = 0,
) -> NBBOQuote:
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


def test_constructor_validates_arguments() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        KyleLambda60sSensor(window_seconds=0)
    with pytest.raises(ValueError, match="min_samples"):
        KyleLambda60sSensor(min_samples=1)


def test_quote_updates_mid_returns_none() -> None:
    sensor = KyleLambda60sSensor()
    state = sensor.initial_state()
    q = _quote(ts_ns=1, bid="100", ask="100.02", sequence=0)
    assert sensor.update(q, state, params={}) is None
    assert state["last_nbbo_mid"] == pytest.approx(100.01)


def test_first_trade_returns_none_without_nbbo_mid() -> None:
    sensor = KyleLambda60sSensor()
    state = sensor.initial_state()
    assert sensor.update(_trade(ts_ns=1, price="100", size=100), state, params={}) is None


def test_handcomputed_lambda_two_samples() -> None:
    """Two Δp_mid samples (+0.01, +0.02) with tick-rule Δq (+100,+200) → λ = 1e-4."""
    sensor = KyleLambda60sSensor(window_seconds=60, min_samples=2)
    state = sensor.initial_state()
    sensor.update(
        _quote(ts_ns=999_999_999, bid="100.00", ask="100.02", sequence=0),
        state,
        params={},
    )
    sensor.update(_trade(ts_ns=1_000_000_000, price="100.00", size=100), state, params={})
    sensor.update(
        _quote(ts_ns=1_999_999_999, bid="100.01", ask="100.03", sequence=2),
        state,
        params={},
    )
    r1 = sensor.update(
        _trade(ts_ns=2_000_000_000, price="100.01", size=100), state, params={},
    )
    sensor.update(
        _quote(ts_ns=2_999_999_999, bid="100.03", ask="100.05", sequence=4),
        state,
        params={},
    )
    r2 = sensor.update(
        _trade(ts_ns=3_000_000_000, price="100.03", size=200), state, params={},
    )
    assert r1 is not None
    # First sample only: denom = n*sum_dq² - sum_dq² = 1*10000 - 10000 = 0 → 0.
    assert r1.value == 0.0
    assert r1.warm is False
    assert r2 is not None
    assert r2.value == pytest.approx(1e-4, rel=1e-9)
    assert r2.warm is True


def test_window_evicts_old_samples() -> None:
    sensor = KyleLambda60sSensor(window_seconds=1, min_samples=2)
    state = sensor.initial_state()
    sensor.update(
        _quote(ts_ns=999_999_999, bid="100.00", ask="100.02", sequence=0),
        state,
        params={},
    )
    sensor.update(_trade(ts_ns=1_000_000_000, price="100.00", size=100), state, params={})
    sensor.update(
        _quote(ts_ns=1_499_999_999, bid="100.01", ask="100.03", sequence=2),
        state,
        params={},
    )
    sensor.update(_trade(ts_ns=1_500_000_000, price="100.01", size=100), state, params={})
    sensor.update(
        _quote(ts_ns=1_899_999_999, bid="100.02", ask="100.04", sequence=4),
        state,
        params={},
    )
    sensor.update(_trade(ts_ns=1_900_000_000, price="100.02", size=100), state, params={})
    assert len(state["samples"]) == 2
    sensor.update(
        _quote(ts_ns=6_999_999_999, bid="100.03", ask="100.05", sequence=6),
        state,
        params={},
    )
    sensor.update(
        _trade(ts_ns=7_000_000_000, price="100.03", size=100), state, params={},
    )
    assert len(state["samples"]) == 1


def test_zero_size_trade_returns_none() -> None:
    sensor = KyleLambda60sSensor()
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=0, bid="99.99", ask="100.01", sequence=0), state, params={})
    sensor.update(_trade(ts_ns=1, price="100", size=100), state, params={})
    assert sensor.update(_trade(ts_ns=2, price="100.01", size=0), state, params={}) is None


def test_constant_price_lambda_is_zero() -> None:
    """If Δp_mid = 0, OLS slope is degenerate — emit 0."""
    sensor = KyleLambda60sSensor(window_seconds=60, min_samples=2)
    state = sensor.initial_state()
    sensor.update(_quote(ts_ns=0, bid="99.99", ask="100.01", sequence=0), state, params={})
    sensor.update(_trade(ts_ns=1, price="100", size=100), state, params={})
    sensor.update(_quote(ts_ns=1, bid="99.99", ask="100.01", sequence=2), state, params={})
    reading = sensor.update(_trade(ts_ns=2, price="100", size=100), state, params={})
    assert reading is not None
    assert reading.value == 0.0
    assert reading.warm is False


def test_locked_vector_replay() -> None:
    sensor = kyle_factory()
    state = sensor.initial_state()
    for i, (event, expected_value, expected_warm) in enumerate(
        load_fixture("kyle_lambda_60s.jsonl")
    ):
        reading = sensor.update(event, state, params={})
        if expected_value is None:
            assert reading is None, f"record {i}: expected no emission"
            continue
        assert reading is not None, f"record {i}: expected an emission"
        assert reading.value == pytest.approx(expected_value, rel=1e-9, abs=1e-12), (
            f"record {i}: value drift"
        )
        assert reading.warm is expected_warm, f"record {i}: warm drift"
