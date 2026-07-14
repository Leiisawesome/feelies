"""Acceptance tests for ``alphas/sig_dislocation_lambda_drift_v1``
(Task 9 commit 1; KYLE_INFO family, candidate H8).

Every numeric constant asserted here is frozen by the formal spec
(docs/research/sig_dislocation_lambda_drift_v1_formal_spec.md §§1.2,
5.2, 6, 11, 13); the tests pin the YAML to those numbers so silent
drift trips CI.  Includes the 00e Track-A strength rider tests
(strength ∈ [0, 1] across full declared parameter ranges; adversarial
Hypothesis property test).
"""

from __future__ import annotations

import math
from functools import lru_cache
from itertools import product
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.bootstrap import (
    _horizon_features_for,
    _required_warm_feature_ids_for_signal_alpha,
)
from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    RegimeState,
    Signal,
    SignalDirection,
    TrendMechanism,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal
from feelies.signals.regime_gate import Bindings


REFERENCE_PATH = Path(
    "alphas/sig_dislocation_lambda_drift_v1/sig_dislocation_lambda_drift_v1.alpha.yaml"
)
ALPHA_ID = "sig_dislocation_lambda_drift_v1"

# Frozen per-symbol constants (spec §1.2 / §5.2) re-stated here so the
# tests fail if the YAML literals drift.
DISLOC_MIN = {"APP": 2.53563e-3, "RMBS": 2.37165e-3}
FLOOR_BPS = {"APP": 4.6809, "RMBS": 5.4645}
APP_LEVEL = 544.0  # pack-05 median RTH bid scale for APP


@lru_cache(maxsize=2)
def _load(strict: bool = True) -> LoadedSignalLayerModule:
    module = AlphaLoader(enforce_trend_mechanism=strict).load(str(REFERENCE_PATH))
    assert isinstance(module, LoadedSignalLayerModule)
    return module


@pytest.fixture
def loaded() -> LoadedSignalLayerModule:
    return _load(strict=True)


# ── Load / gate battery (G2–G16 through the real loader) ────────────────


def test_loads_without_strict_mode() -> None:
    m = _load(strict=False)
    assert m.manifest.alpha_id == ALPHA_ID


def test_loads_under_strict_mode() -> None:
    m = _load(strict=True)
    assert m.manifest.alpha_id == ALPHA_ID
    assert m.manifest.layer == "SIGNAL"
    assert m.horizon_seconds == 300


def test_manifest_sensor_dependencies(loaded: LoadedSignalLayerModule) -> None:
    # Spec §1.3: no ofi_ewma (§16 row 5), no spread_z_30d (§1.1 ban).
    assert loaded.depends_on_sensors == (
        "kyle_lambda_60s",
        "micro_price",
        "realized_vol_30s",
    )


def test_g16_arithmetic_at_frozen_numbers(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.trend_mechanism_enum is TrendMechanism.KYLE_INFO
    hl = loaded.expected_half_life_seconds
    assert hl == 150
    assert 60 <= hl <= 1800  # KYLE_INFO envelope
    ratio = loaded.horizon_seconds / hl
    assert ratio == pytest.approx(2.0)
    assert 0.5 <= ratio <= 4.0

    tm = loaded.manifest.trend_mechanism
    assert tm is not None
    signature_sensors = set(tm["l1_signature_sensors"])
    # Both G16 rule-5 KYLE_INFO fingerprints, present in BOTH lists.
    assert signature_sensors == {"kyle_lambda_60s", "micro_price"}
    assert signature_sensors <= set(loaded.depends_on_sensors)

    clauses = tm["failure_signature"]
    assert len(clauses) == 5
    joined = " || ".join(clauses)
    for phrase in (
        "spread-in-ticks strata within the benign stratum",
        "rolling 20-session window",
        "indistinguishable between kyle_lambda_60s_percentile >= 0.5 and < 0.5",
        ">=4-tick spread stratum",
        "session-interior boundaries",
    ):
        assert phrase in joined, f"missing failure-signature clause: {phrase}"


def test_g12_arithmetic_at_frozen_numbers(loaded: LoadedSignalLayerModule) -> None:
    c = loaded.cost
    assert c.edge_estimate_bps == pytest.approx(6.4)
    assert c.half_spread_bps == 0.0
    assert c.impact_bps == pytest.approx(2.0)
    assert c.fee_bps == pytest.approx(0.08)
    assert c.margin_ratio == pytest.approx(3.08)
    computed = 6.4 / (0.0 + 2.0 + 0.08)
    assert abs(c.margin_ratio - computed) <= 0.05  # ±0.05 absolute (G12)
    assert c.margin_ratio >= 1.5
    assert c.cost_basis == "one_way"


def test_hazard_exit_block_normalized(loaded: LoadedSignalLayerModule) -> None:
    # Spec §6.4: explicit null hard age -> bootstrap derives 2 × hl = 300 s.
    assert loaded.manifest.hazard_exit == {
        "enabled": True,
        "hazard_score_threshold": 0.85,
        "min_age_seconds": 30,
        "hard_exit_age_seconds": None,
    }


def test_risk_budget_frozen_numbers(loaded: LoadedSignalLayerModule) -> None:
    # Lei ruling 3 (2026-07-14): top-of-book scale — APP p50 displayed
    # depth 80 sh, Sharpe-max declaration; inert to protocol steps 2–8.
    rb = loaded.manifest.risk_budget
    assert rb.max_position_per_symbol == 80
    assert rb.max_gross_exposure_pct == pytest.approx(3.0)
    assert rb.max_drawdown_pct == pytest.approx(0.75)
    assert rb.capital_allocation_pct == pytest.approx(5.0)


def test_parameters_frozen_defaults_and_ranges(loaded: LoadedSignalLayerModule) -> None:
    schema = {p.name: p for p in loaded.manifest.parameter_schema}
    assert set(schema) == {"lambda_percentile_min", "edge_scale_bps", "edge_cap_bps"}
    assert schema["lambda_percentile_min"].default == pytest.approx(0.5)
    assert schema["lambda_percentile_min"].range == (0.5, 0.7)
    assert schema["edge_scale_bps"].default == pytest.approx(10.0)
    assert schema["edge_scale_bps"].range == (6.0, 16.0)
    assert schema["edge_cap_bps"].default == pytest.approx(12.0)
    assert schema["edge_cap_bps"].range == (8.0, 20.0)


def test_required_warm_set_is_exactly_the_four_consumed_ids(
    loaded: LoadedSignalLayerModule,
) -> None:
    """Consume-driven required-warm derivation resolves to spec §1.3."""
    features = []
    for sensor_id in loaded.depends_on_sensors:
        features.extend(_horizon_features_for(sensor_id, loaded.horizon_seconds))
    req = _required_warm_feature_ids_for_signal_alpha(
        depends_on_sensors=loaded.depends_on_sensors,
        horizon_seconds=loaded.horizon_seconds,
        horizon_features=features,
        gate=loaded.gate,
        signal_source=loaded.signal_source,
    )
    assert req == frozenset(
        {
            "micro_price_drift",
            "micro_price",
            "kyle_lambda_60s_percentile",
            "realized_vol_30s_zscore",
        }
    )


# ── Gate DSL latch semantics (spec §6.3) ─────────────────────────────────


def _regime(p_vol_breakout: float, symbol: str = "APP") -> RegimeState:
    rest = 1.0 - p_vol_breakout
    return RegimeState(
        timestamp_ns=1_000,
        correlation_id="corr",
        sequence=1,
        symbol=symbol,
        engine_name="hmm_3state_fractional",
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(rest * 0.4, rest * 0.6, p_vol_breakout),
        dominant_state=2 if p_vol_breakout > 0.5 else 1,
        dominant_name="vol_breakout" if p_vol_breakout > 0.5 else "normal",
    )


def _bindings(
    *,
    p_vb: float,
    drift: float = 2.0,
    level: float = APP_LEVEL,
    pctl: float = 0.9,
    rv_z: float = 0.5,
) -> Bindings:
    return Bindings(
        regime=_regime(p_vb),
        sensor_values={"micro_price_drift": drift, "micro_price": level},
        percentiles={"kyle_lambda_60s": pctl},
        zscores={"realized_vol_30s": rv_z},
    )


def test_gate_engine_name_and_hysteresis(loaded: LoadedSignalLayerModule) -> None:
    assert loaded.gate.engine_name == "hmm_3state_fractional"
    assert loaded.gate.hysteresis == {
        "posterior_margin": 0.15,
        "percentile_margin": 0.15,
    }


def test_gate_posterior_latch_arms_below_070_releases_above_085(
    loaded: LoadedSignalLayerModule,
) -> None:
    gate = loaded.gate
    gate.reset()
    assert gate.evaluate(symbol="APP", bindings=_bindings(p_vb=0.69)) is True
    # Inside the hysteresis band (0.70, 0.85]: latch holds ON.
    assert gate.evaluate(symbol="APP", bindings=_bindings(p_vb=0.80)) is True
    # Above 0.70 + posterior_margin = 0.85: releases OFF.
    assert gate.evaluate(symbol="APP", bindings=_bindings(p_vb=0.86)) is False
    # Back below 0.70: re-arms.
    assert gate.evaluate(symbol="APP", bindings=_bindings(p_vb=0.50)) is True
    gate.reset()


def test_gate_lambda_latch_arms_at_050_releases_below_035(
    loaded: LoadedSignalLayerModule,
) -> None:
    gate = loaded.gate
    gate.reset()
    assert gate.evaluate(symbol="APP", bindings=_bindings(p_vb=0.1, pctl=0.50)) is True
    # Inside the band [0.35, 0.50): mechanism-lapse release not tripped.
    assert gate.evaluate(symbol="APP", bindings=_bindings(p_vb=0.1, pctl=0.40)) is True
    # Below 0.50 − percentile_margin = 0.35: mechanism-lapse release.
    assert gate.evaluate(symbol="APP", bindings=_bindings(p_vb=0.1, pctl=0.30)) is False
    # Recovery inside the band does NOT re-arm (on needs >= 0.50).
    assert gate.evaluate(symbol="APP", bindings=_bindings(p_vb=0.1, pctl=0.40)) is False
    gate.reset()


# ── Engine-driven behavior (HorizonSignalEngine, real dispatch path) ─────


def _engine_with_alpha(
    loaded: LoadedSignalLayerModule,
) -> tuple[HorizonSignalEngine, EventBus, list[Signal]]:
    loaded.gate.reset()
    bus = EventBus()
    engine = HorizonSignalEngine(bus=bus, signal_sequence_generator=SequenceGenerator())
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


def _snapshot(
    *,
    symbol: str = "APP",
    drift: float,
    level: float = APP_LEVEL,
    pctl: float,
    rv_z: float = 0.5,
    boundary_index: int = 1,
) -> HorizonFeatureSnapshot:
    return HorizonFeatureSnapshot(
        timestamp_ns=2_000,
        correlation_id="corr",
        sequence=10 + boundary_index,
        symbol=symbol,
        horizon_seconds=300,
        boundary_index=boundary_index,
        values={
            "micro_price_drift": drift,
            "micro_price": level,
            "kyle_lambda_60s_percentile": pctl,
            "realized_vol_30s_zscore": rv_z,
        },
    )


def test_emits_long_on_golden_dislocation(loaded: LoadedSignalLayerModule) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_regime(0.10))
    bus.publish(_snapshot(drift=2.0, pctl=0.9))

    assert len(captured) == 1
    sig = captured[0]
    assert sig.direction == SignalDirection.LONG
    assert sig.layer == "SIGNAL"
    assert sig.regime_gate_state == "ON"
    assert sig.horizon_seconds == 300
    assert sig.strategy_id == ALPHA_ID
    assert sig.trend_mechanism is TrendMechanism.KYLE_INFO
    assert sig.expected_half_life_seconds == 150
    # disloc = 2/544 → d_x ≈ 0.44995; l_x = 0.8; excess ≈ 0.62498.
    assert sig.strength == pytest.approx(0.62498, abs=1e-4)
    assert sig.edge_estimate_bps == pytest.approx(6.2498, abs=1e-3)
    assert sig.edge_estimate_bps >= FLOOR_BPS["APP"]
    assert 0.0 <= sig.strength <= 1.0


def test_emits_short_on_mirrored_dislocation(loaded: LoadedSignalLayerModule) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_regime(0.10))
    bus.publish(_snapshot(drift=-2.0, pctl=0.9))
    assert len(captured) == 1
    assert captured[0].direction == SignalDirection.SHORT
    assert captured[0].strength == pytest.approx(0.62498, abs=1e-4)


def test_no_emission_below_per_symbol_disloc_min(loaded: LoadedSignalLayerModule) -> None:
    """Gate arms on the weaker (RMBS) constant; evaluate() enforces the
    exact APP constant — a drift in the [gate, APP) band emits nothing."""
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_regime(0.10))
    # 0.00237165 × 544 = 1.290 < 1.33 < 1.3794 = 2.53563e-3 × 544.
    bus.publish(_snapshot(drift=1.33, pctl=0.9))
    assert captured == []


def test_no_emission_below_lambda_split_while_latched_on(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_regime(0.10))
    bus.publish(_snapshot(drift=2.0, pctl=0.9, boundary_index=1))
    assert len(captured) == 1
    # pctl 0.45: gate stays ON (release needs < 0.35) but evaluate's
    # own λ arm (pctl < p0 = 0.5) suppresses the entry.
    bus.publish(_snapshot(drift=2.0, pctl=0.45, boundary_index=2))
    assert len(captured) == 1


def test_no_emission_when_ev_gate_fails(loaded: LoadedSignalLayerModule) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_regime(0.10))
    # disloc barely above disloc_min and pctl barely above the split:
    # edge ≈ 0.52 bps < APP floor 4.6809 bps → EV gate returns None.
    bus.publish(_snapshot(drift=1.385, pctl=0.55))
    assert captured == []


def test_no_emission_when_gate_off(loaded: LoadedSignalLayerModule) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_regime(0.90))  # P(vol_breakout) ≥ 0.7 → gate never arms
    bus.publish(_snapshot(drift=2.0, pctl=0.9))
    assert captured == []


def test_no_emission_for_symbol_outside_deployable_set(
    loaded: LoadedSignalLayerModule,
) -> None:
    _, bus, captured = _engine_with_alpha(loaded)
    bus.publish(_regime(0.10, symbol="MSFT"))
    bus.publish(_snapshot(symbol="MSFT", drift=2.0, pctl=0.9))
    assert captured == []


def test_edge_capped_at_declared_maximum() -> None:
    """At defaults edge_scale (10) ≤ edge_cap (12) with excess ≤ 1 the cap
    is unreachable; override to scale 16 / cap 8 (both in-range) to
    exercise the min() cap arm."""
    module = AlphaLoader(enforce_trend_mechanism=True).load(
        str(REFERENCE_PATH),
        param_overrides={"edge_scale_bps": 16.0, "edge_cap_bps": 8.0},
    )
    assert isinstance(module, LoadedSignalLayerModule)
    _, bus, captured = _engine_with_alpha(module)
    bus.publish(_regime(0.10))
    bus.publish(_snapshot(drift=6.0, pctl=1.0))  # excess saturates at 1.0
    assert len(captured) == 1
    assert captured[0].edge_estimate_bps == pytest.approx(8.0)
    assert captured[0].strength == pytest.approx(1.0)


# ── 00e Track-A strength rider (spec §6.2, pre-registered tests) ─────────


def test_strength_in_unit_interval_across_full_parameter_ranges(
    loaded: LoadedSignalLayerModule,
) -> None:
    """Rider test (i): emitted strength ∈ [0, 1] at the min and max of
    every declared parameter range (not just defaults)."""
    schema = {p.name: p for p in loaded.manifest.parameter_schema}
    p0_range = schema["lambda_percentile_min"].range
    scale_range = schema["edge_scale_bps"].range
    cap_range = schema["edge_cap_bps"].range
    assert p0_range is not None and scale_range is not None and cap_range is not None

    drifts = [1.30, 1.38, 1.385, 2.0, 6.0, 1e5]
    pctls = [0.5, 0.55, 0.7, 0.71, 0.9, 1.0]
    levels = {"APP": APP_LEVEL, "RMBS": 102.0}

    emitted = 0
    for p0, scale, cap in product(p0_range, scale_range, cap_range):
        params = {
            "lambda_percentile_min": p0,
            "edge_scale_bps": scale,
            "edge_cap_bps": cap,
        }
        for symbol, level in levels.items():
            for sign in (1.0, -1.0):
                for drift in drifts:
                    for pctl in pctls:
                        snap = _snapshot(symbol=symbol, drift=sign * drift, level=level, pctl=pctl)
                        result = loaded.signal.evaluate(snap, None, params)
                        if result is None:
                            continue
                        emitted += 1
                        assert 0.0 <= result.strength <= 1.0
                        assert result.edge_estimate_bps <= params["edge_cap_bps"]
                        assert result.edge_estimate_bps >= FLOOR_BPS[symbol]
    assert emitted > 0  # the sweep must actually exercise emissions


_ADVERSARIAL = st.one_of(
    st.none(),
    st.floats(allow_nan=True, allow_infinity=True, width=64),
    st.sampled_from(
        [
            float("nan"),
            float("inf"),
            float("-inf"),
            0.0,
            -0.0,
            5e-324,
            -5e-324,
            1.7e308,
            -1.7e308,
        ]
    ),
)


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    drift=_ADVERSARIAL,
    level=_ADVERSARIAL,
    pctl=_ADVERSARIAL,
    symbol=st.sampled_from(["APP", "RMBS", "MSFT"]),
)
def test_property_adversarial_snapshot_values(
    drift: float | None,
    level: float | None,
    pctl: float | None,
    symbol: str,
) -> None:
    """Rider test (ii): under adversarial snapshot values (NaN, ±inf,
    extremes, missing keys, zero/negative micro_price) evaluate returns
    None or an in-range strength with non-negative finite edge."""
    module = _load(strict=True)
    values: dict[str, float] = {}
    if drift is not None:
        values["micro_price_drift"] = drift
    if level is not None:
        values["micro_price"] = level
    if pctl is not None:
        values["kyle_lambda_60s_percentile"] = pctl
    snapshot = HorizonFeatureSnapshot(
        timestamp_ns=2_000,
        correlation_id="corr",
        sequence=11,
        symbol=symbol,
        horizon_seconds=300,
        boundary_index=1,
        values=values,
    )
    result = module.signal.evaluate(snapshot, None, module.params)
    if result is None:
        return
    assert isinstance(result, Signal)
    assert result.direction in (SignalDirection.LONG, SignalDirection.SHORT)
    assert 0.0 <= result.strength <= 1.0
    assert math.isfinite(result.edge_estimate_bps)
    assert result.edge_estimate_bps >= 0.0
