#!/usr/bin/env python3
"""Compare standalone vs multialpha backtest runs on the same symbol/day.

Runs three disk-cache replays (benign-only, inventory-only, multialpha) and
reports:

* fleet net P&L and fill counts per config
* fill-leg price diffs (benign vs multialpha)
* **exit hijacks** — closing fills tagged with a passive alpha (gate-close
  FLAT only) that opened no positions, typical of ``EdgeWeightedArbitrator``
  interference
* per-alpha cost-survival split under multialpha (attribution artifact warning)
* directional vs gate-close signal counts from the bus recorder

Read-only forensics — does not write configs or ledgers.

Usage::

    uv run python scripts/compare_multialpha_runs.py \\
        --symbol APP --date 2026-03-26

    uv run python scripts/compare_multialpha_runs.py \\
        --symbol APP --date 2026-03-26 --json --strict
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT / "src"))
    os.chdir(_REPO_ROOT)

from feelies.core.events import Side, Signal, SignalDirection  # noqa: E402
from feelies.core.platform_config import PlatformConfig  # noqa: E402
from feelies.forensics.cost_survival import per_alpha_cost_survival  # noqa: E402
from feelies.harness.backtest_prep import prepare_backtest_event_log  # noqa: E402
from feelies.harness.backtest_report import dedupe_republished_signal_events  # noqa: E402
from feelies.kernel.orchestrator import StandaloneArbitrationCollision  # noqa: E402
from feelies.storage.cache_replay import CacheReplayError, load_event_log_from_disk_cache  # noqa: E402
from feelies.storage.trade_journal import TradeRecord  # noqa: E402

_DEFAULT_BENIGN = Path("configs/bt_sig_benign_midcap.yaml")
_DEFAULT_INVENTORY = Path("configs/bt_sig_inventory_revert.yaml")
_DEFAULT_MULTIALPHA = Path("configs/bt_multialpha.yaml")

_ENTRY_INTENTS = frozenset({"ENTRY_LONG", "ENTRY_SHORT", "SCALE_UP"})
_EXIT_INTENTS = frozenset({"EXIT", "REVERSE_LONG_TO_SHORT", "REVERSE_SHORT_TO_LONG"})


@dataclass(frozen=True, slots=True)
class FillLeg:
    """One journal row normalized for leg-by-leg comparison."""

    index: int
    side: str
    qty: int
    price: Decimal
    strategy_id: str
    trading_intent: str
    realized_pnl: Decimal
    fees: Decimal
    fill_timestamp_ns: int | None


@dataclass(frozen=True, slots=True)
class FillLegDiff:
    index: int
    qty: int
    benign_price: str
    multi_price: str
    price_delta: float
    short_pnl_impact: float
    benign_strategy_id: str
    multi_strategy_id: str
    multi_trading_intent: str


@dataclass(frozen=True, slots=True)
class ExitHijack:
    """Closing fill credited to *hijack_alpha* while *entry_alpha* opened."""

    fill_index: int
    hijack_alpha: str
    entry_alpha: str
    trading_intent: str
    fill_price: str
    realized_pnl: float
    fees: float
    note: str


@dataclass(frozen=True, slots=True)
class SignalSummary:
    total_bus_rows: int
    deduped: int
    directional: int
    flat_gate_close: int
    by_strategy: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ArbitrationCollisionRow:
    candidate_count: int
    strategy_ids: tuple[str, ...]
    kinds: tuple[tuple[str, str, str], ...]
    harmless: bool
    kind_key: str


@dataclass(frozen=True, slots=True)
class CollisionSummary:
    post_filter_collision_ticks: int
    harmless_flat_gate_close_ticks: int
    actionable_collision_ticks: int
    kind_breakdown: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunSummary:
    config_path: str
    net_pnl: float
    fill_count: int
    signal_summary: SignalSummary | None
    fill_legs: tuple[FillLeg, ...]


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    symbol: str
    date: str
    benign: RunSummary
    inventory: RunSummary
    multialpha: RunSummary
    fill_diffs: tuple[FillLegDiff, ...]
    exit_hijacks: tuple[ExitHijack, ...]
    pnl_delta_benign_to_multi: float
    attribution_warning: str
    hijack_alpha: str
    entry_alpha: str
    collision_summary: CollisionSummary
    arbitration_collisions: tuple[ArbitrationCollisionRow, ...]


def _load_runner():
    script = _REPO_ROOT / "scripts" / "run_backtest.py"
    spec = importlib.util.spec_from_file_location("_compare_multialpha_runner", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_compare_multialpha_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


def _cache_args(*, trace_signal_orders: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        trace_signal_orders=trace_signal_orders,
        emit_fills_jsonl=False,
        emit_sensor_readings_jsonl=False,
        emit_horizon_ticks_jsonl=False,
        emit_snapshots_jsonl=False,
        emit_signals_jsonl=False,
        emit_hazard_spikes_jsonl=False,
        emit_cross_sectional_jsonl=False,
        emit_sized_intents_jsonl=False,
        emit_hazard_exits_jsonl=False,
        emit_net_divergence_jsonl=False,
        emit_size_divergence_jsonl=False,
        emit_edge_calibration=None,
    )


def fills_from_journal(records: Iterable[TradeRecord]) -> list[FillLeg]:
    legs: list[FillLeg] = []
    for i, rec in enumerate(records):
        legs.append(
            FillLeg(
                index=i,
                side=rec.side.name,
                qty=int(rec.filled_quantity),
                price=rec.fill_price or Decimal("0"),
                strategy_id=rec.strategy_id,
                trading_intent=rec.trading_intent,
                realized_pnl=rec.realized_pnl,
                fees=rec.fees,
                fill_timestamp_ns=rec.fill_timestamp_ns,
            )
        )
    return legs


def net_pnl_from_journal(records: Iterable[TradeRecord]) -> float:
    gross = sum((r.realized_pnl for r in records), Decimal("0"))
    fees = sum((r.fees for r in records), Decimal("0"))
    return float(gross - fees)


def summarize_signals(signals: Sequence[Signal]) -> SignalSummary:
    deduped = dedupe_republished_signal_events(list(signals))
    by_strategy: dict[str, dict[str, int]] = {}
    directional = 0
    flat_gate_close = 0
    for s in deduped:
        d = s.direction.name
        by_strategy.setdefault(s.strategy_id, {})
        by_strategy[s.strategy_id][d] = by_strategy[s.strategy_id].get(d, 0) + 1
        if s.direction == SignalDirection.FLAT:
            flat_gate_close += 1
        else:
            directional += 1
    return SignalSummary(
        total_bus_rows=len(signals),
        deduped=len(deduped),
        directional=directional,
        flat_gate_close=flat_gate_close,
        by_strategy=by_strategy,
    )


def collision_kind_key(kinds: Sequence[tuple[str, str, str]]) -> str:
    """Canonical collision pattern (direction/regime, sorted)."""
    return "+".join(f"{d}/{g}" for _, d, g in sorted(kinds))


def arbitration_collision_rows(
    collisions: Sequence[StandaloneArbitrationCollision],
) -> tuple[ArbitrationCollisionRow, ...]:
    return tuple(
        ArbitrationCollisionRow(
            candidate_count=c.candidate_count,
            strategy_ids=c.strategy_ids,
            kinds=c.kinds,
            harmless=c.harmless,
            kind_key=collision_kind_key(c.kinds),
        )
        for c in collisions
    )


def summarize_arbitration_collisions(
    rows: Sequence[ArbitrationCollisionRow],
) -> CollisionSummary:
    kind_breakdown: dict[str, int] = {}
    harmless = 0
    actionable = 0
    for row in rows:
        kind_breakdown[row.kind_key] = kind_breakdown.get(row.kind_key, 0) + 1
        if row.harmless:
            harmless += 1
        else:
            actionable += 1
    return CollisionSummary(
        post_filter_collision_ticks=len(rows),
        harmless_flat_gate_close_ticks=harmless,
        actionable_collision_ticks=actionable,
        kind_breakdown=kind_breakdown,
    )


def _short_cover_pnl_impact(benign_price: Decimal, multi_price: Decimal) -> float:
    """Approximate short-cover P&L delta (multi − benign) for equal qty."""
    return float(benign_price - multi_price)


def compare_fill_legs(
    benign: Sequence[FillLeg],
    multi: Sequence[FillLeg],
) -> list[FillLegDiff]:
    diffs: list[FillLegDiff] = []
    for i, (b, m) in enumerate(zip(benign, multi, strict=False)):
        if b.price == m.price and b.strategy_id == m.strategy_id:
            continue
        delta = float(m.price - b.price)
        diffs.append(
            FillLegDiff(
                index=i,
                qty=b.qty,
                benign_price=str(b.price),
                multi_price=str(m.price),
                price_delta=delta,
                short_pnl_impact=_short_cover_pnl_impact(b.price, m.price) * b.qty,
                benign_strategy_id=b.strategy_id,
                multi_strategy_id=m.strategy_id,
                multi_trading_intent=m.trading_intent,
            )
        )
    if len(benign) != len(multi):
        diffs.append(
            FillLegDiff(
                index=max(len(benign), len(multi)),
                qty=0,
                benign_price=f"(n={len(benign)})",
                multi_price=f"(n={len(multi)})",
                price_delta=0.0,
                short_pnl_impact=0.0,
                benign_strategy_id="—",
                multi_strategy_id="—",
                multi_trading_intent="FILL_COUNT_MISMATCH",
            )
        )
    return diffs


def detect_exit_hijacks(
    multi_legs: Sequence[FillLeg],
    *,
    entry_alpha: str,
    hijack_alpha: str,
    benign_legs: Sequence[FillLeg] | None = None,
) -> list[ExitHijack]:
    """Flag multialpha closing fills tagged with *hijack_alpha*."""
    flags: list[ExitHijack] = []
    for leg in multi_legs:
        if leg.strategy_id != hijack_alpha:
            continue
        is_exit = leg.trading_intent in _EXIT_INTENTS or (
            leg.realized_pnl != 0 and leg.trading_intent not in _ENTRY_INTENTS
        )
        if not is_exit:
            continue
        benign_match = (
            benign_legs[leg.index]
            if benign_legs is not None and leg.index < len(benign_legs)
            else None
        )
        note = "inventory gate-close FLAT won arbitration on exit tick"
        if benign_match is not None and benign_match.price != leg.price:
            note += f"; benign exit was {benign_match.price} vs {leg.price}"
        flags.append(
            ExitHijack(
                fill_index=leg.index,
                hijack_alpha=hijack_alpha,
                entry_alpha=entry_alpha,
                trading_intent=leg.trading_intent,
                fill_price=str(leg.price),
                realized_pnl=float(leg.realized_pnl),
                fees=float(leg.fees),
                note=note,
            )
        )
    return flags


def build_comparison_report(
    *,
    symbol: str,
    date: str,
    benign: RunSummary,
    inventory: RunSummary,
    multialpha: RunSummary,
    entry_alpha: str,
    hijack_alpha: str,
    arbitration_collisions: Sequence[StandaloneArbitrationCollision],
) -> ComparisonReport:
    fill_diffs = tuple(
        compare_fill_legs(benign.fill_legs, multialpha.fill_legs),
    )
    hijacks = tuple(
        detect_exit_hijacks(
            multialpha.fill_legs,
            entry_alpha=entry_alpha,
            hijack_alpha=hijack_alpha,
            benign_legs=benign.fill_legs,
        ),
    )
    pnl_delta = multialpha.net_pnl - benign.net_pnl
    warning = (
        "Per-alpha cost survival under standalone-SIGNAL arbitration attributes "
        "realized PnL to the exit signal's strategy_id, not the alpha that "
        "opened the position. Treat multialpha per-alpha rows as forensics-only."
    )
    collision_rows = arbitration_collision_rows(arbitration_collisions)
    return ComparisonReport(
        symbol=symbol,
        date=date,
        benign=benign,
        inventory=inventory,
        multialpha=multialpha,
        fill_diffs=fill_diffs,
        exit_hijacks=hijacks,
        pnl_delta_benign_to_multi=pnl_delta,
        attribution_warning=warning,
        hijack_alpha=hijack_alpha,
        entry_alpha=entry_alpha,
        collision_summary=summarize_arbitration_collisions(collision_rows),
        arbitration_collisions=collision_rows,
    )


def _run_one(
    runner: Any,
    *,
    config_path: Path,
    prep: Any,
    event_log: Any,
    ingest_result: Any,
    day_sources: Sequence[Any],
    symbols: list[str],
    symbol_str: str,
    date: str,
    quiet: bool,
) -> tuple[Any, Any | None]:
    config = PlatformConfig.from_yaml(config_path)
    config = runner._attach_day_source_provenance(config, symbols, day_sources)
    args = _cache_args()
    stdout = io.StringIO() if quiet else None
    with contextlib.redirect_stdout(stdout) if quiet else contextlib.nullcontext():
        outcome = runner._run_backtest_phases_2_7(
            args,
            event_log,
            ingest_result,
            day_sources,
            config,
            symbols,
            symbol_str,
            date,
            time.monotonic(),
            prep=prep,
        )
    return outcome, outcome.recorder


def _run_summary(
    runner: Any,
    *,
    config_path: Path,
    prep: Any,
    event_log: Any,
    ingest_result: Any,
    day_sources: Sequence[Any],
    symbols: list[str],
    symbol_str: str,
    date: str,
    quiet: bool,
) -> tuple[RunSummary, tuple[StandaloneArbitrationCollision, ...]]:
    outcome, recorder = _run_one(
        runner,
        config_path=config_path,
        prep=prep,
        event_log=event_log,
        ingest_result=ingest_result,
        day_sources=day_sources,
        symbols=symbols,
        symbol_str=symbol_str,
        date=date,
        quiet=quiet,
    )
    journal = outcome.orchestrator.trade_journal
    records = list(journal.query()) if journal is not None else []
    sig_summary: SignalSummary | None = None
    if recorder is not None:
        sig_summary = summarize_signals(recorder.of_type(Signal))
    run = RunSummary(
        config_path=str(config_path),
        net_pnl=net_pnl_from_journal(records),
        fill_count=len(records),
        signal_summary=sig_summary,
        fill_legs=tuple(fills_from_journal(records)),
    )
    return run, outcome.orchestrator.arbitration_collisions


def _format_human(report: ComparisonReport) -> str:
    lines: list[str] = []
    lines.append(f"Multialpha collision report  |  {report.symbol}  {report.date}")
    lines.append("=" * 62)

    def _run_block(label: str, run: RunSummary) -> None:
        lines.append(f"\n[{label}]  {run.config_path}")
        lines.append(f"  net_pnl        ${run.net_pnl:,.2f}")
        lines.append(f"  fills          {run.fill_count}")
        if run.signal_summary is not None:
            s = run.signal_summary
            lines.append(
                f"  signals        {s.deduped} deduped "
                f"({s.directional} directional, {s.flat_gate_close} FLAT)"
            )
            for sid in sorted(s.by_strategy):
                parts = ", ".join(f"{d}={n}" for d, n in sorted(s.by_strategy[sid].items()))
                lines.append(f"    {sid}: {parts}")

    _run_block("benign-only", report.benign)
    _run_block("inventory-only", report.inventory)
    _run_block("multialpha", report.multialpha)

    lines.append(f"\n[P&L delta benign → multialpha]  ${report.pnl_delta_benign_to_multi:+,.2f}")

    if report.fill_diffs:
        lines.append("\n[fill leg diffs vs benign-only]")
        for d in report.fill_diffs:
            if d.multi_trading_intent == "FILL_COUNT_MISMATCH":
                lines.append(f"  !! fill count mismatch: {d.benign_price} vs {d.multi_price}")
                continue
            lines.append(
                f"  leg {d.index}: {d.benign_price} → {d.multi_price} "
                f"(Δ {d.price_delta:+.4f}, short impact ${d.short_pnl_impact:+.2f})"
            )
            if d.benign_strategy_id != d.multi_strategy_id:
                lines.append(
                    f"           strategy {d.benign_strategy_id} → {d.multi_strategy_id} "
                    f"({d.multi_trading_intent})"
                )
    else:
        lines.append("\n[fill leg diffs]  none (identical legs)")

    if report.exit_hijacks:
        lines.append(f"\n[exit hijacks — {report.hijack_alpha} tagged on closes]")
        for h in report.exit_hijacks:
            lines.append(
                f"  leg {h.fill_index}: {h.hijack_alpha} EXIT "
                f"px={h.fill_price} realized=${h.realized_pnl:+.2f}  ({h.note})"
            )
    else:
        lines.append("\n[exit hijacks]  none detected")

    cs = report.collision_summary
    lines.append(
        f"\n[post-filter arbitration collisions — multialpha]  "
        f"{cs.post_filter_collision_ticks} tick(s) "
        f"({cs.harmless_flat_gate_close_ticks} harmless flat gate-close, "
        f"{cs.actionable_collision_ticks} actionable)"
    )
    if cs.kind_breakdown:
        for kind, count in sorted(cs.kind_breakdown.items()):
            lines.append(f"  {kind}: {count}")
    if report.arbitration_collisions:
        lines.append("  detail:")
        for i, row in enumerate(report.arbitration_collisions):
            tag = "harmless" if row.harmless else "actionable"
            lines.append(
                f"    [{i}] {row.candidate_count} candidates "
                f"({', '.join(row.strategy_ids)}) — {row.kind_key} [{tag}]"
            )

    lines.append(f"\n[attribution]  {report.attribution_warning}")

    # Per-alpha split for multialpha (informational)
    if report.multialpha.fill_legs:
        lines.append("\n[multialpha per-alpha cost survival (attribution artifact)]")
        for row in per_alpha_cost_survival(
            [
                TradeRecord(
                    order_id=leg.strategy_id + f":{leg.index}",
                    symbol=report.symbol,
                    strategy_id=leg.strategy_id,
                    side=Side[leg.side],
                    requested_quantity=leg.qty,
                    filled_quantity=leg.qty,
                    fill_price=leg.price,
                    signal_timestamp_ns=0,
                    submit_timestamp_ns=0,
                    fill_timestamp_ns=leg.fill_timestamp_ns,
                    cost_bps=Decimal("0"),
                    fees=leg.fees,
                    realized_pnl=leg.realized_pnl,
                    correlation_id="",
                    trading_intent=leg.trading_intent,
                )
                for leg in report.multialpha.fill_legs
            ]
        ):
            lines.append(
                f"  {row.strategy_id:<28s} fills={row.n_fills} net=${row.net:+,.2f}  {row.verdict}"
            )

    return "\n".join(lines) + "\n"


def _report_to_json(report: ComparisonReport) -> dict[str, Any]:
    def _serialize(obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return str(obj)
        if hasattr(obj, "__dataclass_fields__"):
            return {k: _serialize(v) for k, v in asdict(obj).items()}
        if isinstance(obj, tuple):
            return [_serialize(x) for x in obj]
        if isinstance(obj, dict):
            return {k: _serialize(v) for k, v in obj.items()}
        return obj

    return _serialize(report)


def compare_multialpha_runs(
    *,
    symbol: str,
    date: str,
    benign_config: Path,
    inventory_config: Path,
    multialpha_config: Path,
    cache_dir: Path | None,
    entry_alpha: str,
    hijack_alpha: str,
    quiet: bool = True,
) -> ComparisonReport:
    runner = _load_runner()
    try:
        event_log, ingest_result, day_meta = load_event_log_from_disk_cache(
            [symbol.upper()],
            date,
            date,
            cache_dir=cache_dir,
        )
    except CacheReplayError as exc:
        raise SystemExit(
            f"Disk cache miss for {symbol.upper()}/{date}: {exc}\n"
            "Populate with run_backtest.py first."
        ) from exc

    config_probe = PlatformConfig.from_yaml(benign_config)
    symbols = sorted(config_probe.symbols) or [symbol.upper()]
    symbol_str = ", ".join(symbols)
    day_sources = [
        runner.DaySource(
            symbol=m.symbol,
            date=m.date,
            source=m.source,
            event_count=m.event_count,
            ingestion_health=m.ingestion_health,
        )
        for m in day_meta
    ]
    prep = prepare_backtest_event_log(config_probe, event_log)
    rc = runner._enforce_ingest_event_mix(
        config_probe,
        prep.event_log,
        source_label="loaded from disk cache (compare_multialpha_runs)",
        n_quotes=prep.n_quotes,
        n_trades=prep.n_trades,
    )
    if rc != 0:
        raise SystemExit(f"Ingest event-mix enforcement failed (rc={rc})")

    common = dict(
        runner=runner,
        prep=prep,
        event_log=event_log,
        ingest_result=ingest_result,
        day_sources=day_sources,
        symbols=symbols,
        symbol_str=symbol_str,
        date=date,
        quiet=quiet,
    )
    benign, _ = _run_summary(config_path=benign_config, **common)
    inventory, _ = _run_summary(config_path=inventory_config, **common)
    multialpha, multi_collisions = _run_summary(config_path=multialpha_config, **common)

    return build_comparison_report(
        symbol=symbol.upper(),
        date=date,
        benign=benign,
        inventory=inventory,
        multialpha=multialpha,
        entry_alpha=entry_alpha,
        hijack_alpha=hijack_alpha,
        arbitration_collisions=multi_collisions,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Compare benign / inventory / multialpha backtest runs.",
    )
    p.add_argument("--symbol", required=True)
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--benign-config", type=Path, default=_DEFAULT_BENIGN)
    p.add_argument("--inventory-config", type=Path, default=_DEFAULT_INVENTORY)
    p.add_argument("--multialpha-config", type=Path, default=_DEFAULT_MULTIALPHA)
    p.add_argument("--cache-dir", type=Path, default=None)
    p.add_argument("--entry-alpha", default="sig_benign_midcap_v1")
    p.add_argument("--hijack-alpha", default="sig_inventory_revert_v1")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when exit hijacks or fill-count mismatch is detected.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print full backtest progress (default: quiet replays).",
    )
    args = p.parse_args(argv)

    for path in (args.benign_config, args.inventory_config, args.multialpha_config):
        if not path.is_file():
            print(f"ERROR: config not found: {path}", file=sys.stderr)
            return 1

    report = compare_multialpha_runs(
        symbol=args.symbol,
        date=args.date,
        benign_config=args.benign_config,
        inventory_config=args.inventory_config,
        multialpha_config=args.multialpha_config,
        cache_dir=args.cache_dir,
        entry_alpha=args.entry_alpha,
        hijack_alpha=args.hijack_alpha,
        quiet=not args.verbose,
    )

    if args.json:
        print(json.dumps(_report_to_json(report), indent=2, sort_keys=True))
    else:
        print(_format_human(report), end="")

    if args.strict:
        mismatch = any(d.multi_trading_intent == "FILL_COUNT_MISMATCH" for d in report.fill_diffs)
        if report.exit_hijacks or mismatch:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
