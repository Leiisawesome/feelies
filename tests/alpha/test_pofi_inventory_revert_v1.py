"""Acceptance tests for the reference SIGNAL alpha
``alphas/pofi_inventory_revert_v1`` (Phase 3.1, INVENTORY family)."""

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
    "alphas/pofi_inventory_revert_v1/pofi_inventory_revert_v1.alpha.yaml"
)
ALPHA_ID = "pofi_inventory_revert_v1"


def test_loads_without_strict_mode() -> None:
    m = AlphaLoader().load(str(REFERENCE_PATH))
    assert isinstance(m, LoadedSignalLayerModule)
    assert m.manifest.alpha_id == ALPHA_ID


def test_loads_under_strict_mode() -> None:
    m = AlphaLoader(enforce_trend_mechanism=True).load(str(REFERENCE_PATH))
    assert isinstance(m, LoadedSignalLayerModule)
    assert m.horizon_seconds == 30
    assert m.trend_mechanism_enum is TrendMechanism.INVENTORY
    assert m.expected_half_life_seconds == 20


@pytest.fixture
def loaded() -> LoadedSignalLayerModule:
    return AlphaLoader(enforce_trend_mechanism=True).load(str(REFERENCE_PATH))


def test_manifest_metadata(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.manifest.layer == "SIGNAL"
    assert loaded.depends_on_sensors == (
        "quote_replenish_asymmetry", "spread_z_30d", "quote_hazard_rate",
    )


def test_cost_arithmetic_meets_floor(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.cost.margin_ratio == pytest.approx(1.5)


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


def _normal_with_asym(asym_z: float) -> RegimeState:
    return RegimeState(
        timestamp_ns=1_000,
        correlation_id="corr",
        sequence=1,
        symbol="AAPL",
        engine_name="hmm_3state_fractional",
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.1, 0.8, 0.1),
        dominant_state=1,
        dominant_name="normal",
    )


def _toxic_regime() -> RegimeState:
    return RegimeState(
        timestamp_ns=1_500,
        correlation_id="corr",
        sequence=2,
        symbol="AAPL",
        engine_name="hmm_3state_fractional",
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.7, 0.2, 0.1),
        dominant_state=0,
        dominant_name="compression_clustering",
    )


def _spread_reading(z: float = 0.4) -> SensorReading:
    return SensorReading(
        timestamp_ns=1_700,
        correlation_id="corr",
        sequence=3,
        symbol="AAPL",
        sensor_id="spread_z_30d",
        sensor_version="1.0.0",
        value=z,
    )


def _asym_zscore_reading(value: float) -> SensorReading:
    """Publish a quote_replenish_asymmetry reading with the given z-score
    by stamping the percentile/zscore caches via the snapshot route.

    The regime gate references ``quote_replenish_asymmetry_zscore``
    which the engine resolves from the snapshot's ``values`` dict, so
    we route the value through the snapshot rather than the sensor
    cache.
    """
    return SensorReading(
        timestamp_ns=1_750,
        correlation_id="corr",
        sequence=4,
        symbol="AAPL",
        sensor_id="quote_replenish_asymmetry",
        sensor_version="1.0.0",
        value=value,
    )


def _snapshot(
    *,
    asym_z: float,
    hazard: float,
    boundary_index: int = 1,
) -> HorizonFeatureSnapshot:
    return HorizonFeatureSnapshot(
        timestamp_ns=2_000,
        correlation_id="corr",
        sequence=10 + boundary_index,
        symbol="AAPL",
        horizon_seconds=30,
        boundary_index=boundary_index,
        values={
            "quote_replenish_asymmetry_zscore": asym_z,
            "quote_hazard_rate": hazard,
        },
    )


def test_emits_long_when_positive_asymmetry_above_threshold(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(2.5))
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=2.5, hazard=0.2))

    assert len(captured) == 1
    sig = captured[0]
    assert sig.direction == SignalDirection.LONG  # contrarian fade
    assert sig.layer == "SIGNAL"
    assert sig.horizon_seconds == 30
    assert sig.strategy_id == ALPHA_ID
    assert sig.trend_mechanism is TrendMechanism.INVENTORY
    assert sig.expected_half_life_seconds == 20
    assert 0 < sig.edge_estimate_bps <= 14.0


def test_emits_short_for_negative_asymmetry(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(2.5))
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=-2.5, hazard=0.2))
    assert len(captured) == 1
    assert captured[0].direction == SignalDirection.SHORT


def test_no_emission_when_hazard_below_floor(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(2.5))
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=2.5, hazard=0.01))  # below default 0.05
    assert captured == []


def test_no_emission_when_asymmetry_below_threshold(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(2.5))
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=1.0, hazard=0.2))
    assert captured == []


def test_no_emission_when_gate_off(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_toxic_regime())
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=2.5, hazard=0.2))
    assert captured == []


def test_edge_capped_at_disclosed_maximum(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(2.5))
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=100.0, hazard=0.2))
    assert len(captured) == 1
    assert captured[0].edge_estimate_bps == pytest.approx(14.0)
