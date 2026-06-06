from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from feelies.bootstrap import build_platform
from feelies.core.events import MetricEvent, NBBOQuote, SensorReading
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

args = parse_cache_replay_args([
    "--config", "configs/backtest_app.yaml",
    "--symbol", "APP",
    "--date", "2026-05-26",
    "--end-date", "2026-05-29",
])
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

_skip = {SensorReading, NBBOQuote, MetricEvent}
recorder = BusRecorder(skip_types=frozenset(_skip))
orchestrator._bus.subscribe_all(recorder)
orchestrator.boot(config_out)
orchestrator.run_backtest()

journal = orchestrator.trade_journal
records = list(journal.query()) if journal is not None else []
print("TRADE_RECORDS", len(records))

def et_date(ts_ns: int | None) -> str:
    if ts_ns is None:
        return "UNKNOWN"
    return datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=timezone.utc).astimezone(_TZ_ET).date().isoformat()

by_day = defaultdict(Decimal)
for rec in records:
    by_day[et_date(rec.fill_timestamp_ns)] += rec.realized_pnl

print("BY_DAY_REALIZED")
for day in sorted(by_day):
    print(day, float(by_day[day]))

print("SAMPLE_RECORDS")
for rec in records[:10]:
    print(et_date(rec.fill_timestamp_ns), rec.symbol, rec.side, float(rec.realized_pnl), rec.order_id)
