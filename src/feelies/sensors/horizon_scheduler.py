"""HorizonScheduler — emits ``HorizonTick`` events at event-time boundaries.

Boundary math is **pure integer** (design doc §7.4 / §12.1):

    boundary_index(t, h) = (t - session_open_ns) // (h * 1_000_000_000)

The scheduler emits one tick the first time a new ``boundary_index`` is
crossed for each ``(horizon_seconds, scope, symbol)`` triplet — never
per-event.  Emission ordering inside a single ``on_event`` call is
strict (plan §3.2):

    sorted by horizon ascending,
      then scope: SYMBOL before UNIVERSE,
        then symbol ascending (None last for UNIVERSE)

so two replays of the same event log produce a bit-identical tick
sequence (Inv-C).

`session_open_ns` is **lazily bound** when the platform configuration
omits it: the first ``on_event`` call records ``event.timestamp_ns`` as
the session open and logs a loud INFO message.  Production deployments
should always pass an explicit ``session_open_ns`` from the platform
config; the lazy path exists only to keep the demo ergonomic.
"""

from __future__ import annotations

import logging
from typing import Iterable

from feelies.core.events import Event, HorizonTick, MetricEvent, MetricType
from feelies.core.identifiers import SequenceGenerator, make_correlation_id
from feelies.monitoring.telemetry import MetricCollector

_logger = logging.getLogger(__name__)


_NS_PER_SECOND = 1_000_000_000


class SessionOpenAlreadyBoundError(RuntimeError):
    """Raised when ``bind_session_open()`` is called after auto-bind.

    Auto-bind happens on the first ``on_event`` call when no
    ``session_open_ns`` was provided.  Re-binding after that would
    invalidate already-emitted ticks, so we fail loudly.
    """


class HorizonScheduler:
    """Emits ``HorizonTick`` events when event-time boundaries are crossed.

    Construction parameters:

    - ``horizons``: the registered horizons in seconds (e.g.
      ``frozenset({30, 120, 300, 900, 1800})``).  Empty horizons set
      makes ``on_event`` a no-op (zero overhead — used by the
      orchestrator to short-circuit the legacy path).
    - ``session_id``: passed through to every ``HorizonTick``; built
      by the bootstrap layer as ``f"{market_id}_{session_kind}_{date}"``
      per plan §3.2 / M5.
    - ``symbols``: the per-symbol universe (used for ``scope=SYMBOL``
      ticks).  ``UNIVERSE`` ticks ignore this set and emit a single
      tick per ``(horizon, boundary_index)``.
    - ``session_open_ns``: optional event-time anchor.  When ``None``
      the scheduler binds it on the first ``on_event`` call.
    - ``sequence_generator``: a *dedicated* generator owned by the
      scheduler — separate from the orchestrator's main ``_sequence``
      and from the registry's sensor sequence (Inv-A / C1).
    """

    __slots__ = (
        "_horizons_sorted",
        "_session_id",
        "_symbols_sorted",
        "_session_open_ns",
        "_session_open_locked",
        "_sequence_generator",
        "_last_boundary_symbol",
        "_last_boundary_universe",
        "_metric_collector",
        "_metrics_seq",
    )

    def __init__(
        self,
        *,
        horizons: frozenset[int],
        session_id: str,
        symbols: frozenset[str],
        session_open_ns: int | None = None,
        sequence_generator: SequenceGenerator,
        metric_collector: MetricCollector | None = None,
    ) -> None:
        for h in horizons:
            if h <= 0:
                raise ValueError(
                    f"HorizonScheduler.horizons must be positive ints, "
                    f"got {h}"
                )
        self._horizons_sorted: tuple[int, ...] = tuple(sorted(horizons))
        self._session_id = session_id
        self._symbols_sorted: tuple[str, ...] = tuple(sorted(symbols))

        # S17: warn early when the symbol universe is empty but horizons are
        # configured; SYMBOL-scope ticks will never be emitted, which almost
        # certainly means the platform config is wrong.
        if not symbols and horizons:
            _logger.warning(
                "HorizonScheduler: symbols universe is empty but %d horizon(s) "
                "are configured; SYMBOL-scope ticks will never be emitted "
                "(likely misconfiguration)",
                len(horizons),
            )
        self._session_open_ns: int | None = session_open_ns
        # ``_session_open_locked`` is True iff we have either accepted
        # an explicit session_open_ns at construction or auto-bound on
        # the first event.  Once locked, ``bind_session_open()`` raises.
        self._session_open_locked = session_open_ns is not None
        self._sequence_generator = sequence_generator

        # Per-(horizon, symbol) and per-(horizon,) for UNIVERSE scope:
        # the last boundary index we have already emitted.  The first
        # event in a window emits boundary_index=0 once observed;
        # subsequent events in the same window are no-ops.
        self._last_boundary_symbol: dict[tuple[int, str], int] = {}
        self._last_boundary_universe: dict[int, int] = {}
        # Plan §4.5: ``feelies.horizon.tick.emitted`` (counter, tags
        # ``horizon_seconds`` + ``scope``) is emitted once per
        # ``HorizonTick``.  Dedicated sequence generator so MetricEvent
        # sequences never perturb the locked HorizonTick stream.
        self._metric_collector = metric_collector
        self._metrics_seq: SequenceGenerator | None = (
            SequenceGenerator() if metric_collector is not None else None
        )

    # ── Public API ───────────────────────────────────────────────────

    @property
    def session_open_ns(self) -> int | None:
        """The currently-bound session anchor, or ``None`` if pending."""
        return self._session_open_ns

    @property
    def horizons(self) -> tuple[int, ...]:
        """Registered horizons in ascending order."""
        return self._horizons_sorted

    def bind_session_open(self, ts_ns: int) -> None:
        """Explicitly bind the session anchor before any events arrive.

        Raises :class:`SessionOpenAlreadyBoundError` if a session open
        is already in effect (either via constructor or auto-bind).
        """
        if self._session_open_locked:
            raise SessionOpenAlreadyBoundError(
                f"session_open_ns already bound to {self._session_open_ns}; "
                f"cannot rebind to {ts_ns}"
            )
        self._session_open_ns = ts_ns
        self._session_open_locked = True

    def on_event(self, event: Event) -> tuple[HorizonTick, ...]:
        """Inspect ``event``; return any ticks crossed at its timestamp.

        The returned tuple is in canonical emission order
        (plan §3.2).  The orchestrator publishes the ticks on the bus
        in the returned order, so consumers see the same ordering on
        every replay.
        """
        if not self._horizons_sorted:
            return ()

        if not self._session_open_locked:
            self._session_open_ns = event.timestamp_ns
            self._session_open_locked = True
            _logger.info(
                "HorizonScheduler.session_open_ns auto-bound to "
                "first-event timestamp %d (no explicit session_open_ns "
                "configured); production deployments should set this "
                "from PlatformConfig",
                event.timestamp_ns,
            )

        assert self._session_open_ns is not None

        ts = event.timestamp_ns
        emitted: list[HorizonTick] = []

        for horizon in self._horizons_sorted:
            window_ns = horizon * _NS_PER_SECOND
            elapsed = ts - self._session_open_ns
            if elapsed < 0:
                # Event predates the session open; do not emit.  This
                # only happens with malformed inputs but we'd rather
                # silently skip than emit a negative boundary index.
                continue
            current_boundary = elapsed // window_ns

            emitted.extend(
                self._emit_for_symbols(
                    horizon=horizon,
                    current_boundary=current_boundary,
                    ts_ns=ts,
                )
            )
            emitted.extend(
                self._emit_for_universe(
                    horizon=horizon,
                    current_boundary=current_boundary,
                    ts_ns=ts,
                )
            )

        return tuple(emitted)

    # ── Internals ────────────────────────────────────────────────────

    def _emit_for_symbols(
        self,
        *,
        horizon: int,
        current_boundary: int,
        ts_ns: int,
    ) -> Iterable[HorizonTick]:
        for symbol in self._symbols_sorted:
            key = (horizon, symbol)
            last = self._last_boundary_symbol.get(key)
            if last is not None and current_boundary <= last:
                continue
            self._last_boundary_symbol[key] = current_boundary
            yield self._make_tick(
                horizon=horizon,
                boundary_index=current_boundary,
                ts_ns=ts_ns,
                scope="SYMBOL",
                symbol=symbol,
            )

    def _emit_for_universe(
        self,
        *,
        horizon: int,
        current_boundary: int,
        ts_ns: int,
    ) -> Iterable[HorizonTick]:
        last = self._last_boundary_universe.get(horizon)
        if last is not None and current_boundary <= last:
            return
        self._last_boundary_universe[horizon] = current_boundary
        yield self._make_tick(
            horizon=horizon,
            boundary_index=current_boundary,
            ts_ns=ts_ns,
            scope="UNIVERSE",
            symbol=None,
        )

    def _make_tick(
        self,
        *,
        horizon: int,
        boundary_index: int,
        ts_ns: int,
        scope: str,
        symbol: str | None,
    ) -> HorizonTick:
        seq = self._sequence_generator.next()
        # Plan §3.2 / M4 — deterministic correlation_id formula:
        #   make_correlation_id(prefix=f"htick-{horizon}-{scope}",
        #                       ts_ns=boundary_ts, seq=boundary_index)
        # We reuse ``make_correlation_id`` (symbol/ts/seq triple) by
        # passing the synthesized prefix as the "symbol" slot and the
        # ``boundary_index`` as the "sequence" slot — this keeps the
        # canonical ID format ``{prefix}:{ts}:{idx}`` per the plan.
        boundary_ts = (
            (self._session_open_ns or 0) + boundary_index * horizon * _NS_PER_SECOND
        )
        prefix = f"htick-{horizon}-{scope}"
        if symbol is not None:
            prefix = f"{prefix}-{symbol}"
        correlation_id = make_correlation_id(
            symbol=prefix,
            exchange_timestamp_ns=boundary_ts,
            sequence=boundary_index,
        )
        tick = HorizonTick(
            timestamp_ns=ts_ns,
            correlation_id=correlation_id,
            sequence=seq,
            source_layer="SCHEDULER",
            horizon_seconds=horizon,
            boundary_index=boundary_index,
            session_id=self._session_id,
            scope=scope,  # type: ignore[arg-type]
            symbol=symbol,
        )
        if self._metric_collector is not None:
            self._emit_tick_metric(tick=tick)
        return tick

    # ── Monitoring (plan §4.5) ───────────────────────────────────────

    def _emit_tick_metric(self, *, tick: HorizonTick) -> None:
        """Emit ``feelies.horizon.tick.emitted`` for one tick.

        Counter, tags: ``horizon_seconds`` + ``scope``.  Recorded
        directly into the metric collector (not the bus) so this
        cannot perturb the HorizonTick sequence (Inv-A / C1).
        """
        assert self._metric_collector is not None
        assert self._metrics_seq is not None
        seq = self._metrics_seq.next()
        cid = make_correlation_id(
            symbol=f"metric:scheduler:{tick.horizon_seconds}",
            exchange_timestamp_ns=tick.timestamp_ns,
            sequence=seq,
        )
        self._metric_collector.record(MetricEvent(
            timestamp_ns=tick.timestamp_ns,
            correlation_id=cid,
            sequence=seq,
            source_layer="SCHEDULER",
            layer="scheduler",
            name="feelies.horizon.tick.emitted",
            value=1.0,
            metric_type=MetricType.COUNTER,
            tags={
                "horizon_seconds": str(tick.horizon_seconds),
                "scope": tick.scope,
            },
        ))
