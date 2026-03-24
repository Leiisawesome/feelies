#!/usr/bin/env python3
"""Launch the Feelies operator workbench."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from feelies.ui.server import serve_workbench


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Feelies operator workbench.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    parser.add_argument(
        "--config",
        default="platform.yaml",
        help="Platform config path used for bootstrap defaults (default: platform.yaml)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    serve_workbench(args.host, args.port, config_path=args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())