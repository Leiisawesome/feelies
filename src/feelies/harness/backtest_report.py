"""Backtest report formatting, parity hashes, and verification helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Protocol, TypeVar
from zoneinfo import ZoneInfo

from feelies.core.events import (
    Event,
    HorizonFeatureSnapshot,
    MetricEvent,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    PositionUpdate,
    Signal,
    SignalDirection,
)
from feelies.core.platform_config import PlatformConfig
from feelies.harness.backtest_prep import QuoteTraceIndex
from feelies.ingestion.massive_ingestor import IngestResult
from feelies.kernel.macro import MacroState
from feelies.kernel.orchestrator import Orchestrator
from feelies.monitoring.in_memory import InMemoryMetricCollector
from feelies.storage.cache_replay import IngestDayMeta

T = TypeVar("T", bound=Event)

_W = 62
_RULE_HEAVY = "=" * _W
_TZ_ET = ZoneInfo("America/New_York")

__all__ = [
    "ENGINE_VERSION",
    "BusEventRecorder",
    "compute_artifact_id",
    "compute_combined_parity_hash",
    "compute_config_hash",
    "compute_parity_hash",
    "dedupe_republished_signal_events",
    "format_section",
    "generate_report",
    "live_data_version",
    "run_verification",
]


class BusEventRecorder(Protocol):
    """Minimal recorder surface consumed by :func:`generate_report`."""

    def of_type(self, event_type: type[T]) -> list[T]: ...


def dedupe_republished_signal_events(signals: list[Signal]) -> list[Signal]:
    """One entry per distinct ``Signal`` instance (preserves arrival order).

    ``HorizonSignalEngine`` publishes each evaluation once; the orchestrator
    re-publishes the arbitration-selected ``Signal`` on the same tick
    (``Orchestrator._process_tick_inner``) so downstream bus subscribers see
    it again.  :class:`BusRecorder` therefore often records the **same**
    immutable object twice — inflating naive ``len(recorder.of_type(Signal))``
    counts.  Dedupe by ``id()`` so report totals match distinct horizon
    emissions.

    Separate evaluations are distinct instances (unique ``sequence``), so
    this does not merge two equal-valued signals from different ticks.
    """
    seen: set[int] = set()
    out: list[Signal] = []
    for s in signals:
        oid = id(s)
        if oid in seen:
            continue
        seen.add(oid)
        out.append(s)
    return out



def _report_header(title: str, symbol: str, date_range: str) -> str:
    lines = [
        "",
        _RULE_HEAVY,
        f"  BACKTEST REPORT  |  {title}",
        f"  Symbol: {symbol}  |  Date: {date_range}",
        _RULE_HEAVY,
    ]
    return "\n".join(lines)


def format_section(name: str) -> str:
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


def _pct(v: float, sign: bool = False) -> str:
    prefix = "+" if sign and v > 0 else ""
    return f"{prefix}{v:.2f}%"


def _ns_to_ms(ns: float) -> str:
    return f"{ns / 1_000_000:.3f} ms"


# ── Report generation ────────────────────────────────────────────────


def generate_report(
    *,
    recorder: BusEventRecorder,
    tick_latency_events: list[MetricEvent] | None = None,
    ingest_result: IngestResult,
    config: PlatformConfig,
    orchestrator: Orchestrator,
    symbol_str: str,
    date_range: str,
    day_sources: list[IngestDayMeta] | None = None,
    data_version: str | None = None,
    quote_trace: QuoteTraceIndex | None = None,
    n_quotes: int | None = None,
) -> str:
    """Build the full backtest report string."""
    from feelies.storage.trade_journal import TradeRecord

    raw_signals = recorder.of_type(Signal)
    signals = dedupe_republished_signal_events(raw_signals)
    orders = recorder.of_type(OrderRequest)
    acks = recorder.of_type(OrderAck)
    pos_updates = recorder.of_type(PositionUpdate)

    filled_acks = [a for a in acks if a.status == OrderAckStatus.FILLED]
    rejected_acks = [a for a in acks if a.status == OrderAckStatus.REJECTED]
    pending_orders = len(orders) - len(filled_acks) - len(rejected_acks)

    long_signals = [s for s in signals if s.direction == SignalDirection.LONG]
    short_signals = [s for s in signals if s.direction == SignalDirection.SHORT]
    flat_signals = [s for s in signals if s.direction == SignalDirection.FLAT]

    horizon_snapshots = recorder.of_type(HorizonFeatureSnapshot)

    if quote_trace is not None:
        quote_count = quote_trace.quote_count
    elif n_quotes is not None:
        quote_count = n_quotes
    else:
        quote_count = len(recorder.of_type(NBBOQuote))

    total_shares = sum(abs(a.filled_quantity) for a in filled_acks)

    # Strategy ID from first signal, or fallback
    strategy_id = signals[0].strategy_id if signals else "unknown"

    # ── P&L from position store ──────────────────────────────────
    positions = orchestrator.position_store
    all_pos = positions.all_positions()
    starting_equity = float(orchestrator.account_equity)

    realized_pnl = sum(
        (p.realized_pnl for p in all_pos.values()),
        Decimal("0"),
    )
    unrealized_pnl = sum(
        (p.unrealized_pnl for p in all_pos.values()),
        Decimal("0"),
    )
    gross_pnl = realized_pnl + unrealized_pnl
    fees = sum((a.fees for a in acks), Decimal("0"))
    net_pnl = gross_pnl - fees
    final_equity = Decimal(str(starting_equity)) + net_pnl
    return_pct = float(net_pnl) / starting_equity * 100.0 if starting_equity else 0.0

    # ── Trade summary ────────────────────────────────────────────
    journal = orchestrator.trade_journal
    assert journal is not None, "backtest orchestrator must attach trade_journal"
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
    entry_fills = total_fills - resolved_count
    win_rate = (win_count / resolved_count * 100.0) if resolved_count else 0.0
    avg_win = sum(winning_pnls, Decimal("0")) / len(winning_pnls) if winning_pnls else Decimal("0")
    avg_loss = sum(losing_pnls, Decimal("0")) / len(losing_pnls) if losing_pnls else Decimal("0")
    largest_win = max(winning_pnls) if winning_pnls else Decimal("0")
    largest_loss = min(losing_pnls) if losing_pnls else Decimal("0")
    pnl_per_share = float(realized_pnl) / total_shares if total_shares else 0.0

    # ── Risk ─────────────────────────────────────────────────────
    # Track per-symbol exposure and sum for portfolio-wide max.
    max_exposure = Decimal("0")
    max_exposure_pct = 0.0
    per_symbol_exposure: dict[str, Decimal] = {}
    per_symbol_realized: dict[str, Decimal] = {}
    per_symbol_unrealized: dict[str, Decimal] = {}
    per_symbol_fees: dict[str, Decimal] = {}
    for pu in pos_updates:
        per_symbol_exposure[pu.symbol] = abs(Decimal(str(pu.quantity)) * pu.avg_price)
        per_symbol_realized[pu.symbol] = pu.realized_pnl
        per_symbol_unrealized[pu.symbol] = pu.unrealized_pnl
        per_symbol_fees[pu.symbol] = pu.cumulative_fees

        total_exposure = sum(per_symbol_exposure.values(), Decimal("0"))
        current_equity = (
            Decimal(str(starting_equity))
            + sum(per_symbol_realized.values(), Decimal("0"))
            - sum(per_symbol_fees.values(), Decimal("0"))
            + sum(per_symbol_unrealized.values(), Decimal("0"))
        )
        if total_exposure > max_exposure:
            max_exposure = total_exposure
            max_exposure_pct = (
                float(total_exposure / current_equity * Decimal("100"))
                if current_equity != 0 else 0.0
            )

    # Drawdown: track live NAV from position updates.
    peak_equity = Decimal(str(starting_equity))
    max_drawdown = Decimal("0")
    per_symbol_pnl: dict[str, Decimal] = {}
    per_symbol_fees = {}
    per_symbol_unrealized = {}
    for pu in pos_updates:
        per_symbol_pnl[pu.symbol] = pu.realized_pnl
        per_symbol_fees[pu.symbol] = pu.cumulative_fees
        per_symbol_unrealized[pu.symbol] = pu.unrealized_pnl
        current_equity = (
            Decimal(str(starting_equity))
            + sum(per_symbol_pnl.values(), Decimal("0"))
            - sum(per_symbol_fees.values(), Decimal("0"))
            + sum(per_symbol_unrealized.values(), Decimal("0"))
        )
        if current_equity > peak_equity:
            peak_equity = current_equity
        dd = current_equity - peak_equity
        if dd < max_drawdown:
            max_drawdown = dd
    max_dd_pct = (
        float(max_drawdown / peak_equity * Decimal("100"))
        if peak_equity != 0 else 0.0
    )

    kill_switch = orchestrator.kill_switch
    ks_status = (
        "ACTIVATED" if kill_switch is not None and kill_switch.is_active else "NOT ACTIVATED"
    )

    # ── Performance metrics ──────────────────────────────────────
    mc = orchestrator.metric_collector
    if isinstance(mc, InMemoryMetricCollector):
        tick_summary = mc.get_summary("kernel", "tick_to_decision_latency_ns")
        feat_summary = mc.get_summary("kernel", "feature_compute_ns")
        sig_summary = mc.get_summary("kernel", "signal_evaluate_ns")
    else:
        tick_summary = feat_summary = sig_summary = None

    avg_tick_ns = tick_summary.mean if tick_summary else 0.0
    max_tick_ns = tick_summary.max_value if tick_summary else 0.0
    avg_feat_ns = feat_summary.mean if feat_summary else 0.0
    avg_sig_ns = sig_summary.mean if sig_summary else 0.0

    # Locate the originating quote for the max tick-to-decision spike.
    # Why this matters: a single 1.3-second outlier in a 974K-quote run is
    # almost always (a) the first post-warmup tick, (b) a GC pause, or
    # (c) a real microstructure event (auction/halt/cross). Knowing which
    # quote caused it converts an "alarming number" into an actionable line
    # in the data. Spike origin uses ``quote_trace`` (or BusRecorder NBBOQuote
    # fallback); tick latencies use ``tick_latency_events`` when wired.
    max_tick_meta: dict[str, object] | None = None
    p95_tick_ns: float | None = None
    p99_tick_ns: float | None = None
    if tick_summary:
        # Use dedicated latency list when available (avoids materialising
        # the full ~11 M MetricEvent list from the BusRecorder).
        if tick_latency_events is not None:
            tick_metrics = tick_latency_events
        else:
            tick_metrics = [
                e for e in recorder.of_type(MetricEvent)
                if e.name == "tick_to_decision_latency_ns"
            ]
        if tick_metrics:
            values = sorted(e.value for e in tick_metrics)
            p95_tick_ns = values[min(len(values) - 1, int(0.95 * len(values)))]
            p99_tick_ns = values[min(len(values) - 1, int(0.99 * len(values)))]

            spike = max(tick_metrics, key=lambda e: e.value)
            trace_entry = (
                quote_trace.by_correlation_id.get(spike.correlation_id)
                if quote_trace is not None
                else None
            )
            if trace_entry is not None:
                tick_idx: int | None = trace_entry.tick_index
                max_tick_meta = {
                    "value_ns": spike.value,
                    "correlation_id": spike.correlation_id,
                    "kernel_sequence": spike.sequence,
                    "tick_index": tick_idx,
                    "n_total_ticks": quote_count,
                    "symbol": trace_entry.symbol,
                    "exchange_ts_ns": trace_entry.exchange_timestamp_ns,
                    "is_first_5_pct": (
                        tick_idx is not None
                        and tick_idx <= max(1, quote_count // 20)
                    ),
                }
            else:
                quotes = recorder.of_type(NBBOQuote)
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
                    "n_total_ticks":     quote_count,
                    "symbol":            originating.symbol if originating else "?",
                    "exchange_ts_ns":    (originating.exchange_timestamp_ns
                                          if originating else None),
                    "is_first_5_pct":    (tick_idx is not None
                                          and tick_idx <= max(1, quote_count // 20)),
                }

    # ── Assemble report ──────────────────────────────────────────
    lines: list[str] = []
    lines.append(_report_header(strategy_id, symbol_str, date_range))

    # Ingestion
    lines.append(format_section("Data Ingestion"))
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
    lines.append(format_section("Signal Pipeline"))
    lines.append(_kv("Quotes processed", f"{quote_count:,}"))
    lines.append(_kv("Feature snapshots", f"{len(horizon_snapshots):,}"))
    lines.append(_kv("Signals emitted", f"{len(signals):,}"))
    if len(raw_signals) != len(signals):
        lines.append(
            _sub_kv(
                "Deduplicated from",
                f"{len(raw_signals):,} bus rows (incl. republish)",
            ),
        )
    lines.append(_sub_kv("Long  (entry)", f"{len(long_signals):,}"))
    lines.append(_sub_kv("Short (entry)", f"{len(short_signals):,}"))
    lines.append(_sub_kv("Flat  (exit) ", f"{len(flat_signals):,}"))

    lines.append(_divider())

    # Execution
    lines.append(format_section("Execution"))
    lines.append(_kv("Orders submitted", f"{len(orders):,}"))
    lines.append(_sub_kv("Filled  ", f"{len(filled_acks):,}"))
    lines.append(_sub_kv("Rejected", f"{len(rejected_acks):,}"))
    if pending_orders:
        lines.append(_sub_kv("Pending / no ack", f"{pending_orders:,}"))
    lines.append(_kv("Shares traded", f"{total_shares:,}"))

    lines.append(_divider())

    # P&L
    lines.append(format_section("P&L"))
    lines.append(_kv("Starting equity", _money(Decimal(str(starting_equity)))))
    lines.append(_kv("Gross P&L", _money(gross_pnl)))
    lines.append(_sub_kv("Realized", _money(realized_pnl)))
    lines.append(_sub_kv("Unrealized", _money(unrealized_pnl)))
    lines.append(_kv("Fees", _money(fees)))
    lines.append(_kv("Net P&L", _money(net_pnl)))
    lines.append(_kv("Final equity", _money(final_equity)))
    lines.append(_kv("Return", _pct(return_pct, sign=True)))

    lines.append(_divider())

    # Trade summary
    lines.append(format_section("Trade Analysis"))
    lines.append(_kv("Total fills", f"{total_fills:,}"))
    lines.append(_sub_kv("Entry fills ", f"{entry_fills:,}"))
    lines.append(_sub_kv("Closing fills", f"{resolved_count:,}"))
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
    lines.append(format_section("Risk"))
    lines.append(_kv("Max exposure", f"{_money(max_exposure)} ({_pct(max_exposure_pct)})"))
    lines.append(_kv("Max drawdown", f"{_money(max_drawdown)} ({_pct(max_dd_pct)})"))
    lines.append(_kv("Kill switch", ks_status))

    lines.append(_divider())

    # Performance
    lines.append(format_section("Latency"))
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
            from datetime import datetime
            dt = datetime.fromtimestamp(ts_ns / 1e9, tz=_TZ_ET)
            ts_str = dt.strftime("%H:%M:%S.%f")[:-3] + " ET"
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
        lines.append(format_section("TCA (Transaction Cost Analysis)"))
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
            for decay in decay_signals:
                lines.append(_sub_kv("  Strategy", decay.strategy_id))
                lines.append(_sub_kv("  Hist edge", f"{decay.expected:.2f} bps"))
                lines.append(_sub_kv("  Recent edge", f"{decay.realized:.2f} bps"))
                lines.append(_sub_kv("  Z-score", f"{decay.z_score:.2f}"))

    # Three-hash parity contract — pnl_hash, config_hash, parity_hash (combined bind).
    pnl_hash = compute_parity_hash(orchestrator)
    config_hash = compute_config_hash(config)
    parity_hash = compute_combined_parity_hash(pnl_hash, config_hash)
    resolved_data_version = data_version if data_version is not None else "unknown"
    artifact_id = compute_artifact_id(
        orchestrator, config, data_version=resolved_data_version,
    )
    lines.append(_divider())
    lines.append(format_section("Parity"))
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


# ── Parity hashes (three-hash contract — trade journal + config snapshot) ──


def live_data_version(symbols: list[str], date_range: str) -> str:
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


def compute_parity_hash(orchestrator: Orchestrator) -> str:
    """SHA-256 over the ordered trade sequence (canonical JSON representation).

    Identical inputs MUST yield identical hashes for the same alpha + date range
    + same platform.yaml.
    """
    from feelies.storage.trade_journal import TradeRecord

    journal = orchestrator.trade_journal
    assert journal is not None, "backtest orchestrator must attach trade_journal"
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
    that produced it.
    """
    return hashlib.sha256(f"{pnl_hash}:{config_hash}".encode("utf-8")).hexdigest()


# Bumped whenever the engine's externally-observable contract changes
# (event schema, fill semantics, hash format). Promotion artifacts produced
# under different ``ENGINE_VERSION`` strings are not directly comparable.
ENGINE_VERSION = "0.1.0"


def compute_artifact_id(
    orchestrator: Orchestrator,
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
    registry = orchestrator.alpha_registry
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


def run_verification(
    *,
    recorder: BusEventRecorder,
    ingest_result: IngestResult,
    orchestrator: Orchestrator,
) -> list[tuple[str, bool, str]]:
    """Run moderate verification criteria. Returns (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []

    # 1. Events ingested > 0
    n = ingest_result.events_ingested
    results.append(("Events ingested", n > 0, f"{n} events"))

    # 2. Signals fired > 0 (dedupe orchestrator re-publish of same instance)
    raw_sigs = recorder.of_type(Signal)
    sigs = dedupe_republished_signal_events(raw_sigs)
    detail = f"{len(sigs)} signals"
    if len(raw_sigs) != len(sigs):
        detail += f" ({len(raw_sigs)} bus records incl. republish)"
    results.append(("Signals fired", len(sigs) > 0, detail))

    # 3. Fills occurred >= 1
    acks = recorder.of_type(OrderAck)
    fills = [a for a in acks if a.status == OrderAckStatus.FILLED]
    results.append(("Fills occurred", len(fills) >= 1, f"{len(fills)} fills"))

    # 4. P&L computable
    positions = orchestrator.position_store
    all_pos = positions.all_positions()
    has_pnl = any(p.realized_pnl is not None for p in all_pos.values()) if all_pos else False
    # Also pass if no positions were taken (realized_pnl stays at 0)
    if not all_pos:
        has_pnl = True  # vacuously true — no trades means no PnL to compute
    results.append(("P&L computable", has_pnl, "realized_pnl tracked" if has_pnl else "missing"))

    # 5. Trade journal >= 1
    journal = orchestrator.trade_journal
    n_records = len(list(journal.query())) if journal is not None else 0
    results.append(("Trade journal", n_records >= 1, f"{n_records} records"))

    # 6. Macro state == READY
    macro = orchestrator.macro_state
    results.append(("Macro state", macro == MacroState.READY, macro.name))

    # 7. Kill switch not activated
    kill_switch = orchestrator.kill_switch
    results.append(
        (
            "Kill switch",
            kill_switch is None or not kill_switch.is_active,
            "INACTIVE" if kill_switch is None or not kill_switch.is_active else "ACTIVE",
        ),
    )

    return results


