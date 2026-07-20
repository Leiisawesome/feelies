"""Read-only operator commands for promotion-ledger forensics.

The CLI stays outside the per-tick path and never mutates the ledger,
so invoking it cannot affect replay.
"""


def __getattr__(name: str) -> object:
    if name == "main":
        from feelies.cli.main import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["main"]
