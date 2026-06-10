"""Acceptance tests for the reference SIGNAL alpha
``alphas/sig_inventory_revert_v1`` (Phase 3.1, INVENTORY family)."""

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


REFERENCE_PATH = Path("alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml")
ALPHA_ID = "sig_inventory_revert_v1"


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
        "quote_replenish_asymmetry",
        "spread_z_30d",
        "quote_hazard_rate",
        "realized_vol_30s",
    )


def test_cost_arithmetic_meets_floor(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.cost.margin_ratio == pytest.approx(1.6)
    assert loaded.cost.computed_margin_ratio == pytest.approx(1.6, abs=0.05)


def _engine_with_alpha(
    loaded: LoadedSignalLayerModule,
) -> tuple[HorizonSignalEngine, EventBus, list[Signal]]:
    bus = EventBus()
    seq = SequenceGenerator()
    engine = HorizonSignalEngine(bus=bus, signal_sequence_generator=seq)
    engine.register(
        RegisteredSignal(
            alpha_id=loaded.manifest.alpha_id,
            horizon_seconds=loaded.horizon_seconds,
            signal=loaded.signal,
            params=loaded.params,
            gate=loaded.gate,
            cost_arithmetic=loaded.cost,
            consumed_features=loaded.consumed_features,
            trend_mechanism=loaded.trend_mechanism_enum,
            expected_half_life_seconds=loaded.expected_half_life_seconds,
        )
    )
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
        sensor_version="1.1.0",
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
        sensor_version="1.1.0",
        value=value,
    )


def _snapshot(
    *,
    asym_z: float,
    hazard: float,
    rv_z: float = 0.0,
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
            "realized_vol_30s_zscore": rv_z,
        },
    )


# Default-parameter edge math (calm regime, asym_z=A, hazard >> floor, rv_z=0):
#   peak  = min((A-2.0) * 3.5, 14.0)
#   capt  = peak * 0.646
#   edge  = capt * hazard_weight * vol_weight
# Emission requires ``edge > cost_floor_bps`` (5.5). At hw=vw=1, the
# minimum firing |A| is ~4.43; tests use 4.5 as the canonical "above
# threshold, calm regime" trigger.


def test_emits_long_when_positive_asymmetry_above_threshold(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(4.5))
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=4.5, hazard=8.0))

    assert len(captured) == 1
    sig = captured[0]
    assert sig.direction == SignalDirection.LONG  # contrarian fade
    assert sig.layer == "SIGNAL"
    assert sig.horizon_seconds == 30
    assert sig.strategy_id == ALPHA_ID
    assert sig.trend_mechanism is TrendMechanism.INVENTORY
    assert sig.expected_half_life_seconds == 20
    # Realized cap = 14.0 * 0.646 = 9.044; edge must be above the cost
    # floor (5.5) and at or below that capturable cap.
    assert 5.5 < sig.edge_estimate_bps <= 14.0 * 0.646 + 1e-6


def test_emits_short_for_negative_asymmetry(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(4.5))
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=-4.5, hazard=8.0))
    assert len(captured) == 1
    assert captured[0].direction == SignalDirection.SHORT


def test_no_emission_when_hazard_below_floor(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(2.5))
    bus.publish(_spread_reading())
    # 1.0 events/sec is below the default 4.0/sec floor.
    bus.publish(_snapshot(asym_z=2.5, hazard=1.0))
    assert captured == []


def test_no_emission_when_asymmetry_below_threshold(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(2.5))
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=1.0, hazard=8.0))
    assert captured == []


def test_no_emission_when_gate_off(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_toxic_regime())
    bus.publish(_spread_reading())
    # asym_z=4.5 would clear the cost floor — only the gate suppresses here.
    bus.publish(_snapshot(asym_z=4.5, hazard=8.0))
    assert captured == []


def test_edge_capped_at_capturable_peak(
    loaded: LoadedSignalLayerModule,
) -> None:
    """Saturating asym_z hits ``edge_cap_bps`` (14.0) which is then taxed by
    ``realized_capture_ratio`` (0.646) to yield the capturable cap of
    ~9.04 bps. With no hazard/vol stress, that's exactly what's reported."""
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(2.5))
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=100.0, hazard=8.0, rv_z=0.0))
    assert len(captured) == 1
    assert captured[0].edge_estimate_bps == pytest.approx(14.0 * 0.646)
    # Strength is normalized against the capturable cap, so saturation
    # produces strength = 1.0, preserving downstream conviction
    # resolution that the legacy formula lost.
    assert captured[0].strength == pytest.approx(1.0)


def test_no_emission_below_cost_floor(
    loaded: LoadedSignalLayerModule,
) -> None:
    """asym_z=4.0 clears the z-threshold (>2.0). Peak edge = 2.0*3.5 = 7.0,
    capturable = 7.0*0.646 = 4.52, below cost_floor=5.5 so no emission."""
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(4.0))
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=4.0, hazard=8.0))
    assert captured == []


def test_realized_capture_ratio_taxes_peak_edge(
    loaded: LoadedSignalLayerModule,
) -> None:
    """Capturable edge equals peak times the configured ratio. With
    asym_z=5.5 calm, peak = 3.5*3.5 = 12.25, capturable = 12.25*0.646 = 7.91."""
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(5.5))
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=5.5, hazard=8.0, rv_z=0.0))
    assert len(captured) == 1
    expected_peak = (5.5 - 2.0) * 3.5
    assert captured[0].edge_estimate_bps == pytest.approx(expected_peak * 0.646)


def test_soft_hazard_ramp_scales_edge_below_full_weight(
    loaded: LoadedSignalLayerModule,
) -> None:
    """Hazard partway up the soft ramp scales capturable edge by
    ``(hazard - floor) / band``. We use a 0.9 weight here so the
    suppressed edge still clears the 5.5 bps cost floor; smaller weights
    correctly suppress emission entirely (covered by other tests)."""
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(100.0))
    bus.publish(_spread_reading())
    # hazard = floor + 0.9*band = 4.0 + 1.8 = 5.8 → hazard_weight = 0.9
    bus.publish(_snapshot(asym_z=100.0, hazard=5.8, rv_z=0.0))
    assert len(captured) == 1
    # Saturated peak (14.0) * ratio (0.646) * hazard_weight (0.9).
    assert captured[0].edge_estimate_bps == pytest.approx(14.0 * 0.646 * 0.9)


def test_soft_hazard_ramp_suppresses_when_weight_pushes_below_floor(
    loaded: LoadedSignalLayerModule,
) -> None:
    """Hazard just above the floor weights edge down enough to fall
    below ``cost_floor_bps`` — even at saturating asym_z — so no signal
    is emitted. This is the soft-ramp's reason to exist: marginal
    ladders shrink toward zero rather than firing at full peak edge."""
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(100.0))
    bus.publish(_spread_reading())
    # hazard = floor + 0.5*band = 4.0 + 1.0 = 5.0 → hazard_weight = 0.5
    # ⇒ edge = 14*0.646*0.5 = 4.52 < 5.5
    bus.publish(_snapshot(asym_z=100.0, hazard=5.0, rv_z=0.0))
    assert captured == []


def test_vol_taper_reduces_edge_under_stress(
    loaded: LoadedSignalLayerModule,
) -> None:
    """Mild vol stress (rv_z=0.7) yields vol_weight = 1 - 0.7/3.5 = 0.8
    so capturable edge is reduced 20%. Heavier stress suppresses
    emission via the cost floor — covered separately."""
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(100.0))
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=100.0, hazard=8.0, rv_z=0.7))
    assert len(captured) == 1
    assert captured[0].edge_estimate_bps == pytest.approx(14.0 * 0.646 * 0.8)


def test_direction_sign_locked_to_hypothesis(
    loaded: LoadedSignalLayerModule,
) -> None:
    """Regression-lock on the LONG/SHORT mapping.

    NOTE: the sensor-sign assumption (positive ``asym_z`` ⇒ bid-side
    replenishing faster ⇒ price was pushed down ⇒ contrarian LONG) is
    EMPIRICAL and is documented in the alpha YAML as needing live
    confirmation against forward 30 s micro-price returns. This test
    does NOT verify that assumption; it only ensures the LONG/SHORT
    decision in ``evaluate()`` does not silently flip relative to the
    hypothesis comment. Operators must run the empirical sign check
    against a representative event log before promotion."""
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_normal_with_asym(4.5))
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=+4.5, hazard=8.0))
    bus.publish(_normal_with_asym(-4.5))
    bus.publish(_spread_reading())
    bus.publish(_snapshot(asym_z=-4.5, hazard=8.0, boundary_index=2))
    assert len(captured) == 2
    pos_sig, neg_sig = captured
    assert pos_sig.direction == SignalDirection.LONG
    assert neg_sig.direction == SignalDirection.SHORT
