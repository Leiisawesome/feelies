"""CLI tests for ``feelies backtest``."""

from __future__ import annotations

from feelies.cli import backtest
from feelies.cli.main import _build_parser


def test_backtest_subcommand_is_registered() -> None:
    # Audit P1-3: subcommands are registered lazily, so the real
    # ``backtest`` parser (with its args + handler) is wired only when
    # ``backtest`` is the selected command.  ``main(argv)`` passes the
    # real argv through, so production invocation is unaffected.
    argv = ["backtest", "--date", "2026-03-26", "--symbol", "APP"]
    parser = _build_parser(argv)
    args = parser.parse_args(argv)
    assert args.command == "backtest"
    assert args.date == "2026-03-26"
    assert args.symbol == ["APP"]
    assert args.handler is backtest.run_backtest_handler
