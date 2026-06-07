from pathlib import Path

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

args = parse_cache_replay_args([
    "--config", "configs/backtest_app.yaml",
    "--symbol", "APP",
    "--date", "2026-06-01",
    "--end-date", "2026-06-04",
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
rc = _enforce_ingest_event_mix(config, prep.event_log, source_label="loaded from disk cache", n_quotes=prep.n_quotes, n_trades=prep.n_trades)
if rc != 0:
    raise SystemExit(rc)
config = _attach_day_source_provenance(config, symbols, list(day_meta))
config = _ensure_backtest_session_anchor(config, first_event_ts_ns=prep.first_event_ts_ns)
orchestrator, config_out = build_platform(config, event_log=prep.event_log, signal_order_trace_sink=None, precomputed_ex_date_spans=prep.calendar_spans, regime_calibration_quotes=prep.regime_calibration_quotes)
rec = BusRecorder(skip_types=frozenset({SensorReading, NBBOQuote, MetricEvent}))
orchestrator._bus.subscribe_all(rec)
orchestrator.boot(config_out)
orchestrator.run_backtest()
records = list(orchestrator.trade_journal.query())
updates = rec.of_type(PositionUpdate)
print('TRADE_RECORDS', len(records))
print('POSITION_UPDATES', len(updates))
for r in records[:12]:
    matches = [u for u in updates if u.correlation_id == r.correlation_id]
    print('\nRECORD', 'order=', r.order_id, 'corr=', r.correlation_id, 'intent=', r.trading_intent, 'side=', r.side.name, 'fill_qty=', r.filled_quantity, 'fill_price=', r.fill_price, 'fees=', r.fees, 'realized=', r.realized_pnl)
    print(' MATCH_COUNT', len(matches))
    for u in matches[:6]:
        print('  PU', 'qty=', u.quantity, 'avg=', u.avg_price, 'realized=', u.realized_pnl, 'cfees=', u.cumulative_fees, 'ts=', u.timestamp_ns)
