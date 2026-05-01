"""HorizonAggregator — passive bridge from sensors to horizon snapshots.

Architectural decisions (plan §4.3):

1.  **Pull, not push.**  The aggregator subscribes once each to
    ``SensorReading`` and ``HorizonTick`` on the bus.  ``SensorReading``
    handlers fold readings into per-``(symbol, sensor_id)`` ring
    buffers; ``HorizonTick`` handlers iterate every registered
    :class:`feelies.features.protocol.HorizonFeature` and call
    ``finalize`` on it.  Features therefore never subscribe to the
    bus — bus-handler count stays O(1) regardless of how many
    features exist (mirrors the
    :class:`feelies.sensors.registry.SensorRegistry` pattern).

2.  **Per-(symbol, sensor_id) ring buffers.**  Buffers store at most
    ``2 * max(horizons_seconds)`` worth of readings (event-time bound,
    not count bound), so eviction is robust to bursty quote streams.
    The factor of 2 ensures a feature whose ``horizon_seconds`` equals
    ``max(horizons)`` still has a full window of history available
    when it ``finalize``s on the boundary.

3.  **Iteration determinism (Inv-C).**  ``HorizonTick`` handling
    iterates features in ``sorted(feature_id, feature_version)`` order
    and symbols in ``sorted(symbols)`` order, both fixed at
    registration time so the hot path does not re-sort on every tick.

4.  **Passive-emitter mode (Phase 2 reality).**  When
    ``horizon_features`` is empty (the v0.2 default — no concrete
    features land until Phase 3) the aggregator still emits one
    ``HorizonFeatureSnapshot`` per ``HorizonTick`` carrying empty
    ``values`` / ``warm`` / ``stale`` dicts.  This keeps the
    Level-3 parity hash non-empty and observable from day one.

5.  **Sequence-number isolation (Inv-A / C1).**  Every
    ``HorizonFeatureSnapshot`` draws its sequence number from the
    aggregator's *dedicated* ``_snapshot_seq`` generator — never the
    main orchestrator sequence and never the sensor / horizon
    sequences.  Adding the aggregator therefore cannot perturb any
    pre-Phase-2 event sequence.

6.  **No signals, no orders (Inv-E).**  The aggregator only ever
    publishes ``HorizonFeatureSnapshot`` events.  It never publishes
    ``Signal``, ``OrderIntent``, ``OrderAck``, or any other event
    type that would re-enter the legacy execution path.
"""

from __future__ import annotations

import logging
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


class HorizonAggregator:
    """Bridges Layer-1 ``SensorReading``s to Layer-2 snapshots.

    Construction parameters:

    - ``bus``: shared platform :class:`EventBus`.
    - ``horizon_features``: mapping ``feature_id -> HorizonFeature``.
      In Phase 2 the standard wiring passes an empty dict; the
      aggregator then runs in *passive* mode (empty snapshots — see
      module docstring).
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
        "_symbols_sorted",
        "_buffer_window_ns",
        "_sequence_generator",
        "_buffers",
        "_feature_state",
        "_last_snapshot_boundary",
        "_last_reading_ns",
        "_subscribed",
        "_metric_collector",
        "_metrics_seq",
    )

    def __init__(
        self,
        *,
        bus: EventBus,
        horizon_features: (
            Sequence[HorizonFeature]
            | Mapping[str, HorizonFeature]
            | None
        ) = None,
        symbols: frozenset[str],
        sensor_buffer_seconds: int,
        sequence_generator: SequenceGenerator,
        metric_collector: MetricCollector | None = None,
    ) -> None:
        if sensor_buffer_seconds <= 0:
            raise ValueError(
                f"sensor_buffer_seconds must be > 0, got {sensor_buffer_seconds}"
            )
        # Normalise to a plain list of features.  Accept a Mapping for
        # backward compatibility (existing tests pass {key: feature});
        # the Mapping keys are ignored — feature.feature_id is used.
        if horizon_features is None:
            features_list: list[HorizonFeature] = []
        elif isinstance(horizon_features, MappingABC):
            features_list = list(horizon_features.values())
        else:
            features_list = list(horizon_features)

        # Sort features once at construction so iteration is O(F)
        # without per-tick re-sorting (Inv-C / hot-path determinism).
        # Sorted by (feature_id, horizon_seconds, feature_version) so
        # the same sensor at multiple horizons gets stable ordering.
        self._features_sorted: tuple[HorizonFeature, ...] = tuple(
            sorted(
                features_list,
                key=lambda f: (f.feature_id, f.horizon_seconds, f.feature_version),
            )
        )

        # M9: detect same (feature_id, horizon_seconds) with conflicting
        # feature_version — aggregator cannot deterministically pick one.
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
        self._symbols_sorted: tuple[str, ...] = tuple(sorted(symbols))
        self._buffer_window_ns = sensor_buffer_seconds * _NS_PER_SECOND
        self._sequence_generator = sequence_generator
        self._bus = bus

        # Per-(symbol, sensor_id) ring buffer of (ts_ns, reading).
        # ``deque`` for O(1) popleft on eviction.
        self._buffers: dict[
            tuple[str, str], deque[tuple[int, SensorReading]]
        ] = defaultdict(deque)

        # Per-(feature_id, horizon_seconds, symbol) feature state owned
        # by the aggregator (mirrors the SensorRegistry per-symbol state
        # ownership pattern).  Using horizon_seconds as part of the key
        # allows the same feature_id (e.g. "ofi_ewma") to exist at
        # multiple horizon boundaries without state collision.
        self._feature_state: dict[tuple[str, int, str], dict[str, Any]] = {}
        for feature in self._features_sorted:
            for symbol in self._symbols_sorted:
                self._feature_state[
                    (feature.feature_id, feature.horizon_seconds, symbol)
                ] = feature.initial_state()

        # H1 / M3: per-(horizon_seconds, symbol) last boundary index for
        # which a snapshot has already been emitted.  Prevents the
        # UNIVERSE-tick fan-out from producing a second identical snapshot
        # for symbols already covered by their own SYMBOL tick at the
        # same boundary.
        self._last_snapshot_boundary: dict[tuple[int, str], int] = {}

        # H9 / M8: latest event-time timestamp at which a SensorReading
        # was observed, keyed by (symbol, sensor_id).  Used in
        # _build_snapshot to mark features stale when their input sensor
        # has not fired within the feature's horizon window.
        self._last_reading_ns: dict[tuple[str, str], int] = {}

        self._subscribed = False

        # Plan §4.5: ``feelies.feature.snapshot.stale_fraction``
        # (gauge, tag ``horizon_seconds``) — emitted once per
        # snapshot.  Dedicated sequence generator so MetricEvent
        # sequences never perturb the locked HorizonFeatureSnapshot
        # stream (Inv-A / C1).
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
        self._bus.subscribe(SensorReading, self._on_sensor_reading)  # type: ignore[arg-type]
        self._bus.subscribe(HorizonTick, self._on_horizon_tick)  # type: ignore[arg-type]
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
        key = (symbol, reading.sensor_id)
        buf = self._buffers[key]
        buf.append((reading.timestamp_ns, reading))
        # H9 / M8: record the latest event-time timestamp for each
        # (symbol, sensor_id) so _build_snapshot can declare a feature
        # stale when its input sensor has not fired within the horizon.
        self._last_reading_ns[key] = reading.timestamp_ns
        # Event-time eviction.  Anchored to the just-appended ts so
        # late-arriving events do not retroactively prune the buffer.
        cutoff = reading.timestamp_ns - self._buffer_window_ns
        while buf and buf[0][0] < cutoff:
            buf.popleft()

        # Notify any feature whose ``input_sensor_ids`` contains this
        # sensor_id.  Passive mode (no features) skips this loop
        # entirely with zero cost.
        for feature in self._features_sorted:
            if reading.sensor_id not in feature.input_sensor_ids:
                continue
            state_key = (feature.feature_id, feature.horizon_seconds, symbol)
            state = self._feature_state.get(state_key)
            if state is None:
                # New symbol observed after construction; allocate
                # lazily so dynamic universes (Phase 4+) still work.
                state = feature.initial_state()
                self._feature_state[state_key] = state
            feature.observe(reading, state, params={})

    def _on_horizon_tick(
        self, tick: HorizonTick
    ) -> tuple[HorizonFeatureSnapshot, ...]:
        # Universe ticks fan out across every symbol; symbol-scoped
        # ticks emit a single snapshot for that one symbol.
        # H1 / M3: the scheduler emits both per-symbol SYMBOL ticks and
        # a UNIVERSE tick at each boundary.  To prevent each
        # (symbol, horizon, boundary_index) triple from producing two
        # identical snapshots, skip any symbol that already received a
        # snapshot at this boundary (SYMBOL ticks arrive before UNIVERSE
        # ticks per the scheduler's canonical emission order).
        if tick.scope == "SYMBOL":
            assert tick.symbol is not None
            target_symbols: tuple[str, ...] = (tick.symbol,)
        else:
            target_symbols = tuple(
                sym for sym in self._symbols_sorted
                if self._last_snapshot_boundary.get(
                    (tick.horizon_seconds, sym), -1
                ) < tick.boundary_index
            )

        snapshots: list[HorizonFeatureSnapshot] = []
        for symbol in target_symbols:
            snapshot = self._build_snapshot(tick=tick, symbol=symbol)
            # Record that this (horizon, symbol) has been snapshotted at
            # this boundary so a later UNIVERSE tick (or an out-of-order
            # SYMBOL tick) cannot produce a duplicate.
            self._last_snapshot_boundary[
                (tick.horizon_seconds, symbol)
            ] = tick.boundary_index
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

        for feature in self._features_sorted:
            if feature.horizon_seconds != tick.horizon_seconds:
                continue
            state_key = (feature.feature_id, feature.horizon_seconds, symbol)
            state = self._feature_state.get(state_key)
            if state is None:
                state = feature.initial_state()
                self._feature_state[state_key] = state
            value, w, s = feature.finalize(tick, state, params={})
            # H9 / M8: override stale=True when any input sensor has not
            # fired within the feature's horizon window.  This catches the
            # "sensor goes silent" case that the buffer-eviction anchor
            # alone cannot detect (eviction only fires when the sensor
            # re-fires, so a silent sensor keeps a stale buffer alive).
            if not s:
                horizon_ns = feature.horizon_seconds * _NS_PER_SECOND
                for sid in feature.input_sensor_ids:
                    last_ns = self._last_reading_ns.get((symbol, sid))
                    if last_ns is None or (tick.timestamp_ns - last_ns) > horizon_ns:
                        s = True
                        break
            values[feature.feature_id] = float(value)
            warm[feature.feature_id] = bool(w)
            stale[feature.feature_id] = bool(s)
            source_sensors[feature.feature_id] = tuple(feature.input_sensor_ids)

        seq = self._sequence_generator.next()
        cid = make_correlation_id(
            symbol=f"snap:{symbol}:{tick.horizon_seconds}",
            exchange_timestamp_ns=tick.timestamp_ns,
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
            values=values,
            warm=warm,
            stale=stale,
            source_sensors=source_sensors,
        )

    # ── Monitoring (plan §4.5) ───────────────────────────────────────

    def _emit_snapshot_metric(
        self, *, snapshot: HorizonFeatureSnapshot
    ) -> None:
        """Emit ``feelies.feature.snapshot.stale_fraction`` for one snapshot.

        Gauge in ``[0, 1]`` reporting the fraction of features whose
        ``stale`` flag is True for this snapshot.  Passive-mode
        snapshots (no features) report ``0.0`` by convention so the
        gauge time-series remains continuous across feature
        registration.
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
        self._metric_collector.record(MetricEvent(
            timestamp_ns=snapshot.timestamp_ns,
            correlation_id=cid,
            sequence=seq,
            source_layer="FEATURE",
            layer="feature",
            name="feelies.feature.snapshot.stale_fraction",
            value=float(fraction),
            metric_type=MetricType.GAUGE,
            tags={"horizon_seconds": str(snapshot.horizon_seconds)},
        ))

    # ── Introspection helpers (used by tests / forensics) ────────────

    def buffer_size(self, *, symbol: str, sensor_id: str) -> int:
        """Number of readings currently retained for ``(symbol, sensor_id)``."""
        return len(self._buffers.get((symbol, sensor_id), ()))

    def is_passive(self) -> bool:
        """True iff no features were registered (passive-emitter mode)."""
        return not self._features_sorted


__all__ = ["HorizonAggregator"]
