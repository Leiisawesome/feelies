"""Top-level CLI dispatcher for the ``feelies`` console script.

Subcommands live in their own modules under ``feelies.cli`` and
register themselves with the central :class:`argparse.ArgumentParser`
constructed here.  Each subcommand handler takes a parsed
:class:`argparse.Namespace` and returns an integer exit code; the
dispatcher propagates that code straight to the caller.

Exit-code convention (Workstream F-3):

  ``0``  success (subcommand ran and reported all-clear)
  ``1``  user error (missing args, unrecognised subcommand,
                     ledger path resolved to a non-existent file)
  ``2``  data error (corrupt ledger entries, malformed YAML config)
  ``3``  validation failed (e.g. ``replay-evidence`` found a
                            transition whose recorded evidence
                            no longer satisfies current thresholds)

Stable codes matter for CI integrations: an operator wiring the CLI
into a deployment gate can ``feelies promote validate --ledger
... && feelies promote replay-evidence ALPHA-ID --ledger ...`` and
distinguish "ledger corrupt" from "evidence stale".
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from feelies.cli import promote


EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_DATA_ERROR = 2
EXIT_VALIDATION_FAILED = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feelies",
        description=(
            "Operator command-line surface for the feelies trading "
            "platform.  Read-only forensic tooling — does not perturb "
            "replay determinism (audit A-DET-02)."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    promote_parser = subparsers.add_parser(
        "promote",
        help="Inspect and audit the alpha-promotion ledger.",
        description=(
            "Subcommands that read the append-only promotion-evidence "
            "ledger written by AlphaLifecycle on every committed "
            "lifecycle transition.  See "
            "src/feelies/alpha/promotion_ledger.py for the writer "
            "contract."
        ),
    )
    promote.register(promote_parser)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and dispatch to the matching subcommand handler.

    Returns the subcommand's integer exit code.  ``argv`` defaults to
    ``sys.argv[1:]`` when called from the console-script entry-point;
    test code passes a list explicitly.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return EXIT_USER_ERROR
    result = handler(args)
    if not isinstance(result, int):
        raise TypeError(
            f"CLI subcommand handler {handler!r} must return int, "
            f"got {type(result).__name__}"
        )
    return result


__all__ = [
    "EXIT_DATA_ERROR",
    "EXIT_OK",
    "EXIT_USER_ERROR",
    "EXIT_VALIDATION_FAILED",
    "main",
]
