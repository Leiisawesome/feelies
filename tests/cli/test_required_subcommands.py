"""A missing subcommand is an argparse usage error, exit 2.

``feelies``, ``feelies forensics``, and ``feelies promote`` each require a
subcommand. The requirement is an ``add_subparsers(required=True)`` argument.
"""

from __future__ import annotations

import pytest

from feelies.cli.main import main


@pytest.mark.parametrize(
    ("argv", "prog", "named"),
    [
        ([], "feelies", "<command>"),
        (["forensics"], "feelies forensics", "<subcommand>"),
        (["promote"], "feelies promote", "<subcommand>"),
    ],
    ids=("feelies", "feelies forensics", "feelies promote"),
)
def test_missing_subcommand_is_usage_error_exit_2(
    argv: list[str],
    prog: str,
    named: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith(f"usage: {prog} ")
    assert f"{prog}: error: the following arguments are required: {named}" in err
