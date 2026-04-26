"""Acceptance tests for the reference SIGNAL alpha
``alphas/pofi_benign_midcap_v1`` (Phase 3-α).

Verifies:

* The YAML loads cleanly via :class:`AlphaLoader`, dispatches to the
  SIGNAL-layer path, and surfaces a :class:`LoadedSignalLayerModule`.
* All declared sensors resolve, the regime gate compiles, and the
  cost-arithmetic block validates.
* The :class:`HorizonSignalEngine` end-to-end emits a Phase-3
  ``Signal(layer="SIGNAL")`` with the expected provenance fields when
  the gate is ON and the threshold is exceeded.
* The same engine swallows the snapshot when the OFI z-score is
  below threshold (gate-on but no edge).
* The signal is suppressed when the regime gate is OFF.
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
)
from feelies.core.identifiers import SequenceGenerator
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal


REFERENCE_PATH = Path(
    "alphas/pofi_benign_midcap_v1/pofi_benign_midcap_v1.alpha.yaml"
)
ALPHA_ID = "pofi_benign_midcap_v1"


@pytest.fixture
def loaded() -> LoadedSignalLayerModule:
    m = AlphaLoader().load(str(REFERENCE_PATH))
    assert isinstance(m, LoadedSignalLayerModule)
    return m


# ── Manifest / metadata ─────────────────────────────────────────────────


def test_manifest_metadata(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.manifest.alpha_id == ALPHA_ID
    assert loaded.manifest.layer == "SIGNAL"
    assert loaded.manifest.version == "1.0.0"
    assert loaded.horizon_seconds == 120
    assert loaded.depends_on_sensors == (
        "ofi_ewma", "micro_price", "spread_z_30d",
    )
    assert loaded.consumed_features == loaded.depends_on_sensors


def test_cost_arithmetic_meets_floor(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.cost.margin_ratio == pytest.approx(1.8)
    assert loaded.cost.computed_margin_ratio == pytest.approx(1.8, abs=0.05)


def test_regime_gate_engine_name(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.gate.engine_name == "hmm_3state_fractional"


def test_default_parameters(loaded: LoadedSignalLayerModule) -> None:
    p = loaded.params
    assert p["entry_threshold_z"] == pytest.approx(2.0)
    assert p["edge_per_z_bps"] == pytest.approx(4.0)
    assert p["edge_cap_bps"] == pytest.approx(20.0)


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
    ))
    captured: list[Signal] = []
    bus.subscribe(Signal, captured.append)  # type: ignore[arg-type]
    engine.attach()
    return engine, bus, captured


def _normal_high(symbol: str = "AAPL") -> RegimeState:
    return RegimeState(
        timestamp_ns=1_000,
        correlation_id="corr",
        sequence=1,
        symbol=symbol,
        engine_name="hmm_3state_fractional",
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.1, 0.85, 0.05),
        dominant_state=1,
        dominant_name="normal",
    )


def _normal_low(symbol: str = "AAPL") -> RegimeState:
    return RegimeState(
        timestamp_ns=1_500,
        correlation_id="corr",
        sequence=2,
        symbol=symbol,
        engine_name="hmm_3state_fractional",
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(0.7, 0.2, 0.1),
        dominant_state=0,
        dominant_name="compression_clustering",
    )


def _spread_low_reading(symbol: str = "AAPL") -> SensorReading:
    return SensorReading(
        timestamp_ns=1_700,
        correlation_id="corr",
        sequence=3,
        symbol=symbol,
        sensor_id="spread_z_30d",
        sensor_version="1.0.0",
        value=0.1,
    )


def _snapshot_with_z(
    z: float,
    *,
    symbol: str = "AAPL",
    boundary_index: int = 1,
) -> HorizonFeatureSnapshot:
    """Snapshot whose ``values`` carries the ``ofi_ewma_zscore`` reading."""
    return HorizonFeatureSnapshot(
        timestamp_ns=2_000,
        correlation_id="corr",
        sequence=10 + boundary_index,
        symbol=symbol,
        horizon_seconds=120,
        boundary_index=boundary_index,
        values={"ofi_ewma_zscore": z},
    )


def test_emits_long_when_gate_on_and_z_above_threshold(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_high())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot_with_z(z=2.5))

    assert len(captured) == 1
    sig = captured[0]
    assert sig.layer == "SIGNAL"
    assert sig.regime_gate_state == "ON"
    assert sig.horizon_seconds == 120
    assert sig.symbol == "AAPL"
    assert sig.strategy_id == ALPHA_ID
    assert sig.direction == SignalDirection.LONG
    assert 0 < sig.edge_estimate_bps <= 20.0


def test_emits_short_for_negative_z(loaded: LoadedSignalLayerModule) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_high())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot_with_z(z=-3.0))

    assert len(captured) == 1
    assert captured[0].direction == SignalDirection.SHORT


def test_no_emission_below_threshold(loaded: LoadedSignalLayerModule) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_high())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot_with_z(z=1.0))               # below default threshold 2.0
    assert captured == []


def test_no_emission_when_gate_off(loaded: LoadedSignalLayerModule) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_low())                         # P(normal)=0.2
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot_with_z(z=2.5))
    assert captured == []


def test_edge_capped_at_disclosed_maximum(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_high())
    bus.publish(_spread_low_reading())
    bus.publish(_snapshot_with_z(z=100.0))             # would extrapolate huge

    assert len(captured) == 1
    assert captured[0].edge_estimate_bps == pytest.approx(20.0)
