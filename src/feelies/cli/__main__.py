"""Module entry-point so ``python -m feelies <subcommand>`` works.

Mirrors the ``[project.scripts]`` ``feelies`` console-script entry —
both routes call :func:`feelies.cli.main.main` and propagate its
return value to ``sys.exit``.
"""

from __future__ import annotations

import sys

from feelies.cli.main import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
