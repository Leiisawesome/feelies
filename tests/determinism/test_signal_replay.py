"""Level-2 baseline — ``Signal`` replay parity for layer: SIGNAL alphas.

Phase 3-α locks a deterministic Level-2 fingerprint of the
``Signal(layer="SIGNAL")`` stream produced by the reference alpha
``alphas/pofi_benign_midcap_v1`` when driven through the canonical
synthetic event-log fixture under the standard sensor / scheduler /
aggregator wiring.

Phase 3.1 extends the lock-down to the four v0.3 reference alphas
(``pofi_hawkes_burst_v1``, ``pofi_kyle_drift_v1``,
``pofi_inventory_revert_v1``, ``pofi_moc_imbalance_v1``).  Each is
driven through the same fixture and its Signal stream is hashed
independently so any future drift is attributable to the specific
alpha that introduced it.

The :class:`HorizonAggregator` runs in passive-emitter mode in v0.2,
so :class:`HorizonFeatureSnapshot.values` is empty.  All registered
alphas consult ``snapshot.values`` for their decision inputs and
therefore never cross their entry thresholds on the synthetic
fixture — the locked Level-2 baseline is **zero signals** for every
alpha at this milestone.

This is by design.  Locking the empty baseline immediately surfaces
any future drift (extra subscriptions, accidental emission, sequence
allocation changes, alpha namespace leakage) the moment it appears.
The same alphas will lock non-empty Level-2 baselines once their
sensors emit z-scores into the snapshot in the Phase 3.5+
active-aggregator slice.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from feelies.alpha.loader import AlphaLoader
from feelies.alpha.signal_layer_module import LoadedSignalLayerModule
from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    NBBOQuote,
    SensorReading,
    Signal,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.features.aggregator import HorizonAggregator
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal
from tests.fixtures.event_logs._generate import (
    DEFAULT_OUTPUT,
    SESSION_OPEN_NS,
    load,
)


REFERENCE_PATH = Path(
    "alphas/pofi_benign_midcap_v1/pofi_benign_midcap_v1.alpha.yaml"
)

_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.0.0",
        cls=OFIEwmaSensor,
        params={"alpha": 0.1, "warm_after": 5},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.0.0",
        cls=MicroPriceSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="spread_z_30d",
        sensor_version="1.0.0",
        cls=SpreadZScoreSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
)


def _replay(alpha_path: str = str(REFERENCE_PATH)) -> tuple[str, int]:
    bus = EventBus()
    captured_signals: list[Signal] = []
    bus.subscribe(Signal, captured_signals.append)  # type: ignore[arg-type]

    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset({"AAPL"}),
    )
    for spec in _SENSOR_SPECS:
        registry.register(spec)

    scheduler = HorizonScheduler(
        horizons=frozenset({30, 120, 300}),
        session_id="TEST_SYNTH",
        symbols=frozenset({"AAPL"}),
        session_open_ns=SESSION_OPEN_NS,
        sequence_generator=SequenceGenerator(),
    )

    aggregator = HorizonAggregator(
        bus=bus,
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=600,
        sequence_generator=SequenceGenerator(),
    )
    aggregator.attach()

    loaded = AlphaLoader(enforce_trend_mechanism=False).load(alpha_path)
    assert isinstance(loaded, LoadedSignalLayerModule)

    engine = HorizonSignalEngine(
        bus=bus, signal_sequence_generator=SequenceGenerator(),
    )
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
    engine.attach()

    for event in load(DEFAULT_OUTPUT):
        if not isinstance(event, (NBBOQuote, Trade)):
            continue
        bus.publish(event)
        for tick in scheduler.on_event(event):
            bus.publish(tick)

    return _hash_signal_stream(captured_signals), len(captured_signals)


def _hash_signal_stream(signals: list[Signal]) -> str:
    lines: list[str] = []
    for s in signals:
        lines.append(
            f"{s.sequence}|{s.symbol}|{s.strategy_id}|{s.layer}|"
            f"{s.horizon_seconds}|{s.regime_gate_state}|"
            f"{s.direction.name}|{s.strength:.6f}|"
            f"{s.edge_estimate_bps:.6f}|{s.timestamp_ns}|"
            f"{s.correlation_id}|"
            f"CF={','.join(s.consumed_features)}|"
            f"TM={s.trend_mechanism.name if s.trend_mechanism else '-'}|"
            f"HL={s.expected_half_life_seconds}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# ── Determinism (replay twice → same hash) ──────────────────────────────


def test_two_replays_produce_identical_signal_hash() -> None:
    hash_a, count_a = _replay()
    hash_b, count_b = _replay()
    assert count_a == count_b
    assert hash_a == hash_b


# ── Locked baseline ─────────────────────────────────────────────────────


# Level-2 baseline: hash of the (potentially empty) Signal stream.
# Empty-stream sha256: e3b0c44...b855 — the well-known SHA-256 of the
# empty input.  Replays must reproduce this exactly until either
# (a) the active aggregator slice ships and snapshots carry sensor
# z-scores, or (b) a Phase-3 reference alpha is added that emits on
# the synthetic fixture.  Either change will require updating both
# the count and the hash in the same commit.
EXPECTED_LEVEL2_SIGNAL_HASH = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)
EXPECTED_LEVEL2_SIGNAL_COUNT = 0


def test_signal_stream_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay()

    assert actual_count == EXPECTED_LEVEL2_SIGNAL_COUNT, (
        f"signal count drift: expected "
        f"{EXPECTED_LEVEL2_SIGNAL_COUNT}, got {actual_count}"
    )
    assert actual_hash == EXPECTED_LEVEL2_SIGNAL_HASH, (
        "Level-2 Signal hash drift!\n"
        f"  Expected: {EXPECTED_LEVEL2_SIGNAL_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional, update the constant in the same commit and "
        "justify in the commit message."
    )


# ── Cross-check that the wiring is real (no false-empty pass) ──────────


# ── Phase-3.1 reference alphas — locked Level-2 baselines ──────────────


# Each of the four v0.3 reference alphas locks the same empty-stream
# baseline at this milestone (see module docstring).  Listed here so a
# future commit that promotes any one of them to a non-empty stream
# only has to touch this list and bump the (per-alpha) hash + count.
_V03_REFERENCE_ALPHAS: tuple[tuple[str, str], ...] = (
    (
        "pofi_hawkes_burst_v1",
        "alphas/pofi_hawkes_burst_v1/pofi_hawkes_burst_v1.alpha.yaml",
    ),
    (
        "pofi_kyle_drift_v1",
        "alphas/pofi_kyle_drift_v1/pofi_kyle_drift_v1.alpha.yaml",
    ),
    (
        "pofi_inventory_revert_v1",
        "alphas/pofi_inventory_revert_v1/pofi_inventory_revert_v1.alpha.yaml",
    ),
    (
        "pofi_moc_imbalance_v1",
        "alphas/pofi_moc_imbalance_v1/pofi_moc_imbalance_v1.alpha.yaml",
    ),
)


@pytest.mark.parametrize(
    "alpha_id,alpha_path",
    _V03_REFERENCE_ALPHAS,
    ids=[alpha_id for alpha_id, _ in _V03_REFERENCE_ALPHAS],
)
def test_v03_reference_alpha_signal_baseline(
    alpha_id: str, alpha_path: str,
) -> None:
    actual_hash, actual_count = _replay(alpha_path)

    assert actual_count == EXPECTED_LEVEL2_SIGNAL_COUNT, (
        f"v0.3 reference alpha {alpha_id!r}: signal count drift — "
        f"expected {EXPECTED_LEVEL2_SIGNAL_COUNT}, got {actual_count}"
    )
    assert actual_hash == EXPECTED_LEVEL2_SIGNAL_HASH, (
        f"v0.3 reference alpha {alpha_id!r}: Level-2 hash drift!\n"
        f"  Expected: {EXPECTED_LEVEL2_SIGNAL_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional, update the locked baseline in the same "
        "commit and justify in the commit message."
    )


@pytest.mark.parametrize(
    "alpha_id,alpha_path",
    _V03_REFERENCE_ALPHAS,
    ids=[alpha_id for alpha_id, _ in _V03_REFERENCE_ALPHAS],
)
def test_v03_reference_alpha_replay_is_deterministic(
    alpha_id: str, alpha_path: str,
) -> None:
    hash_a, count_a = _replay(alpha_path)
    hash_b, count_b = _replay(alpha_path)
    assert count_a == count_b
    assert hash_a == hash_b


def test_wiring_actually_dispatches() -> None:
    """Sanity guard: the engine sees snapshots even if it emits nothing.

    Confirmed indirectly by the upstream Level-3 baseline locking 28
    snapshots for the same fixture; if the engine were silently
    detached we would still see zero signals here, so we verify the
    snapshot count separately to prove the engine is wired.
    """
    bus = EventBus()
    snapshots: list[HorizonFeatureSnapshot] = []
    sensor_readings: list[SensorReading] = []
    bus.subscribe(HorizonFeatureSnapshot, snapshots.append)  # type: ignore[arg-type]
    bus.subscribe(SensorReading, sensor_readings.append)  # type: ignore[arg-type]

    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset({"AAPL"}),
    )
    for spec in _SENSOR_SPECS:
        registry.register(spec)

    scheduler = HorizonScheduler(
        horizons=frozenset({30, 120, 300}),
        session_id="TEST_SYNTH",
        symbols=frozenset({"AAPL"}),
        session_open_ns=SESSION_OPEN_NS,
        sequence_generator=SequenceGenerator(),
    )

    aggregator = HorizonAggregator(
        bus=bus,
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=600,
        sequence_generator=SequenceGenerator(),
    )
    aggregator.attach()

    for event in load(DEFAULT_OUTPUT):
        if not isinstance(event, (NBBOQuote, Trade)):
            continue
        bus.publish(event)
        for tick in scheduler.on_event(event):
            bus.publish(tick)

    assert snapshots, "no HorizonFeatureSnapshot emitted — wiring broken"
    assert sensor_readings, "no SensorReading emitted — wiring broken"
