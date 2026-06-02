"""Shared harness helpers for backtest and replay operator scripts."""

from feelies.harness.backtest_cli import (
    apply_backtest_cli_overrides,
    add_backtest_api_arguments,
    load_platform_config,
    resolve_backtest_symbols,
)
from feelies.harness.backtest_jsonl import emit_signals_jsonl
from feelies.harness.backtest_prep import (
    BacktestEventLogPrep,
    QuoteReplayObserver,
    QuoteTraceEntry,
    QuoteTraceIndex,
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
from feelies.harness.backtest_runner import (
    BacktestRunOutcome,
    BusRecorder,
    main,
    main_cache_replay,
    run_backtest_api,
)

__all__ = [
    "BacktestEventLogPrep",
    "BacktestRunOutcome",
    "BusRecorder",
    "QuoteReplayObserver",
    "QuoteTraceEntry",
    "QuoteTraceIndex",
    "add_backtest_api_arguments",
    "apply_backtest_cli_overrides",
    "compute_combined_parity_hash",
    "compute_config_hash",
    "compute_parity_hash",
    "emit_signals_jsonl",
    "format_section",
    "generate_report",
    "live_data_version",
    "load_platform_config",
    "main",
    "main_cache_replay",
    "prepare_backtest_event_log",
    "resolve_backtest_symbols",
    "run_backtest_api",
    "run_verification",
]
