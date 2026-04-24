"""Acceptance tests for the reference SIGNAL alpha
``alphas/pofi_moc_imbalance_v1`` (Phase 3.1, SCHEDULED_FLOW family).

Exercises the tuple-sensor expansion path
(``scheduled_flow_window`` → ``scheduled_flow_window_active``,
``seconds_to_window_close``, ``scheduled_flow_window_direction_prior``)
end-to-end through :class:`HorizonSignalEngine`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    RegimeState,
    SensorReading,
    Signal,
    SignalDirection,
    TrendMechanism,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal


REFERENCE_PATH = Path(
    "alphas/pofi_moc_imbalance_v1/pofi_moc_imbalance_v1.alpha.yaml"
)
ALPHA_ID = "pofi_moc_imbalance_v1"


def test_loads_without_strict_mode() -> None:
    m = AlphaLoader().load(str(REFERENCE_PATH))
    assert isinstance(m, LoadedSignalLayerModule)
    assert m.manifest.alpha_id == ALPHA_ID


def test_loads_under_strict_mode() -> None:
    m = AlphaLoader(enforce_trend_mechanism=True).load(str(REFERENCE_PATH))
    assert isinstance(m, LoadedSignalLayerModule)
    assert m.horizon_seconds == 120
    assert m.trend_mechanism_enum is TrendMechanism.SCHEDULED_FLOW
    assert m.expected_half_life_seconds == 240


@pytest.fixture
def loaded() -> LoadedSignalLayerModule:
    return AlphaLoader(enforce_trend_mechanism=True).load(str(REFERENCE_PATH))


def test_manifest_metadata(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.manifest.layer == "SIGNAL"
    assert loaded.depends_on_sensors == ("scheduled_flow_window", "ofi_ewma")


def test_cost_arithmetic_meets_floor(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.cost.margin_ratio == pytest.approx(2.0)


def _engine_with_alpha(
    loaded: LoadedSignalLayerModule,
) -> tuple[HorizonSignalEngine, EventBus, list[Signal]]:
    bus = EventBus()
    seq = SequenceGenerator()
    engine = HorizonSignalEngine(bus=bus, signal_sequence_generator=seq)
    engine.register(RegisteredSignal(
        alpha_id=loaded.manifest.alpha_id,
        horizon_seconds=loaded.horizon_seconds,
        signal=loaded.signal,
        params=loaded.params,
        gate=loaded.gate,
        cost_arithmetic=loaded.cost,
        consumed_features=loaded.consumed_features,
        trend_mechanism=loaded.trend_mechanism_enum,
        expected_half_life_seconds=loaded.expected_half_life_seconds,
    ))
    captured: list[Signal] = []
    bus.subscribe(Signal, captured.append)  # type: ignore[arg-type]
    engine.attach()
    return engine, bus, captured


def _normal_regime() -> RegimeState:
    return RegimeState(
        timestamp_ns=1_000,
        correlation_id="corr",
        sequence=1,
        symbol="AAPL",
        engine_name="hmm_3state_fractional",
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.05, 0.85, 0.10),
        dominant_state=1,
        dominant_name="normal",
    )


def _flow_window_reading(
    *,
    active: float,
    seconds_to_close: float,
    direction_prior: float = 1.0,
    window_id_hash: float = 12345.0,
) -> SensorReading:
    """Publish the scheduled_flow_window 4-tuple per design §20.4.2."""
    return SensorReading(
        timestamp_ns=1_500,
        correlation_id="corr",
        sequence=2,
        symbol="AAPL",
        sensor_id="scheduled_flow_window",
        sensor_version="1.0.0",
        value=(active, seconds_to_close, window_id_hash, direction_prior),
    )


def _snapshot(
    *,
    active: float,
    seconds_to_close: float,
    direction_prior: float,
    ofi: float,
    boundary_index: int = 1,
) -> HorizonFeatureSnapshot:
    return HorizonFeatureSnapshot(
        timestamp_ns=2_000,
        correlation_id="corr",
        sequence=10 + boundary_index,
        symbol="AAPL",
        horizon_seconds=120,
        boundary_index=boundary_index,
        values={
            "scheduled_flow_window_active": active,
            "seconds_to_window_close": seconds_to_close,
            "scheduled_flow_window_direction_prior": direction_prior,
            "ofi_ewma": ofi,
        },
    )


def test_emits_long_when_window_active_and_ofi_positive(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_regime())
    bus.publish(_flow_window_reading(
        active=1.0, seconds_to_close=180.0, direction_prior=1.0,
    ))
    bus.publish(_snapshot(
        active=1.0, seconds_to_close=180.0, direction_prior=1.0, ofi=0.5,
    ))

    assert len(captured) == 1
    sig = captured[0]
    assert sig.direction == SignalDirection.LONG
    assert sig.layer == "SIGNAL"
    assert sig.regime_gate_state == "ON"
    assert sig.horizon_seconds == 120
    assert sig.strategy_id == ALPHA_ID
    assert sig.trend_mechanism is TrendMechanism.SCHEDULED_FLOW
    assert sig.expected_half_life_seconds == 240
    assert 0 < sig.edge_estimate_bps <= 18.0


def test_emits_short_when_direction_prior_negative_and_ofi_negative(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_regime())
    bus.publish(_flow_window_reading(
        active=1.0, seconds_to_close=180.0, direction_prior=-1.0,
    ))
    bus.publish(_snapshot(
        active=1.0, seconds_to_close=180.0, direction_prior=-1.0, ofi=-0.5,
    ))
    assert len(captured) == 1
    assert captured[0].direction == SignalDirection.SHORT


def test_no_emission_when_window_inactive(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_regime())
    bus.publish(_flow_window_reading(
        active=0.0, seconds_to_close=-1.0, direction_prior=0.0,
    ))
    bus.publish(_snapshot(
        active=0.0, seconds_to_close=-1.0, direction_prior=0.0, ofi=0.5,
    ))
    assert captured == []


def test_no_emission_when_too_close_to_close(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_regime())
    bus.publish(_flow_window_reading(
        active=1.0, seconds_to_close=45.0, direction_prior=1.0,
    ))
    bus.publish(_snapshot(
        active=1.0, seconds_to_close=45.0, direction_prior=1.0, ofi=0.5,
    ))
    # Below 60s — gate off_condition triggers (seconds_to_window_close < 30
    # is false, but on_condition (>60) is also false → gate stays OFF).
    assert captured == []


def test_no_emission_when_ofi_disagrees_with_prior(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_regime())
    bus.publish(_flow_window_reading(
        active=1.0, seconds_to_close=180.0, direction_prior=1.0,
    ))
    bus.publish(_snapshot(
        active=1.0, seconds_to_close=180.0, direction_prior=1.0, ofi=-0.5,
    ))
    assert captured == []


def test_tuple_sensor_expansion_populates_gate_bindings(
    loaded: LoadedSignalLayerModule,
) -> None:
    """Smoke: the engine fans out the 4-tuple into the documented
    component names so the regime-gate DSL can reference them."""
    engine, bus, _ = _engine_with_alpha(loaded)
    bus.publish(_flow_window_reading(
        active=1.0, seconds_to_close=180.0, direction_prior=1.0,
        window_id_hash=42.0,
    ))
    cache = engine._sensor_cache  # type: ignore[attr-defined]
    assert cache[("AAPL", "scheduled_flow_window_active")] == 1.0
    assert cache[("AAPL", "seconds_to_window_close")] == 180.0
    assert cache[("AAPL", "scheduled_flow_window_id_hash")] == 42.0
    assert cache[("AAPL", "scheduled_flow_window_direction_prior")] == 1.0
