"""``feelies backtest`` subcommand — historical L1 replay via Massive API."""

from __future__ import annotations

import argparse

from feelies.harness.backtest_cli import add_backtest_api_arguments
from feelies.harness.backtest_runner import (
    _configure_logging_for_cli,
    _force_utf8_console,
    run_backtest_api,
)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "backtest",
        help="Run a historical backtest with Massive L1 data.",
        description=(
            "Replay NBBO/trade events through the platform pipeline and "
            "print the operator report.  Requires MASSIVE_API_KEY in the "
            "environment (or .env).  Equivalent to "
            "``python scripts/run_backtest.py``."
        ),
    )
    add_backtest_api_arguments(parser)
    parser.set_defaults(handler=run_backtest_handler)


def run_backtest_handler(args: argparse.Namespace) -> int:
    _force_utf8_console()
    _configure_logging_for_cli()
    return run_backtest_api(args)


__all__ = ["register", "run_backtest_handler"]
