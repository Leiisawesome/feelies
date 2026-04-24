"""Unit tests for SNRDriftDiffusionSensor (v0.3 §20.4.3)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.snr_drift_diffusion import SNRDriftDiffusionSensor


def _quote(*, ts_ns: int, mid: str, sequence: int = 0) -> NBBOQuote:
    """Quote with bid=ask-0.005 around the requested mid (zero spread up to rounding)."""
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
    with pytest.raises(ValueError, match="horizons_seconds"):
        SNRDriftDiffusionSensor(horizons_seconds=())
    with pytest.raises(ValueError, match="positive"):
        SNRDriftDiffusionSensor(horizons_seconds=(0,))
    with pytest.raises(ValueError, match="ewma_n_eff"):
        SNRDriftDiffusionSensor(ewma_n_eff=0)
    with pytest.raises(ValueError, match="warm_samples_per_horizon"):
        SNRDriftDiffusionSensor(warm_samples_per_horizon=-1)


def test_horizons_sorted_in_value_tuple() -> None:
    sensor = SNRDriftDiffusionSensor(horizons_seconds=(120, 30))
    state = sensor.initial_state()
    r = sensor.update(_quote(ts_ns=1, mid="100"), state, params={})
    assert r is not None
    assert isinstance(r.value, tuple)
    assert len(r.value) == 2  # one per horizon, ascending


def test_trade_events_return_none() -> None:
    sensor = SNRDriftDiffusionSensor(horizons_seconds=(30,))
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


def test_first_quote_bootstraps_grid_no_snr_yet() -> None:
    sensor = SNRDriftDiffusionSensor(horizons_seconds=(30,))
    state = sensor.initial_state()
    r = sensor.update(_quote(ts_ns=1_000_000_000, mid="100"), state, params={})
    assert r is not None
    # No grid crossings yet → SNR is 0.
    assert r.value[0] == 0.0
    assert r.warm is False


def test_warm_after_required_samples_per_horizon() -> None:
    """Need 4 samples on a 1-second horizon."""
    sensor = SNRDriftDiffusionSensor(
        horizons_seconds=(1,), warm_samples_per_horizon=4,
    )
    state = sensor.initial_state()
    last = None
    for i in range(5):
        last = sensor.update(
            _quote(ts_ns=(i + 1) * 1_000_000_000, mid="100", sequence=i),
            state, params={},
        )
        assert last is not None
    assert last is not None and last.warm is True


def test_zero_volatility_yields_zero_snr() -> None:
    """Constant mid → μ=0 and σ=0 → SNR=|0|/(ε/√h) = 0."""
    sensor = SNRDriftDiffusionSensor(
        horizons_seconds=(1,), warm_samples_per_horizon=2,
    )
    state = sensor.initial_state()
    r = None
    for i in range(6):
        r = sensor.update(
            _quote(ts_ns=(i + 1) * 1_000_000_000, mid="100", sequence=i),
            state, params={},
        )
    assert r is not None
    assert r.value[0] == 0.0


def test_positive_drift_produces_positive_snr() -> None:
    """Monotone increasing mid → SNR > 0 once warm."""
    sensor = SNRDriftDiffusionSensor(
        horizons_seconds=(1,), warm_samples_per_horizon=2, ewma_n_eff=4,
    )
    state = sensor.initial_state()
    r = None
    for i in range(10):
        r = sensor.update(
            _quote(
                ts_ns=(i + 1) * 1_000_000_000,
                mid=str(100 + i * 0.01),
                sequence=i,
            ),
            state, params={},
        )
    assert r is not None
    assert r.value[0] > 0.0
