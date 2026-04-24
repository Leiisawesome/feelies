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


def test_constructor_validates_arguments() -> None:
    with pytest.raises(ValueError, match="window_seconds"):
        KyleLambda60sSensor(window_seconds=0)
    with pytest.raises(ValueError, match="min_samples"):
        KyleLambda60sSensor(min_samples=1)


def test_quote_events_return_none() -> None:
    sensor = KyleLambda60sSensor()
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


def test_first_trade_returns_none_no_prior_price() -> None:
    sensor = KyleLambda60sSensor()
    state = sensor.initial_state()
    assert sensor.update(_trade(ts_ns=1, price="100", size=100), state, params={}) is None


def test_handcomputed_lambda_two_samples() -> None:
    """Two samples (Δp, Δq) = (+0.01, +100), (+0.02, +200) → λ exactly 1e-4.

    OLS slope with mean centering on two points:
        numer = n*Σ(ΔpΔq) - ΣΔp*ΣΔq = 2*5 - 0.03*300 = 1
        denom = n*Σ(Δq²) - (ΣΔq)²    = 2*50000 - 90000 = 10000
        λ = 1 / 10000 = 1e-4
    """
    sensor = KyleLambda60sSensor(window_seconds=60, min_samples=2)
    state = sensor.initial_state()
    sensor.update(_trade(ts_ns=1_000_000_000, price="100.00", size=100), state, params={})
    r1 = sensor.update(
        _trade(ts_ns=2_000_000_000, price="100.01", size=100), state, params={},
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
    sensor.update(_trade(ts_ns=1_000_000_000, price="100.00", size=100), state, params={})
    sensor.update(_trade(ts_ns=1_500_000_000, price="100.01", size=100), state, params={})
    sensor.update(_trade(ts_ns=1_900_000_000, price="100.02", size=100), state, params={})
    # All three samples in the window so far.
    assert len(state["samples"]) == 2  # only the deltas (n trades → n-1 deltas)
    # Jump 5s into the future — every prior sample is now older than
    # the 1s window cutoff.
    sensor.update(
        _trade(ts_ns=7_000_000_000, price="100.03", size=100), state, params={},
    )
    assert len(state["samples"]) == 1


def test_zero_size_trade_returns_none() -> None:
    sensor = KyleLambda60sSensor()
    state = sensor.initial_state()
    sensor.update(_trade(ts_ns=1, price="100", size=100), state, params={})
    assert sensor.update(_trade(ts_ns=2, price="100.01", size=0), state, params={}) is None


def test_constant_price_lambda_is_zero() -> None:
    """If price never changes, OLS slope is degenerate — emit 0."""
    sensor = KyleLambda60sSensor(window_seconds=60, min_samples=2)
    state = sensor.initial_state()
    sensor.update(_trade(ts_ns=1, price="100", size=100), state, params={})
    reading = sensor.update(_trade(ts_ns=2, price="100", size=100), state, params={})
    # Δp = 0 for every observation, denom = 0 → fall through to 0.
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
