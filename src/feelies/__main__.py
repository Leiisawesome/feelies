"""Top-level ``python -m feelies`` entry-point.

Delegates to :func:`feelies.cli.main.main`.  The same dispatcher backs
the ``feelies`` console script registered via ``[project.scripts]`` in
``pyproject.toml`` and the ``python -m feelies.cli`` invocation, so
all three routes share identical behaviour.
"""

from __future__ import annotations

import sys

from feelies.cli.main import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
