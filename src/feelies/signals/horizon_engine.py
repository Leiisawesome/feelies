"""Turn horizon snapshots into regime-gated signals.

Registrations bind a pure evaluator, parameters, regime gate, horizon, costs,
and provenance. The engine caches regime state, evaluates matching snapshots in
stable order, and publishes through a dedicated sequence stream. With no signal
alphas registered it does not subscribe to the bus.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Mapping

from feelies.alpha.cost_arithmetic import CostArithmetic
from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    EXIT_ONLY_MECHANISMS,
    HorizonFeatureSnapshot,
    MetricEvent,
    MetricType,
    RegimeState,
    SafetyReason,
    SafetyStateChange,
    SensorReading,
    Signal,
    SignalDirection,
    TrendMechanism,
)
from feelies.core.identifiers import SequenceGenerator, make_correlation_id
from feelies.monitoring.telemetry import MetricCollector
from feelies.signals.horizon_protocol import HorizonSignal
from feelies.signals.regime_gate import (
    Bindings,
    RegimeGate,
    RegimeGateError,
    UnknownIdentifierError,
)


_logger = logging.getLogger(__name__)


# Explicitly map tuple sensors to the scalar names exposed by the gate DSL.
# Unlisted tuple sensors are ignored.
_TUPLE_SENSOR_COMPONENTS: dict[str, tuple[str, ...]] = {
    # (active, seconds_to_close, window_id_hash, direction_prior)
    "scheduled_flow_window": (
        "scheduled_flow_window_active",
        "seconds_to_window_close",
        "scheduled_flow_window_id_hash",
        "scheduled_flow_window_direction_prior",
    ),
    # (buy_intensity, sell_intensity, intensity_ratio, branching_ratio)
    "hawkes_intensity": (
        "hawkes_intensity_buy",
        "hawkes_intensity_sell",
        "hawkes_intensity_ratio",
        "hawkes_branching_ratio_est",
    ),
}


@dataclass(frozen=True, kw_only=True)
class RegisteredSignal:
    """Immutable signal registration used by the dispatch loop."""

    alpha_id: str
    horizon_seconds: int
    signal: HorizonSignal
    params: Mapping[str, Any]
    gate: RegimeGate
    cost_arithmetic: CostArithmetic
    trend_mechanism: TrendMechanism | None = None
    expected_half_life_seconds: int = 0
    consumed_features: tuple[str, ...] = ()
    # None requires every snapshot feature; otherwise require only these IDs.
    required_warm_feature_ids: frozenset[str] | None = None
    # Stage-0 dual-permission decoupling (design §2.3, §3.1).  When True, every
    # gate-close path emits a typed ``SafetyStateChange`` and suppresses the
    # direct gate-close FLAT — the risk-layer composer
    # (:class:`~feelies.risk.exit_composer.ExitComposer`) actuates the unwind
    # from that event: a *clean* ON→OFF becomes a bounded HOLD (the deferral cap
    # owns the timed exit), and the three fail-closed error paths become an
    # immediate EXIT.  Default False keeps today's unconditional auto-FLAT on
    # every path, so the emitted Signal stream stays bit-identical (Inv-5).
    decouple_gate_close: bool = False


class HorizonSignalEngine:
    """Turn horizon snapshots into gated ``Signal`` events."""

    __slots__ = (
        "_bus",
        "_signal_seq",
        "_clock",
        "_signals",
        "_regime_cache",
        "_sensor_cache",
        "_attached",
        "_regime_min_discriminability",
        "_metric_collector",
        "_metrics_seq",
        "_safety_seq",
        "_last_boundary_index",
    )

    def __init__(
        self,
        *,
        bus: EventBus,
        signal_sequence_generator: SequenceGenerator,
        clock: Any | None = None,
        regime_min_discriminability: float = 0.0,
        metric_collector: MetricCollector | None = None,
    ) -> None:
        self._bus = bus
        self._signal_seq = signal_sequence_generator
        self._clock = clock
        # Isolate metrics so instrumentation cannot shift signal event IDs.
        self._metric_collector = metric_collector
        self._metrics_seq: SequenceGenerator | None = (
            SequenceGenerator() if metric_collector is not None else None
        )
        # Isolate SafetyStateChange on its own sequence stream so publishing it
        # on every gate-close path can never perturb the locked Signal stream
        # (Inv-5) — mirrors the metrics-seq isolation above.
        self._safety_seq: SequenceGenerator = SequenceGenerator()
        # Fail regime gates closed when calibrated states are not distinct.
        self._regime_min_discriminability = float(regime_min_discriminability)
        self._signals: list[RegisteredSignal] = []
        self._regime_cache: dict[tuple[str, str], RegimeState] = {}
        # Retain two scalar readings per sensor so boundary evaluation can ignore
        # a newer post-boundary value and still use the last causal value.
        self._sensor_cache: dict[tuple[str, str], list[tuple[int, float]]] = {}
        self._attached: bool = False
        # Observe duplicate or out-of-order boundaries without blocking dispatch.
        self._last_boundary_index: dict[tuple[str, str], int] = {}

    # ── Registration ─────────────────────────────────────────────────

    def register(self, registered: RegisteredSignal) -> None:
        """Register one signal.  Idempotent within ``alpha_id``.

        Re-registering the same ``alpha_id`` raises :class:`ValueError`
        — the platform's :class:`feelies.alpha.registry.AlphaRegistry`
        already enforces alpha-id uniqueness, so this is a defensive
        belt-and-suspenders check.
        """
        for existing in self._signals:
            if existing.alpha_id == registered.alpha_id:
                raise ValueError(
                    f"HorizonSignalEngine: alpha {registered.alpha_id!r} is already registered"
                )
        self._signals.append(registered)
        # Sort by (horizon_seconds, alpha_id) so iteration order is a
        # deterministic function of registered ids — independent of
        # registration order.
        self._signals.sort(key=lambda s: (s.horizon_seconds, s.alpha_id))

    @property
    def is_empty(self) -> bool:
        """True iff no SIGNAL alphas have been registered."""
        return not self._signals

    @property
    def signals(self) -> tuple[RegisteredSignal, ...]:
        """Read-only view of registered signals in dispatch order."""
        return tuple(self._signals)

    # ── Bus wiring ───────────────────────────────────────────────────

    def attach(self) -> None:
        """Subscribe to :class:`HorizonFeatureSnapshot` and
        :class:`RegimeState` events on the configured bus.

        When no signals are registered the subscription is deferred:
        ``_attached`` is left ``False`` so a subsequent call *after*
        :meth:`register` will still subscribe correctly.

        .. warning::
           Once subscribed this method is a no-op (``_attached`` is
           ``True``).  Signals registered **after** a successful
           ``attach()`` call are dispatched correctly (they are in
           ``self._signals``), but calling ``attach()`` again is
           harmless; do not rely on it to add subscriptions.
        """
        if self._attached:
            return
        if not self._signals:
            _logger.debug(
                "HorizonSignalEngine.attach() — no signals registered, "
                "skipping bus subscription (legacy fast-path preserved)"
            )
            return
        self._bus.subscribe(RegimeState, self._on_regime_state)
        self._bus.subscribe(SensorReading, self._on_sensor_reading)
        self._bus.subscribe(HorizonFeatureSnapshot, self._on_snapshot)
        self._attached = True

    # ── Bus handlers ─────────────────────────────────────────────────

    def _on_regime_state(self, event: RegimeState) -> None:
        """Cache the latest ``RegimeState`` per ``(symbol, engine_name)``."""
        self._regime_cache[(event.symbol, event.engine_name)] = event

    def _on_sensor_reading(self, event: SensorReading) -> None:
        """Cache warm scalar readings for boundary-safe gate bindings.

        Known tuple sensors fan out to scalar component names. Cold readings
        invalidate cached values so gates fail closed after data gaps. The two
        latest timestamps are retained for as-of-boundary lookup.
        """
        value = event.value
        if isinstance(value, tuple):
            components = _TUPLE_SENSOR_COMPONENTS.get(event.sensor_id)
            if components is None:
                _logger.warning(
                    "HorizonSignalEngine: tuple sensor %r emitted "
                    "without a registered component map in "
                    "_TUPLE_SENSOR_COMPONENTS; skipping (add mapping for "
                    "regime-gate bindings)",
                    event.sensor_id,
                )
                return
            if not event.warm:
                for name in components:
                    self._sensor_cache.pop((event.symbol, name), None)
                return
            for name, component_value in zip(components, value):
                self._cache_reading(
                    (event.symbol, name),
                    (event.timestamp_ns, float(component_value)),
                )
            return
        if not event.warm:
            self._sensor_cache.pop((event.symbol, event.sensor_id), None)
            return
        self._cache_reading((event.symbol, event.sensor_id), (event.timestamp_ns, float(value)))

    def _cache_reading(self, key: tuple[str, str], reading: tuple[int, float]) -> None:
        """Append ``reading`` to *key*'s cache slot, retaining the prior one.

        Only the two most recent readings are kept (oldest first).  The
        immediately-preceding reading is retained so :meth:`_build_bindings`
        can still serve the last value at or before a snapshot boundary when
        the newest reading was stamped after it — the boundary-crossing quote
        publishes its ``SensorReading`` before the ``HorizonFeatureSnapshot``,
        so without the fallback that quote's post-boundary reading would
        overwrite (then, under the Inv-6 filter, drop) a causally valid
        pre-boundary value.
        """
        prior = self._sensor_cache.get(key)
        if prior is None:
            self._sensor_cache[key] = [reading]
        else:
            self._sensor_cache[key] = [prior[-1], reading]

    def _on_snapshot(self, snapshot: HorizonFeatureSnapshot) -> None:
        """Evaluate every registered signal whose horizon matches."""
        if not self._signals:
            return
        for registered in self._signals:
            if registered.horizon_seconds != snapshot.horizon_seconds:
                continue
            self._dispatch_one(registered, snapshot)

    # ── Per-signal dispatch ──────────────────────────────────────────

    def _dispatch_one(
        self,
        registered: RegisteredSignal,
        snapshot: HorizonFeatureSnapshot,
    ) -> None:
        """Evaluate gate, then signal, and publish the resulting event."""
        self._check_duplicate_boundary(registered, snapshot)
        # Cold or stale inputs block entries, but gate evaluation continues so an
        # existing position can still receive a conservative close.
        entry_blocked = False
        not_warm = False
        is_stale = False
        if snapshot.warm:
            if registered.required_warm_feature_ids is None:
                keys_to_check = tuple(snapshot.warm.keys())
            else:
                keys_to_check = tuple(registered.required_warm_feature_ids)
            not_warm = any(not snapshot.warm[k] for k in keys_to_check if k in snapshot.warm)
            is_stale = any(
                snapshot.stale.get(k, False) for k in keys_to_check if k in snapshot.stale
            )
            entry_blocked = not_warm or is_stale
            if entry_blocked:
                _logger.debug(
                    "HorizonSignalEngine: %s snapshot for %s at "
                    "boundary=%d is not ready (warm=%s stale=%s); "
                    "suppressing entry (exit/gate-close still permitted)",
                    registered.alpha_id,
                    snapshot.symbol,
                    snapshot.boundary_index,
                    not not_warm,
                    is_stale,
                )

        regime = self._lookup_regime(snapshot.symbol, registered.gate)
        bindings = self._build_bindings(
            snapshot, regime, self._sensor_cache, self._regime_min_discriminability
        )
        was_on = registered.gate.is_on(snapshot.symbol)
        # Blocked entries may close an ON latch but cannot arm an OFF latch.
        gate_will_commit = not (entry_blocked and not was_on)
        try:
            on = registered.gate.evaluate(
                symbol=snapshot.symbol,
                bindings=bindings,
                mutate=gate_will_commit,
            )
        except UnknownIdentifierError as exc:
            # Missing bindings force the latch OFF; an ON position must unwind.
            registered.gate.reset(snapshot.symbol)
            hint = (
                f" hint: published RegimeState.engine_name must match "
                f"regime_gate.regime_engine={registered.gate.engine_name!r}."
                if "no RegimeState" in str(exc)
                else ""
            )
            # Missing sensor bindings are routine during warm-up.
            log_fn = _logger.debug if exc.missing_binding_token is not None else _logger.warning
            log_fn(
                "HorizonSignalEngine: %s gate suppressed for %s — %s%s",
                registered.alpha_id,
                snapshot.symbol,
                exc,
                hint,
            )
            if was_on:
                self._publish_gate_close(snapshot, registered, reason="missing_binding")
                self._emit_metric(
                    "feelies.signal.gate.failsafe_unwind",
                    ts_ns=snapshot.timestamp_ns,
                    tags={"alpha_id": registered.alpha_id, "reason": "unknown_identifier"},
                )
            return
        except RegimeGateError as exc:
            # Any gate error forces OFF so a bad close expression cannot strand risk.
            registered.gate.reset(snapshot.symbol)
            _logger.warning(
                "HorizonSignalEngine: %s gate parse/eval error for %s: %s "
                "— forcing OFF and unwinding any open position",
                registered.alpha_id,
                snapshot.symbol,
                exc,
            )
            if was_on:
                self._publish_gate_close(snapshot, registered, reason="gate_error")
                self._emit_metric(
                    "feelies.signal.gate.failsafe_unwind",
                    ts_ns=snapshot.timestamp_ns,
                    tags={"alpha_id": registered.alpha_id, "reason": "regime_gate_error"},
                )
            return
        except (
            ZeroDivisionError,
            ArithmeticError,
            TypeError,
            ValueError,
        ) as exc:
            # Arithmetic and type errors in authored expressions also force OFF.
            registered.gate.reset(snapshot.symbol)
            _logger.warning(
                "HorizonSignalEngine: %s gate arithmetic/type error for "
                "%s (%s: %s) — forcing OFF and unwinding any open "
                "position; review the gate expression for divide-by-zero "
                "or string-vs-number comparison",
                registered.alpha_id,
                snapshot.symbol,
                type(exc).__name__,
                exc,
            )
            if was_on:
                self._publish_gate_close(snapshot, registered, reason="arithmetic_error")
                self._emit_metric(
                    "feelies.signal.gate.failsafe_unwind",
                    ts_ns=snapshot.timestamp_ns,
                    tags={"alpha_id": registered.alpha_id, "reason": "arithmetic_error"},
                )
            return

        if was_on and not on:
            # ON to OFF closes the position (clean transition).
            self._publish_gate_close(snapshot, registered, reason="clean_transition")
            self._emit_metric(
                "feelies.signal.gate.transition",
                ts_ns=snapshot.timestamp_ns,
                tags={"alpha_id": registered.alpha_id, "to": "OFF"},
            )
            return
        if not on:
            return
        if not was_on and gate_will_commit:
            # Count only committed OFF-to-ON transitions.
            self._emit_metric(
                "feelies.signal.gate.transition",
                ts_ns=snapshot.timestamp_ns,
                tags={"alpha_id": registered.alpha_id, "to": "ON"},
            )

        # The close path has run; now suppress any blocked entry.
        if entry_blocked:
            self._emit_metric(
                "feelies.signal.entry.suppressed",
                ts_ns=snapshot.timestamp_ns,
                tags={
                    "alpha_id": registered.alpha_id,
                    "reason": "not_warm" if not_warm else "stale",
                },
            )
            return

        try:
            raw = registered.signal.evaluate(
                snapshot,
                regime,
                registered.params,
            )
        except Exception as exc:
            _logger.warning(
                "HorizonSignalEngine: %s.evaluate raised on symbol=%s boundary_index=%d: %s",
                registered.alpha_id,
                snapshot.symbol,
                snapshot.boundary_index,
                exc,
            )
            return

        if raw is None:
            return

        if not isinstance(raw, Signal):
            _logger.warning(
                "HorizonSignalEngine: %s.evaluate returned %r (expected "
                "Signal | None); discarding",
                registered.alpha_id,
                type(raw).__name__,
            )
            return
        if raw.direction == SignalDirection.FLAT:
            # FLAT is a no-trade result at this entry boundary.
            return

        # Dynamic exit-only signals need the same runtime guard as literal ones.
        if registered.trend_mechanism in EXIT_ONLY_MECHANISMS:
            _logger.warning(
                "HorizonSignalEngine: %s is an exit-only mechanism (%s) but "
                "evaluate returned a non-FLAT %s entry for %s; suppressing "
                "(exit-only alphas may not open exposure — §20.6.1 rule 7)",
                registered.alpha_id,
                registered.trend_mechanism.name,
                raw.direction.name,
                snapshot.symbol,
            )
            return

        emitted = self._patch_signal(raw, snapshot, registered)
        self._bus.publish(emitted)
        self._emit_metric(
            "feelies.signal.emitted",
            ts_ns=snapshot.timestamp_ns,
            tags={"alpha_id": registered.alpha_id, "direction": emitted.direction.name},
        )

    def _publish_gate_close(
        self,
        snapshot: HorizonFeatureSnapshot,
        registered: RegisteredSignal,
        *,
        reason: SafetyReason,
    ) -> None:
        """Force-close the gate: emit the typed ``SafetyStateChange`` and, unless
        suppressed, the gate-close FLAT ``Signal``.

        Called on all four legacy flatten paths — the clean ON→OFF transition
        and the three fail-closed error paths (``reason`` names which). The
        ``SafetyStateChange`` is published on **every** path (design §3.1);
        omitting it on an error path would strand an open book under a decoupled
        alpha — a fail-open defect, not an optimization.

        For a **decoupled** alpha (``decouple_gate_close``) the direct FLAT is
        suppressed on **every** path: the risk-layer exit composer
        (:class:`~feelies.risk.exit_composer.ExitComposer`) actuates the unwind
        from the ``SafetyStateChange`` instead — a clean ON→OFF becomes a bounded
        HOLD (the deferral cap owns the timed exit), and the three fail-closed
        error paths become an immediate EXIT via the composer. The composer runs
        synchronously on this same dispatch, so the fail-closed unwind keeps the
        liveness the inline FLAT had (design §3.1, §3.6). This removes the
        Phase-1 temporary error-path FLAT that held decoupled error unwinds
        before the composer existed.

        Default (non-decoupled) alphas always FLAT on every path — keeping the
        emitted Signal stream bit-identical (Inv-5). The FLAT retains entry
        provenance so the unwind is attributed correctly.
        """
        self._publish_safety_state_change(snapshot, registered, reason)
        if registered.decouple_gate_close:
            return
        self._bus.publish(
            Signal(
                timestamp_ns=snapshot.timestamp_ns,
                correlation_id=snapshot.correlation_id,
                sequence=self._signal_seq.next(),
                source_layer="SIGNAL",
                symbol=snapshot.symbol,
                strategy_id=registered.alpha_id,
                direction=SignalDirection.FLAT,
                strength=0.0,
                edge_estimate_bps=0.0,
                layer="SIGNAL",
                horizon_seconds=registered.horizon_seconds,
                regime_gate_state="OFF",
                consumed_features=registered.consumed_features,
                trend_mechanism=registered.trend_mechanism,
                expected_half_life_seconds=(registered.expected_half_life_seconds),
                disclosed_cost_total_bps=(registered.cost_arithmetic.cost_total_bps),
                disclosed_margin_ratio=(registered.cost_arithmetic.margin_ratio),
            )
        )

    def _publish_safety_state_change(
        self,
        snapshot: HorizonFeatureSnapshot,
        registered: RegisteredSignal,
        reason: SafetyReason,
    ) -> None:
        """Publish a typed ``SafetyStateChange(safe=False)`` carrying the same
        alpha-level provenance as the gate-close FLAT (Inv-13).

        Emitted on the dedicated safety sequence stream so it never perturbs the
        locked Signal stream (Inv-5). Consumed by the risk-layer exit composer
        in a later phase; harmless (no subscriber) until then.
        """
        self._bus.publish(
            SafetyStateChange(
                timestamp_ns=snapshot.timestamp_ns,
                correlation_id=snapshot.correlation_id,
                sequence=self._safety_seq.next(),
                source_layer="SIGNAL",
                symbol=snapshot.symbol,
                strategy_id=registered.alpha_id,
                safe=False,
                reason=reason,
                trend_mechanism=registered.trend_mechanism,
                regime_gate_state="OFF",
                consumed_features=registered.consumed_features,
                expected_half_life_seconds=registered.expected_half_life_seconds,
                disclosed_cost_total_bps=registered.cost_arithmetic.cost_total_bps,
                disclosed_margin_ratio=registered.cost_arithmetic.margin_ratio,
            )
        )

    # Observability.

    def _emit_metric(self, name: str, *, ts_ns: int, tags: dict[str, str]) -> None:
        """Record one signal-engine counter (value 1.0).

        No-op when no collector is wired.  Uses the dedicated metrics sequence
        so it can never perturb the locked Signal stream (Inv-A / C1).
        """
        if self._metric_collector is None:
            return
        assert self._metrics_seq is not None
        seq = self._metrics_seq.next()
        cid = make_correlation_id(
            symbol=f"metric:signal:{tags.get('alpha_id', '?')}",
            exchange_timestamp_ns=ts_ns,
            sequence=seq,
        )
        self._metric_collector.record(
            MetricEvent(
                timestamp_ns=ts_ns,
                correlation_id=cid,
                sequence=seq,
                source_layer="SIGNAL",
                layer="signal",
                name=name,
                value=1.0,
                metric_type=MetricType.COUNTER,
                tags=tags,
            )
        )

    def _check_duplicate_boundary(
        self,
        registered: RegisteredSignal,
        snapshot: HorizonFeatureSnapshot,
    ) -> None:
        """Observe, but do not block, duplicate or out-of-order dispatch.

        A non-increasing boundary can double-evaluate and double-emit a signal.

        This is observability-only, matching the platform's existing Inv-11
        preference for surfacing an anomaly over speculatively rejecting it
        (:mod:`feelies.alpha.cost_arithmetic` module docstring): a real
        duplicate is logged and metered, but still dispatched normally, so a
        legitimate but unexpected upstream replay pattern is never
        silently dropped.
        """
        key = (snapshot.symbol, registered.alpha_id)
        last_boundary = self._last_boundary_index.get(key)
        if last_boundary is not None and snapshot.boundary_index <= last_boundary:
            _logger.warning(
                "HorizonSignalEngine: %s received a non-increasing "
                "boundary_index for %s (got %d, last dispatched %d) — "
                "possible duplicate or out-of-order HorizonFeatureSnapshot "
                "upstream; dispatching anyway (audit P2 2026-07-02)",
                registered.alpha_id,
                snapshot.symbol,
                snapshot.boundary_index,
                last_boundary,
            )
            self._emit_metric(
                "feelies.signal.snapshot.duplicate_boundary",
                ts_ns=snapshot.timestamp_ns,
                tags={"alpha_id": registered.alpha_id, "symbol": snapshot.symbol},
            )
            return
        self._last_boundary_index[key] = snapshot.boundary_index

    # ── Symbol lifecycle ───────────────────────────────────────────

    def forget(self, symbol: str) -> None:
        """Remove all per-symbol cached state for *symbol* (S7).

        Called when a symbol is delisted or when a clean restart of
        per-symbol state is needed.  Drops the regime cache, sensor
        cache, last-dispatched-boundary tracking, and gate latch state
        for *symbol* so a re-admission starts clean without stale
        cached values contaminating the new evaluation context.
        """
        self._regime_cache = {k: v for k, v in self._regime_cache.items() if k[0] != symbol}
        self._sensor_cache = {k: v for k, v in self._sensor_cache.items() if k[0] != symbol}
        self._last_boundary_index = {
            k: v for k, v in self._last_boundary_index.items() if k[0] != symbol
        }
        for registered in self._signals:
            registered.gate.reset(symbol)

    # ── Helpers ──────────────────────────────────────────────────────

    def _lookup_regime(self, symbol: str, gate: RegimeGate) -> RegimeState | None:
        """Resolve the cached :class:`RegimeState` for *symbol*.

        Picks by ``gate.engine_name`` when declared; otherwise returns
        the most-recently-published regime for *symbol* across all
        engines.  In a multi-engine deployment, when more than one
        engine has published for *symbol* and no ``engine_name`` is
        declared, this method picks by highest timestamp to be
        deterministic rather than relying on dict insertion order and logs a
        warning so the ambiguity is visible
        in production (S9).
        """
        if gate.engine_name is not None:
            return self._regime_cache.get((symbol, gate.engine_name))
        # Multi-engine fallback — pick the most recently published
        # RegimeState for this symbol so the selection rule is
        # deterministic and independent of dict insertion order.
        best: RegimeState | None = None
        best_engine: str | None = None
        count = 0
        for (sym, engine), state in self._regime_cache.items():
            if sym != symbol:
                continue
            count += 1
            if best is None or state.timestamp_ns > best.timestamp_ns:
                best = state
                best_engine = engine
        # Warn when fallback selection is ambiguous; operators
        # should always declare engine_name in multi-engine deployments.
        if count > 1:
            _logger.warning(
                "HorizonSignalEngine: regime lookup for symbol %s found "
                "%d engines (%r selected by latest timestamp); declare "
                "engine_name in the alpha config to remove ambiguity",
                symbol,
                count,
                best_engine,
            )
        return best

    @staticmethod
    def _build_bindings(
        snapshot: HorizonFeatureSnapshot,
        regime: RegimeState | None,
        sensor_cache: Mapping[tuple[str, str], list[tuple[int, float]]],
        min_discriminability: float = 0.0,
    ) -> Bindings:
        """Build gate bindings using snapshot values before cached sensors.

        Cache fallback selects the newest reading at or before the nominal
        boundary. Newer readings are ignored; a missing valid reading leaves
        the identifier absent so gate evaluation fails closed.
        """
        asof_ns = snapshot.boundary_ts_ns or snapshot.timestamp_ns
        sensor_values = dict(snapshot.values)
        for (sym, sensor_id), readings in sensor_cache.items():
            if sym != snapshot.symbol:
                continue
            # Readings are ordered oldest-first; serve the newest one at or
            # before the boundary so a post-boundary overwrite does not drop
            # a causally valid pre-boundary value (Inv-6).
            for reading_ts_ns, value in reversed(readings):
                if reading_ts_ns > asof_ns:
                    continue
                sensor_values.setdefault(sensor_id, value)
                break

        percentiles = {
            k[: -len("_percentile")]: v
            for k, v in sensor_values.items()
            if k.endswith("_percentile")
        }
        zscores = {
            k[: -len("_zscore")]: v for k, v in sensor_values.items() if k.endswith("_zscore")
        }
        return Bindings(
            regime=regime,
            sensor_values=sensor_values,
            percentiles=percentiles,
            zscores=zscores,
            min_discriminability=min_discriminability,
        )

    def _patch_signal(
        self,
        raw: Signal,
        snapshot: HorizonFeatureSnapshot,
        registered: RegisteredSignal,
    ) -> Signal:
        """Tag the alpha-emitted ``Signal`` with engine provenance.

        The alpha is free to leave provenance fields empty; the engine
        fills them in from the snapshot + registration record.  Any
        field already set by the alpha (e.g. ``metadata``) is
        preserved.
        """
        timestamp_ns = raw.timestamp_ns if raw.timestamp_ns else snapshot.timestamp_ns
        if not timestamp_ns and self._clock is not None:
            timestamp_ns = self._clock.now_ns()

        return replace(
            raw,
            timestamp_ns=timestamp_ns,
            correlation_id=snapshot.correlation_id,
            sequence=self._signal_seq.next(),
            source_layer="SIGNAL",
            symbol=raw.symbol or snapshot.symbol,
            strategy_id=raw.strategy_id or registered.alpha_id,
            layer="SIGNAL",
            horizon_seconds=registered.horizon_seconds,
            regime_gate_state="ON",
            consumed_features=(
                raw.consumed_features if raw.consumed_features else registered.consumed_features
            ),
            trend_mechanism=(
                raw.trend_mechanism
                if raw.trend_mechanism is not None
                else registered.trend_mechanism
            ),
            # Use the validated manifest half-life, never an inline signal override.
            expected_half_life_seconds=registered.expected_half_life_seconds,
            disclosed_cost_total_bps=(registered.cost_arithmetic.cost_total_bps),
            disclosed_margin_ratio=(registered.cost_arithmetic.margin_ratio),
        )


__all__ = ["HorizonSignalEngine", "RegisteredSignal"]
