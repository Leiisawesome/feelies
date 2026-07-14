"""Census-consistency smoke for ``sig_dislocation_lambda_drift_v1`` —
one-cell predicate reproduction (Task 9 commit 6; impl plan §2.5).

Cache-gated (``functional``; skips on disk-cache miss with the populate
command).  Replays ONE known cell — APP 2026-01-15, the densest original
grid cell — through the production stack (the census instrument's
pipeline: ``SensorRegistry → HorizonScheduler → HorizonAggregator`` at
reference ``platform.yaml`` params, ``hmm_3state_fractional`` regime
engine calibrated on the first 100k RTH quotes) and asserts, against the
frozen census artifact
(``docs/research/artifacts/dislocation_lambda_census_2026-07-12.json``):

(a) the §1.1 entry-predicate arms, expressed through the ALPHA's own
    loaded machinery — the compiled ``on_condition`` evaluated
    memorylessly per boundary (latch reset, ``mutate=False``) plus
    ``evaluate()``'s exact APP dislocation constant tightening the
    gate's weaker RMBS arm — count exactly the census
    including-flagged number for the cell: **13**;
(b) every in-window boundary where the loaded ``evaluate()`` actually
    emits through the real ``HorizonSignalEngine`` dispatch path is a
    **subset** of those 13 predicate boundaries.

Why (b) asserts emissions ⊆ predicate set and NOT equality (Lei ruling
4, 2026-07-14): the frozen §1.1 census predicate is arms 1–6 only
(session window, warm, λ ≥ 0.5, dislocation ≥ disloc_min, posterior
< 0.7, vol-z ≤ 3.0), while ``evaluate()`` additionally applies the §6.2
EV gate (``edge_bps ≥ floor_bps(symbol)``) — emission is therefore a
strict subset of census eligibility BY CONSTRUCTION.  Asserting
equality would be wrong (it would demand the EV gate never bind), and
asserting subset without saying why would hide the EV-gate difference
from future readers.

No forward return, IC, or outcome statistic is computed — boundary
counting only (census-class, N-neutral per the 8-F C.6 rule).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

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
    Signal,
    SignalDirection,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.core.session_clock import rth_open_ns
from feelies.features.aggregator import HorizonAggregator
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec
from feelies.services.regime_engine import get_regime_engine
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal
from feelies.storage.disk_event_cache import DiskEventCache

pytestmark = pytest.mark.functional

_NS = 1_000_000_000
_H = 300
_SYM = "APP"
_DATE = "2026-01-15"
_TZ_ET = ZoneInfo("America/New_York")

# Frozen census artifact value for this cell (cond_incl == gate_on):
# dislocation_lambda_census_2026-07-12.json, APP/2026-01-15.
_CENSUS_INCL = 13

# evaluate()'s exact APP dislocation constant (spec §1.2 / Appendix-A
# instrument, verbatim) — the gate arms on the weaker RMBS constant, so
# the predicate count tightens with this one, exactly as evaluate() does.
_DISLOC_MIN_APP = 2.53563e-3

# §1.1 arm-1 session window (run-config discipline constants).
_NO_ENTRY_FIRST_SECONDS = 300
_CUTOFF_ET_SECS = 15 * 3600 + 50 * 60

_REGIME_CALIBRATION_MAX_QUOTES = 100_000  # platform.yaml regime_calibration_max_quotes

_ENTRY_WARM_IDS = (
    "kyle_lambda_60s_percentile",
    "micro_price_drift",
    "micro_price",
    "realized_vol_30s_zscore",
)

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


def _load() -> LoadedSignalLayerModule:
    module = AlphaLoader(enforce_trend_mechanism=True).load(_ALPHA_PATH)
    assert isinstance(module, LoadedSignalLayerModule)
    return module


def _in_rth(exchange_timestamp_ns: int) -> bool:
    dt = datetime.fromtimestamp(exchange_timestamp_ns / 1e9, tz=_TZ_ET)
    secs = dt.hour * 3600 + dt.minute * 60 + dt.second
    return (9 * 3600 + 30 * 60) <= secs < (16 * 3600)


@dataclass
class _Cell:
    # (snapshot, regime posteriors at snapshot time) per h=300 boundary.
    rows: list[tuple[HorizonFeatureSnapshot, list[float] | None]]
    session_open_ns: int
    state_names: tuple[str, ...]
    calibrated: bool
    discriminability: float


def _replay_cell() -> _Cell:
    cache = DiskEventCache(Path.home() / ".feelies" / "cache")
    raw = cache.load(_SYM, _DATE)
    if not raw:
        pytest.skip(
            f"Disk cache miss for {_SYM}/{_DATE} — populate with:\n"
            "  uv run python scripts/run_backtest.py "
            "--config configs/bt_sig_dislocation_lambda_drift_v1.yaml "
            f"--symbol {_SYM} --date {_DATE}"
        )
    events = [
        ev
        for ev in sorted(raw, key=lambda e: (e.timestamp_ns, e.sequence))
        if _in_rth(ev.exchange_timestamp_ns)
    ]
    session_open = rth_open_ns(events[0].timestamp_ns)

    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)  # type: ignore[arg-type]
    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset({_SYM}),
    )
    for spec in _SENSOR_SPECS:
        registry.register(spec)
    scheduler = HorizonScheduler(
        horizons=frozenset({_H}),
        session_id=f"H8SMOKE_{_SYM}_{_DATE}",
        symbols=frozenset({_SYM}),
        session_open_ns=session_open,
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

    engine = get_regime_engine("hmm_3state_fractional")
    cal_quotes = [e for e in events if isinstance(e, NBBOQuote)][:_REGIME_CALIBRATION_MAX_QUOTES]
    engine.calibrate(cal_quotes)

    rows: list[tuple[HorizonFeatureSnapshot, list[float] | None]] = []
    n_seen = 0
    for ev in events:
        if isinstance(ev, NBBOQuote):
            engine.posterior(ev)
        bus.publish(ev)
        for tick in scheduler.on_event(ev):
            bus.publish(tick)
        while n_seen < len(captured):
            s = captured[n_seen]
            n_seen += 1
            if s.horizon_seconds != _H:
                continue
            rows.append((s, engine.current_state(_SYM)))
    return _Cell(
        rows=rows,
        session_open_ns=session_open,
        state_names=tuple(engine.state_names),
        calibrated=engine.calibrated,
        discriminability=engine.discriminability,
    )


def _in_window(asof_ns: int, session_open_ns: int) -> bool:
    offset_s = (asof_ns - session_open_ns) // _NS
    dt = datetime.fromtimestamp(asof_ns / 1e9, tz=_TZ_ET)
    et_secs = dt.hour * 3600 + dt.minute * 60 + dt.second
    return offset_s >= _NO_ENTRY_FIRST_SECONDS and et_secs <= _CUTOFF_ET_SECS


def _regime_event(
    snap: HorizonFeatureSnapshot, posteriors: list[float], cell: _Cell
) -> RegimeState:
    dom = max(range(len(posteriors)), key=posteriors.__getitem__)
    return RegimeState(
        timestamp_ns=snap.timestamp_ns,
        correlation_id=f"regime-{snap.boundary_ts_ns}",
        sequence=snap.sequence,
        symbol=_SYM,
        engine_name="hmm_3state_fractional",
        state_names=cell.state_names,
        posteriors=tuple(posteriors),
        dominant_state=dom,
        dominant_name=cell.state_names[dom],
        calibrated=cell.calibrated,
        discriminability=cell.discriminability,
    )


def _predicate_boundaries(cell: _Cell, loaded: LoadedSignalLayerModule) -> set[int]:
    """§1.1 arms 1–6 via the alpha's own machinery, memorylessly per
    boundary: arm 1 = session window; arm 2 = warm/not-stale on the four
    consumed ids; arms 3–6 = the compiled ``on_condition`` (latch reset,
    ``mutate=False``) tightened by evaluate()'s exact APP dislocation
    constant (the gate arms on the weaker RMBS constant by design)."""
    out: set[int] = set()
    for snap, post in cell.rows:
        if not _in_window(snap.boundary_ts_ns, cell.session_open_ns):
            continue
        if not all(
            snap.warm.get(fid, False) and not snap.stale.get(fid, True) for fid in _ENTRY_WARM_IDS
        ):
            continue
        if post is None:
            continue
        bindings = HorizonSignalEngine._build_bindings(
            snap, _regime_event(snap, post, cell), {}, 0.0
        )
        loaded.gate.reset()
        if not loaded.gate.evaluate(symbol=_SYM, bindings=bindings, mutate=False):
            continue
        mp = snap.values["micro_price"]
        drift = snap.values["micro_price_drift"]
        mag = drift if drift >= 0.0 else -drift
        if mp <= 0.0 or mag / mp < _DISLOC_MIN_APP:
            continue
        out.add(snap.boundary_ts_ns)
    loaded.gate.reset()
    return out


@pytest.fixture(scope="module")
def cell() -> _Cell:
    return _replay_cell()


def test_predicate_arms_reproduce_census_including_flagged_count(cell: _Cell) -> None:
    """(a) The alpha-expressed predicate counts exactly the census
    including-flagged number (13) for APP/2026-01-15."""
    boundaries = _predicate_boundaries(cell, _load())
    assert len(boundaries) == _CENSUS_INCL


def test_engine_emissions_are_a_strict_subset_of_the_predicate_set(cell: _Cell) -> None:
    """(b) In-window boundaries where the loaded ``evaluate()`` emits
    through the real engine dispatch (latched gate, required-warm set,
    §6.2 EV gate) ⊆ the predicate set — see the module docstring for why
    subset, not equality, is the correct assertion."""
    loaded = _load()
    predicate = _predicate_boundaries(cell, loaded)

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
    loaded.gate.reset()

    emitted: set[int] = set()
    for snap, post in cell.rows:
        if post is not None:
            bus.publish(_regime_event(snap, post, cell))
        before = len(captured)
        bus.publish(snap)
        # Gate-close hints are FLAT (exit-direction only, Inv-11); entry
        # emissions are the LONG/SHORT signals evaluate() produced.
        if any(s.direction != SignalDirection.FLAT for s in captured[before:]):
            emitted.add(snap.boundary_ts_ns)
    loaded.gate.reset()

    # Session-window discipline (arm 1) is run-config-level enforcement
    # (no_entry_first_seconds / session flatten), not the engine's job —
    # the census count is defined on in-window boundaries, so that is the
    # comparison set.
    in_window_emitted = {b for b in emitted if _in_window(b, cell.session_open_ns)}
    assert in_window_emitted <= predicate
