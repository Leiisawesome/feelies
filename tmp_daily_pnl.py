import argparse
from datetime import datetime, timezone
from decimal import Decimal
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

_TZ_ET = ZoneInfo('America/New_York')

args = parse_cache_replay_args([
    '--config', 'configs/backtest_app.yaml',
    '--symbol', 'APP',
    '--date', '2026-05-26',
    '--end-date', '2026-05-29',
])
config = _load_backtest_config(args)
if config is None:
    raise SystemExit('No config')
symbols = resolve_backtest_symbols(config)
print('symbols', symbols)

cache_path = Path(args.cache_dir) if getattr(args, 'cache_dir', None) else None
event_log, ingest_result, day_meta = load_event_log_from_disk_cache(
    symbols,
    args.date,
    args.end_date or args.date,
    cache_dir=cache_path,
    require_healthy_ingestion_manifests=config.require_healthy_disk_cache_manifests,
)
prep = prepare_backtest_event_log(config, event_log)
rc = _enforce_ingest_event_mix(config, prep.event_log, source_label='loaded from disk cache', n_quotes=prep.n_quotes, n_trades=prep.n_trades)
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

print('macro', orchestrator.macro_state)
print('account_equity_before', orchestrator.account_equity)

orchestrator.run_backtest()

pos_updates = recorder.of_type(PositionUpdate)
print('position_updates', len(pos_updates))

starting_equity = Decimal('100000')
current_realized = {}
current_unrealized = {}
current_fees = {}
current_equity = starting_equity
last_day = None
end_equity_by_day = {}

def et_date(ts_ns):
    return datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=timezone.utc).astimezone(_TZ_ET).date().isoformat()

for pu in pos_updates:
    day = et_date(pu.timestamp_ns)
    if last_day is not None and day != last_day:
        end_equity_by_day[last_day] = current_equity
    current_realized[pu.symbol] = pu.realized_pnl
    current_unrealized[pu.symbol] = pu.unrealized_pnl
    current_fees[pu.symbol] = pu.cumulative_fees
    current_equity = (
        starting_equity
        + sum(current_realized.values(), Decimal('0'))
        - sum(current_fees.values(), Decimal('0'))
        + sum(current_unrealized.values(), Decimal('0'))
    )
    last_day = day

if last_day is not None:
    end_equity_by_day[last_day] = current_equity

print('end_equity_by_day', {k: str(v) for k, v in sorted(end_equity_by_day.items())})

prev = None
for day in sorted(end_equity_by_day):
    eq = end_equity_by_day[day]
    pnl = eq - (end_equity_by_day[prev] if prev is not None else starting_equity)
    print(f'{day}: equity={float(eq):.2f}, daily_pnl={float(pnl):.2f}')
    prev = day

print('final_equity', float(current_equity))
print('final_minus_start', float(current_equity - starting_equity))
