"""CLI tests for ``feelies backtest``."""

from __future__ import annotations

from feelies.cli import backtest
from feelies.cli.main import _build_parser


def test_backtest_subcommand_is_registered() -> None:
    parser = _build_parser()
    args = parser.parse_args(["backtest", "--date", "2026-03-26", "--symbol", "APP"])
    assert args.command == "backtest"
    assert args.date == "2026-03-26"
    assert args.symbol == ["APP"]
    assert args.handler is backtest.run_backtest_handler
