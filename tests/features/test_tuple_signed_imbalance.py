"""TupleSignedImbalanceFeature — directional Hawkes fingerprint (audit P1-3)."""

from __future__ import annotations

import pytest

from feelies.core.events import HorizonTick, SensorReading
from feelies.features.impl.sensor_passthrough import TupleSignedImbalanceFeature


def _reading(value, *, warm=True) -> SensorReading:
    return SensorReading(
        timestamp_ns=1_000,
        correlation_id="c",
        sequence=1,
        source_layer="SENSORS",
        symbol="TEST",
        sensor_id="hawkes_intensity",
        sensor_version="1.2.0",
        value=value,
        warm=warm,
    )


def _tick() -> HorizonTick:
    return HorizonTick(
        timestamp_ns=2_000,
        correlation_id="c2",
        sequence=2,
        source_layer="FEATURES",
        horizon_seconds=30,
        boundary_index=1,
        session_id="US_EQUITY_RTH_2026-01-15",
        scope="SYMBOL",
        symbol="TEST",
    )


def _feat() -> TupleSignedImbalanceFeature:
    # λ_buy at index 0, λ_sell at index 1.
    return TupleSignedImbalanceFeature(
        "hawkes_intensity", 0, 1, "hawkes_intensity_imbalance", 30,
    )


def test_signed_imbalance_buy_dominant_is_positive() -> None:
    feat = _feat()
    state = feat.initial_state()
    feat.observe(_reading((3.0, 1.0, 0.75, 8.0)), state, {})
    val, warm, stale = feat.finalize(_tick(), state, {})
    assert warm is True
    assert stale is False
    # (3 - 1) / (3 + 1) = 0.5
    assert val == pytest.approx(0.5)


def test_signed_imbalance_sell_dominant_is_negative() -> None:
    feat = _feat()
    state = feat.initial_state()
    feat.observe(_reading((1.0, 3.0, 0.75, 8.0)), state, {})
    val, _, _ = feat.finalize(_tick(), state, {})
    assert val == pytest.approx(-0.5)


def test_signed_imbalance_zero_when_no_information() -> None:
    """Both sides ~0 ⇒ 0.0, not a div-by-zero blow-up."""
    feat = _feat()
    state = feat.initial_state()
    feat.observe(_reading((0.0, 0.0, 0.5, 8.0)), state, {})
    val, warm, _ = feat.finalize(_tick(), state, {})
    assert warm is True
    assert val == 0.0


def test_cold_reading_does_not_warm() -> None:
    feat = _feat()
    state = feat.initial_state()
    feat.observe(_reading((3.0, 1.0, 0.75, 8.0), warm=False), state, {})
    val, warm, stale = feat.finalize(_tick(), state, {})
    assert warm is False
    assert val == 0.0
    assert stale is False


def test_scalar_value_is_ignored() -> None:
    feat = _feat()
    state = feat.initial_state()
    feat.observe(_reading(0.42), state, {})  # not a tuple
    _, warm, _ = feat.finalize(_tick(), state, {})
    assert warm is False
