"""Backtest runner — connects real Massive data to the platform pipeline.

Usage:
    python scripts/run_backtest.py --symbol AAPL --date 2024-01-15
    python scripts/run_backtest.py --symbol AAPL --date 2024-01-15 --end-date 2024-01-16
    python scripts/run_backtest.py --symbol AAPL --date 2026-04-08 --trace-signal-orders
    python scripts/run_backtest.py --config platform.yaml  # uses symbols from config

Workstream-D update — the ``--demo`` synthetic-tick mode was retired
along with the ``trade_cluster_drift`` LEGACY reference alpha (D.2).
For a no-API-key smoke test of the orchestration pipeline use the
end-to-end suite directly: ``pytest tests/integration/test_phase4_e2e.py``.

Offline replay from gzipped JSONL disk cache (no Massive API key)::

    Import and call ``main_cache_replay`` from this module (see
    ``parse_cache_replay_args``).  Populate cache first with a normal API
    run using ``--cache-dir``; see ``feelies.storage.cache_replay``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_TZ_ET = ZoneInfo("America/New_York")
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Sequence, TypeVar

from feelies.bootstrap import build_platform

if TYPE_CHECKING:
    from feelies.execution.portfolio_netter import NetDivergence
    from feelies.risk.edge_weighted_sizer import SizeDivergence
from feelies.cli.env import MASSIVE_API_KEY_ERROR, load_dotenv_optional, massive_api_key_from_env
from feelies.harness.backtest_cli import (
    ConfigNotFoundError,
    add_backtest_api_arguments,
    add_common_backtest_arguments,
    apply_backtest_cli_overrides,
    disable_backtest_jsonl_emit_flags,
    load_platform_config,
    resolve_backtest_symbols,
)
from feelies.harness.backtest_jsonl import (
    _emit_fills_jsonl,
    _emit_net_divergence_jsonl,
    _emit_size_divergence_jsonl,
    _emit_phase2_jsonl,
)
from feelies.harness.backtest_prep import (
    BacktestEventLogPrep,
    QuoteReplayObserver,
    prepare_backtest_event_log,
)
from feelies.harness.backtest_report import (
    compute_combined_parity_hash,
    compute_config_hash,
    compute_parity_hash,
    format_section,
    generate_report,
    live_data_version,
    run_verification,
)
from feelies.kernel.orchestrator import Orchestrator
from feelies.kernel.signal_order_trace import (
    SignalOrderTraceRow,
    print_signal_order_trace,
)
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    CrossSectionalContext,
    Event,
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
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.ingestion.data_integrity import DataHealth
from feelies.ingestion.ingest_health import terminal_symbol_health_rows
from feelies.ingestion.massive_ingestor import IngestResult
from feelies.kernel.macro import MacroState
from feelies.storage.cache_replay import IngestDayMeta, iter_calendar_dates
from feelies.storage.disk_event_cache import DiskEventCache
from feelies.storage.event_resequence import resequence_event_list
from feelies.storage.memory_event_log import InMemoryEventLog

T = TypeVar("T", bound=Event)

# ── Report layout constants ──────────────────────────────────────────

_W = 62
_RULE_HEAVY = "=" * _W
_RULE_LIGHT = "-" * _W


def _scan_event_log(
    event_log: InMemoryEventLog,
) -> tuple[int | None, int, int]:
    """First replay timestamp, quote count, and trade count in one pass."""
    first_ts: int | None = None
    n_quotes = 0
    n_trades = 0
    for ev in event_log.replay():
        if first_ts is None:
            first_ts = int(ev.timestamp_ns)
        if isinstance(ev, NBBOQuote):
            n_quotes += 1
        elif isinstance(ev, Trade):
            n_trades += 1
    return first_ts, n_quotes, n_trades


def _enforce_ingest_event_mix(
    config: PlatformConfig,
    event_log: InMemoryEventLog,
    *,
    source_label: str,
    n_quotes: int | None = None,
    n_trades: int | None = None,
) -> int:
    """Apply ``backtest_reject_zero_ingest_events`` per event type.

    Returns ``0`` on success or ``1`` if the run should abort.  Logs to
    stderr with the same shape as the legacy total-only check.

    When ``n_quotes`` / ``n_trades`` are supplied (from a fused pre-replay
    scan), the event log is not rescanned — pass the prepared log (post-RTH
    filter) as ``event_log`` so callers stay aligned with the counts.
    """
    if not config.backtest_reject_zero_ingest_events:
        return 0
    if n_quotes is None or n_trades is None:
        _first_ts, n_quotes, n_trades = _scan_event_log(event_log)
    if n_quotes == 0 and n_trades == 0:
        print(
            f"\n  ERROR: Zero events {source_label} — "
            "backtest_reject_zero_ingest_events is enabled in platform config.",
            file=sys.stderr,
        )
        return 1
    if n_quotes == 0:
        print(
            f"\n  ERROR: Zero NBBOQuote events {source_label} "
            f"(trades={n_trades:,}) — backtest_reject_zero_ingest_events "
            "rejects quote-starved feeds because quote-driven sensors "
            "(spread_z_30d, ofi_ewma, micro_price, ...) cannot warm.",
            file=sys.stderr,
        )
        return 1
    if n_trades == 0:
        # Only fail when at least one configured sensor consumes Trade.
        # A pure-quote universe is legitimate when no trade-driven sensor
        # is registered.
        trade_consumers = tuple(
            spec.sensor_id
            for spec in (config.sensor_specs or ())
            if "Trade" in (getattr(spec, "subscribes_to", ()) or ())
        )
        if trade_consumers:
            print(
                f"\n  ERROR: Zero Trade events {source_label} "
                f"(quotes={n_quotes:,}) — sensors {list(trade_consumers)} "
                "subscribe to Trade and would never warm. "
                "backtest_reject_zero_ingest_events is enabled.",
                file=sys.stderr,
            )
            return 1
    return 0


def _ensure_backtest_session_anchor(
    config: PlatformConfig,
    *,
    first_event_ts_ns: int | None,
) -> PlatformConfig:
    """Set ``session_open_ns`` when unset so bootstrap skips H10 (audit).

    *first_event_ts_ns* must be the first event in replay order — identical
    anchor to :class:`HorizonScheduler` auto-binding when ordering matches.
    """
    if config.mode != OperatingMode.BACKTEST or config.session_open_ns is not None:
        return config
    if first_event_ts_ns is None:
        return config
    return replace(config, session_open_ns=first_event_ts_ns)


# ── BusRecorder (same pattern as test_backtest_e2e.py) ───────────────


@dataclass
class BusRecorder:
    # ``events`` (flat list of all events) has been removed: it accumulated
    # ~20 M pointers by tick #913 K and triggered a 30–50 ms Windows
    # VirtualAlloc/copy realloc at a deterministic threshold.  Nothing in
    # the report path reads ``recorder.events``; all consumers use
    # ``recorder.of_type(X)`` which goes through ``by_type``.
    by_type: dict[type, list[Event]] = field(default_factory=lambda: defaultdict(list))
    # Event types to skip storing entirely.  Pass ``{SensorReading}`` when
    # ``--emit-sensor-readings-jsonl`` is not requested: that eliminates a
    # second large list (~10 M entries) whose realloc can also spike latency.
    skip_types: frozenset[type] = field(default_factory=frozenset)

    def __call__(self, event: Event) -> None:
        t = type(event)
        if t not in self.skip_types:
            self.by_type[t].append(event)

    def of_type(self, t: type[T]) -> list[T]:
        return self.by_type[t]  # type: ignore[return-value]


# ── Progress reporter ────────────────────────────────────────────────


def _step(msg: str, t0: float | None = None) -> float:
    """Print a progress step with optional elapsed time from a prior step.

    Each step is emitted as a **full line** (trailing newline).  Historically
    ``end=""`` glued the next ``print``/log/progress output onto the same
    physical line as ``Booting …`` / ``Replaying …``, which produced scrambled
    CLI output when ``logging`` (stdout) or ``QuoteReplayObserver`` interleaved.
    """
    now = time.monotonic()
    if t0 is not None:
        dt = now - t0
        print(f"  OK ({dt:.1f}s)", flush=True)
    print(f"  {msg} ...", flush=True)
    return now


# ── CLI ──────────────────────────────────────────────────────────────


# Backward-compatible alias for tests and report helpers that import ``DaySource``.
DaySource = IngestDayMeta


def _load_backtest_config(args: argparse.Namespace) -> PlatformConfig | None:
    """Load platform YAML and apply CLI stress / symbol overrides."""
    try:
        config = load_platform_config(args.config)
    except ConfigNotFoundError as exc:
        print(f"ERROR: Config file not found: {exc.path}", file=sys.stderr)
        return None
    end_date = getattr(args, "end_date", None) or getattr(args, "date", None)
    return apply_backtest_cli_overrides(
        config,
        inv12_stress=args.inv12_stress,
        stress_cost=args.stress_cost,
        symbols=args.symbol,
        start_date=getattr(args, "date", None),
        end_date=end_date,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run a historical backtest with real Massive L1 data.",
    )
    add_backtest_api_arguments(p)
    return p.parse_args(argv)


def parse_cache_replay_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI for :func:`main_cache_replay` — disk cache only, no API."""
    p = argparse.ArgumentParser(
        description=(
            "Replay a backtest using only gzipped JSONL cache files "
            "(see DiskEventCache layout under ~/.feelies/cache by default)."
        ),
    )
    add_common_backtest_arguments(p)
    p.add_argument("--date", type=str, required=True, help="YYYY-MM-DD")
    args = p.parse_args(argv)
    disable_backtest_jsonl_emit_flags(args)
    return args


def ingest_data(
    api_key: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
    *,
    cache_dir: Path | None = None,
    no_cache: bool = False,
    enable_rest_sequence_gap_detection: bool = False,
) -> tuple[InMemoryEventLog, IngestResult, list[DaySource]]:
    """Download historical data with per-day cache and parallel download."""
    from feelies.ingestion.massive_ingestor import MassiveHistoricalIngestor
    from feelies.ingestion.massive_normalizer import MassiveNormalizer

    cache: DiskEventCache | None = None
    if not no_cache:
        resolved_dir = cache_dir or Path.home() / ".feelies" / "cache"
        cache = DiskEventCache(resolved_dir)

    dates = iter_calendar_dates(start_date, end_date)
    multi_day_or_symbol = len(symbols) * len(dates) > 1
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
                    manifest = cache.read_manifest(symbol, day)
                    ing_h = manifest.get("ingestion_health") if manifest else None
                    all_events.extend(loaded)
                    day_sources.append(
                        DaySource(
                            symbol=symbol,
                            date=day,
                            source="cache",
                            event_count=len(loaded),
                            ingestion_health=(str(ing_h) if ing_h is not None else None),
                        )
                    )
                    if multi_day_or_symbol:
                        print(
                            f"  {symbol} {day}: {len(loaded):,} events (cache)",
                            flush=True,
                        )
                    continue

            clock = SimulatedClock(start_ns=1_000_000_000)
            normalizer = MassiveNormalizer(
                clock,
                enable_rest_sequence_gap_detection=enable_rest_sequence_gap_detection,
            )
            day_log = InMemoryEventLog()

            ingestor = MassiveHistoricalIngestor(
                api_key=api_key,
                normalizer=normalizer,
                event_log=day_log,
                clock=clock,
            )

            print(f"  {symbol} {day}: fetching from API ...", flush=True)

            def _on_page(
                feed_type: str,
                page_num: int,
                total: int,
                elapsed: float,
                _sym: str = symbol,
                _day: str = day,
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

            sym_health = normalizer.all_health().get(symbol)
            ing_health_str = (
                "HEALTHY"
                if sym_health == DataHealth.HEALTHY
                else (sym_health.name if sym_health is not None else "UNKNOWN")
            )
            if cache is not None:
                cache.save(
                    symbol,
                    day,
                    day_events,
                    ingestion_health=ing_health_str,
                )

            all_events.extend(day_events)
            day_sources.append(
                DaySource(
                    symbol=symbol,
                    date=day,
                    source="api",
                    event_count=len(day_events),
                    ingestion_health=ing_health_str,
                )
            )
            if multi_day_or_symbol:
                print(
                    f"  {symbol} {day}: {len(day_events):,} events "
                    f"(api, {result.pages_processed} pages)",
                    flush=True,
                )

    resequenced = resequence_event_list(all_events)

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


def _warn_if_unhealthy_manifest_days(day_sources: Sequence[DaySource]) -> None:
    """Advisory banner when ingest/cache metadata reports degraded health."""
    bad: list[DaySource] = []
    for ds in day_sources:
        h = ds.ingestion_health
        if h is not None and h != "HEALTHY":
            bad.append(ds)
    if not bad:
        return
    lines = [f"    {ds.symbol} {ds.date}: {ds.ingestion_health!r}" for ds in bad[:20]]
    extra = "" if len(bad) <= 20 else f"\n    ... and {len(bad) - 20} more day(s)"
    print(
        "\n  WARNING: One or more loaded days have ingestion_health != HEALTHY.\n"
        "  Replay continues; set require_healthy_disk_cache_manifests: true or "
        "backtest_enforce_ingest_terminal_health: true (after ingest attaches rows) "
        "to fail boot, or fix/re-ingest degraded days.\n" + "\n".join(lines) + extra + "\n",
        file=sys.stderr,
        flush=True,
    )


def _attach_disk_cache_health_rows(
    config: PlatformConfig,
    day_sources: Sequence[DaySource],
) -> PlatformConfig:
    """Fold per-day ingestion_health into config for offline integrity gates."""
    from dataclasses import replace as _cfg_replace

    rows = tuple((ds.symbol, ds.date, ds.ingestion_health or "UNKNOWN") for ds in day_sources)
    return _cfg_replace(config, disk_cache_ingestion_health_rows=rows)


def _attach_day_source_provenance(
    config: PlatformConfig,
    symbols: list[str],
    day_sources: Sequence[DaySource],
) -> PlatformConfig:
    """Attach per-day manifest rows plus worst-case per-symbol terminal health."""
    cfg = _attach_disk_cache_health_rows(config, day_sources)
    return replace(
        cfg,
        ingest_terminal_symbol_health=terminal_symbol_health_rows(symbols, day_sources),
    )


# ── Verification checks ─────────────────────────────────────────────


def print_verification(results: list[tuple[str, bool, str]]) -> bool:
    """Print verification table. Returns True if all passed."""
    print(format_section("Verification"))
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


def _configure_logging_for_cli() -> None:
    """Send ``logging`` output to stdout (keep WARNING+ only).

    Bootstrap emits H10 and other notices via ``logger.warning``, which
    defaults to stderr.  PowerShell wraps stderr from Python as
    ``NativeCommandError``, splitting log lines across ``print`` progress
    output.  Stdout stays plain text alongside this script's banners.
    """
    logging.basicConfig(
        level=logging.WARNING,
        format="  %(levelname)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )


@dataclass(frozen=True)
class BacktestRunOutcome:
    """Result of ``_run_backtest_phases_2_7`` for CLI exit codes and tests."""

    exit_code: int
    orchestrator: Orchestrator
    config: PlatformConfig
    recorder: BusRecorder | None = None


def _emit_edge_calibration(orchestrator: Orchestrator, path: str, *, version: str) -> None:
    """Close-the-loop: build per-alpha edge realization factors from this
    run's trade journal (realized vs disclosed edge) and write them to an
    ``EdgeCalibrationStore`` for a subsequent ``--edge-calibration`` run.

    Factors stay 1.0 until an alpha clears the 30-fill evidence bar, so a
    single sparse session produces no haircut — accumulate a multi-session
    window (run over a date range) for the factors to bite.
    """
    from feelies.forensics.edge_calibration import (
        EdgeCalibrationStore,
        build_edge_calibrations,
    )

    journal = orchestrator.trade_journal
    records = list(journal.query()) if journal is not None else []
    disclosed: dict[str, float] = {}
    registry = orchestrator.alpha_registry
    if registry is not None:
        for alpha_id in registry.alpha_ids():
            module = registry.get(alpha_id)
            cost = getattr(module, "cost", None)
            edge = getattr(cost, "edge_estimate_bps", None)
            if isinstance(edge, (int, float)):
                disclosed[alpha_id] = float(edge)

    cals = build_edge_calibrations(records, disclosed)
    EdgeCalibrationStore(path).save(cals, version=version)
    print(f"  edge calibration written -> {path}", flush=True)
    for sid in sorted(cals):
        c = cals[sid]
        print(
            f"    {sid:<26s} n={c.n_fills:<4d} "
            f"realized={c.realized_edge_bps_mean:7.2f}b "
            f"disclosed={c.disclosed_edge_bps:6.2f}b "
            f"lcb_factor={c.lcb_factor:.3f}",
            flush=True,
        )


def _run_backtest_phases_2_7(
    args: argparse.Namespace,
    event_log: InMemoryEventLog,
    ingest_result: IngestResult,
    day_sources: Sequence[DaySource],
    config: PlatformConfig,
    symbols: list[str],
    symbol_str: str,
    date_range: str,
    run_t0: float,
    *,
    prep: BacktestEventLogPrep | None = None,
) -> BacktestRunOutcome:
    """Bootstrap → replay → report → verification (shared by API and cache harness)."""
    _warn_if_unhealthy_manifest_days(day_sources)

    if prep is None:
        prep = prepare_backtest_event_log(config, event_log)
    event_log = prep.event_log
    if prep.rth_dropped:
        ingest_result = replace(
            ingest_result,
            events_ingested=ingest_result.events_ingested - prep.rth_dropped,
        )

    config = _ensure_backtest_session_anchor(
        config,
        first_event_ts_ns=prep.first_event_ts_ns,
    )
    n_quotes = prep.n_quotes

    # ── Phase 2: Platform bootstrap ───────────────────────────
    step_t = _step("Composing platform (alphas, engines, risk)")
    signal_trace_sink: list[SignalOrderTraceRow] | None = [] if args.trace_signal_orders else None
    # G-5 measurement: cross-alpha net-shadow sink (parity-neutral; wiring it
    # only records NetDivergence, it does not drive).  ``_cache_args`` and
    # other lightweight callers may omit the flag, hence ``getattr``.
    net_shadow_sink: "list[NetDivergence] | None" = (
        [] if getattr(args, "emit_net_divergence_jsonl", False) else None
    )
    # G-7 measurement: edge/vol/inventory size-shadow sink (parity-neutral;
    # wiring it only records SizeDivergence, it does not drive).
    size_shadow_sink: "list[SizeDivergence] | None" = (
        [] if getattr(args, "emit_size_divergence_jsonl", False) else None
    )
    # Close-the-loop (gate): apply per-alpha edge realization factors from a
    # prior multi-session run's EdgeCalibrationStore (no flag -> None -> no
    # haircut -> parity-preserving).
    _edge_factors = None
    _apply_edge_cal = getattr(args, "edge_calibration", None)
    if _apply_edge_cal:
        from feelies.forensics.edge_calibration import EdgeCalibrationStore

        _edge_factors = EdgeCalibrationStore(_apply_edge_cal).factors()
        print(
            f"  applying edge calibration from {_apply_edge_cal} "
            f"({len(_edge_factors)} alpha factor(s))",
            flush=True,
        )
    orchestrator, config_out = build_platform(
        config,
        event_log=event_log,
        signal_order_trace_sink=signal_trace_sink,
        net_shadow_sink=net_shadow_sink,
        size_shadow_sink=size_shadow_sink,
        precomputed_ex_date_spans=prep.calendar_spans,
        regime_calibration_quotes=prep.regime_calibration_quotes,
        edge_calibration_factors=_edge_factors,
    )
    alpha_count = (
        len(orchestrator.alpha_registry.alpha_ids())
        if orchestrator.alpha_registry is not None
        else 0
    )
    dt = time.monotonic() - step_t
    print(f"  OK - {alpha_count} alpha(s) registered [{dt:.1f}s]", flush=True)

    # ── Phase 3: Attach recorder ──────────────────────────────
    # Skip storing SensorReadings unless the caller requested
    # --emit-sensor-readings-jsonl: those ~10 M entries cause the same
    # Windows VirtualAlloc realloc spike we eliminated from ``events``.
    _skip: set[type] = set()
    if not getattr(args, "emit_sensor_readings_jsonl", False):
        _skip.add(SensorReading)
    # Skip NBBOQuote and MetricEvent from the BusRecorder: quotes are indexed
    # lightly via QuoteReplayObserver; metrics use dedicated subscribers.
    _skip.add(NBBOQuote)
    _skip.add(MetricEvent)
    recorder = BusRecorder(skip_types=frozenset(_skip))
    orchestrator._bus.subscribe_all(recorder)

    # Dedicated latency recorder — captures only tick_to_decision_latency_ns
    # MetricEvents so the report can compute p95/p99 and locate the spike
    # origin without materialising the full ~11 M MetricEvent list.
    _tick_latency_events: list[MetricEvent] = []

    def _on_metric_event(event: Event) -> None:
        if isinstance(event, MetricEvent) and event.name == "tick_to_decision_latency_ns":
            _tick_latency_events.append(event)

    orchestrator._bus.subscribe(MetricEvent, _on_metric_event)

    # ── Phase 4: Boot ─────────────────────────────────────────
    step_t = _step("Booting orchestrator (integrity checks, warm-start)")
    orchestrator.boot(config_out)
    macro = orchestrator.macro_state
    dt = time.monotonic() - step_t
    print(f"  OK - macro state: {macro.name} [{dt:.1f}s]", flush=True)

    if macro != MacroState.READY:
        print(
            f"  ERROR: Boot failed — macro state is {macro.name}, expected READY",
            file=sys.stderr,
        )
        return BacktestRunOutcome(exit_code=1, orchestrator=orchestrator, config=config_out)

    # ── Phase 5: Run pipeline ─────────────────────────────────
    quote_observer = QuoteReplayObserver(total_events=n_quotes, interval=100_000)
    orchestrator._bus.subscribe(NBBOQuote, quote_observer)

    step_t = _step(f"Replaying {n_quotes:,} quotes through pipeline")
    print(flush=True)
    # Prevent CPython GC pauses from inflating tick-to-decision latency.
    # Per-tick allocations (MetricEvent, correlation-id strings, dicts) are
    # short-lived and bounded; incremental collection buys nothing and causes
    # multi-hundred-ms gen2 sweeps deep into the replay.  We disable GC for
    # the duration and do a single collection at the end.
    import gc as _gc
    import sys as _sys

    # Bootstrap disables raw MetricEvent storage for BACKTEST; clear any
    # warmup events accumulated before replay starts.
    _metrics_collector = orchestrator.metric_collector
    if hasattr(_metrics_collector, "_events"):
        _metrics_collector._events.clear()
    _gc.collect()
    _gc.freeze()
    _gc.disable()
    # On Windows, elevate process priority to HIGH_PRIORITY_CLASS to reduce
    # OS scheduler preemption events that can inflate the max tick-to-decision
    # reading.  Falls back silently on non-Windows or if psutil is absent.
    _prev_nice: object = None
    try:
        if _sys.platform == "win32":
            import psutil as _psutil  # type: ignore[import-untyped]

            _proc = _psutil.Process()
            _prev_nice = _proc.nice()
            _proc.nice(_psutil.HIGH_PRIORITY_CLASS)
    except Exception:
        pass
    try:
        orchestrator.run_backtest()
    finally:
        if _prev_nice is not None:
            try:
                _proc.nice(_prev_nice)
            except Exception:
                pass
        _gc.enable()
        _gc.unfreeze()
        _gc.collect()
    dt = time.monotonic() - step_t
    print(f"  Pipeline complete - {quote_observer.summary()}", flush=True)

    # ── Phase 6: Report ───────────────────────────────────────
    step_t = _step("Generating report")
    report = generate_report(
        recorder=recorder,
        tick_latency_events=_tick_latency_events,
        ingest_result=ingest_result,
        config=config_out,
        orchestrator=orchestrator,
        symbol_str=symbol_str,
        date_range=date_range,
        day_sources=list(day_sources),
        data_version=live_data_version(symbols, date_range),
        quote_trace=quote_observer.trace,
        n_quotes=n_quotes,
    )
    dt = time.monotonic() - step_t
    print(f"  OK [{dt:.1f}s]", flush=True)
    print(report)

    if args.trace_signal_orders and signal_trace_sink is not None:
        print_signal_order_trace(signal_trace_sink)

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
    if net_shadow_sink is not None:
        _emit_net_divergence_jsonl(net_shadow_sink)
    if size_shadow_sink is not None:
        _emit_size_divergence_jsonl(size_shadow_sink)
    _emit_phase2_jsonl(args, recorder)

    _emit_edge_cal = getattr(args, "emit_edge_calibration", None)
    if _emit_edge_cal:
        _emit_edge_calibration(orchestrator, _emit_edge_cal, version=date_range)

    return BacktestRunOutcome(
        exit_code=0 if all_passed else 2,
        orchestrator=orchestrator,
        config=config_out,
        recorder=recorder,
    )


def run_backtest_api(args: argparse.Namespace) -> int:
    """Run the Massive API backtest path (shared by script and ``feelies backtest``)."""
    if not args.date:
        print(
            "ERROR: --date is required (the synthetic --demo mode was "
            "retired with workstream D.2; use the integration suite "
            "for no-API-key smoke tests)",
            file=sys.stderr,
        )
        return 1

    # 1. Load .env and API key
    load_dotenv_optional()
    api_key = massive_api_key_from_env()
    if api_key is None:
        print(MASSIVE_API_KEY_ERROR, file=sys.stderr)
        return 1

    config = _load_backtest_config(args)
    if config is None:
        return 1

    symbols = resolve_backtest_symbols(config)
    if not symbols:
        print(
            "ERROR: No symbols specified (use --symbol or set in platform.yaml)", file=sys.stderr
        )
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
            api_key,
            symbols,
            start_date,
            end_date,
            cache_dir=cache_dir,
            no_cache=no_cache,
            enable_rest_sequence_gap_detection=(config.enable_rest_sequence_gap_detection),
        )
    except ImportError as exc:
        print(
            f"\n  ERROR: {exc}\n  Install the massive extra: pip install 'feelies[massive]'",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"\n  ERROR: Ingestion failed: {exc!r}", file=sys.stderr)
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

    prep = prepare_backtest_event_log(config, event_log)
    rc = _enforce_ingest_event_mix(
        config,
        prep.event_log,
        source_label="ingested",
        n_quotes=prep.n_quotes,
        n_trades=prep.n_trades,
    )
    if rc != 0:
        return rc

    config = _attach_day_source_provenance(config, symbols, day_sources)

    return _run_backtest_phases_2_7(
        args,
        event_log,
        ingest_result,
        day_sources,
        config,
        symbols,
        symbol_str,
        date_range,
        run_t0,
        prep=prep,
    ).exit_code


def main(argv: list[str] | None = None) -> int:
    _force_utf8_console()
    _configure_logging_for_cli()
    return run_backtest_api(parse_args(argv))


def main_cache_replay(argv: list[str] | None = None) -> int:
    """Entry point: replay from DiskEventCache JSONL.gz only (no Massive API)."""
    _force_utf8_console()
    _configure_logging_for_cli()
    args = parse_cache_replay_args(argv)

    config = _load_backtest_config(args)
    if config is None:
        return 1

    symbols = resolve_backtest_symbols(config)
    if not symbols:
        print(
            "ERROR: No symbols specified (use --symbol or set in platform.yaml)",
            file=sys.stderr,
        )
        return 1

    start_date = args.date
    end_date = args.end_date or start_date
    date_range = start_date if start_date == end_date else f"{start_date} to {end_date}"
    symbol_str = ", ".join(symbols)
    run_t0 = time.monotonic()

    print(f"\n  Cache replay: {symbol_str}  |  {date_range}", flush=True)
    print(f"  {_RULE_LIGHT}", flush=True)

    step_t = _step("Loading disk cache (JSONL.gz only)")
    print(flush=True)

    from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache

    cache_path = Path(args.cache_dir) if args.cache_dir else None

    try:
        event_log, ingest_result, day_meta = load_event_log_from_disk_cache(
            symbols,
            start_date,
            end_date,
            cache_dir=cache_path,
            require_healthy_ingestion_manifests=(config.require_healthy_disk_cache_manifests),
        )
    except CacheReplayError as exc:
        print(f"\n  ERROR: {exc}", file=sys.stderr)
        return 1

    dt_load = time.monotonic() - step_t
    print(
        f"  OK - {ingest_result.events_ingested:,} events (disk cache only) [{dt_load:.1f}s]",
        flush=True,
    )

    day_sources = list(day_meta)
    prep = prepare_backtest_event_log(config, event_log)
    rc = _enforce_ingest_event_mix(
        config,
        prep.event_log,
        source_label="loaded from disk cache",
        n_quotes=prep.n_quotes,
        n_trades=prep.n_trades,
    )
    if rc != 0:
        return rc

    config = _attach_day_source_provenance(config, symbols, day_sources)

    return _run_backtest_phases_2_7(
        args,
        event_log,
        ingest_result,
        day_sources,
        config,
        symbols,
        symbol_str,
        date_range,
        run_t0,
        prep=prep,
    ).exit_code
