#!/usr/bin/env python3
"""Backtest runner — connects real Massive data to the platform pipeline.

Usage:
    python scripts/run_backtest.py --symbol AAPL --date 2024-01-15
    python scripts/run_backtest.py --symbol AAPL --date 2024-01-15 --end-date 2024-01-16
    python scripts/run_backtest.py --config platform.yaml  # uses symbols from config

Workstream-D update — the ``--demo`` synthetic-tick mode was retired
along with the ``trade_cluster_drift`` LEGACY reference alpha (D.2).
For a no-API-key smoke test of the orchestration pipeline use the
end-to-end suite directly: ``pytest tests/integration/test_phase4_e2e.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TypeVar

# Ensure the project root is on sys.path so `feelies` is importable
# when running the script directly (e.g. `python scripts/run_backtest.py`).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from feelies.bootstrap import build_platform
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    CrossSectionalContext,
    Event,
    FeatureVector,
    HorizonFeatureSnapshot,
    HorizonTick,
    MetricEvent,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    PositionUpdate,
    RegimeHazardSpike,
    SensorReading,
    Signal,
    SignalDirection,
    SizedPositionIntent,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator, make_correlation_id
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.ingestion.massive_ingestor import IngestResult
from feelies.kernel.macro import MacroState
from feelies.monitoring.in_memory import InMemoryMetricCollector
from feelies.storage.disk_event_cache import DiskEventCache
from feelies.storage.memory_event_log import InMemoryEventLog

T = TypeVar("T", bound=Event)

# ── Report layout constants ──────────────────────────────────────────

_W = 62
_RULE_HEAVY = "=" * _W
_RULE_LIGHT = "-" * _W


# ── BusRecorder (same pattern as test_backtest_e2e.py) ───────────────


@dataclass
class BusRecorder:
    events: list[Event] = field(default_factory=list)
    by_type: dict[type, list[Event]] = field(default_factory=lambda: defaultdict(list))

    def __call__(self, event: Event) -> None:
        self.events.append(event)
        self.by_type[type(event)].append(event)

    def of_type(self, t: type[T]) -> list[T]:
        return self.by_type[t]  # type: ignore[return-value]


# ── Progress reporter ────────────────────────────────────────────────


class _ProgressReporter:
    """Subscribes to the bus and prints periodic progress during replay."""

    def __init__(self, total_events: int, interval: int = 100_000) -> None:
        self._total = total_events
        self._interval = interval
        self._count = 0
        self._t0 = time.monotonic()
        self._last_print = self._t0

    def __call__(self, event: Event) -> None:
        if not isinstance(event, NBBOQuote):
            return
        self._count += 1
        if self._count % self._interval == 0:
            elapsed = time.monotonic() - self._t0
            pct = self._count / self._total * 100.0 if self._total else 0.0
            rate = self._count / elapsed if elapsed > 0 else 0.0
            remaining = (self._total - self._count) / rate if rate > 0 else 0.0
            print(
                f"  [{pct:5.1f}%]  {self._count:>10,} / {self._total:,} quotes  "
                f"({rate:,.0f} q/s, ~{remaining:.0f}s remaining)",
                flush=True,
            )
            self._last_print = time.monotonic()

    def summary(self) -> str:
        elapsed = time.monotonic() - self._t0
        rate = self._count / elapsed if elapsed > 0 else 0.0
        return f"{self._count:,} quotes in {elapsed:.1f}s ({rate:,.0f} q/s)"


def _step(msg: str, t0: float | None = None) -> float:
    """Print a progress step with optional elapsed time from a prior step."""
    now = time.monotonic()
    if t0 is not None:
        dt = now - t0
        print(f"  OK ({dt:.1f}s)", flush=True)
    print(f"  {msg} ...", end="", flush=True)
    return now


# ── CLI ──────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run a historical backtest with real Massive L1 data.",
    )
    p.add_argument(
        "--symbol",
        type=str,
        nargs="+",
        default=None,
        help="Trading symbol(s), space-separated (default: from platform.yaml)",
    )
    p.add_argument(
        "--date",
        type=str,
        default=None,
        help="Start date in YYYY-MM-DD format (required)",
    )
    p.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date in YYYY-MM-DD (default: same as --date)",
    )
    p.add_argument(
        "--config",
        type=str,
        default="platform.yaml",
        help="Path to platform.yaml (default: platform.yaml)",
    )
    p.add_argument(
        "--cache-dir",
        type=str,
        default=None,
        help="Disk cache directory (default: ~/.feelies/cache/)",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Force re-download, skip disk cache",
    )
    p.add_argument(
        "--stress-cost",
        type=float,
        default=1.0,
        metavar="MULT",
        help="Cost stress multiplier (e.g. 1.5 = 50%% higher fees, default: 1.0)",
    )
    p.add_argument(
        "--emit-fills-jsonl",
        action="store_true",
        help=(
            "After the backtest completes, emit one JSON object per "
            "FILLED OrderAck to stdout (one per line), in arrival order. "
            "Originally consumed by the LEGACY_SIGNAL Level-1 fill "
            "parity test (design_docs/three_layer_architecture.md "
            "§11.1); the test was retired with workstream D.2 (loader "
            "rejection in PR-1, leaf deletion in PR-2a, per-tick engine "
            "deletion in PR-2b-ii) but the emitter is preserved as a "
            "debugging hook for fill streams."
        ),
    )
    # ── Phase-2 emit flags (composable with --emit-fills-jsonl) ─────
    # Each flag dumps one JSON object per relevant event in arrival
    # order, prefixed with a tag so consumers can grep / split a
    # single run's stdout into separate Level-N parity streams.
    p.add_argument(
        "--emit-sensor-readings-jsonl",
        action="store_true",
        help=(
            "Emit one JSON object per SensorReading to stdout "
            "(prefix 'SENSOR_JSONL'). Used by the Level-4 parity "
            "test (Phase-2 plan §3.7)."
        ),
    )
    p.add_argument(
        "--emit-horizon-ticks-jsonl",
        action="store_true",
        help=(
            "Emit one JSON object per HorizonTick to stdout "
            "(prefix 'HTICK_JSONL'). Used by the Level-2 parity "
            "test (Phase-2 plan §3.7)."
        ),
    )
    p.add_argument(
        "--emit-snapshots-jsonl",
        action="store_true",
        help=(
            "Emit one JSON object per HorizonFeatureSnapshot to "
            "stdout (prefix 'SNAP_JSONL'). Used by the Level-3 "
            "parity test (Phase-2 plan §3.7)."
        ),
    )
    # ── Phase-3 emit flags (composable with Phase-1/2 emitters) ─────
    p.add_argument(
        "--emit-signals-jsonl",
        action="store_true",
        help=(
            "Emit one JSON object per Signal to stdout "
            "(prefix 'SIGNAL_JSONL'). Tags each row with the "
            "originating layer (only ``SIGNAL`` post-D.2). Used by "
            "the Level-2 SIGNAL parity test "
            "(design_docs/three_layer_architecture.md §11.2)."
        ),
    )
    # ── Phase-3.1 emit flags (composable with all prior emitters) ───
    p.add_argument(
        "--emit-hazard-spikes-jsonl",
        action="store_true",
        help=(
            "Emit one JSON object per RegimeHazardSpike to stdout "
            "(prefix 'HAZARD_JSONL'). Used by the Level-5 hazard "
            "parity test (design_docs/three_layer_architecture.md "
            "§20.11.2)."
        ),
    )
    # ── Phase-4 emit flags (composable with all prior emitters) ────
    p.add_argument(
        "--emit-cross-sectional-jsonl",
        action="store_true",
        help=(
            "Emit one JSON object per CrossSectionalContext to stdout "
            "(prefix 'XSECT_JSONL').  Used by the Level-2 cross-"
            "sectional parity test (Phase-4 §11.2)."
        ),
    )
    p.add_argument(
        "--emit-sized-intents-jsonl",
        action="store_true",
        help=(
            "Emit one JSON object per SizedPositionIntent to stdout "
            "(prefix 'INTENT_JSONL').  Used by the Level-3 portfolio "
            "intent parity tests (Phase-4 / Phase-4.1 §11.3)."
        ),
    )
    p.add_argument(
        "--emit-hazard-exits-jsonl",
        action="store_true",
        help=(
            "Emit one JSON object per OrderRequest whose reason is "
            "'HAZARD_SPIKE' or 'HARD_EXIT_AGE' (prefix "
            "'HAZARD_EXIT_JSONL').  Used by the Phase-4.1 Level-1 + "
            "Level-4 hazard-exit determinism tests."
        ),
    )
    return p.parse_args(argv)


def _emit_fills_jsonl(recorder: BusRecorder) -> None:
    """Print one JSON line per FILLED OrderAck in arrival order.

    Stable shape — fields are ordered for deterministic hashing across
    Python versions: (sequence, symbol, order_id, filled_quantity,
    fill_price).  ``fill_price`` is rendered via ``str(Decimal)`` to
    preserve the exact textual representation; never float-formatted.

    Designed to be machine-checkable.  The original consumer
    ``tests/determinism/test_legacy_alpha_parity.py`` was retired with
    workstream D.2 alongside the ``trade_cluster_drift`` reference
    alpha; the canonical-JSON shape is preserved verbatim so any
    future fill-stream parity test can re-anchor on it without touching
    this emitter.
    """
    import json
    from decimal import Decimal

    acks = recorder.of_type(OrderAck)
    fills = [a for a in acks if a.status == OrderAckStatus.FILLED]
    for a in fills:
        line = {
            "sequence": a.sequence,
            "symbol": a.symbol,
            "order_id": a.order_id,
            "filled_quantity": a.filled_quantity,
            "fill_price": (
                str(a.fill_price) if isinstance(a.fill_price, Decimal)
                else None if a.fill_price is None
                else str(Decimal(str(a.fill_price)))
            ),
        }
        print("FILL_JSONL " + json.dumps(line, sort_keys=True), flush=True)


def _emit_sensor_readings_jsonl(recorder: BusRecorder) -> None:
    """Print one JSON line per ``SensorReading`` in arrival order.

    Stable shape: ``(sequence, sensor_id, sensor_version, symbol,
    value, warm)``.  Sensor values may be scalar or tuple; tuples are
    JSON-serialised as arrays.  The Level-4 baseline test (plan §3.7)
    SHA-256s the canonical-JSON line stream.
    """
    for r in recorder.of_type(SensorReading):
        value: object
        if isinstance(r.value, tuple):
            value = list(r.value)
        else:
            value = float(r.value)
        line = {
            "sequence": r.sequence,
            "sensor_id": r.sensor_id,
            "sensor_version": r.sensor_version,
            "symbol": r.symbol,
            "value": value,
            "warm": bool(r.warm),
        }
        print("SENSOR_JSONL " + json.dumps(line, sort_keys=True), flush=True)


def _emit_horizon_ticks_jsonl(recorder: BusRecorder) -> None:
    """Print one JSON line per ``HorizonTick`` in arrival order.

    Stable shape: ``(sequence, horizon_seconds, boundary_index,
    scope, symbol, session_id)``.  Used by the Level-2 baseline
    test (plan §3.7).  The same hash is also reproducible by reading
    the in-process tick stream directly via the
    :func:`tests.fixtures.replay.hash_horizon_tick_stream` helper.
    """
    for t in recorder.of_type(HorizonTick):
        line = {
            "sequence": t.sequence,
            "horizon_seconds": t.horizon_seconds,
            "boundary_index": t.boundary_index,
            "scope": t.scope,
            "symbol": t.symbol,
            "session_id": t.session_id,
        }
        print("HTICK_JSONL " + json.dumps(line, sort_keys=True), flush=True)


def _emit_snapshots_jsonl(recorder: BusRecorder) -> None:
    """Print one JSON line per ``HorizonFeatureSnapshot`` in arrival order.

    Stable shape: ``(sequence, symbol, horizon_seconds,
    boundary_index, values, warm, stale)``.  Empty dicts are emitted
    in passive mode (Phase 2: no horizon features registered) so
    consumers can still hash a non-empty stream from day one.
    """
    for s in recorder.of_type(HorizonFeatureSnapshot):
        line = {
            "sequence": s.sequence,
            "symbol": s.symbol,
            "horizon_seconds": s.horizon_seconds,
            "boundary_index": s.boundary_index,
            "values": dict(s.values),
            "warm": {k: bool(v) for k, v in s.warm.items()},
            "stale": {k: bool(v) for k, v in s.stale.items()},
        }
        print("SNAP_JSONL " + json.dumps(line, sort_keys=True), flush=True)


def _emit_signals_jsonl(recorder: BusRecorder) -> None:
    """Print one JSON line per ``Signal`` in arrival order.

    Stable shape — fields are ordered for deterministic hashing across
    Python versions: ``(sequence, symbol, strategy_id, layer,
    horizon_seconds, regime_gate_state, direction, strength,
    edge_estimate_bps, consumed_features, trend_mechanism,
    expected_half_life_seconds)``.

    Tagged with prefix ``SIGNAL_JSONL`` so a single run's stdout can
    be sliced out from the other emit-channels by a downstream
    consumer.  Post-D.2 every emitted row carries ``layer="SIGNAL"``;
    the historical ``layer="LEGACY_SIGNAL"`` rows were retired with
    the per-tick legacy path.  The Level-2 SIGNAL baseline test
    (design_docs/three_layer_architecture.md §11.2) hashes the
    canonical-JSON line stream and compares it across Phase changes
    to surface drift in scope, ordering, or sequence allocation.
    """
    for s in recorder.of_type(Signal):
        line = {
            "sequence": s.sequence,
            "symbol": s.symbol,
            "strategy_id": s.strategy_id,
            "layer": s.layer,
            "horizon_seconds": s.horizon_seconds,
            "regime_gate_state": s.regime_gate_state,
            "direction": s.direction.name,
            "strength": float(s.strength),
            "edge_estimate_bps": float(s.edge_estimate_bps),
            "consumed_features": list(s.consumed_features),
            "trend_mechanism": (
                s.trend_mechanism.name if s.trend_mechanism is not None
                else None
            ),
            "expected_half_life_seconds": int(s.expected_half_life_seconds),
        }
        print("SIGNAL_JSONL " + json.dumps(line, sort_keys=True), flush=True)


def _emit_hazard_spikes_jsonl(recorder: BusRecorder) -> None:
    """Print one JSON line per ``RegimeHazardSpike`` in arrival order.

    Stable shape — fields ordered for deterministic hashing across
    Python versions: ``(sequence, symbol, engine_name, departing_state,
    departing_posterior_prev, departing_posterior_now, incoming_state,
    hazard_score, timestamp_ns, correlation_id)``.

    Tagged with prefix ``HAZARD_JSONL`` so a single run's stdout can
    interleave hazard emissions with the Phase-1/2/3 emit streams and
    still be sliced by a downstream consumer.  The Level-5 hazard
    baseline test (design_docs/three_layer_architecture.md §20.11.2)
    SHA-256s the canonical-JSON line stream.
    """
    for s in recorder.of_type(RegimeHazardSpike):
        line = {
            "sequence": s.sequence,
            "symbol": s.symbol,
            "engine_name": s.engine_name,
            "departing_state": s.departing_state,
            "departing_posterior_prev": float(s.departing_posterior_prev),
            "departing_posterior_now": float(s.departing_posterior_now),
            "incoming_state": s.incoming_state,
            "hazard_score": float(s.hazard_score),
            "timestamp_ns": s.timestamp_ns,
            "correlation_id": s.correlation_id,
        }
        print("HAZARD_JSONL " + json.dumps(line, sort_keys=True), flush=True)


def _emit_cross_sectional_jsonl(recorder: BusRecorder) -> None:
    """Print one JSON line per ``CrossSectionalContext`` in arrival order.

    Stable shape — fields ordered for deterministic hashing across
    Python versions: ``(sequence, timestamp_ns, horizon_seconds,
    boundary_index, universe, completeness, correlation_id)``.

    Tagged with prefix ``XSECT_JSONL`` so a single run's stdout can
    interleave LEGACY/SIGNAL/PORTFOLIO emissions and still be sliced
    by a downstream consumer.  The Level-2 cross-sectional parity test
    (Phase-4 §11.2) SHA-256s the canonical-JSON line stream.
    """
    for c in recorder.of_type(CrossSectionalContext):
        line = {
            "sequence": c.sequence,
            "timestamp_ns": c.timestamp_ns,
            "horizon_seconds": c.horizon_seconds,
            "boundary_index": c.boundary_index,
            "universe": list(c.universe),
            "completeness": float(c.completeness),
            "correlation_id": c.correlation_id,
        }
        print("XSECT_JSONL " + json.dumps(line, sort_keys=True), flush=True)


def _emit_sized_intents_jsonl(recorder: BusRecorder) -> None:
    """Print one JSON line per ``SizedPositionIntent`` in arrival order.

    Stable shape: ``(sequence, timestamp_ns, strategy_id,
    horizon_seconds, target_positions, factor_exposures,
    expected_turnover_usd, expected_gross_exposure_usd,
    mechanism_breakdown, correlation_id)``.

    Target-position values are emitted as a *sorted* list of
    ``{symbol, target_usd}`` records so byte-identity holds across
    dict-ordering differences.  The Level-3 parity test
    (Phase-4 / Phase-4.1 §11.3) SHA-256s the canonical-JSON stream.
    """
    for it in recorder.of_type(SizedPositionIntent):
        targets = [
            {"symbol": s, "target_usd": float(tp.target_usd)}
            for s, tp in sorted(it.target_positions.items())
        ]
        mech_breakdown = {
            (k.name if hasattr(k, "name") else str(k)): float(v)
            for k, v in sorted(
                it.mechanism_breakdown.items(),
                key=lambda kv: (
                    kv[0].name if hasattr(kv[0], "name") else str(kv[0])
                ),
            )
        }
        line = {
            "sequence": it.sequence,
            "timestamp_ns": it.timestamp_ns,
            "strategy_id": it.strategy_id,
            "horizon_seconds": it.horizon_seconds,
            "target_positions": targets,
            "factor_exposures": {
                k: float(v) for k, v in sorted(it.factor_exposures.items())
            },
            "expected_turnover_usd": float(it.expected_turnover_usd),
            "expected_gross_exposure_usd": float(
                it.expected_gross_exposure_usd
            ),
            "mechanism_breakdown": mech_breakdown,
            "correlation_id": it.correlation_id,
        }
        print("INTENT_JSONL " + json.dumps(line, sort_keys=True), flush=True)


def _emit_hazard_exits_jsonl(recorder: BusRecorder) -> None:
    """Print one JSON line per hazard-driven exit ``OrderRequest``.

    Filters ``OrderRequest`` events whose ``reason`` is either
    ``"HAZARD_SPIKE"`` or ``"HARD_EXIT_AGE"`` and emits a stable
    ``(sequence, timestamp_ns, symbol, side, quantity, order_id,
    strategy_id, reason, correlation_id)`` record tagged
    ``HAZARD_EXIT_JSONL``.  Used by the Phase-4.1 Level-1 + Level-4
    hazard-exit determinism tests.
    """
    for o in recorder.of_type(OrderRequest):
        reason = getattr(o, "reason", "") or ""
        if reason not in ("HAZARD_SPIKE", "HARD_EXIT_AGE"):
            continue
        line = {
            "sequence": o.sequence,
            "timestamp_ns": o.timestamp_ns,
            "symbol": o.symbol,
            "side": o.side.name,
            "quantity": int(o.quantity),
            "order_id": o.order_id,
            "strategy_id": o.strategy_id or "",
            "reason": reason,
            "correlation_id": o.correlation_id,
        }
        print(
            "HAZARD_EXIT_JSONL " + json.dumps(line, sort_keys=True),
            flush=True,
        )


def _emit_phase2_jsonl(args: argparse.Namespace, recorder: BusRecorder) -> None:
    """Composable wrapper — invokes each enabled Phase-2/3/3.1/4 emitter."""
    if args.emit_sensor_readings_jsonl:
        _emit_sensor_readings_jsonl(recorder)
    if args.emit_horizon_ticks_jsonl:
        _emit_horizon_ticks_jsonl(recorder)
    if args.emit_snapshots_jsonl:
        _emit_snapshots_jsonl(recorder)
    if args.emit_signals_jsonl:
        _emit_signals_jsonl(recorder)
    if args.emit_hazard_spikes_jsonl:
        _emit_hazard_spikes_jsonl(recorder)
    if getattr(args, "emit_cross_sectional_jsonl", False):
        _emit_cross_sectional_jsonl(recorder)
    if getattr(args, "emit_sized_intents_jsonl", False):
        _emit_sized_intents_jsonl(recorder)
    if getattr(args, "emit_hazard_exits_jsonl", False):
        _emit_hazard_exits_jsonl(recorder)


# ── Ingestion ────────────────────────────────────────────────────────


def _iter_dates(start_date: str, end_date: str) -> list[str]:
    """Generate YYYY-MM-DD strings for each calendar date in [start, end]."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    dates: list[str] = []
    current = start
    while current <= end:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def _resequence(
    events: list[NBBOQuote | Trade],
) -> list[NBBOQuote | Trade]:
    """Sort by exchange time and assign globally monotonic sequences.

    Multi-symbol events may arrive concatenated (all AAPL then all MSFT).
    Sorting by exchange_timestamp_ns ensures the SimulatedClock advances
    correctly and all components see chronologically ordered ticks.
    """
    events.sort(key=lambda e: e.exchange_timestamp_ns)
    seq = SequenceGenerator()
    result: list[NBBOQuote | Trade] = []
    for event in events:
        new_seq = seq.next()
        new_cid = make_correlation_id(
            event.symbol, event.exchange_timestamp_ns, new_seq,
        )
        result.append(replace(event, sequence=new_seq, correlation_id=new_cid))
    return result


@dataclass(frozen=True)
class DaySource:
    """Provenance for a single (symbol, date) ingestion."""
    symbol: str
    date: str
    source: str
    event_count: int


def ingest_data(
    api_key: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
    *,
    cache_dir: Path | None = None,
    no_cache: bool = False,
) -> tuple[InMemoryEventLog, IngestResult, list[DaySource]]:
    """Download historical data with per-day cache and parallel download."""
    from feelies.ingestion.massive_ingestor import MassiveHistoricalIngestor
    from feelies.ingestion.massive_normalizer import MassiveNormalizer

    cache: DiskEventCache | None = None
    if not no_cache:
        resolved_dir = cache_dir or Path.home() / ".feelies" / "cache"
        cache = DiskEventCache(resolved_dir)

    dates = _iter_dates(start_date, end_date)
    all_events: list[NBBOQuote | Trade] = []
    day_sources: list[DaySource] = []

    total_events_from_api = 0
    total_pages = 0
    total_gaps = 0
    total_dupes = 0

    for symbol in symbols:
        for day in dates:
            if cache is not None and cache.exists(symbol, day):
                loaded = cache.load(symbol, day)
                if loaded is not None:
                    all_events.extend(loaded)
                    day_sources.append(DaySource(
                        symbol=symbol, date=day,
                        source="cache", event_count=len(loaded),
                    ))
                    print(f"  {symbol} {day}: {len(loaded):,} events (cache)", flush=True)
                    continue

            clock = SimulatedClock(start_ns=1_000_000_000)
            normalizer = MassiveNormalizer(clock)
            day_log = InMemoryEventLog()

            ingestor = MassiveHistoricalIngestor(
                api_key=api_key,
                normalizer=normalizer,
                event_log=day_log,
                clock=clock,
            )

            print(f"  {symbol} {day}: fetching from API ...", flush=True)
            _fetch_t0 = time.monotonic()

            def _on_page(
                feed_type: str, page_num: int, total: int, elapsed: float,
                _sym: str = symbol, _day: str = day,
            ) -> None:
                if page_num == 1 or page_num % 25 == 0:
                    print(
                        f"    {feed_type:6s}  p{page_num:<4d}  {total:>9,} records"
                        f"  ({elapsed:.1f}s)",
                        flush=True,
                    )

            result = ingestor.ingest([symbol], day, day, on_page=_on_page)
            total_events_from_api += result.events_ingested
            total_pages += result.pages_processed
            total_gaps += result.symbols_with_gaps
            total_dupes += result.duplicates_filtered

            day_events: list[NBBOQuote | Trade] = list(day_log.replay())  # type: ignore[arg-type]

            if cache is not None:
                cache.save(symbol, day, day_events)

            all_events.extend(day_events)
            day_sources.append(DaySource(
                symbol=symbol, date=day,
                source="api", event_count=len(day_events),
            ))
            print(
                f"  {symbol} {day}: {len(day_events):,} events (api, {result.pages_processed} pages)",
                flush=True,
            )

    resequenced = _resequence(all_events)

    event_log = InMemoryEventLog()
    event_log.append_batch(resequenced)

    total_event_count = len(resequenced)
    completed = frozenset(symbols)

    ingest_result = IngestResult(
        events_ingested=total_event_count,
        pages_processed=total_pages,
        symbols_with_gaps=total_gaps,
        duplicates_filtered=total_dupes,
        symbols_completed=completed,
    )

    return event_log, ingest_result, day_sources


# ── Report formatting helpers ────────────────────────────────────────


def _header(title: str, symbol: str, date_range: str) -> str:
    lines = [
        "",
        _RULE_HEAVY,
        f"  BACKTEST REPORT  |  {title}",
        f"  Symbol: {symbol}  |  Date: {date_range}",
        _RULE_HEAVY,
    ]
    return "\n".join(lines)


def _section(name: str) -> str:
    return f"\n  [{name.upper()}]"


def _kv(key: str, value: str, indent: int = 4) -> str:
    label = f"{key}"
    return f"{' ' * indent}{label:<24s}{value}"


def _sub_kv(key: str, value: str) -> str:
    label = f"{key}"
    return f"{'':6s}{label:<22s}{value}"


def _divider() -> str:
    return f"  {'- ' * 29}-"


def _money(v: Decimal) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def _pct(v: float) -> str:
    return f"{v:.2f}%"


def _ns_to_ms(ns: float) -> str:
    return f"{ns / 1_000_000:.3f} ms"


# ── Report generation ────────────────────────────────────────────────


def generate_report(
    *,
    recorder: BusRecorder,
    ingest_result: IngestResult,
    config: PlatformConfig,
    orchestrator: object,
    symbol_str: str,
    date_range: str,
    day_sources: list[DaySource] | None = None,
    data_version: str | None = None,
) -> str:
    """Build the full backtest report string."""
    from feelies.storage.trade_journal import TradeRecord

    quotes = recorder.of_type(NBBOQuote)
    features = recorder.of_type(FeatureVector)
    signals = recorder.of_type(Signal)
    orders = recorder.of_type(OrderRequest)
    acks = recorder.of_type(OrderAck)
    pos_updates = recorder.of_type(PositionUpdate)

    filled_acks = [a for a in acks if a.status == OrderAckStatus.FILLED]
    rejected_acks = [a for a in acks if a.status == OrderAckStatus.REJECTED]

    long_signals = [s for s in signals if s.direction == SignalDirection.LONG]
    short_signals = [s for s in signals if s.direction == SignalDirection.SHORT]

    warmup_features = [f for f in features if not f.warm]

    total_shares = sum(abs(a.filled_quantity) for a in filled_acks)

    # Strategy ID from first signal, or fallback
    strategy_id = signals[0].strategy_id if signals else "unknown"

    # ── P&L from position store ──────────────────────────────────
    positions = orchestrator._positions  # type: ignore[attr-defined]
    all_pos = positions.all_positions()
    starting_equity = float(orchestrator._account_equity)  # type: ignore[attr-defined]

    realized_pnl = sum(
        (p.realized_pnl for p in all_pos.values()),
        Decimal("0"),
    )
    unrealized_pnl = sum(
        (p.unrealized_pnl for p in all_pos.values()),
        Decimal("0"),
    )
    gross_pnl = realized_pnl + unrealized_pnl
    fees = sum(
        (a.fees for a in filled_acks),
        Decimal("0"),
    )
    net_pnl = gross_pnl - fees
    final_equity = Decimal(str(starting_equity)) + net_pnl
    return_pct = float(net_pnl) / starting_equity * 100.0 if starting_equity else 0.0

    # ── Trade summary ────────────────────────────────────────────
    journal = orchestrator._trade_journal  # type: ignore[attr-defined]
    records: list[TradeRecord] = list(journal.query())

    open_positions = sum(1 for p in all_pos.values() if p.quantity != 0)

    winning_pnls: list[Decimal] = []
    losing_pnls: list[Decimal] = []
    for rec in records:
        if rec.realized_pnl > 0:
            winning_pnls.append(rec.realized_pnl)
        elif rec.realized_pnl < 0:
            losing_pnls.append(rec.realized_pnl)

    total_fills = len(records)
    win_count = len(winning_pnls)
    loss_count = len(losing_pnls)
    resolved_count = win_count + loss_count
    win_rate = (win_count / resolved_count * 100.0) if resolved_count else 0.0
    avg_win = sum(winning_pnls, Decimal("0")) / len(winning_pnls) if winning_pnls else Decimal("0")
    avg_loss = sum(losing_pnls, Decimal("0")) / len(losing_pnls) if losing_pnls else Decimal("0")
    largest_win = max(winning_pnls) if winning_pnls else Decimal("0")
    largest_loss = min(losing_pnls) if losing_pnls else Decimal("0")
    pnl_per_share = float(realized_pnl) / total_shares if total_shares else 0.0

    # ── Risk ─────────────────────────────────────────────────────
    # Track per-symbol exposure and sum for portfolio-wide max.
    max_exposure = Decimal("0")
    per_symbol_exposure: dict[str, Decimal] = {}
    for pu in pos_updates:
        per_symbol_exposure[pu.symbol] = abs(Decimal(str(pu.quantity)) * pu.avg_price)
        total_exposure = sum(per_symbol_exposure.values())
        if total_exposure > max_exposure:
            max_exposure = total_exposure
    max_exposure_pct = float(max_exposure) / starting_equity * 100.0 if starting_equity else 0.0

    # Drawdown: track net equity curve from position updates.
    # Net equity = starting + gross_pnl - cumulative_fees.
    peak_equity = Decimal(str(starting_equity))
    max_drawdown = Decimal("0")
    per_symbol_pnl: dict[str, Decimal] = {}
    per_symbol_fees: dict[str, Decimal] = {}
    for pu in pos_updates:
        per_symbol_pnl[pu.symbol] = pu.realized_pnl
        per_symbol_fees[pu.symbol] = pu.cumulative_fees
        current_equity = (
            Decimal(str(starting_equity))
            + sum(per_symbol_pnl.values())
            - sum(per_symbol_fees.values())
        )
        if current_equity > peak_equity:
            peak_equity = current_equity
        dd = current_equity - peak_equity
        if dd < max_drawdown:
            max_drawdown = dd
    max_dd_pct = float(max_drawdown) / starting_equity * 100.0 if starting_equity else 0.0

    kill_switch = orchestrator._kill_switch  # type: ignore[attr-defined]
    ks_status = "ACTIVATED" if kill_switch.is_active else "NOT ACTIVATED"

    # ── Performance metrics ──────────────────────────────────────
    metrics: InMemoryMetricCollector = orchestrator._metrics  # type: ignore[attr-defined]

    tick_summary = metrics.get_summary("kernel", "tick_to_decision_latency_ns")
    feat_summary = metrics.get_summary("kernel", "feature_compute_ns")
    sig_summary = metrics.get_summary("kernel", "signal_evaluate_ns")

    avg_tick_ns = tick_summary.mean if tick_summary else 0.0
    max_tick_ns = tick_summary.max_value if tick_summary else 0.0
    avg_feat_ns = feat_summary.mean if feat_summary else 0.0
    avg_sig_ns = sig_summary.mean if sig_summary else 0.0

    # Locate the originating quote for the max tick-to-decision spike.
    # Why this matters: a single 1.3-second outlier in a 974K-quote run is
    # almost always (a) the first post-warmup tick, (b) a GC pause, or
    # (c) a real microstructure event (auction/halt/cross). Knowing which
    # quote caused it converts an "alarming number" into an actionable line
    # in the data. Cheap because we already have every MetricEvent in
    # `recorder` and every quote in `quotes`.
    max_tick_meta: dict[str, object] | None = None
    p95_tick_ns: float | None = None
    p99_tick_ns: float | None = None
    if tick_summary:
        tick_metrics = [
            e for e in recorder.of_type(MetricEvent)
            if e.name == "tick_to_decision_latency_ns"
        ]
        if tick_metrics:
            values = sorted(e.value for e in tick_metrics)
            p95_tick_ns = values[min(len(values) - 1, int(0.95 * len(values)))]
            p99_tick_ns = values[min(len(values) - 1, int(0.99 * len(values)))]

            spike = max(tick_metrics, key=lambda e: e.value)
            quote_by_cid = {q.correlation_id: q for q in quotes}
            originating = quote_by_cid.get(spike.correlation_id)
            tick_index_by_cid = {
                q.correlation_id: i for i, q in enumerate(quotes, start=1)
            }
            tick_idx = tick_index_by_cid.get(spike.correlation_id)
            max_tick_meta = {
                "value_ns":          spike.value,
                "correlation_id":    spike.correlation_id,
                "kernel_sequence":   spike.sequence,
                "tick_index":        tick_idx,
                "n_total_ticks":     len(quotes),
                "symbol":            originating.symbol if originating else "?",
                "exchange_ts_ns":    (originating.exchange_timestamp_ns
                                      if originating else None),
                "is_first_5_pct":    (tick_idx is not None
                                      and tick_idx <= max(1, len(quotes) // 20)),
            }

    # ── Assemble report ──────────────────────────────────────────
    lines: list[str] = []
    lines.append(_header(strategy_id, symbol_str, date_range))

    # Ingestion
    lines.append(_section("Data Ingestion"))
    lines.append(_kv("Events ingested", f"{ingest_result.events_ingested:,}"))
    lines.append(_kv("Pages processed", f"{ingest_result.pages_processed}"))
    lines.append(_kv("Symbols with gaps", f"{ingest_result.symbols_with_gaps}"))
    lines.append(_kv("Duplicates filtered", f"{ingest_result.duplicates_filtered}"))
    if day_sources:
        lines.append("")
        for ds in day_sources:
            lines.append(_sub_kv(f"{ds.symbol} {ds.date}", f"{ds.event_count:,} ({ds.source})"))

    lines.append(_divider())

    # Pipeline
    lines.append(_section("Signal Pipeline"))
    lines.append(_kv("Quotes processed", f"{len(quotes):,}"))
    lines.append(_kv("Feature vectors", f"{len(features):,}"))
    lines.append(_kv("Warm-up ticks", f"{len(warmup_features)}"))
    lines.append(_kv("Signals emitted", f"{len(signals):,}"))
    lines.append(_sub_kv("Long", f"{len(long_signals):,}"))
    lines.append(_sub_kv("Short", f"{len(short_signals):,}"))

    lines.append(_divider())

    # Execution
    lines.append(_section("Execution"))
    lines.append(_kv("Orders submitted", f"{len(orders):,}"))
    lines.append(_kv("Orders filled", f"{len(filled_acks):,}"))
    lines.append(_kv("Orders rejected", f"{len(rejected_acks):,}"))
    lines.append(_kv("Total shares traded", f"{total_shares:,}"))

    lines.append(_divider())

    # P&L
    lines.append(_section("P&L"))
    lines.append(_kv("Starting equity", _money(Decimal(str(starting_equity)))))
    lines.append(_kv("Gross P&L", _money(gross_pnl)))
    lines.append(_sub_kv("Realized", _money(realized_pnl)))
    lines.append(_sub_kv("Unrealized", _money(unrealized_pnl)))
    lines.append(_kv("Fees", _money(fees)))
    lines.append(_kv("Net P&L", _money(net_pnl)))
    lines.append(_kv("Final equity", _money(final_equity)))
    lines.append(_kv("Return", _pct(return_pct)))

    lines.append(_divider())

    # Trade summary
    lines.append(_section("Trade Analysis"))
    lines.append(_kv("Total fills", f"{total_fills:,}"))
    lines.append(_kv("Closing fills", f"{resolved_count:,}"))
    lines.append(_kv("Open positions", f"{open_positions}"))
    win_rate_str = f"{win_rate:.1f}% ({win_count}/{resolved_count})" if resolved_count else "N/A"
    lines.append(_kv("Win rate", win_rate_str))
    lines.append(_kv("Avg winner", _money(avg_win)))
    lines.append(_kv("Avg loser", _money(avg_loss)))
    lines.append(_kv("Largest win", _money(largest_win)))
    lines.append(_kv("Largest loss", _money(largest_loss)))
    lines.append(_kv("P&L per share", f"${pnl_per_share:.4f}"))

    lines.append(_divider())

    # Risk
    lines.append(_section("Risk"))
    lines.append(_kv("Max exposure", f"{_money(max_exposure)} ({_pct(max_exposure_pct)})"))
    lines.append(_kv("Max drawdown", f"{_money(max_drawdown)} ({_pct(max_dd_pct)})"))
    lines.append(_kv("Kill switch", ks_status))

    lines.append(_divider())

    # Performance
    lines.append(_section("Latency"))
    lines.append(_kv("Avg tick-to-decision", _ns_to_ms(avg_tick_ns)))
    if p95_tick_ns is not None:
        lines.append(_kv("p95 tick-to-decision", _ns_to_ms(p95_tick_ns)))
    if p99_tick_ns is not None:
        lines.append(_kv("p99 tick-to-decision", _ns_to_ms(p99_tick_ns)))
    lines.append(_kv("Max tick-to-decision", _ns_to_ms(max_tick_ns)))
    if max_tick_meta is not None:
        ts_ns = max_tick_meta.get("exchange_ts_ns")
        ts_str = ""
        if isinstance(ts_ns, int):
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
            ts_str = dt.strftime("%H:%M:%S.%f")[:-3] + " UTC"
        warmup_flag = "  [warm-up]" if max_tick_meta.get("is_first_5_pct") else ""
        lines.append(_sub_kv(
            "spike origin",
            f"{max_tick_meta['symbol']} tick "
            f"#{max_tick_meta['tick_index']}/{max_tick_meta['n_total_ticks']:,}"
            + (f" @ {ts_str}" if ts_str else "")
            + warmup_flag,
        ))
        lines.append(_sub_kv(
            "correlation_id",
            str(max_tick_meta["correlation_id"]),
        ))
    lines.append(_kv("Avg feature compute", _ns_to_ms(avg_feat_ns)))
    lines.append(_kv("Avg signal evaluate", _ns_to_ms(avg_sig_ns)))

    # TCA (transaction cost analysis)
    if records:
        from feelies.forensics.decay_detector import DecayDetector
        tca = DecayDetector().analyze_fills(records)

        lines.append(_divider())
        lines.append(_section("TCA (Transaction Cost Analysis)"))
        lines.append(_kv("Trades analysed", f"{tca.trade_count:,}"))
        lines.append(_kv("Mean cost", f"{tca.mean_cost_bps:.2f} bps"))
        lines.append(_kv("p95 cost", f"{tca.p95_cost_bps:.2f} bps"))
        lines.append(_kv("Mean edge", f"{tca.mean_edge_bps:.2f} bps"))
        lines.append(_kv("p95 edge", f"{tca.p95_edge_bps:.2f} bps"))
        lines.append(_kv("Positive-edge trades", f"{tca.pct_positive_edge:.1f}%"))
        lines.append(_kv("Edge covers 2× cost", f"{tca.pct_edge_covers_cost:.1f}%"))
        if tca.trade_count >= 50:
            lines.append(_kv("Rolling-50 mean edge", f"{tca.rolling_50_mean_edge_bps:.2f} bps"))
        if tca.trade_count >= 200:
            lines.append(_kv("Rolling-200 mean edge", f"{tca.rolling_200_mean_edge_bps:.2f} bps"))
        lines.append("")
        hist = tca.size_histogram
        lines.append(_kv("Order-size histogram", ""))
        for bucket, count in hist.items():
            pct = count / tca.trade_count * 100.0 if tca.trade_count else 0.0
            lines.append(_sub_kv(f"  {bucket} shares", f"{count} ({pct:.1f}%)"))

        # Edge-decay check
        decay_signals = DecayDetector().detect_edge_decay(strategy_id, records)
        if decay_signals:
            lines.append("")
            lines.append(_kv("EDGE DECAY DETECTED", f"{len(decay_signals)} signal(s)"))
            for ds in decay_signals:
                lines.append(_sub_kv("  Strategy", ds.strategy_id))
                lines.append(_sub_kv("  Hist edge", f"{ds.expected:.2f} bps"))
                lines.append(_sub_kv("  Recent edge", f"{ds.realized:.2f} bps"))
                lines.append(_sub_kv("  Z-score", f"{ds.z_score:.2f}"))

    # Three-hash parity contract — pnl_hash, config_hash, parity_hash.
    # Grok's VERIFY(signal_id, local_pnl_hash, local_config_hash) consumes both.
    pnl_hash = compute_parity_hash(orchestrator)
    config_hash = compute_config_hash(config)
    parity_hash = compute_combined_parity_hash(pnl_hash, config_hash)
    resolved_data_version = data_version if data_version is not None else "unknown"
    artifact_id = compute_artifact_id(
        orchestrator, config, data_version=resolved_data_version,
    )
    lines.append(_divider())
    lines.append(_section("Parity"))
    lines.append(_kv("Trade count", f"{len(records)}"))
    lines.append(_kv("pnl_hash    (trades)", pnl_hash))
    lines.append(_kv("config_hash (cfg)",    config_hash))
    lines.append(_kv("parity_hash (both)",   parity_hash))
    lines.append(_kv("engine_version",       ENGINE_VERSION))
    lines.append(_kv("data_version",         resolved_data_version))
    lines.append(_kv("artifact_id (B-PROMO-04)", artifact_id))

    lines.append("")
    lines.append(_RULE_HEAVY)
    lines.append("")

    return "\n".join(lines)


# ── Parity hashes (three-hash contract — see grok/05_EXPORT_LIFECYCLE.md) ──


def compute_parity_hash(orchestrator: object) -> str:
    """SHA-256 over the ordered trade sequence.

    Canonical format shared with the Grok REPL (grok/04_BACKTEST_EXECUTION.md).
    Both sides MUST produce identical hashes for the same alpha + date range
    + same platform.yaml.
    """
    from feelies.storage.trade_journal import TradeRecord

    journal = orchestrator._trade_journal  # type: ignore[attr-defined]
    records: list[TradeRecord] = list(journal.query())
    trade_seq = [
        {
            "order_id": str(r.order_id),
            "symbol": str(r.symbol),
            "side": str(r.side).split(".")[-1],
            "quantity": int(r.filled_quantity),
            "fill_price": str(r.fill_price),
            "realized_pnl": str(r.realized_pnl),
        }
        for r in records
    ]
    payload = json.dumps(trade_seq, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_config_hash(config: PlatformConfig) -> str:
    """SHA-256 of the resolved PlatformConfig snapshot.

    Identical to ``PlatformConfig.snapshot().checksum``. Re-exposed here so
    callers don't need to import ``ConfigSnapshot`` to obtain it.
    """
    return config.snapshot().checksum


def compute_combined_parity_hash(pnl_hash: str, config_hash: str) -> str:
    """SHA-256(pnl_hash + ":" + config_hash).

    Single comparator that binds the trade sequence to the configuration
    that produced it. Mirrors the Grok REPL's ``_compute_combined_parity_hash``
    in ``grok/04_BACKTEST_EXECUTION.md``.
    """
    return hashlib.sha256(f"{pnl_hash}:{config_hash}".encode("utf-8")).hexdigest()


# Bumped whenever the engine's externally-observable contract changes
# (event schema, fill semantics, hash format). Promotion artifacts produced
# under different ``ENGINE_VERSION`` strings are not directly comparable.
ENGINE_VERSION = "0.1.0"


def compute_artifact_id(
    orchestrator: object,
    config: PlatformConfig,
    *,
    data_version: str,
) -> str:
    """Deterministic artifact id for the run (audit B-PROMO-04).

    Combines four orthogonal axes that together identify a backtest run:

      - ``strategy_version``: ``alpha_id@manifest.version`` for every
        active alpha, sorted. Picks up code-level alpha changes.
      - ``config_version``: the resolved ``PlatformConfig.version``
        (the ``version:`` field of ``platform.yaml``).
      - ``data_version``: caller-supplied identifier of the input
        dataset. Demo mode hashes the static tick payload; live mode
        encodes ``symbols + date range``.
      - ``engine_version``: the ``ENGINE_VERSION`` constant above.

    Same inputs produce the same id; any drift across consecutive
    audits flags an unintentional change in the artifact contract.
    """
    registry = getattr(orchestrator, "_alpha_registry", None)
    strategy_payload: list[str] = []
    if registry is not None:
        for aid in sorted(registry.alpha_ids()):
            alpha = registry.get(aid)
            strategy_payload.append(f"{aid}@{alpha.manifest.version}")

    payload = json.dumps(
        {
            "strategy_version": strategy_payload,
            "config_version": config.version,
            "data_version": data_version,
            "engine_version": ENGINE_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _live_data_version(symbols: list[str], date_range: str) -> str:
    """Stable identifier for a live backtest's input dataset.

    Encodes the (symbol set, date range) pair. Two runs over the same
    universe and dates collide; a different universe or window does not.
    """
    payload = json.dumps(
        {"symbols": sorted(symbols), "date_range": date_range},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "live:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ── Verification checks ─────────────────────────────────────────────


def run_verification(
    *,
    recorder: BusRecorder,
    ingest_result: IngestResult,
    orchestrator: object,
) -> list[tuple[str, bool, str]]:
    """Run moderate verification criteria. Returns (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []

    # 1. Events ingested > 0
    n = ingest_result.events_ingested
    results.append(("Events ingested", n > 0, f"{n} events"))

    # 2. Signals fired > 0
    sigs = recorder.of_type(Signal)
    results.append(("Signals fired", len(sigs) > 0, f"{len(sigs)} signals"))

    # 3. Fills occurred >= 1
    acks = recorder.of_type(OrderAck)
    fills = [a for a in acks if a.status == OrderAckStatus.FILLED]
    results.append(("Fills occurred", len(fills) >= 1, f"{len(fills)} fills"))

    # 4. P&L computable
    positions = orchestrator._positions  # type: ignore[attr-defined]
    all_pos = positions.all_positions()
    has_pnl = any(p.realized_pnl is not None for p in all_pos.values()) if all_pos else False
    # Also pass if no positions were taken (realized_pnl stays at 0)
    if not all_pos:
        has_pnl = True  # vacuously true — no trades means no PnL to compute
    results.append(("P&L computable", has_pnl, "realized_pnl tracked" if has_pnl else "missing"))

    # 5. Trade journal >= 1
    journal = orchestrator._trade_journal  # type: ignore[attr-defined]
    n_records = len(journal)
    results.append(("Trade journal", n_records >= 1, f"{n_records} records"))

    # 6. Macro state == READY
    macro = orchestrator.macro_state
    results.append(("Macro state", macro == MacroState.READY, macro.name))

    # 7. Kill switch not activated
    ks = orchestrator._kill_switch  # type: ignore[attr-defined]
    results.append(("Kill switch", not ks.is_active, "INACTIVE" if not ks.is_active else "ACTIVE"))

    return results


def print_verification(results: list[tuple[str, bool, str]]) -> bool:
    """Print verification table. Returns True if all passed."""
    print(_section("Verification"))
    all_passed = True
    for name, passed, detail in results:
        tag = "PASS" if passed else "FAIL"
        print(f"    [{tag}]  {name:<22s}{detail}")
        if not passed:
            all_passed = False
    print()
    passed_count = sum(1 for _, p, _ in results if p)
    total = len(results)
    if all_passed:
        print(f"    Result: {passed_count}/{total} checks passed.")
    else:
        print(f"    Result: {passed_count}/{total} checks passed. Review failures above.")
    print()
    return all_passed


# ── Main ─────────────────────────────────────────────────────────────


def _force_utf8_console() -> None:
    """Make stdout/stderr emit UTF-8 so unicode glyphs (×, σ, →, …) print
    correctly on Windows consoles whose default code page is cp1252.

    Best-effort: silently no-op on streams that don't support reconfigure
    (e.g. when redirected through a non-text wrapper, or on Python < 3.7).
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_console()
    args = parse_args(argv)

    # Workstream-D update — the synthetic ``--demo`` path was retired
    # with the ``trade_cluster_drift`` LEGACY reference alpha.  The
    # live path below is now the only entry point; for a no-API smoke
    # test of orchestration, run ``pytest tests/integration/
    # test_phase4_e2e.py`` directly.
    if not args.date:
        print(
            "ERROR: --date is required (the synthetic --demo mode was "
            "retired with workstream D.2; use the integration suite "
            "for no-API-key smoke tests)",
            file=sys.stderr,
        )
        return 1

    # 1. Load .env
    try:
        from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]
        load_dotenv()
    except ImportError:
        pass  # dotenv is optional; env vars can be set directly

    api_key = os.getenv("MASSIVE_API_KEY")
    if not api_key:
        print(
            "ERROR: MASSIVE_API_KEY not set.\n"
            "Set it in your environment or in a .env file.\n"
            "  export MASSIVE_API_KEY=your_key_here",
            file=sys.stderr,
        )
        return 1

    # 2. Load platform config
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        return 1

    config = PlatformConfig.from_yaml(config_path)

    # Apply CLI cost stress multiplier if provided
    if args.stress_cost != 1.0:
        from dataclasses import replace as _replace
        config = _replace(config, cost_stress_multiplier=args.stress_cost)

    # Override symbols if provided via CLI
    if args.symbol:
        config.symbols = frozenset(s.upper() for s in args.symbol)

    symbols = sorted(config.symbols)
    if not symbols:
        print("ERROR: No symbols specified (use --symbol or set in platform.yaml)", file=sys.stderr)
        return 1

    start_date = args.date
    end_date = args.end_date or start_date
    date_range = start_date if start_date == end_date else f"{start_date} to {end_date}"
    symbol_str = ", ".join(symbols)
    run_t0 = time.monotonic()

    print(f"\n  Backtest: {symbol_str}  |  {date_range}", flush=True)
    print(f"  {_RULE_LIGHT}", flush=True)

    # ── Phase 1: Data ingestion ───────────────────────────────
    step_t = _step("Loading market data")
    print(flush=True)

    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    no_cache: bool = args.no_cache

    try:
        event_log, ingest_result, day_sources = ingest_data(
            api_key, symbols, start_date, end_date,
            cache_dir=cache_dir, no_cache=no_cache,
        )
    except ImportError as exc:
        print(
            f"\n  ERROR: {exc}\n"
            "  Install the massive extra: pip install 'feelies[massive]'",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"\n  ERROR: Ingestion failed: {exc}", file=sys.stderr)
        return 1

    cache_days = sum(1 for ds in day_sources if ds.source == "cache")
    api_days = sum(1 for ds in day_sources if ds.source == "api")
    dt = time.monotonic() - step_t
    src = []
    if api_days:
        src.append(f"{api_days}d API")
    if cache_days:
        src.append(f"{cache_days}d cache")
    src_str = ", ".join(src)
    print(
        f"  OK - {ingest_result.events_ingested:,} events ({src_str}) [{dt:.1f}s]",
        flush=True,
    )

    # ── Phase 2: Platform bootstrap ───────────────────────────
    step_t = _step("Composing platform (alphas, engines, risk)")
    orchestrator, config = build_platform(config, event_log=event_log)
    alpha_count = len(orchestrator._alpha_registry) if orchestrator._alpha_registry else 0  # type: ignore[attr-defined]
    dt = time.monotonic() - step_t
    print(f"  OK - {alpha_count} alpha(s) registered [{dt:.1f}s]", flush=True)

    # ── Phase 3: Attach recorder ──────────────────────────────
    recorder = BusRecorder()
    orchestrator._bus.subscribe_all(recorder)  # type: ignore[attr-defined]

    # ── Phase 4: Boot ─────────────────────────────────────────
    step_t = _step("Booting orchestrator (integrity checks, warm-start)")
    orchestrator.boot(config)
    macro = orchestrator.macro_state
    dt = time.monotonic() - step_t
    print(f"  OK - macro state: {macro.name} [{dt:.1f}s]", flush=True)

    if macro != MacroState.READY:
        print(f"  ERROR: Boot failed — macro state is {macro.name}, expected READY",
              file=sys.stderr)
        return 1

    # ── Phase 5: Run pipeline ─────────────────────────────────
    n_quotes = sum(1 for e in event_log.replay() if isinstance(e, NBBOQuote))
    progress = _ProgressReporter(total_events=n_quotes, interval=100_000)
    orchestrator._bus.subscribe(NBBOQuote, progress)  # type: ignore[attr-defined]

    step_t = _step(f"Replaying {n_quotes:,} quotes through pipeline")
    print(flush=True)
    orchestrator.run_backtest()
    dt = time.monotonic() - step_t
    print(f"  Pipeline complete - {progress.summary()}", flush=True)

    # ── Phase 6: Report ───────────────────────────────────────
    step_t = _step("Generating report")
    report = generate_report(
        recorder=recorder,
        ingest_result=ingest_result,
        config=config,
        orchestrator=orchestrator,
        symbol_str=symbol_str,
        date_range=date_range,
        day_sources=day_sources,
        data_version=_live_data_version(symbols, date_range),
    )
    dt = time.monotonic() - step_t
    print(f"  OK [{dt:.1f}s]", flush=True)
    print(report)

    # ── Phase 7: Verification ─────────────────────────────────
    results = run_verification(
        recorder=recorder,
        ingest_result=ingest_result,
        orchestrator=orchestrator,
    )
    all_passed = print_verification(results)

    total_elapsed = time.monotonic() - run_t0
    print(f"  Total elapsed: {total_elapsed:.1f}s\n", flush=True)

    if args.emit_fills_jsonl:
        _emit_fills_jsonl(recorder)
    _emit_phase2_jsonl(args, recorder)

    return 0 if all_passed else 2


if __name__ == "__main__":
    sys.exit(main())
