#!/usr/bin/env python3
"""Paper-trading runner — wires MassiveLiveFeed + IB Gateway end-to-end.

Usage::

    # Prerequisites:
    #   1. IB Gateway running on localhost:4002 with a *paper* account.
    #   2. MASSIVE_API_KEY exported (or in a local .env file).
    #
    # Standard run (uses ``platform.yaml`` from CWD):
    python scripts/run_paper.py
    python scripts/run_paper.py --config configs/paper_run.yaml

The script wires the platform like ``run_backtest.py`` does, then:

    1. ``orchestrator.boot(config)``                       — G0 → G2 boot
    2. ``orchestrator.ib_connection.connect_and_start()``  — IB handshake
    3. ``orchestrator.live_feed.start()``                  — Massive WS start
    4. ``orchestrator.run_paper()``                        — drive pipeline
    5. SIGINT handler → ``orchestrator.halt()`` (CMD_STOP → READY)
    6. ``finally:`` teardown — feed.stop → ib.disconnect_and_stop →
       ``orchestrator.shutdown()`` (which itself drains any final acks)

Note: this script is the *only* place the platform's wall-clock-driven
threads are spun up.  Backtest replay never touches this code path
(Inv-9 mode-swap parity), so the determinism parity hashes in
``tests/determinism/`` are unaffected by changes here.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from types import FrameType

# Ensure the project root is on sys.path so ``feelies`` is importable
# when running the script directly (e.g. ``python scripts/run_paper.py``).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from feelies.bootstrap import build_platform
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.macro import MacroState

logger = logging.getLogger("feelies.run_paper")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the feelies platform in PAPER mode against an IB "
                    "Gateway paper account and a live Massive WS feed.",
    )
    p.add_argument(
        "--config", default="platform.yaml",
        help="PlatformConfig YAML path (default: platform.yaml)",
    )
    p.add_argument(
        "--ib-ready-timeout-s", type=float, default=10.0,
        help="Seconds to wait for IB ``nextValidId`` handshake "
             "(default: 10.0)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)

    try:
        from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]
        load_dotenv()
    except ImportError:
        pass

    if not os.getenv("MASSIVE_API_KEY"):
        print(
            "ERROR: MASSIVE_API_KEY not set.\n"
            "Set it in your environment or in a .env file.",
            file=sys.stderr,
        )
        return 1

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        return 1

    config = PlatformConfig.from_yaml(config_path)
    if config.mode != OperatingMode.PAPER:
        print(
            f"ERROR: {config_path} has mode={config.mode.name}; "
            "run_paper.py requires mode: PAPER",
            file=sys.stderr,
        )
        return 1

    logger.info(
        "Booting PAPER platform: symbols=%s ib=%s:%d cid=%d ws=%s",
        sorted(config.symbols),
        config.ib_host, config.ib_port, config.ib_client_id,
        config.massive_ws_url,
    )

    orchestrator, _ = build_platform(config)
    live_feed = orchestrator.live_feed  # type: ignore[attr-defined]
    ib_connection = orchestrator.ib_connection  # type: ignore[attr-defined]
    assert live_feed is not None, "PAPER bootstrap must attach live_feed"
    assert ib_connection is not None, "PAPER bootstrap must attach ib_connection"

    _halt_requested = threading.Event()

    def _handle_sigint(signum: int, frame: FrameType | None) -> None:
        logger.warning("SIGINT received → orchestrator.halt()")
        _halt_requested.set()
        try:
            orchestrator.halt()
        except Exception:
            logger.exception("halt() raised")

    signal.signal(signal.SIGINT, _handle_sigint)

    try:
        orchestrator.boot(config)
        if orchestrator.macro_state != MacroState.READY:
            logger.error(
                "Boot failed — macro state is %s, expected READY",
                orchestrator.macro_state.name,
            )
            return 1
        ib_connection.connect_and_start(ready_timeout_s=args.ib_ready_timeout_s)
        live_feed.start()
        if not _halt_requested.is_set():
            orchestrator.run_paper()
    except Exception:
        logger.exception("PAPER session failed")
        return 1
    finally:
        # Tear down in reverse start order.  Drain happens at the top
        # of ``orchestrator.shutdown`` so any in-flight IB fills land
        # in the trade journal before we disconnect.
        try:
            live_feed.stop()
        except Exception:
            logger.exception("live_feed.stop() raised")
        try:
            ib_connection.disconnect_and_stop()
        except Exception:
            logger.exception("ib_connection.disconnect_and_stop() raised")
        try:
            orchestrator.shutdown()
        except Exception:
            logger.exception("orchestrator.shutdown() raised")

    logger.info("PAPER session complete; exit 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
