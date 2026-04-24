"""Unit tests for HawkesIntensitySensor (v0.3 §20.4.1)."""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.hawkes_intensity import HawkesIntensitySensor


def _trade(*, ts_ns: int, price: str, size: int = 100, sequence: int = 0) -> Trade:
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
    with pytest.raises(ValueError, match="alpha"):
        HawkesIntensitySensor(alpha=0)
    with pytest.raises(ValueError, match="beta"):
        HawkesIntensitySensor(beta=0)
    with pytest.raises(ValueError, match="warm_window_seconds"):
        HawkesIntensitySensor(warm_window_seconds=0)
    with pytest.raises(ValueError, match="warm_trades_per_side"):
        HawkesIntensitySensor(warm_trades_per_side=-1)


def test_quote_events_return_none() -> None:
    sensor = HawkesIntensitySensor()
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


def test_first_buy_trade_emits_alpha_on_buy_side() -> None:
    """First trade of a side: λ = β·0 + α = α."""
    sensor = HawkesIntensitySensor(alpha=0.4, beta=0.05)
    state = sensor.initial_state()
    r = sensor.update(_trade(ts_ns=1_000_000_000, price="100.01"), state, params={})
    assert r is not None
    assert isinstance(r.value, tuple)
    lam_buy, lam_sell, ratio, branching = r.value
    assert lam_buy == pytest.approx(0.4, rel=1e-12)
    assert lam_sell == 0.0
    assert branching == pytest.approx(0.4 / 0.05, rel=1e-12)
    assert ratio == pytest.approx(1.0, rel=1e-9)


def test_decay_between_trades() -> None:
    """One buy trade then 10s gap then another buy: decay applied first."""
    sensor = HawkesIntensitySensor(alpha=0.4, beta=0.05)
    state = sensor.initial_state()
    sensor.update(_trade(ts_ns=1_000_000_000, price="100.01"), state, params={})
    r = sensor.update(_trade(ts_ns=11_000_000_000, price="100.02"), state, params={})
    assert r is not None
    lam_buy, _lam_sell, _ratio, _br = r.value
    # Hand: λ(t) = 0.4·exp(-0.05·10) ≈ 0.4·0.6065 ≈ 0.2426; then jump
    # to β·λ + α = 0.05·0.2426 + 0.4 ≈ 0.4121.
    expected = 0.05 * (0.4 * math.exp(-0.05 * 10.0)) + 0.4
    assert lam_buy == pytest.approx(expected, rel=1e-9)


def test_buy_then_sell_independent_intensities() -> None:
    sensor = HawkesIntensitySensor(alpha=0.4, beta=0.05)
    state = sensor.initial_state()
    sensor.update(_trade(ts_ns=1_000_000_000, price="100.01"), state, params={})
    r = sensor.update(_trade(ts_ns=2_000_000_000, price="99.99"), state, params={})
    assert r is not None
    lam_buy, lam_sell, _ratio, _br = r.value
    assert lam_buy > 0.0
    assert lam_sell == pytest.approx(0.4, rel=1e-12)


def test_warm_after_min_trades_per_side() -> None:
    sensor = HawkesIntensitySensor(
        warm_window_seconds=60, warm_trades_per_side=2,
    )
    state = sensor.initial_state()
    last: object = None
    # 2 buys + 2 sells inside 60s.
    sensor.update(_trade(ts_ns=1_000_000_000, price="100.01", sequence=0), state, params={})
    last = sensor.update(_trade(ts_ns=2_000_000_000, price="100.02", sequence=1), state, params={})
    assert last is not None and last.warm is False  # need sells too
    sensor.update(_trade(ts_ns=3_000_000_000, price="99.99", sequence=2), state, params={})
    last = sensor.update(_trade(ts_ns=4_000_000_000, price="99.98", sequence=3), state, params={})
    assert last is not None and last.warm is True


def test_zero_size_trade_returns_none() -> None:
    sensor = HawkesIntensitySensor()
    state = sensor.initial_state()
    assert sensor.update(_trade(ts_ns=1, price="100", size=0), state, params={}) is None
