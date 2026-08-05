"""Top-level CLI dispatcher for the ``feelies`` console script.

Subcommands live in their own modules under ``feelies.cli`` and
register themselves with the central :class:`argparse.ArgumentParser`
constructed here.  Each subcommand handler takes a parsed
:class:`argparse.Namespace` and returns an integer exit code; the
dispatcher propagates that code straight to the caller.

Exit-code convention:

  ``0``  success (subcommand ran and reported all-clear)
  ``1``  user error (missing args, unrecognised subcommand,
                     ledger path resolved to a non-existent file)
  ``2``  data error (corrupt ledger entries, malformed YAML config)
  ``3``  validation failed (e.g. ``replay-evidence`` found a
                            transition whose recorded evidence
                            no longer satisfies current thresholds), or
                            ``forensics circuit-breaker`` recommends a
                            quarantine that was not applied

Stable codes matter for CI integrations: an operator wiring the CLI
into a deployment gate can ``feelies promote validate --ledger
... && feelies promote replay-evidence ALPHA-ID --ledger ...`` and
distinguish "ledger corrupt" from "evidence stale".
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_DATA_ERROR = 2
EXIT_VALIDATION_FAILED = 3


def _build_parser(argv: Sequence[str] | None = None) -> argparse.ArgumentParser:
    """Build the parser, loading the optional backtest stack only when selected."""
    parser = argparse.ArgumentParser(
        prog="feelies",
        description=(
            "Operator command-line surface for the feelies trading "
            "platform.  Forensic tooling reads durable session artifacts and "
            "does not perturb replay determinism (audit A-DET-02).  Read-only "
            "except ``forensics circuit-breaker --apply``, which demotes a "
            "bleeding LIVE alpha to QUARANTINED."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    from feelies.cli import promote

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

    from feelies.cli import forensics

    forensics_parser = subparsers.add_parser(
        "forensics",
        help="Post-trade analysis over a finished session.",
        description=(
            "Subcommands that score a completed session's fills.  Read-only by "
            "default; ``circuit-breaker --apply`` is the one path that writes "
            "lifecycle state, and it only tightens (LIVE -> QUARANTINED)."
        ),
    )
    forensics.register(forensics_parser)

    selected = argv[0] if argv else None
    if selected == "backtest":
        from feelies.cli import backtest

        backtest.register(subparsers)
    else:
        subparsers.add_parser(
            "backtest",
            help="Run a historical backtest with Massive L1 data (loaded on demand).",
        )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``argv`` and dispatch to the matching subcommand handler.

    Returns the subcommand's integer exit code.  ``argv`` defaults to
    ``sys.argv[1:]`` when called from the console-script entry-point;
    test code passes a list explicitly.
    """
    resolved_argv = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser(resolved_argv)
    args = parser.parse_args(resolved_argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return EXIT_USER_ERROR
    result = handler(args)
    if not isinstance(result, int):
        raise TypeError(
            f"CLI subcommand handler {handler!r} must return int, got {type(result).__name__}"
        )
    return result


__all__ = [
    "EXIT_DATA_ERROR",
    "EXIT_OK",
    "EXIT_USER_ERROR",
    "EXIT_VALIDATION_FAILED",
    "main",
]
