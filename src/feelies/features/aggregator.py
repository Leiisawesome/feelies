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

7.  **Symmetric SYMBOL/UNIVERSE dedup (audit #1).**  Both tick scopes
    consult ``_last_snapshot_boundary`` before emitting, so the
    (symbol, horizon, boundary) invariant holds regardless of which
    scope arrives first at the same boundary.

8.  **Warm-only, monotonic freshness clock (audits #3, #6).**
    ``_last_reading_ns`` advances only on *warm* readings and only
    when the timestamp is monotonically newer.  Cold readings do not
    refresh the sensor (features ignore them), and out-of-order late
    arrivals cannot regress freshness.

9.  **No cross-feature fusion — sign reconciliation is the caller's job
    (audit P1-H).**  The snapshot is a flat ``{feature_id: value}`` map;
    the aggregator performs **no** orthogonalization, decorrelation, or
    sign reconciliation across features.  Two features can carry opposite
    implications for the same forward return — e.g. ``ofi_ewma`` /
    ``ofi_ewma_integrated`` are *momentum* (positive ⇒ continuation) while
    ``inventory_pressure`` is *mean-reverting* (positive ⇒ up-revert of the
    move that loaded it) — and several KYLE features are collinear
    (``micro_price_zscore`` and integrated OFI are both largely
    price-momentum).  A Layer-2 alpha that consumes more than one mechanism
    family MUST resolve the sign conflict and the collinearity itself; the
    aggregator will not do it.  Cross-sectional standardization (z within
    the universe at the boundary) is likewise out of scope here — it is a
    Layer-3 (composition) concern (see the composition-layer skill).
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
        # #17: Pre-bucket features by horizon so per-tick dispatch is
        # O(F_h) instead of O(F).  Tuple is preserved in sorted order so
        # iteration determinism (Inv-C) is unchanged.
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

        # #7: Per-feature params plumbed from construction time.  The
        # protocol exposes a ``params: Mapping[str, Any]`` argument to
        # both ``observe`` and ``finalize``; the aggregator previously
        # hard-coded ``{}`` everywhere, leaving the protocol surface as
        # dead area.  Now callers pass ``feature_params={feature_id: {...}}``
        # at construction time and the aggregator forwards each feature's
        # params to its lifecycle methods (defaults to ``{}`` when absent).
        self._feature_params: dict[str, Mapping[str, Any]] = (
            dict(feature_params) if feature_params is not None else {}
        )

        # S16: at construction time, warn about any feature input_sensor_id
        # that is not in the registered sensor universe.  Such a feature will
        # never observe any readings, which is almost certainly a config error.
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

        # Per-(symbol, sensor_id, sensor_version) ring buffer of (ts_ns, reading).
        # ``deque`` for O(1) popleft on eviction.  Keying on version prevents
        # two versions of the same sensor from contaminating each other's
        # ring buffer when both are registered (S8).
        #
        # Audit #8: feature ``observe()`` dispatch does *not* read from
        # these buffers — features keep their own state.  The buffers
        # exist for forensic introspection (``buffer_size``, late-arrival
        # reconciliation per plan §4.3) and as the audit-spine ring used
        # by the determinism harness.  The 2× ``max(horizons)`` window
        # ensures a feature whose horizon equals the max still has a full
        # history on the boundary.
        self._buffers: dict[tuple[str, str, str], deque[tuple[int, SensorReading]]] = defaultdict(
            deque
        )

        # Per-(feature_id, horizon_seconds, symbol) feature state owned
        # by the aggregator (mirrors the SensorRegistry per-symbol state
        # ownership pattern).  Using horizon_seconds as part of the key
        # allows the same feature_id (e.g. "ofi_ewma") to exist at
        # multiple horizon boundaries without state collision.
        self._feature_state: dict[tuple[str, int, str], dict[str, Any]] = {}
        for feature in self._features_sorted:
            for symbol in self._symbols_sorted:
                self._feature_state[(feature.feature_id, feature.horizon_seconds, symbol)] = (
                    feature.initial_state()
                )

        # Reverse index sensor_id -> features that consume it, built once
        # at construction in ``_features_sorted`` order.  ``_on_sensor_reading``
        # dispatches through this instead of scanning every feature per
        # reading: on a wide feature set the old O(features) membership test
        # ran for every one of ~10^7 readings/session.  Preserving the
        # sorted order within each bucket keeps observe() dispatch
        # byte-identical to the full-scan version (features own disjoint
        # per-(feature_id, horizon, symbol) state, so cross-feature order is
        # irrelevant, but pinning it costs nothing and avoids surprise).
        self._features_by_sensor: dict[str, list[HorizonFeature]] = {}
        for feature in self._features_sorted:
            for sid in feature.input_sensor_ids:
                self._features_by_sensor.setdefault(sid, []).append(feature)

        # H1 / M3: per-(horizon_seconds, symbol) last boundary index for
        # which a snapshot has already been emitted.  Prevents either
        # tick scope from producing a second identical snapshot for
        # symbols already covered at the same boundary.  Sentinel is
        # ``-1`` so the first tick (boundary_index >= 0) always passes
        # the ``< boundary_index`` guard; the scheduler currently emits
        # ``boundary_index >= 1`` but the sentinel handles 0 correctly
        # too (audit #16 observation).
        self._last_snapshot_boundary: dict[tuple[int, str], int] = {}

        # H9 / M8: latest event-time timestamp at which a *warm*
        # SensorReading was observed, keyed by (symbol, sensor_id).  Used
        # in _build_snapshot to mark features stale when their input
        # sensor has not fired within the feature's horizon window.
        #
        # Audit #3: updates use ``max(prev, ts_ns)`` so out-of-order
        # arrivals (late delivery, multi-source merge) cannot regress
        # freshness; without the guard, an old reading arriving after a
        # newer one would spuriously mark fresh features stale on the
        # next horizon tick.
        #
        # Audit #6: only *warm* readings update this clock.  A sensor
        # that fires continuously but never warms (still in its own
        # warm-up) must not appear "fresh" to the stale-override logic,
        # because features ignore cold readings anyway and the semantic
        # we are tracking is "freshness of usable data", not "did the
        # sensor publish any event recently".
        self._last_reading_ns: dict[tuple[str, str], int] = {}

        # Audit #2: ``_buffers`` is keyed by (symbol, sensor_id, version)
        # for S8 forensic isolation, but feature ``observe()`` dispatch is
        # version-blind by design — features aggregate over whichever
        # version is live.  This is correct under the standing assumption
        # that *exactly one* sensor_version is active per sensor_id at
        # runtime; A/B deployments must use distinct feature_ids.  We
        # track observed versions per (symbol, sensor_id) and emit a
        # one-shot warning the first time a second version delivers a
        # reading to a feature, so the misconfiguration is loud.
        self._observed_versions: dict[tuple[str, str], set[str]] = defaultdict(set)
        self._multi_version_warned: set[tuple[str, str]] = set()

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
        # S8: key on (symbol, sensor_id, sensor_version) to prevent two
        # concurrent versions of the same sensor from contaminating each
        # other's ring buffer.
        key = (symbol, reading.sensor_id, reading.sensor_version)
        buf = self._buffers[key]
        buf.append((reading.timestamp_ns, reading))
        # H9 / M8 + audit #3 + audit #6: record the latest event-time
        # timestamp for each (symbol, sensor_id), but only for warm
        # readings and only when monotonically advancing.  Cold readings
        # do not "refresh" the sensor because features ignore them; late
        # arrivals do not regress freshness.
        if reading.warm:
            sid_key = (symbol, reading.sensor_id)
            prev = self._last_reading_ns.get(sid_key)
            if prev is None or reading.timestamp_ns > prev:
                self._last_reading_ns[sid_key] = reading.timestamp_ns
        # Event-time eviction.  Anchored to the just-appended ts so
        # late-arriving events do not retroactively prune the buffer.
        cutoff = reading.timestamp_ns - self._buffer_window_ns
        while buf and buf[0][0] < cutoff:
            buf.popleft()

        # Audit #2: track which versions of this sensor have delivered
        # readings; warn (once per pair) when a second version appears,
        # since feature state is shared across versions by design.
        version_seen = self._observed_versions[(symbol, reading.sensor_id)]
        if reading.sensor_version not in version_seen:
            version_seen.add(reading.sensor_version)
            if (
                len(version_seen) > 1
                and (symbol, reading.sensor_id) not in self._multi_version_warned
            ):
                self._multi_version_warned.add((symbol, reading.sensor_id))
                _logger.warning(
                    "HorizonAggregator: sensor %r on symbol %r has "
                    "delivered readings from multiple versions %s; "
                    "feature observe() dispatch is version-blind and "
                    "will fold both streams into the same per-feature "
                    "state.  Use a distinct feature_id (or feature) for "
                    "each version when running A/B sensor variants.",
                    reading.sensor_id,
                    symbol,
                    sorted(version_seen),
                )

        # Notify any feature whose ``input_sensor_ids`` contains this
        # sensor_id, via the precomputed reverse index.  Passive mode
        # (no features) and readings from sensors no feature consumes
        # both resolve to an empty list with zero per-feature cost.
        for feature in self._features_by_sensor.get(reading.sensor_id, ()):
            state_key = (feature.feature_id, feature.horizon_seconds, symbol)
            state = self._feature_state.get(state_key)
            if state is None:
                # New symbol observed after construction; allocate
                # lazily so dynamic universes (Phase 4+) still work.
                state = feature.initial_state()
                self._feature_state[state_key] = state
            # Audit #7: forward per-feature params from construction.
            feature.observe(
                reading,
                state,
                params=self._feature_params.get(feature.feature_id, {}),
            )

    def _on_horizon_tick(self, tick: HorizonTick) -> tuple[HorizonFeatureSnapshot, ...]:
        # Universe ticks fan out across every symbol; symbol-scoped
        # ticks emit a single snapshot for that one symbol.
        # H1 / M3: the scheduler emits both per-symbol SYMBOL ticks and
        # a UNIVERSE tick at each boundary.  To prevent each
        # (symbol, horizon, boundary_index) triple from producing two
        # identical snapshots, skip any symbol that already received a
        # snapshot at this boundary.
        #
        # Audit #1: dedup must be symmetric.  The previous version only
        # guarded the UNIVERSE branch, relying on the scheduler's
        # canonical "SYMBOL before UNIVERSE" emission order.  Anything
        # publishing ticks directly to the bus (tests, replayers, future
        # gateways) could publish UNIVERSE → SYMBOL at the same boundary
        # and produce duplicate snapshots with non-deterministic
        # ``sequence`` allocation.  The guard is now applied in both
        # branches so the (symbol, horizon, boundary) invariant holds
        # regardless of upstream ordering.
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
            # Record that this (horizon, symbol) has been snapshotted at
            # this boundary so a later UNIVERSE tick (or an out-of-order
            # SYMBOL tick) cannot produce a duplicate.
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

        # Audit #17: dispatch on horizon-bucketed view so passive
        # horizons cost O(1), not O(F).  Iteration order matches the
        # global sorted order because we built the buckets from it.
        for feature in self._features_by_horizon.get(tick.horizon_seconds, ()):
            state_key = (feature.feature_id, feature.horizon_seconds, symbol)
            state = self._feature_state.get(state_key)
            if state is None:
                state = feature.initial_state()
                self._feature_state[state_key] = state
            # Audit #7: forward per-feature params from construction.
            value, w, s = feature.finalize(
                tick,
                state,
                params=self._feature_params.get(feature.feature_id, {}),
            )
            # H9 / M8: override stale=True when any input sensor has not
            # fired (warm) within the feature's horizon window.  This
            # catches the "sensor goes silent" case that the
            # buffer-eviction anchor alone cannot detect (eviction only
            # fires when the sensor re-fires, so a silent sensor keeps a
            # stale buffer alive).
            #
            # Semantic: "stale" here means "no fresh usable data within
            # the horizon window".  When the feature has never observed
            # a warm reading (last_ns is None) we treat that as stale —
            # combined with warm=False from the feature itself, the
            # downstream gate (``warm and not stale``) suppresses
            # correctly either way, but recording stale=True makes the
            # absence of fresh data explicit in the snapshot.
            if not s:
                horizon_ns = feature.horizon_seconds * _NS_PER_SECOND
                for sid in feature.input_sensor_ids:
                    last_ns = self._last_reading_ns.get((symbol, sid))
                    if last_ns is None or (tick.timestamp_ns - last_ns) > horizon_ns:
                        s = True
                        break
            # 3P-1: defence in depth.  The registry already suppresses
            # non-finite *sensor* values, but a feature reducer could still
            # produce a NaN/Inf (e.g. a degenerate variance path).  Never let
            # one into ``values`` — it would poison the gate and signal — so a
            # non-finite warm value is demoted to cold (warm=False) and omitted.
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
            # S2: always populate warm/stale for every registered feature
            # so the engine can detect active mode even when all features
            # are temporarily cold.  Only add to values when the feature
            # is warm — cold features are absent (not 0.0) so consumers
            # correctly distinguish "not yet warm" from "computed zero".
            warm[feature.feature_id] = w_eff
            stale[feature.feature_id] = bool(s)
            if w_eff:
                assert fv is not None
                values[feature.feature_id] = fv
            source_sensors[feature.feature_id] = tuple(feature.input_sensor_ids)
            # Audit #12: provenance now records feature_version so a
            # consumer reading an archived snapshot can reconstruct which
            # version produced each value (Inv-13).
            feature_versions[feature.feature_id] = feature.feature_version

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
            feature_versions=feature_versions,
            parent_correlation_id=tick.correlation_id,  # S4: audit-spine chain
        )

    # ── Monitoring (plan §4.5) ───────────────────────────────────────

    def _emit_snapshot_metric(self, *, snapshot: HorizonFeatureSnapshot) -> None:
        """Emit ``feelies.feature.snapshot.stale_fraction`` for one snapshot.

        Gauge in ``[0, 1]`` reporting the fraction of features whose
        ``stale`` flag is True for this snapshot, computed against the
        *total* number of registered features (warm + cold), not just
        the warm subset.  Cold features count as "not stale" in the
        denominator — a snapshot with one warm-stale feature out of ten
        registered reports 0.1.  This matches Plan §4.5 ("fraction of
        features").  Passive-mode snapshots (no features) report
        ``0.0`` by convention so the gauge time-series remains
        continuous across feature registration (audit #15).
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


__all__ = ["HorizonAggregator"]
