"""``feelies backtest`` subcommand — historical L1 replay via Massive API."""

from __future__ import annotations

import argparse
import sys

from feelies.cli.env import MASSIVE_API_KEY_ERROR, load_dotenv_optional, massive_api_key_from_env
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
    load_dotenv_optional()
    api_key = massive_api_key_from_env()
    if api_key is None:
        print(MASSIVE_API_KEY_ERROR, file=sys.stderr)
        return 1
    return run_backtest_api(args, api_key=api_key)


__all__ = ["register", "run_backtest_handler"]
