"""Acceptance tests for the reference SIGNAL alpha
``alphas/pofi_hawkes_burst_v1`` (Phase 3.1, HAWKES_SELF_EXCITE family).

Verifies that:

* The YAML loads cleanly under both default and ``enforce_trend_mechanism``
  strict mode.
* G16 metadata propagates onto :class:`LoadedSignalLayerModule`.
* The :class:`HorizonSignalEngine` emits a deterministic
  ``Signal(layer="SIGNAL")`` with the expected provenance fields,
  ``trend_mechanism``, and ``expected_half_life_seconds`` when the gate
  is ON and the burst threshold is exceeded.
* No emission when the regime gate is OFF or when intensity / trade-through
  preconditions fail.
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
    "alphas/pofi_hawkes_burst_v1/pofi_hawkes_burst_v1.alpha.yaml"
)
ALPHA_ID = "pofi_hawkes_burst_v1"


# ── Loading ──────────────────────────────────────────────────────────────


def test_loads_without_strict_mode() -> None:
    m = AlphaLoader().load(str(REFERENCE_PATH))
    assert isinstance(m, LoadedSignalLayerModule)
    assert m.manifest.alpha_id == ALPHA_ID


def test_loads_under_strict_mode() -> None:
    m = AlphaLoader(enforce_trend_mechanism=True).load(str(REFERENCE_PATH))
    assert isinstance(m, LoadedSignalLayerModule)
    assert m.manifest.layer == "SIGNAL"
    assert m.horizon_seconds == 30


@pytest.fixture
def loaded() -> LoadedSignalLayerModule:
    m = AlphaLoader(enforce_trend_mechanism=True).load(str(REFERENCE_PATH))
    assert isinstance(m, LoadedSignalLayerModule)
    return m


# ── Manifest / metadata ─────────────────────────────────────────────────


def test_manifest_metadata(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.manifest.layer == "SIGNAL"
    assert loaded.manifest.version == "1.0.0"
    assert loaded.horizon_seconds == 30
    assert loaded.depends_on_sensors == (
        "hawkes_intensity",
        "trade_through_rate",
        "ofi_ewma",
        "spread_z_30d",
    )


def test_cost_arithmetic_meets_floor(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.cost.margin_ratio == pytest.approx(1.6)


def test_regime_gate_engine_name(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.gate.engine_name == "hmm_3state_fractional"


# ── End-to-end via HorizonSignalEngine ──────────────────────────────────


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
        posteriors=(0.7, 0.2, 0.1),
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
        value=0.25,
    )


def _snapshot(
    *,
    z: float,
    ttr: float,
    ofi: float,
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
            "hawkes_intensity_zscore": z,
            "trade_through_rate": ttr,
            "ofi_ewma": ofi,
        },
    )


def test_emits_long_when_burst_above_threshold(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_high())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot(z=2.5, ttr=0.7, ofi=0.5))

    assert len(captured) == 1
    sig = captured[0]
    assert sig.layer == "SIGNAL"
    assert sig.regime_gate_state == "ON"
    assert sig.horizon_seconds == 30
    assert sig.symbol == "AAPL"
    assert sig.strategy_id == ALPHA_ID
    assert sig.direction == SignalDirection.LONG
    assert sig.trend_mechanism is TrendMechanism.HAWKES_SELF_EXCITE
    assert sig.expected_half_life_seconds == 30
    assert 0 < sig.edge_estimate_bps <= 12.0


def test_emits_short_for_negative_ofi(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_high())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot(z=2.5, ttr=0.7, ofi=-0.5))

    assert len(captured) == 1
    assert captured[0].direction == SignalDirection.SHORT


def test_no_emission_when_intensity_below_floor(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_high())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot(z=1.0, ttr=0.7, ofi=0.5))
    assert captured == []


def test_no_emission_when_trade_through_below_floor(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_high())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot(z=2.5, ttr=0.4, ofi=0.5))
    assert captured == []


def test_no_emission_when_gate_off(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_low())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot(z=2.5, ttr=0.7, ofi=0.5))
    assert captured == []


def test_edge_capped_at_disclosed_maximum(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_high())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot(z=100.0, ttr=0.9, ofi=0.5))

    assert len(captured) == 1
    assert captured[0].edge_estimate_bps == pytest.approx(12.0)
