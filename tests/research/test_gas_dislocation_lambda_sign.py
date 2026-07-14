"""Sign-goldens for ``sig_dislocation_lambda_drift_v1`` — the five
protocol §2.1 assertions, implemented exactly (Task 9 commit 3).

Gas convention (``test_gas_ofi_integrated.py`` is the model): the REAL
``SensorRegistry → HorizonScheduler → HorizonAggregator`` stack replays
a synthetic tape with known ground truth (reference ``platform.yaml``
sensor params, verbatim), and the loader-compiled alpha is driven
through the real ``HorizonSignalEngine`` dispatch path with the
bootstrap-derived required-warm set.  No cached data, no forward
returns, no outcome statistic — correctness certification only
(protocol §2.1: any assertion failure at Task-8 execution time is an
implementation-correction re-run, N unchanged).

Tape construction: phase A (0–300 s) is a flat mid at $544 (quotes
only); phase B (300–600 s) builds a 300 s micro-price dislocation of
|Δ| ≈ 3.0 (≥ ``disloc_min(APP) × level``) out of per-second
(quote, trade) pairs where the mid move over each inter-trade interval
is ``c_k × Δq_{k-1}`` — exactly the causal (Δp, Δq) pairing the
kyle_lambda_60s sensor regresses (alignment="causal").  Ramping the
impact coefficient ``c_k`` UP makes λ rise into the boundary
(percentile ≥ 0.5, the informed-flow fingerprint); ramping it DOWN
with the same dislocation magnitude makes λ fall (percentile < 0.5,
the liquidity-shock look-alike) — the card-defining contrast.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.bootstrap import (
    _horizon_features_for,
    _required_warm_feature_ids_for_signal_alpha,
)
from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    NBBOQuote,
    RegimeState,
    SensorReading,
    Signal,
    SignalDirection,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.features.aggregator import HorizonAggregator
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal

_NS = 1_000_000_000
_H = 300
_SYM = "APP"
_BOUNDARY_NS = 600 * _NS

# Frozen spec constants re-stated for ground-truth assertions (§1.2/§5.2).
_DISLOC_MIN_APP = 2.53563e-3
_FLOOR_BPS_APP = 4.6809

_ALPHA_PATH = "alphas/sig_dislocation_lambda_drift_v1/sig_dislocation_lambda_drift_v1.alpha.yaml"

# Reference sensor specs — platform.yaml params, verbatim (census parity).
_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="kyle_lambda_60s",
        sensor_version="2.0.0",
        cls=KyleLambda60sSensor,
        params={"min_samples": 30, "alignment": "causal", "sensor_version": "2.0.0"},
        subscribes_to=(NBBOQuote, Trade),
    ),
    SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.1.0",
        cls=MicroPriceSensor,
        params={"warm_after": 1, "warm_window_seconds": 60},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="realized_vol_30s",
        sensor_version="1.3.0",
        cls=RealizedVol30sSensor,
        params={"window_seconds": 30, "warm_after": 16},
        subscribes_to=(NBBOQuote,),
    ),
)


@lru_cache(maxsize=1)
def _load() -> LoadedSignalLayerModule:
    module = AlphaLoader(enforce_trend_mechanism=True).load(_ALPHA_PATH)
    assert isinstance(module, LoadedSignalLayerModule)
    return module


# ── Tape construction ─────────────────────────────────────────────────────


def _quote(ts_ns: int, mid: float, *, sym: str = _SYM) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{ts_ns}",
        sequence=ts_ns,
        symbol=sym,
        bid=Decimal(str(round(mid - 0.05, 6))),
        ask=Decimal(str(round(mid + 0.05, 6))),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts_ns,
    )


def _trade(
    ts_ns: int,
    price: float,
    size: int,
    *,
    sym: str = _SYM,
    conditions: tuple[int, ...] = (),
) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{ts_ns}",
        sequence=ts_ns,
        symbol=sym,
        price=Decimal(str(round(price, 6))),
        size=size,
        exchange_timestamp_ns=ts_ns,
        conditions=conditions,
    )


def _build_tape(
    *,
    sign: float,
    lam_rising: bool,
    trade_every_s: int = 1,
) -> list[NBBOQuote | Trade]:
    """Synthetic APP tape with a phase-B dislocation of known sign.

    ``dp_k = c_k × Δq_{k-1}``: the mid move over interval k is
    proportional to the PREVIOUS trade's signed size — the exact causal
    pairing the λ sensor regresses, so the regression slope in the
    trailing 60 s window tracks ``c`` and its 300 s percentile tracks
    the ``c`` ramp direction.  Trade sizes alternate 50/150 for Δq
    variance; trade prices are strictly monotone in the drift direction
    so the tick rule signs every Δq with ``sign``.
    """
    events: list[NBBOQuote | Trade] = []
    mid = 544.0
    for t in range(0, 300):
        events.append(_quote(t * _NS, mid))

    n = 300 // trade_every_s
    trade_price = mid
    prev_size = 100
    for k in range(n):
        frac = k / (n - 1)
        c = (0.4e-4 + 1.2e-4 * frac) if lam_rising else (1.6e-4 - 1.2e-4 * frac)
        t_ns = (300 + k * trade_every_s) * _NS
        mid += c * prev_size * sign
        events.append(_quote(t_ns, mid))
        trade_price += 0.0001 * sign
        events.append(_trade(t_ns + 400_000_000, trade_price, 50 if k % 2 == 0 else 150))
        prev_size = 50 if k % 2 == 0 else 150

    events.append(_quote(_BOUNDARY_NS, mid))
    return events


# ── Real-pipeline replay (registry → scheduler → aggregator) ──────────────


def _replay(
    events: list[NBBOQuote | Trade],
) -> tuple[list[HorizonFeatureSnapshot], list[SensorReading]]:
    bus = EventBus()
    snaps: list[HorizonFeatureSnapshot] = []
    readings: list[SensorReading] = []
    bus.subscribe(HorizonFeatureSnapshot, snaps.append)  # type: ignore[arg-type]
    bus.subscribe(SensorReading, readings.append)  # type: ignore[arg-type]
    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset({_SYM}),
    )
    for spec in _SENSOR_SPECS:
        registry.register(spec)
    scheduler = HorizonScheduler(
        horizons=frozenset({_H}),
        session_id="H8SIGN",
        symbols=frozenset({_SYM}),
        session_open_ns=0,
        sequence_generator=SequenceGenerator(),
    )
    aggregator = HorizonAggregator(
        bus=bus,
        symbols=frozenset({_SYM}),
        sensor_buffer_seconds=2 * _H,
        sequence_generator=SequenceGenerator(),
        horizon_features=[
            f
            for sid in ("kyle_lambda_60s", "micro_price", "realized_vol_30s")
            for f in _horizon_features_for(sid, _H)
        ],
    )
    aggregator.attach()
    for ev in events:
        bus.publish(ev)
        for tick in scheduler.on_event(ev):
            bus.publish(tick)
    return snaps, readings


def _boundary_snapshot(snaps: list[HorizonFeatureSnapshot]) -> HorizonFeatureSnapshot:
    matches = [s for s in snaps if s.boundary_ts_ns == _BOUNDARY_NS]
    assert len(matches) == 1, f"expected one t=600s snapshot, got {len(matches)}"
    return matches[0]


# ── Engine dispatch (real HorizonSignalEngine, required-warm set) ─────────


def _regime(p_vol_breakout: float) -> RegimeState:
    rest = 1.0 - p_vol_breakout
    return RegimeState(
        timestamp_ns=1,
        correlation_id="regime",
        sequence=1,
        symbol=_SYM,
        engine_name="hmm_3state_fractional",
        state_names=("compression_clustering", "normal", "vol_breakout"),
        posteriors=(rest * 0.4, rest * 0.6, p_vol_breakout),
        dominant_state=1,
        dominant_name="normal",
    )


def _drive_engine(snaps: list[HorizonFeatureSnapshot]) -> list[Signal]:
    loaded = _load()
    loaded.gate.reset()
    features = [
        f
        for sensor_id in loaded.depends_on_sensors
        for f in _horizon_features_for(sensor_id, loaded.horizon_seconds)
    ]
    required_warm = _required_warm_feature_ids_for_signal_alpha(
        depends_on_sensors=loaded.depends_on_sensors,
        horizon_seconds=loaded.horizon_seconds,
        horizon_features=features,
        gate=loaded.gate,
        signal_source=loaded.signal_source,
    )
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
            required_warm_feature_ids=required_warm,
        )
    )
    captured: list[Signal] = []
    bus.subscribe(Signal, captured.append)  # type: ignore[arg-type]
    engine.attach()
    bus.publish(_regime(0.10))
    for snap in snaps:
        bus.publish(snap)
    loaded.gate.reset()
    return captured


# ── Protocol §2.1 assertion 1: informed-continuation golden (LONG) ────────


def test_long_golden_informed_continuation() -> None:
    snaps, readings = _replay(_build_tape(sign=1.0, lam_rising=True))
    snap = _boundary_snapshot(snaps)

    # Ground truth: dislocation above the APP constant, λ elevated.
    level = snap.values["micro_price"]
    drift = snap.values["micro_price_drift"]
    assert drift / level >= _DISLOC_MIN_APP
    assert snap.values["kyle_lambda_60s_percentile"] >= 0.5

    # ≥ 30 causal (Δp, Δq) pairs in the trailing 60 s (λ warm) and the
    # raw kyle_lambda_60s regression slope is positive at the boundary.
    lam = [
        r
        for r in readings
        if r.sensor_id == "kyle_lambda_60s" and r.warm and r.timestamp_ns <= _BOUNDARY_NS
    ]
    assert lam, "λ never warm — tape must carry >= 30 pairs per 60 s window"
    assert lam[-1].value > 0.0
    in_window = [r for r in lam if r.timestamp_ns > _BOUNDARY_NS - 60 * _NS]
    assert len(in_window) >= 30

    signals = _drive_engine(snaps)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.direction == SignalDirection.LONG
    assert sig.strategy_id == "sig_dislocation_lambda_drift_v1"
    assert sig.edge_estimate_bps >= _FLOOR_BPS_APP


# ── Assertion 2: mirror golden (SHORT) ────────────────────────────────────


def test_short_golden_mirrored_tape() -> None:
    snaps, _readings = _replay(_build_tape(sign=-1.0, lam_rising=True))
    snap = _boundary_snapshot(snaps)
    assert snap.values["micro_price_drift"] < 0.0
    assert -snap.values["micro_price_drift"] / snap.values["micro_price"] >= _DISLOC_MIN_APP

    signals = _drive_engine(snaps)
    assert len(signals) == 1
    assert signals[0].direction == SignalDirection.SHORT


# ── Assertion 3: λ-contrast golden (card-defining) ────────────────────────


def test_lambda_contrast_same_dislocation_low_impact_emits_nothing() -> None:
    """Same dislocation magnitude, built from LOW-impact flow (large Δq
    per unit Δp; λ falling into the boundary ⇒ percentile < 0.5) ⇒ no
    entry.  The λ split — not the dislocation — is what discriminates."""
    snaps, _readings = _replay(_build_tape(sign=1.0, lam_rising=False))
    snap = _boundary_snapshot(snaps)

    # The dislocation arm alone WOULD qualify...
    assert snap.values["micro_price_drift"] / snap.values["micro_price"] >= _DISLOC_MIN_APP
    # ...but the impact fingerprint is absent.
    assert snap.values["kyle_lambda_60s_percentile"] < 0.5

    # Engine path: the gate's λ arm never arms — nothing is emitted.
    assert _drive_engine(snaps) == []

    # Direct evaluate() ground truth: the λ split returns None.
    loaded = _load()
    assert loaded.signal.evaluate(snap, None, loaded.params) is None


# ── Assertion 4: warm-gate golden (< 30 pairs ⇒ suppressed) ───────────────


def test_warm_gate_sparse_trades_suppress_entry() -> None:
    """Trades every 3 s ⇒ 20 pairs per 60 s window < min_samples 30 ⇒
    λ never warm ⇒ the percentile feature id stays cold ⇒ the engine's
    required-warm set suppresses the entry (Inv-11: warm-up suppresses
    entries, never exits)."""
    snaps, readings = _replay(_build_tape(sign=1.0, lam_rising=True, trade_every_s=3))
    snap = _boundary_snapshot(snaps)

    assert not any(r.warm for r in readings if r.sensor_id == "kyle_lambda_60s")
    assert snap.warm.get("kyle_lambda_60s_percentile") is False
    assert "kyle_lambda_60s_percentile" not in snap.values

    assert _drive_engine(snaps) == []


# ── Assertion 5: h=300 key-presence golden (factory wiring, P0-1) ─────────


def test_snapshot_carries_all_four_consumed_ids() -> None:
    snaps, _readings = _replay(_build_tape(sign=1.0, lam_rising=True))
    snap = _boundary_snapshot(snaps)
    for fid in (
        "micro_price",
        "micro_price_drift",
        "kyle_lambda_60s_percentile",
        "realized_vol_30s_zscore",
    ):
        assert fid in snap.values, f"h=300 snapshot missing consumed id {fid}"
        assert snap.warm.get(fid) is True
        assert snap.stale.get(fid) is False


# ── sensor_feature_ic H8-row smoke (impl plan §1.3; Task 9 commit 5) ──────
# The gas-01 ``_ofi_integrated_ab`` pattern: prove the protocol §2.2
# harness extension runs end-to-end on a synthetic tape and reports a row
# per (stratum, contamination way) plus the λ-contrast — no cached-data IC
# run executes here (first outcome contact belongs to Task 8 step 2).


def _load_ic_script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_sensor_feature_ic_h8", Path("scripts/sensor_feature_ic.py").resolve()
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _h8_smoke_tape(sym: str) -> list[NBBOQuote | Trade]:
    """1,205 s tape: λ ramps UP into the 600 s boundary (elevated stratum)
    and DOWN into the 900 s boundary (baseline stratum); a single Class-B
    flagged print at 895 s puts the baseline boundary's trailing-60 s
    window far above 2.0× the tape base rate, so the intensity and binary
    exclusions both fire on exactly that boundary.  Trailing drift keeps
    the mid moving so both boundaries have realised forward windows."""
    events: list[NBBOQuote | Trade] = []
    mid = 544.0
    for t in range(0, 300):
        events.append(_quote(t * _NS, mid, sym=sym))
    trade_price = mid
    prev_size = 100
    for t_s in range(300, 1205):
        if t_s < 600:
            c = 0.4e-4 + 1.2e-4 * (t_s - 300) / 299
        elif t_s < 900:
            c = 1.6e-4 - 1.2e-4 * (t_s - 600) / 299
        else:
            c = 0.5e-4
        mid += c * prev_size
        events.append(_quote(t_s * _NS, mid, sym=sym))
        trade_price += 0.0001
        events.append(
            _trade(
                t_s * _NS + 400_000_000,
                trade_price,
                50 if t_s % 2 == 0 else 150,
                sym=sym,
                conditions=(2,) if t_s == 895 else (),
            )
        )
        prev_size = 50 if t_s % 2 == 0 else 150
    return events


def test_harness_h8_row_reports_both_strata_and_all_three_contamination_ways() -> None:
    ic = _load_ic_script()
    tape = _h8_smoke_tape(_SYM)
    mids = ic._MidSeries.from_events(tape)
    rows = ic._h8_dislocation_lambda(tape, mids, _SYM, "2026-01-01", 0)

    by = {r.variant: r for r in rows}
    assert set(by) == {
        "lambda_elevated|incl",
        "lambda_elevated|primary",
        "lambda_elevated|binary",
        "lambda_baseline|incl",
        "lambda_baseline|primary",
        "lambda_baseline|binary",
        "lambda_contrast|primary",
    }
    assert all(r.feature == "h8_disloc_lambda" and r.horizon == 300 for r in rows)

    # 600 s boundary: λ-elevated, clean window ⇒ counted all three ways.
    assert by["lambda_elevated|primary"].n == 1
    assert by["lambda_elevated|incl"].n == 1
    assert by["lambda_elevated|binary"].n == 1
    # 900 s boundary: λ-baseline, flagged window ⇒ in (a) but excluded by
    # the intensity-primary (b) AND the binary (c) hooks.
    assert by["lambda_baseline|incl"].n == 1
    assert by["lambda_baseline|primary"].n == 0
    assert by["lambda_baseline|binary"].n == 0


def test_harness_h8_oln_is_evidence_only_and_contributes_no_ic_row() -> None:
    """OLN cells feed the §2.4 tick-artifact reporting hooks only — the
    protocol preamble bars OLN from every pooled IC statistic."""
    ic = _load_ic_script()
    tape = _h8_smoke_tape("OLN")
    mids = ic._MidSeries.from_events(tape)
    assert ic._h8_dislocation_lambda(tape, mids, "OLN", "2026-01-01", 0) == []
