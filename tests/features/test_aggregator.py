"""Unit tests for :class:`feelies.features.aggregator.HorizonAggregator`.

Two execution modes are exercised:

- **Passive mode** (Phase-2 default) — no horizon features registered;
  the aggregator emits one empty :class:`HorizonFeatureSnapshot` per
  ``HorizonTick`` it receives.
- **Active mode** — a tiny test :class:`HorizonFeature` is registered
  to verify ``observe`` / ``finalize`` lifecycle, per-symbol state
  isolation, ring-buffer eviction, and snapshot wiring.
"""

from __future__ import annotations

from typing import Any, Mapping

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    HorizonTick,
    SensorReading,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.features.aggregator import HorizonAggregator
from feelies.features.impl.horizon_windowed import HorizonWindowedFeature
from feelies.features.protocol import HorizonFeature


# ── Test feature ────────────────────────────────────────────────────


class _SumFeature:
    """Sums all sensor-reading scalars seen in the current window."""

    feature_id: str = "sum_feat"
    feature_version: str = "1.0.0"
    input_sensor_ids: tuple[str, ...] = ("ofi_ewma",)
    horizon_seconds: int = 30

    def initial_state(self) -> dict[str, Any]:
        return {"sum": 0.0, "count": 0, "received": False}

    def observe(
        self,
        reading: SensorReading,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> None:
        v = reading.value
        if isinstance(v, tuple):
            v = v[0]
        state["sum"] += float(v)
        state["count"] += 1
        state["received"] = True

    def finalize(
        self,
        tick: HorizonTick,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> tuple[float, bool, bool]:
        n = state["count"]
        value = state["sum"] if n > 0 else 0.0
        warm = n > 0
        stale = not state["received"]
        # Reset window state so the next horizon starts clean.
        state["sum"] = 0.0
        state["count"] = 0
        state["received"] = False
        return value, warm, stale


# ── Helpers ────────────────────────────────────────────────────────


def _reading(
    *,
    symbol: str = "AAPL",
    ts_ns: int,
    sensor_id: str = "ofi_ewma",
    value: float = 1.0,
    warm: bool = True,
) -> SensorReading:
    return SensorReading(
        timestamp_ns=ts_ns,
        correlation_id=f"r-{ts_ns}",
        sequence=ts_ns,
        symbol=symbol,
        sensor_id=sensor_id,
        sensor_version="1.0.0",
        value=value,
        warm=warm,
    )


def _tick(
    *,
    horizon: int = 30,
    boundary: int,
    ts_ns: int,
    symbol: str | None = "AAPL",
    scope: str = "SYMBOL",
    boundary_ts_ns: int = 0,
) -> HorizonTick:
    return HorizonTick(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{horizon}-{scope}-{boundary}",
        sequence=boundary + 1,
        horizon_seconds=horizon,
        boundary_index=boundary,
        scope=scope,
        boundary_timestamp_ns=boundary_ts_ns,
        symbol=symbol,
        session_id="TEST",
    )


# ── Passive-mode tests ─────────────────────────────────────────────


def test_passive_mode_emits_empty_snapshot_per_symbol_tick() -> None:
    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)

    agg = HorizonAggregator(
        bus=bus,
        symbols=frozenset({"AAPL", "MSFT"}),
        sensor_buffer_seconds=600,
        sequence_generator=SequenceGenerator(),
    )
    agg.attach()

    assert agg.is_passive()
    bus.publish(_tick(boundary=1, ts_ns=1_030_000_000_000, symbol="AAPL"))

    assert len(captured) == 1
    snap = captured[0]
    assert snap.symbol == "AAPL"
    assert snap.horizon_seconds == 30
    assert snap.boundary_index == 1
    assert snap.values == {}
    assert snap.warm == {}
    assert snap.stale == {}


def test_passive_mode_universe_tick_fans_out_to_all_symbols() -> None:
    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)

    agg = HorizonAggregator(
        bus=bus,
        symbols=frozenset({"AAPL", "MSFT", "TSLA"}),
        sensor_buffer_seconds=600,
        sequence_generator=SequenceGenerator(),
    )
    agg.attach()

    bus.publish(
        _tick(
            boundary=2,
            ts_ns=2_030_000_000_000,
            symbol=None,
            scope="UNIVERSE",
        )
    )

    assert len(captured) == 3
    assert sorted(s.symbol for s in captured) == ["AAPL", "MSFT", "TSLA"]
    for snap in captured:
        assert snap.boundary_index == 2
        assert snap.values == {}


def test_attach_is_idempotent() -> None:
    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)

    agg = HorizonAggregator(
        bus=bus,
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=600,
        sequence_generator=SequenceGenerator(),
    )
    agg.attach()
    agg.attach()  # second call must not double-subscribe

    bus.publish(_tick(boundary=1, ts_ns=1_030_000_000_000))
    assert len(captured) == 1


def test_invalid_buffer_seconds_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="sensor_buffer_seconds"):
        HorizonAggregator(
            bus=EventBus(),
            symbols=frozenset({"AAPL"}),
            sensor_buffer_seconds=0,
            sequence_generator=SequenceGenerator(),
        )


# ── Active-mode tests ──────────────────────────────────────────────


def test_active_mode_finalizes_feature_with_value() -> None:
    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)

    feat: HorizonFeature = _SumFeature()
    agg = HorizonAggregator(
        bus=bus,
        horizon_features={"sum_feat": feat},
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=600,
        sequence_generator=SequenceGenerator(),
    )
    agg.attach()

    assert not agg.is_passive()

    for ts, value in [
        (1_001_000_000_000, 1.0),
        (1_002_000_000_000, 2.0),
        (1_003_000_000_000, 3.0),
    ]:
        bus.publish(_reading(ts_ns=ts, value=value))

    bus.publish(_tick(boundary=1, ts_ns=1_030_000_000_000))

    assert len(captured) == 1
    snap = captured[0]
    assert snap.values == {"sum_feat": 6.0}
    assert snap.warm == {"sum_feat": True}
    assert snap.stale == {"sum_feat": False}
    assert snap.source_sensors == {"sum_feat": ("ofi_ewma",)}


def test_boundary_asof_excludes_post_boundary_reading_from_window_snapshot() -> None:
    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)

    feat = HorizonWindowedFeature(
        "ofi_ewma",
        30,
        reducer="last",
        feature_id="ofi_last",
        min_samples=1,
    )
    agg = HorizonAggregator(
        bus=bus,
        horizon_features={"ofi_last": feat},
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=600,
        sequence_generator=SequenceGenerator(),
    )
    agg.attach()

    boundary_ts = 30_000_000_000
    post_boundary_ts = boundary_ts + 100_000_000
    bus.publish(_reading(ts_ns=29_000_000_000, value=1.0))
    bus.publish(_reading(ts_ns=post_boundary_ts, value=99.0))
    bus.publish(
        _tick(
            boundary=1,
            ts_ns=post_boundary_ts,
            boundary_ts_ns=boundary_ts,
        )
    )

    assert len(captured) == 1
    snap = captured[0]
    assert snap.timestamp_ns == post_boundary_ts
    assert snap.correlation_id == "snap:AAPL:30:30000000000:1"
    assert snap.values == {"ofi_last": 1.0}
    assert snap.warm == {"ofi_last": True}
    assert snap.stale == {"ofi_last": False}


def test_active_mode_second_horizon_reports_stale_when_no_new_readings() -> None:
    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)

    agg = HorizonAggregator(
        bus=bus,
        horizon_features={"sum_feat": _SumFeature()},
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=600,
        sequence_generator=SequenceGenerator(),
    )
    agg.attach()

    bus.publish(_reading(ts_ns=1_001_000_000_000, value=2.5))
    bus.publish(_tick(boundary=1, ts_ns=1_030_000_000_000))
    bus.publish(_tick(boundary=2, ts_ns=1_060_000_000_000))

    assert len(captured) == 2
    assert captured[0].stale == {"sum_feat": False}
    assert captured[1].stale == {"sum_feat": True}
    assert captured[1].values == {}  # S2: cold features are absent from values


def test_horizon_mismatch_skips_feature() -> None:
    """A feature on the 30s horizon must not appear on a 120s tick."""

    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)

    agg = HorizonAggregator(
        bus=bus,
        horizon_features={"sum_feat": _SumFeature()},
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=600,
        sequence_generator=SequenceGenerator(),
    )
    agg.attach()

    bus.publish(_tick(horizon=120, boundary=1, ts_ns=1_120_000_000_000))

    assert len(captured) == 1
    assert captured[0].values == {}


def test_per_symbol_state_isolation() -> None:
    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)

    agg = HorizonAggregator(
        bus=bus,
        horizon_features={"sum_feat": _SumFeature()},
        symbols=frozenset({"AAPL", "MSFT"}),
        sensor_buffer_seconds=600,
        sequence_generator=SequenceGenerator(),
    )
    agg.attach()

    bus.publish(_reading(symbol="AAPL", ts_ns=1_001_000_000_000, value=1.0))
    bus.publish(_reading(symbol="MSFT", ts_ns=1_002_000_000_000, value=10.0))
    bus.publish(_reading(symbol="AAPL", ts_ns=1_003_000_000_000, value=2.0))

    bus.publish(
        _tick(
            boundary=1,
            ts_ns=1_030_000_000_000,
            symbol=None,
            scope="UNIVERSE",
        )
    )

    by_symbol = {s.symbol: s for s in captured}
    assert by_symbol["AAPL"].values == {"sum_feat": 3.0}
    assert by_symbol["MSFT"].values == {"sum_feat": 10.0}


def test_buffer_eviction_evicts_old_readings() -> None:
    bus = EventBus()
    agg = HorizonAggregator(
        bus=bus,
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=10,
        sequence_generator=SequenceGenerator(),
    )

    base_ns = 1_000_000_000
    for i in range(5):
        agg.on_sensor_reading(_reading(ts_ns=base_ns + i * 1_000_000_000, value=float(i)))
    assert agg.buffer_size(symbol="AAPL", sensor_id="ofi_ewma") == 5

    # Fast-forward 30s; everything older than (now - 10s) is evicted.
    agg.on_sensor_reading(_reading(ts_ns=base_ns + 30_000_000_000, value=99.0))
    remaining = agg.buffer_size(symbol="AAPL", sensor_id="ofi_ewma")
    assert remaining == 1


def test_snapshot_sequence_isolated_from_tick_sequence() -> None:
    """The aggregator's snapshot sequence is independent of the tick sequence."""

    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)

    snapshot_seq = SequenceGenerator()
    agg = HorizonAggregator(
        bus=bus,
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=60,
        sequence_generator=snapshot_seq,
    )
    agg.attach()

    bus.publish(_tick(boundary=1, ts_ns=1_030_000_000_000))
    bus.publish(_tick(boundary=2, ts_ns=1_060_000_000_000))

    assert [s.sequence for s in captured] == [0, 1]


def test_same_boundary_dedup_prevents_snapshot_cid_collision() -> None:
    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)

    agg = HorizonAggregator(
        bus=bus,
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=60,
        sequence_generator=SequenceGenerator(),
    )
    agg.attach()

    first_tick = _tick(boundary=7, ts_ns=7_030_000_000_000, symbol="AAPL")
    duplicate_boundary_tick = _tick(
        boundary=7,
        ts_ns=7_030_000_000_000,
        symbol=None,
        scope="UNIVERSE",
    )
    next_tick = _tick(boundary=8, ts_ns=8_030_000_000_000, symbol="AAPL")

    first = agg.on_horizon_tick(first_tick)
    duplicate = agg.on_horizon_tick(duplicate_boundary_tick)
    second = agg.on_horizon_tick(next_tick)

    assert len(first) == 1
    assert duplicate == ()
    assert len(second) == 1
    assert [snap.boundary_index for snap in captured] == [7, 8]
    assert captured[0].correlation_id == "snap:AAPL:30:7030000000000:7"
    assert captured[1].correlation_id == "snap:AAPL:30:8030000000000:8"
    assert captured[0].correlation_id != captured[1].correlation_id


def test_symbol_after_universe_dedup_symmetry() -> None:
    """Audit #1 regression guard: dedup must hold even when SYMBOL arrives
    after UNIVERSE at the same boundary.  The scheduler currently emits
    SYMBOL before UNIVERSE, but anything publishing ticks directly to the
    bus (replayers, tests) could invert that order — the aggregator must
    still emit exactly one snapshot per (symbol, horizon, boundary)."""

    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)

    agg = HorizonAggregator(
        bus=bus,
        symbols=frozenset({"AAPL", "MSFT"}),
        sensor_buffer_seconds=60,
        sequence_generator=SequenceGenerator(),
    )
    agg.attach()

    # UNIVERSE first (fans out to both symbols), then a SYMBOL tick at the
    # same boundary for one of them — the SYMBOL tick must be suppressed.
    universe_first = _tick(
        boundary=3,
        ts_ns=3_030_000_000_000,
        symbol=None,
        scope="UNIVERSE",
    )
    symbol_after = _tick(
        boundary=3,
        ts_ns=3_030_000_000_000,
        symbol="AAPL",
        scope="SYMBOL",
    )

    universe_emitted = agg.on_horizon_tick(universe_first)
    late_symbol = agg.on_horizon_tick(symbol_after)

    assert len(universe_emitted) == 2  # one snapshot per symbol
    assert late_symbol == ()  # SYMBOL branch must suppress duplicate
    assert [s.symbol for s in captured] == ["AAPL", "MSFT"]
    assert all(s.boundary_index == 3 for s in captured)


def test_feature_versions_in_snapshot_provenance() -> None:
    """Audit #12 regression guard: snapshot.feature_versions records the
    feature_version per feature_id so consumers can reconstruct exactly
    which version produced each value."""

    class _V1Feature:
        feature_id: str = "demo"
        feature_version: str = "1.2.3"
        input_sensor_ids: tuple[str, ...] = ("ofi_ewma",)
        horizon_seconds: int = 30

        def initial_state(self) -> dict[str, Any]:
            return {}

        def observe(
            self,
            reading: SensorReading,
            state: dict[str, Any],
            params: Mapping[str, Any],
        ) -> None:
            state["last"] = float(reading.value) if not isinstance(reading.value, tuple) else 0.0

        def finalize(
            self,
            tick: HorizonTick,
            state: dict[str, Any],
            params: Mapping[str, Any],
        ) -> tuple[float, bool, bool]:
            return state.get("last", 0.0), "last" in state, False

    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)

    agg = HorizonAggregator(
        bus=bus,
        horizon_features={"demo": _V1Feature()},
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=60,
        sequence_generator=SequenceGenerator(),
    )
    agg.attach()

    bus.publish(_reading(ts_ns=1_000_000_000, value=4.2))
    bus.publish(_tick(boundary=1, ts_ns=30_000_000_000))

    assert len(captured) == 1
    assert captured[0].feature_versions == {"demo": "1.2.3"}
    assert captured[0].values == {"demo": 4.2}


def test_feature_params_plumbed_to_observe_and_finalize() -> None:
    """Audit #7 regression guard: feature_params from construction reach
    both observe() and finalize() instead of being hard-coded to {}."""

    seen_params: list[Mapping[str, Any]] = []

    class _ParamsRecordingFeature:
        feature_id: str = "params_demo"
        feature_version: str = "1.0.0"
        input_sensor_ids: tuple[str, ...] = ("ofi_ewma",)
        horizon_seconds: int = 30

        def initial_state(self) -> dict[str, Any]:
            return {}

        def observe(
            self,
            reading: SensorReading,
            state: dict[str, Any],
            params: Mapping[str, Any],
        ) -> None:
            seen_params.append(dict(params))

        def finalize(
            self,
            tick: HorizonTick,
            state: dict[str, Any],
            params: Mapping[str, Any],
        ) -> tuple[float, bool, bool]:
            seen_params.append(dict(params))
            return 0.0, True, False

    bus = EventBus()
    agg = HorizonAggregator(
        bus=bus,
        horizon_features={"params_demo": _ParamsRecordingFeature()},
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=60,
        sequence_generator=SequenceGenerator(),
        feature_params={"params_demo": {"threshold": 0.5, "mode": "test"}},
    )
    agg.attach()

    bus.publish(_reading(ts_ns=1_000_000_000, value=1.0))
    bus.publish(_tick(boundary=1, ts_ns=30_000_000_000))

    assert len(seen_params) == 2  # one observe + one finalize
    for params in seen_params:
        assert params == {"threshold": 0.5, "mode": "test"}
