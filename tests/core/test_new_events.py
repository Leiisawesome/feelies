"""Phase-1 event-contract tests (three-layer architecture v0.2).

Covers the five new event types added in §5.1-5.7 of
``docs/three_layer_architecture.md`` plus the additive fields
on ``RegimeState`` and ``Signal`` and the ``source_layer`` provenance
tag on the ``Event`` base class.

These tests exercise:
  - Instantiation with required and default fields.
  - Frozenness (immutability) per Inv-7.
  - Default equivalence with legacy producers (no behavior change).
  - Round-trip via ``dataclasses.replace`` — the closest stand-in for
    bus serialization given that ``core/serialization.py`` is currently
    a Protocol with no concrete implementation.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from feelies.core.events import (
    CrossSectionalContext,
    Event,
    HorizonFeatureSnapshot,
    HorizonTick,
    RegimeState,
    SensorProvenance,
    SensorReading,
    Signal,
    SignalDirection,
    SizedPositionIntent,
    TargetPosition,
)


# ── source_layer on Event base ──────────────────────────────────────────


def test_source_layer_default_preserves_legacy_construction() -> None:
    """Legacy producers that never set source_layer must still construct.

    A bare ``Signal(...)`` built with the original 5 fields must
    yield ``source_layer == "UNKNOWN"`` so existing code is unaffected.
    """
    sig = Signal(
        timestamp_ns=1_000_000_000,
        correlation_id="corr-1",
        sequence=1,
        symbol="AAPL",
        strategy_id="legacy_strat",
        direction=SignalDirection.LONG,
        strength=0.7,
        edge_estimate_bps=2.5,
    )
    assert sig.source_layer == "UNKNOWN"


def test_source_layer_explicit_set() -> None:
    """source_layer is a free-form tag set by the producer."""
    sig = Signal(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        strategy_id="s",
        direction=SignalDirection.FLAT,
        strength=0.0,
        edge_estimate_bps=0.0,
        source_layer="SIGNAL",
    )
    assert sig.source_layer == "SIGNAL"


# ── RegimeState additive fields (§5.4) ──────────────────────────────────


def test_regime_state_legacy_defaults() -> None:
    """Legacy regime emission gets horizon_seconds=0 and stability=1.0."""
    rs = RegimeState(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        engine_name="hmm_3state_fractional",
        state_names=("compression", "normal", "vol_breakout"),
        posteriors=(0.6, 0.3, 0.1),
        dominant_state=0,
        dominant_name="compression",
    )
    assert rs.horizon_seconds == 0
    assert rs.stability == 1.0


def test_regime_state_horizon_anchored() -> None:
    rs = RegimeState(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        engine_name="hmm_3state_fractional",
        state_names=("a", "b"),
        posteriors=(0.7, 0.3),
        dominant_state=0,
        dominant_name="a",
        horizon_seconds=120,
        stability=0.85,
    )
    assert rs.horizon_seconds == 120
    assert rs.stability == 0.85


# ── Signal additive fields (§5.5) ───────────────────────────────────────


def test_signal_default_layer_is_signal_post_d2() -> None:
    """A bare-fields Signal defaults to layer="SIGNAL" with horizon=0.

    Workstream D.2 PR-2b-ii narrowed ``Signal.layer`` to
    ``Literal["SIGNAL", "PORTFOLIO"]`` and changed the default from the
    historical ``"LEGACY_SIGNAL"`` to ``"SIGNAL"``.  Horizon-agnostic
    additive fields (``horizon_seconds``, ``regime_gate_state``,
    ``consumed_features``) keep their original neutral defaults so that
    pre-Phase-3 callers continue to construct ``Signal`` without
    specifying horizon or gate metadata.
    """
    sig = Signal(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        strategy_id="s",
        direction=SignalDirection.LONG,
        strength=0.5,
        edge_estimate_bps=1.0,
    )
    assert sig.layer == "SIGNAL"
    assert sig.horizon_seconds == 0
    assert sig.regime_gate_state == "N/A"
    assert sig.consumed_features == ()


def test_signal_horizon_layer_construction() -> None:
    sig = Signal(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        strategy_id="s",
        direction=SignalDirection.LONG,
        strength=0.5,
        edge_estimate_bps=1.0,
        layer="SIGNAL",
        horizon_seconds=300,
        regime_gate_state="ON",
        consumed_features=("ofi_ewma", "spread_z"),
    )
    assert sig.layer == "SIGNAL"
    assert sig.horizon_seconds == 300
    assert sig.regime_gate_state == "ON"
    assert sig.consumed_features == ("ofi_ewma", "spread_z")


# ── HorizonTick (§5.1) ──────────────────────────────────────────────────


def test_horizon_tick_symbol_scope() -> None:
    tick = HorizonTick(
        timestamp_ns=2_000_000_000,
        correlation_id="ht-30-1",
        sequence=1,
        horizon_seconds=30,
        boundary_index=42,
        session_id="US_EQUITY_RTH_20260420",
        scope="SYMBOL",
        symbol="AAPL",
    )
    assert tick.scope == "SYMBOL"
    assert tick.symbol == "AAPL"
    assert tick.horizon_seconds == 30


def test_horizon_tick_universe_scope_no_symbol() -> None:
    tick = HorizonTick(
        timestamp_ns=2_000_000_000,
        correlation_id="ht-300-1",
        sequence=1,
        horizon_seconds=300,
        boundary_index=1,
        session_id="US_EQUITY_RTH_20260420",
        scope="UNIVERSE",
    )
    assert tick.symbol is None


# ── SensorReading (§5.2) ────────────────────────────────────────────────


def test_sensor_reading_scalar_value() -> None:
    reading = SensorReading(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        sensor_id="ofi_ewma",
        sensor_version="1.0.0",
        value=0.42,
    )
    assert reading.confidence == 1.0
    assert reading.warm is True
    assert isinstance(reading.provenance, SensorProvenance)
    assert reading.provenance.input_event_kinds == ()


def test_sensor_reading_vector_value() -> None:
    prov = SensorProvenance(
        input_sensor_ids=("hawkes_intensity",),
        input_event_kinds=("Trade",),
    )
    reading = SensorReading(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        sensor_id="hawkes_intensity_v1",
        sensor_version="1.0.0",
        value=(1.2, 0.8, 0.6, 0.4),
        confidence=0.9,
        warm=False,
        provenance=prov,
    )
    assert isinstance(reading.value, tuple)
    assert len(reading.value) == 4
    assert reading.warm is False
    assert reading.provenance.input_sensor_ids == ("hawkes_intensity",)


# ── HorizonFeatureSnapshot (§5.3) ───────────────────────────────────────


def test_horizon_feature_snapshot_defaults() -> None:
    snap = HorizonFeatureSnapshot(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        horizon_seconds=300,
        boundary_index=1,
    )
    assert snap.values == {}
    assert snap.warm == {}
    assert snap.stale == {}
    assert snap.source_sensors == {}


def test_horizon_feature_snapshot_populated() -> None:
    snap = HorizonFeatureSnapshot(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        horizon_seconds=300,
        boundary_index=1,
        values={"ofi_ewma": 0.42, "spread_z": -1.2},
        warm={"ofi_ewma": True, "spread_z": True},
        stale={"ofi_ewma": False, "spread_z": False},
        source_sensors={"ofi_ewma": ("ofi_ewma_sensor",)},
    )
    assert snap.values["ofi_ewma"] == 0.42
    assert snap.warm["spread_z"] is True


# ── CrossSectionalContext (§5.6) ────────────────────────────────────────


def test_cross_sectional_context_completeness_default() -> None:
    ctx = CrossSectionalContext(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        horizon_seconds=300,
        boundary_index=1,
        universe=("AAPL", "MSFT"),
    )
    assert ctx.completeness == 0.0
    assert ctx.signals_by_symbol == {}
    assert ctx.snapshots_by_symbol == {}


# ── SizedPositionIntent (§5.7) ──────────────────────────────────────────


def test_sized_position_intent_defaults() -> None:
    intent = SizedPositionIntent(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        strategy_id="pofi_xsect_v1",
    )
    assert intent.layer == "PORTFOLIO"
    assert intent.target_positions == {}
    assert intent.factor_exposures == {}
    assert intent.expected_turnover_usd == 0.0
    assert intent.expected_gross_exposure_usd == 0.0
    assert intent.mechanism_breakdown == {}


def test_target_position_construction() -> None:
    tp = TargetPosition(symbol="AAPL", target_usd=10000.0, urgency=0.8)
    assert tp.symbol == "AAPL"
    assert tp.target_usd == 10000.0
    assert tp.urgency == 0.8


def test_target_position_default_urgency() -> None:
    tp = TargetPosition(symbol="MSFT", target_usd=-5000.0)
    assert tp.urgency == 0.5


# ── Frozenness (Inv-7) ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "event,attr,new_value",
    [
        (
            HorizonTick(
                timestamp_ns=1, correlation_id="c", sequence=1,
                horizon_seconds=30, boundary_index=1,
                session_id="s", scope="UNIVERSE",
            ),
            "horizon_seconds", 60,
        ),
        (
            SensorReading(
                timestamp_ns=1, correlation_id="c", sequence=1,
                symbol="AAPL", sensor_id="x", sensor_version="1.0.0",
                value=0.0,
            ),
            "value", 1.0,
        ),
        (
            HorizonFeatureSnapshot(
                timestamp_ns=1, correlation_id="c", sequence=1,
                symbol="AAPL", horizon_seconds=300, boundary_index=1,
            ),
            "boundary_index", 2,
        ),
        (
            CrossSectionalContext(
                timestamp_ns=1, correlation_id="c", sequence=1,
                horizon_seconds=300, boundary_index=1,
                universe=("A",),
            ),
            "completeness", 1.0,
        ),
        (
            SizedPositionIntent(
                timestamp_ns=1, correlation_id="c", sequence=1,
                strategy_id="s",
            ),
            "expected_turnover_usd", 100.0,
        ),
        (
            TargetPosition(symbol="A", target_usd=1.0),
            "target_usd", 2.0,
        ),
        (
            SensorProvenance(),
            "input_sensor_ids", ("x",),
        ),
    ],
)
def test_frozenness(event: Event, attr: str, new_value: object) -> None:
    """Every new event/support type is immutable."""
    with pytest.raises(FrozenInstanceError):
        setattr(event, attr, new_value)


# ── Round-trip via dataclasses.replace (serialization stand-in) ─────────


def test_signal_replace_round_trip() -> None:
    """``dataclasses.replace`` produces an equal-by-value copy.

    Stand-in for bus serialization until ``core/serialization.py`` is
    implemented (Phase 2+).  Replace is the closest equivalent to
    "construct from same field values" without relying on JSON or
    pickle round-trips that the platform's serialization layer will
    eventually formalize.
    """
    sig = Signal(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        strategy_id="s",
        direction=SignalDirection.LONG,
        strength=0.5,
        edge_estimate_bps=1.0,
        layer="SIGNAL",
        horizon_seconds=300,
        consumed_features=("a", "b"),
    )
    copy = replace(sig)
    assert copy == sig
    assert copy is not sig


def test_horizon_tick_replace_with_field_change() -> None:
    tick = HorizonTick(
        timestamp_ns=1,
        correlation_id="c",
        sequence=1,
        horizon_seconds=30,
        boundary_index=1,
        session_id="s",
        scope="SYMBOL",
        symbol="AAPL",
    )
    bumped = replace(tick, boundary_index=2, sequence=2)
    assert bumped.boundary_index == 2
    assert bumped.sequence == 2
    assert bumped.symbol == "AAPL"
    assert tick.boundary_index == 1
