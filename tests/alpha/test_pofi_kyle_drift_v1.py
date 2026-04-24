"""Acceptance tests for the reference SIGNAL alpha
``alphas/pofi_kyle_drift_v1`` (Phase 3.1, KYLE_INFO family)."""

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
    "alphas/pofi_kyle_drift_v1/pofi_kyle_drift_v1.alpha.yaml"
)
ALPHA_ID = "pofi_kyle_drift_v1"


def test_loads_without_strict_mode() -> None:
    m = AlphaLoader().load(str(REFERENCE_PATH))
    assert isinstance(m, LoadedSignalLayerModule)
    assert m.manifest.alpha_id == ALPHA_ID


def test_loads_under_strict_mode() -> None:
    m = AlphaLoader(enforce_trend_mechanism=True).load(str(REFERENCE_PATH))
    assert isinstance(m, LoadedSignalLayerModule)
    assert m.horizon_seconds == 300
    assert m.trend_mechanism_enum is TrendMechanism.KYLE_INFO
    assert m.expected_half_life_seconds == 600


@pytest.fixture
def loaded() -> LoadedSignalLayerModule:
    return AlphaLoader(enforce_trend_mechanism=True).load(str(REFERENCE_PATH))


def test_manifest_metadata(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.manifest.layer == "SIGNAL"
    assert loaded.depends_on_sensors == (
        "kyle_lambda_60s", "ofi_ewma", "micro_price", "spread_z_30d",
    )


def test_cost_arithmetic_meets_floor(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.cost.margin_ratio == pytest.approx(1.8)


def test_regime_gate_engine_name(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.gate.engine_name == "hmm_3state_fractional"


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


def _normal_high() -> RegimeState:
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


def _normal_low() -> RegimeState:
    return RegimeState(
        timestamp_ns=1_500,
        correlation_id="corr",
        sequence=2,
        symbol="AAPL",
        engine_name="hmm_3state_fractional",
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.6, 0.2, 0.2),
        dominant_state=0,
        dominant_name="compression_clustering",
    )


def _spread_low_reading() -> SensorReading:
    return SensorReading(
        timestamp_ns=1_700,
        correlation_id="corr",
        sequence=3,
        symbol="AAPL",
        sensor_id="spread_z_30d",
        sensor_version="1.0.0",
        value=0.4,
    )


def _snapshot(
    *, lam_pct: float, lam_z: float, ofi: float, boundary_index: int = 1,
) -> HorizonFeatureSnapshot:
    return HorizonFeatureSnapshot(
        timestamp_ns=2_000,
        correlation_id="corr",
        sequence=10 + boundary_index,
        symbol="AAPL",
        horizon_seconds=300,
        boundary_index=boundary_index,
        values={
            "kyle_lambda_60s_percentile": lam_pct,
            "kyle_lambda_60s_zscore": lam_z,
            "ofi_ewma": ofi,
        },
    )


def test_emits_long_when_lambda_high_and_ofi_positive(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_high())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot(lam_pct=0.9, lam_z=2.0, ofi=0.8))

    assert len(captured) == 1
    sig = captured[0]
    assert sig.direction == SignalDirection.LONG
    assert sig.layer == "SIGNAL"
    assert sig.regime_gate_state == "ON"
    assert sig.horizon_seconds == 300
    assert sig.strategy_id == ALPHA_ID
    assert sig.trend_mechanism is TrendMechanism.KYLE_INFO
    assert sig.expected_half_life_seconds == 600
    assert 0 < sig.edge_estimate_bps <= 25.0


def test_emits_short_for_negative_ofi(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_high())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot(lam_pct=0.85, lam_z=1.5, ofi=-0.7))
    assert len(captured) == 1
    assert captured[0].direction == SignalDirection.SHORT


def test_no_emission_when_lambda_below_percentile(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_high())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot(lam_pct=0.5, lam_z=0.2, ofi=0.8))
    assert captured == []


def test_no_emission_when_ofi_below_threshold(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_high())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot(lam_pct=0.9, lam_z=2.0, ofi=0.1))
    assert captured == []


def test_no_emission_when_gate_off(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_low())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot(lam_pct=0.9, lam_z=2.0, ofi=0.8))
    assert captured == []


def test_edge_capped_at_disclosed_maximum(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_high())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot(lam_pct=0.99, lam_z=100.0, ofi=0.8))
    assert len(captured) == 1
    assert captured[0].edge_estimate_bps == pytest.approx(25.0)
