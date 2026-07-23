"""Passive bridge from sensor readings to horizon snapshots.

Features read event-time buffers on horizon ticks; they never subscribe to
the bus. Buffers retain twice the longest horizon to preserve a full window.
Feature and symbol order is fixed for deterministic replay.

The aggregator emits snapshots only, including empty snapshots when no
features are registered. It uses a dedicated sequence and deduplicates each
``(symbol, horizon, boundary)``. Only warm, newer readings advance freshness.

Snapshots remain flat feature maps. Signal direction, collinearity, and
cross-sectional standardization belong to downstream layers.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict, deque
from collections.abc import Mapping as MappingABC
from typing import Any, Mapping, Sequence

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    HorizonTick,
    MetricEvent,
    MetricType,
    SensorReading,
)
from feelies.core.identifiers import SequenceGenerator, make_correlation_id
from feelies.features.protocol import HorizonFeature
from feelies.monitoring.telemetry import MetricCollector

_logger = logging.getLogger(__name__)


_NS_PER_SECOND = 1_000_000_000


class MultiVersionFeatureDispatchError(RuntimeError):
    """Raised when two live ``sensor_version``s of one ``sensor_id`` both
    deliver readings to a feature that consumes it.

    Feature ``observe()`` dispatch is version-blind by design — state is
    keyed by ``(feature_id, horizon_seconds, symbol)``, never
    ``sensor_version`` — so folding
    two concurrent estimators into one state would silently corrupt it. A
    ``sensor_id`` with no consuming feature is unaffected (the sensor-reading
    buffers alone are version-keyed for forensic isolation, S8); an A/B
    sensor-version deployment must give each version its own feature
    registration rather than relying on dispatch to separate them.
    """


class HorizonAggregator:
    """Bridges Layer-1 ``SensorReading``s to Layer-2 snapshots.

    Construction parameters:

    - ``bus``: shared platform :class:`EventBus`.
    - ``horizon_features``: mapping ``feature_id -> HorizonFeature``.
      An empty dict enables passive mode with empty snapshots.
    - ``symbols``: per-symbol universe, used both for buffer
      pre-allocation and for ``HorizonTick(scope='UNIVERSE')`` fan-out
      iteration.
    - ``sensor_buffer_seconds``: trailing window in seconds retained
      in each sensor-reading ring buffer.  Should equal
      ``2 * max(horizons_seconds)`` per the plan; the bootstrap layer
      computes this so the aggregator does not need to inspect
      :class:`PlatformConfig` directly.
    - ``sequence_generator``: dedicated ``_snapshot_seq`` generator.
    """

    __slots__ = (
        "_bus",
        "_features_sorted",
        "_features_by_horizon",
        "_features_by_sensor",
        "_symbols_sorted",
        "_buffer_window_ns",
        "_sequence_generator",
        "_buffers",
        "_feature_state",
        "_feature_params",
        "_last_snapshot_boundary",
        "_last_reading_ns",
        "_observed_versions",
        "_multi_version_warned",
        "_subscribed",
        "_metric_collector",
        "_metrics_seq",
    )

    def __init__(
        self,
        *,
        bus: EventBus,
        horizon_features: (Sequence[HorizonFeature] | Mapping[str, HorizonFeature] | None) = None,
        symbols: frozenset[str],
        sensor_buffer_seconds: int,
        sequence_generator: SequenceGenerator,
        metric_collector: MetricCollector | None = None,
        known_sensor_ids: frozenset[str] | None = None,
        feature_params: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        if sensor_buffer_seconds <= 0:
            raise ValueError(f"sensor_buffer_seconds must be > 0, got {sensor_buffer_seconds}")
        # Mapping keys are ignored; each feature supplies its own ID.
        if horizon_features is None:
            features_list: list[HorizonFeature] = []
        elif isinstance(horizon_features, MappingABC):
            features_list = list(horizon_features.values())
        else:
            features_list = list(horizon_features)

        # Sort once for stable hot-path iteration across horizons and versions.
        self._features_sorted: tuple[HorizonFeature, ...] = tuple(
            sorted(
                features_list,
                key=lambda f: (f.feature_id, f.horizon_seconds, f.feature_version),
            )
        )

        # Each feature and horizon pair must resolve to one version.
        _seen_fv: dict[tuple[str, int], str] = {}
        for _f in self._features_sorted:
            _key = (_f.feature_id, _f.horizon_seconds)
            _prev = _seen_fv.get(_key)
            if _prev is None:
                _seen_fv[_key] = _f.feature_version
            elif _prev != _f.feature_version:
                raise ValueError(
                    f"HorizonAggregator: feature_id={_f.feature_id!r} at "
                    f"horizon={_f.horizon_seconds}s is declared with "
                    f"conflicting versions {_prev!r} and "
                    f"{_f.feature_version!r}; each (feature_id, horizon) "
                    f"pair must have exactly one version"
                )
        # Pre-bucket by horizon so a tick visits only relevant features.
        _by_horizon: dict[int, list[HorizonFeature]] = defaultdict(list)
        for _f in self._features_sorted:
            _by_horizon[_f.horizon_seconds].append(_f)
        self._features_by_horizon: dict[int, tuple[HorizonFeature, ...]] = {
            h: tuple(fs) for h, fs in _by_horizon.items()
        }

        self._symbols_sorted: tuple[str, ...] = tuple(sorted(symbols))
        self._buffer_window_ns = sensor_buffer_seconds * _NS_PER_SECOND
        self._sequence_generator = sequence_generator
        self._bus = bus

        # Forward construction-time parameters to each feature lifecycle.
        self._feature_params: dict[str, Mapping[str, Any]] = (
            dict(feature_params) if feature_params is not None else {}
        )

        # Warn when a feature depends on a sensor that cannot publish.
        if known_sensor_ids is not None:
            for _f in self._features_sorted:
                for _sid in _f.input_sensor_ids:
                    if _sid not in known_sensor_ids:
                        _logger.warning(
                            "HorizonAggregator: feature %r declares "
                            "input_sensor_id %r which is not in the "
                            "registered sensor set; feature will never "
                            "observe readings (likely misconfiguration)",
                            _f.feature_id,
                            _sid,
                        )

        # Version-isolated reading buffers support inspection and reconciliation;
        # features own separate computational state.
        self._buffers: dict[tuple[str, str, str], deque[tuple[int, SensorReading]]] = defaultdict(
            deque
        )

        # Horizon belongs in the state key because one feature may serve many horizons.
        self._feature_state: dict[tuple[str, int, str], dict[str, Any]] = {}
        for feature in self._features_sorted:
            for symbol in self._symbols_sorted:
                self._feature_state[(feature.feature_id, feature.horizon_seconds, symbol)] = (
                    feature.initial_state()
                )

        # Reverse-index sensors to consumers without changing stable feature order.
        self._features_by_sensor: dict[str, list[HorizonFeature]] = {}
        for feature in self._features_sorted:
            for sid in feature.input_sensor_ids:
                self._features_by_sensor.setdefault(sid, []).append(feature)

        # Last emitted boundary per horizon and symbol; -1 admits boundary zero.
        self._last_snapshot_boundary: dict[tuple[int, str], int] = {}

        # Track usable-data freshness. Cold or late readings cannot advance it.
        self._last_reading_ns: dict[tuple[str, str], int] = {}

        # Feature dispatch is version-blind, so only one active version may feed
        # a consumed sensor ID. Unconsumed versions remain isolated in buffers.
        self._observed_versions: dict[tuple[str, str], set[str]] = defaultdict(set)
        self._multi_version_warned: set[tuple[str, str]] = set()

        self._subscribed = False

        # Isolate metric sequences from the snapshot stream.
        self._metric_collector = metric_collector
        self._metrics_seq: SequenceGenerator | None = (
            SequenceGenerator() if metric_collector is not None else None
        )

    # ── Bus wiring ────────────────────────────────────────────────────

    def attach(self) -> None:
        """Subscribe the aggregator to ``SensorReading`` + ``HorizonTick``.

        Idempotent: a second call is a no-op.  Keeping subscription as
        an explicit step lets the bootstrap layer order the wiring
        deterministically against the sensor registry.
        """
        if self._subscribed:
            return
        self._bus.subscribe(SensorReading, self._on_sensor_reading)
        self._bus.subscribe(HorizonTick, self._on_horizon_tick)
        self._subscribed = True

    # ── Public entry points (also used directly by tests) ────────────

    def on_sensor_reading(self, reading: SensorReading) -> None:
        """Public wrapper around the bus handler — convenient for tests."""
        self._on_sensor_reading(reading)

    def on_horizon_tick(self, tick: HorizonTick) -> tuple[HorizonFeatureSnapshot, ...]:
        """Public wrapper that also returns emitted snapshots for tests."""
        return self._on_horizon_tick(tick)

    # ── Internal handlers ────────────────────────────────────────────

    def _on_sensor_reading(self, reading: SensorReading) -> None:
        symbol = reading.symbol
        # Sensor version isolates concurrent versions in separate buffers.
        key = (symbol, reading.sensor_id, reading.sensor_version)
        buf = self._buffers[key]
        buf.append((reading.timestamp_ns, reading))
        # Only newer warm readings refresh usable-data time.
        if reading.warm:
            sid_key = (symbol, reading.sensor_id)
            prev = self._last_reading_ns.get(sid_key)
            if prev is None or reading.timestamp_ns > prev:
                self._last_reading_ns[sid_key] = reading.timestamp_ns
        # Anchor eviction to this event so late arrivals cannot prune newer history.
        cutoff = reading.timestamp_ns - self._buffer_window_ns
        while buf and buf[0][0] < cutoff:
            buf.popleft()

        # Refuse multiple versions when version-blind feature state would mix them.
        version_seen = self._observed_versions[(symbol, reading.sensor_id)]
        if reading.sensor_version not in version_seen:
            version_seen.add(reading.sensor_version)
            if len(version_seen) > 1 and reading.sensor_id in self._features_by_sensor:
                consumers = sorted(
                    f.feature_id for f in self._features_by_sensor[reading.sensor_id]
                )
                raise MultiVersionFeatureDispatchError(
                    f"sensor {reading.sensor_id!r} on symbol {symbol!r} has "
                    f"delivered readings from multiple versions "
                    f"{sorted(version_seen)}, consumed by feature(s) "
                    f"{consumers}; feature observe() dispatch is "
                    f"version-blind and cannot safely fold concurrent "
                    f"estimators into one state.  Give each sensor_version "
                    f"its own feature_id instead of relying on dispatch to "
                    f"separate them."
                )
            if (
                len(version_seen) > 1
                and (symbol, reading.sensor_id) not in self._multi_version_warned
            ):
                self._multi_version_warned.add((symbol, reading.sensor_id))
                _logger.warning(
                    "HorizonAggregator: sensor %r on symbol %r has "
                    "delivered readings from multiple versions %s; no "
                    "feature currently consumes it so this is harmless, but "
                    "wiring one later will raise "
                    "MultiVersionFeatureDispatchError immediately.",
                    reading.sensor_id,
                    symbol,
                    sorted(version_seen),
                )

        # Dispatch through the precomputed sensor-to-feature index.
        for feature in self._features_by_sensor.get(reading.sensor_id, ()):
            state_key = (feature.feature_id, feature.horizon_seconds, symbol)
            state = self._feature_state.get(state_key)
            if state is None:
                # Allocate state lazily for symbols added after construction.
                state = feature.initial_state()
                self._feature_state[state_key] = state
            feature.observe(
                reading,
                state,
                params=self._feature_params.get(feature.feature_id, {}),
            )

    def _on_horizon_tick(self, tick: HorizonTick) -> tuple[HorizonFeatureSnapshot, ...]:
        # Emit each symbol/horizon/boundary once, regardless of tick scope order.
        boundary_idx = tick.boundary_index
        horizon = tick.horizon_seconds
        if tick.scope == "SYMBOL":
            assert tick.symbol is not None
            if self._last_snapshot_boundary.get((horizon, tick.symbol), -1) >= boundary_idx:
                return ()
            target_symbols: tuple[str, ...] = (tick.symbol,)
        else:
            target_symbols = tuple(
                sym
                for sym in self._symbols_sorted
                if self._last_snapshot_boundary.get((horizon, sym), -1) < boundary_idx
            )

        snapshots: list[HorizonFeatureSnapshot] = []
        for symbol in target_symbols:
            snapshot = self._build_snapshot(tick=tick, symbol=symbol)
            # Mark before a later tick scope can duplicate this snapshot.
            self._last_snapshot_boundary[(tick.horizon_seconds, symbol)] = tick.boundary_index
            self._bus.publish(snapshot)
            snapshots.append(snapshot)
            if self._metric_collector is not None:
                self._emit_snapshot_metric(snapshot=snapshot)
        return tuple(snapshots)

    def _build_snapshot(
        self,
        *,
        tick: HorizonTick,
        symbol: str,
    ) -> HorizonFeatureSnapshot:
        values: dict[str, float] = {}
        warm: dict[str, bool] = {}
        stale: dict[str, bool] = {}
        source_sensors: dict[str, tuple[str, ...]] = {}
        feature_versions: dict[str, str] = {}
        asof_ns = tick.asof_timestamp_ns

        # Visit only this horizon's features in their global stable order.
        for feature in self._features_by_horizon.get(tick.horizon_seconds, ()):
            state_key = (feature.feature_id, feature.horizon_seconds, symbol)
            state = self._feature_state.get(state_key)
            if state is None:
                state = feature.initial_state()
                self._feature_state[state_key] = state
            value, w, s = feature.finalize(
                tick,
                state,
                params=self._feature_params.get(feature.feature_id, {}),
            )
            # A silent input is stale even if its buffer was never revisited for eviction.
            if not s:
                horizon_ns = feature.horizon_seconds * _NS_PER_SECOND
                for sid in feature.input_sensor_ids:
                    last_ns = self._latest_warm_reading_ns_at_or_before(
                        symbol=symbol,
                        sensor_id=sid,
                        asof_ns=asof_ns,
                    )
                    if last_ns is None or (asof_ns - last_ns) > horizon_ns:
                        s = True
                        break
            # Demote non-finite reducer output to cold before it reaches a gate.
            w_eff = bool(w)
            fv: float | None = None
            if w_eff:
                fv = float(value)
                if not math.isfinite(fv):
                    _logger.warning(
                        "feature %r produced a non-finite value %r for symbol "
                        "%s at horizon %ds; demoting to cold (3P-1 fail-safe)",
                        feature.feature_id,
                        value,
                        symbol,
                        feature.horizon_seconds,
                    )
                    w_eff = False
                    fv = None
            # Record status for every feature; omit cold values instead of using zero.
            warm[feature.feature_id] = w_eff
            stale[feature.feature_id] = bool(s)
            if w_eff:
                assert fv is not None
                values[feature.feature_id] = fv
            source_sensors[feature.feature_id] = tuple(feature.input_sensor_ids)
            # Preserve the producing feature version in snapshot provenance.
            feature_versions[feature.feature_id] = feature.feature_version

        seq = self._sequence_generator.next()
        cid = make_correlation_id(
            symbol=f"snap:{symbol}:{tick.horizon_seconds}",
            exchange_timestamp_ns=asof_ns,
            sequence=tick.boundary_index,
        )
        return HorizonFeatureSnapshot(
            timestamp_ns=tick.timestamp_ns,
            correlation_id=cid,
            sequence=seq,
            source_layer="FEATURE",
            symbol=symbol,
            horizon_seconds=tick.horizon_seconds,
            boundary_index=tick.boundary_index,
            boundary_ts_ns=tick.boundary_ts_ns,  # ENG-1: carry the nominal grid anchor
            values=values,
            warm=warm,
            stale=stale,
            source_sensors=source_sensors,
            feature_versions=feature_versions,
            parent_correlation_id=tick.correlation_id,  # Preserve event lineage.
        )

    # Snapshot freshness helpers.
    def _latest_warm_reading_ns_at_or_before(
        self,
        *,
        symbol: str,
        sensor_id: str,
        asof_ns: int,
    ) -> int | None:
        """Latest warm sensor timestamp that is causal for this boundary."""
        cached = self._last_reading_ns.get((symbol, sensor_id))
        if cached is not None and cached <= asof_ns:
            return cached

        latest: int | None = None
        for (buf_symbol, buf_sensor_id, _version), buf in self._buffers.items():
            if buf_symbol != symbol or buf_sensor_id != sensor_id:
                continue
            for ts_ns, reading in buf:
                if reading.warm and ts_ns <= asof_ns and (latest is None or ts_ns > latest):
                    latest = ts_ns
        return latest

    # Monitoring.
    def _emit_snapshot_metric(self, *, snapshot: HorizonFeatureSnapshot) -> None:
        """Emit ``feelies.feature.snapshot.stale_fraction`` for one snapshot.

        Gauge in ``[0, 1]`` reporting the fraction of features whose
        ``stale`` flag is True for this snapshot, computed against the
        *total* number of registered features (warm + cold), not just
        the warm subset.  Cold features count as "not stale" in the
        denominator — a snapshot with one warm-stale feature out of ten
        registered reports 0.1. Passive-mode snapshots (no features) report
        ``0.0`` by convention so the gauge remains continuous.
        """
        assert self._metric_collector is not None
        assert self._metrics_seq is not None
        n = len(snapshot.stale)
        stale_count = sum(1 for v in snapshot.stale.values() if v)
        fraction = stale_count / n if n > 0 else 0.0
        seq = self._metrics_seq.next()
        cid = make_correlation_id(
            symbol=f"metric:feature:{snapshot.horizon_seconds}",
            exchange_timestamp_ns=snapshot.timestamp_ns,
            sequence=seq,
        )
        self._metric_collector.record(
            MetricEvent(
                timestamp_ns=snapshot.timestamp_ns,
                correlation_id=cid,
                sequence=seq,
                source_layer="FEATURE",
                layer="feature",
                name="feelies.feature.snapshot.stale_fraction",
                value=float(fraction),
                metric_type=MetricType.GAUGE,
                tags={"horizon_seconds": str(snapshot.horizon_seconds)},
            )
        )

    # ── Introspection helpers (used by tests / forensics) ────────────

    def buffer_size(
        self, *, symbol: str, sensor_id: str, sensor_version: str | None = None
    ) -> int:
        """Number of readings currently retained for ``(symbol, sensor_id[, version])``.

        When ``sensor_version`` is ``None`` (default), returns the total
        count across all versions of ``sensor_id`` for backward
        compatibility with tests that pre-date the version-keyed buffer
        change (S8).
        """
        if sensor_version is not None:
            return len(self._buffers.get((symbol, sensor_id, sensor_version), ()))
        return sum(
            len(buf)
            for (sym, sid, _ver), buf in self._buffers.items()
            if sym == symbol and sid == sensor_id
        )

    def is_passive(self) -> bool:
        """True iff no features were registered (passive-emitter mode)."""
        return not self._features_sorted


__all__ = ["HorizonAggregator", "MultiVersionFeatureDispatchError"]
