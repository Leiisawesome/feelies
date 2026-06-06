from pathlib import Path

from feelies.bootstrap import build_platform
from decimal import Decimal

from feelies.core.events import Alert, OrderRequest, PositionUpdate, RiskVerdict
from feelies.harness.backtest_cli import resolve_backtest_symbols
from feelies.harness.backtest_prep import prepare_backtest_event_log
from feelies.harness.backtest_runner import (
    BusRecorder,
    _attach_day_source_provenance,
    _ensure_backtest_session_anchor,
    _enforce_ingest_event_mix,
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
print("CONFIG", "enforce_per_alpha_risk_budget=", config.enforce_per_alpha_risk_budget, "max_gross_exposure_pct=", config.risk_max_gross_exposure_pct, "max_position_per_symbol=", config.risk_max_position_per_symbol, "account_equity=", config.account_equity)

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
print("RC", rc, "quotes", prep.n_quotes, "trades", prep.n_trades, "first_ts", prep.first_event_ts_ns)
config = _attach_day_source_provenance(config, symbols, list(day_meta))
config = _ensure_backtest_session_anchor(config, first_event_ts_ns=prep.first_event_ts_ns)

orchestrator, config_out = build_platform(
    config,
    event_log=prep.event_log,
    signal_order_trace_sink=None,
    precomputed_ex_date_spans=prep.calendar_spans,
    regime_calibration_quotes=prep.regime_calibration_quotes,
)
rec = BusRecorder(skip_types=frozenset())
orchestrator._bus.subscribe_all(rec)
orchestrator.boot(config_out)
orchestrator.run_backtest()

for event_type in (RiskVerdict, OrderRequest, Alert):
    items = rec.of_type(event_type)
    print("\nTYPE", event_type.__name__, "COUNT", len(items))
    if event_type is RiskVerdict:
        for e in items[:10]:
            print("  RISK", e.action, "symbol=", e.symbol, "reason=", e.reason, "seq=", e.sequence)
    elif event_type is OrderRequest:
        for e in items[:15]:
            print("  ORDER", "side=", getattr(e, "side", None), "symbol=", e.symbol, "qty=", e.quantity, "limit=", e.limit_price, "strategy=", getattr(e, "strategy_id", None), "corr=", e.correlation_id)
    else:
        for e in items[:10]:
            print("  ALERT", e.alert_name, "sev=", e.severity, "msg=", e.message)

position_updates = rec.of_type(PositionUpdate)
print("\nPOSITION_UPDATES", len(position_updates))
max_exposure = Decimal('0')
max_pct = 0.0
starting_equity = Decimal('50000')
for pu in position_updates:
    total_exposure = abs(Decimal(str(pu.quantity))) * pu.avg_price
    current_equity = starting_equity + pu.realized_pnl - pu.cumulative_fees + pu.unrealized_pnl
    pct = float(total_exposure / current_equity * Decimal('100')) if current_equity != 0 else 0.0
    if total_exposure > max_exposure:
        max_exposure = total_exposure
        max_pct = pct
print("MAX_EXPOSURE_FROM_UPDATES", max_exposure, "PCT", max_pct, "EQUITY_AT_MAX", starting_equity + position_updates[position_updates.index(max(position_updates, key=lambda x: abs(Decimal(str(x.quantity))) * x.avg_price))].realized_pnl - position_updates[position_updates.index(max(position_updates, key=lambda x: abs(Decimal(str(x.quantity))) * x.avg_price))].cumulative_fees + position_updates[position_updates.index(max(position_updates, key=lambda x: abs(Decimal(str(x.quantity))) * x.avg_price))].unrealized_pnl)

print("\nFINAL POSITIONS")
for sym, p in sorted(orchestrator.position_store.all_positions().items()):
    print(" ", sym, "qty=", p.quantity, "avg_entry=", p.avg_entry_price, "unreal=", p.unrealized_pnl, "real=", p.realized_pnl, "fees=", p.cumulative_fees)
print("TOTAL_EXPOSURE", orchestrator.position_store.total_exposure())
print("OPEN_POSITION_COUNT", sum(1 for p in orchestrator.position_store.all_positions().values() if p.quantity != 0))
print("TRADE_JOURNAL_RECORDS", len(list(orchestrator.trade_journal.query())) if orchestrator.trade_journal is not None else None)
