from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from feelies.bootstrap import build_platform
from feelies.core.events import MetricEvent, NBBOQuote, PositionUpdate, SensorReading
from feelies.harness.backtest_cli import resolve_backtest_symbols
from feelies.harness.backtest_prep import prepare_backtest_event_log
from feelies.harness.backtest_runner import (
    BusRecorder,
    _attach_day_source_provenance,
    _enforce_ingest_event_mix,
    _ensure_backtest_session_anchor,
    _load_backtest_config,
    parse_cache_replay_args,
)
from feelies.storage.cache_replay import load_event_log_from_disk_cache

_TZ_ET = ZoneInfo("America/New_York")
_CENTS = Decimal("0.01")


def fmt_money(value: Decimal) -> str:
    return format(value.quantize(_CENTS, rounding=ROUND_HALF_UP), ".2f")


def fmt_ts(ns: int | None) -> str:
    if ns is None:
        return ""
    return (
        datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc)
        .astimezone(_TZ_ET)
        .isoformat(timespec="seconds")
    )


def signal_type_from_intent(name: str, strategy_id: str = "") -> str:
    if strategy_id == "__stop_exit__":
        return "reversal"

    normalized = name.strip().lower()
    if normalized.startswith("entry_"):
        return "entry"
    if normalized.startswith("reverse_"):
        return "reversal"
    if normalized == "exit":
        return "exit"
    return normalized.replace("_", " ")


def direction_from_quantity(quantity: int) -> str:
    if quantity > 0:
        return "long"
    if quantity < 0:
        return "short"
    return "flat"


def main() -> None:
    args = parse_cache_replay_args(
        [
            "--config",
            "configs/backtest_app.yaml",
            "--symbol",
            "APP",
            "--date",
            "2026-06-01",
            "--end-date",
            "2026-06-04",
        ]
    )
    config = _load_backtest_config(args)
    if config is None:
        raise SystemExit("No config")

    symbols = resolve_backtest_symbols(config)
    cache_path = Path(args.cache_dir) if getattr(args, "cache_dir", None) else None

    event_log, ingest_result, day_meta = load_event_log_from_disk_cache(
        symbols,
        args.date,
        args.end_date or args.date,
        cache_dir=cache_path,
        require_healthy_ingestion_manifests=config.require_healthy_disk_cache_manifests,
    )
    prep = prepare_backtest_event_log(config, event_log)
    rc = _enforce_ingest_event_mix(
        config,
        prep.event_log,
        source_label="loaded from disk cache",
        n_quotes=prep.n_quotes,
        n_trades=prep.n_trades,
    )
    if rc != 0:
        raise SystemExit(rc)

    config = _attach_day_source_provenance(config, symbols, list(day_meta))
    config = _ensure_backtest_session_anchor(config, first_event_ts_ns=prep.first_event_ts_ns)

    orchestrator, config_out = build_platform(
        config,
        event_log=prep.event_log,
        signal_order_trace_sink=None,
        precomputed_ex_date_spans=prep.calendar_spans,
        regime_calibration_quotes=prep.regime_calibration_quotes,
    )
    recorder = BusRecorder(skip_types=frozenset({SensorReading, NBBOQuote, MetricEvent}))
    orchestrator._bus.subscribe_all(recorder)
    orchestrator.boot(config_out)
    orchestrator.run_backtest()

    records = (
        list(orchestrator.trade_journal.query()) if orchestrator.trade_journal is not None else []
    )
    position_updates = recorder.of_type(PositionUpdate)
    position_updates_by_ts: dict[int, PositionUpdate] = {
        pu.timestamp_ns: pu for pu in position_updates
    }

    output_path = Path("docs/app_trade_list_full.csv")
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "time",
                "signal_type",
                "direction",
                "current_position",
                "entry_price",
                "fill_price",
                "qty",
                "cost",
                "realized_pnl",
                "net_pnl_after_cost",
            ]
        )

        for rec in records:
            pu = position_updates_by_ts.get(rec.fill_timestamp_ns)
            qty = pu.quantity if pu is not None else rec.filled_quantity
            entry_price = rec.fill_price or Decimal("0")
            writer.writerow(
                [
                    fmt_ts(rec.fill_timestamp_ns),
                    signal_type_from_intent(rec.trading_intent or "", rec.strategy_id),
                    direction_from_quantity(qty),
                    qty,
                    fmt_money(entry_price),
                    fmt_money(rec.fill_price or Decimal("0")),
                    rec.filled_quantity,
                    fmt_money(rec.fees),
                    fmt_money(rec.realized_pnl),
                    fmt_money(rec.realized_pnl - rec.fees),
                ]
            )

    print(f"WROTE {len(records)} trades to {output_path}")


if __name__ == "__main__":
    main()
