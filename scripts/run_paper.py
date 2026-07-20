#!/usr/bin/env python3
"""Run paper trading with Massive market data and IB Gateway.

Usage::

    # Prerequisites:
    #   1. IB Gateway running on localhost:4002 with a *paper* account.
    #   2. MASSIVE_API_KEY exported (or in a local .env file).
    #
    # Standard run (uses ``platform.yaml`` from CWD):
    python scripts/run_paper.py
    python scripts/run_paper.py --config configs/paper_run.yaml
    python scripts/run_paper.py --config configs/paper_smoke_rth.yaml \\
        --max-runtime-s 600 --run-dir runs/paper_$(date +%F)

The runner boots the platform, starts IB and the live feed, runs the paper
pipeline, handles SIGINT, drains acknowledgements, and disconnects. Backtests do
not execute this wall-clock-driven path.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType

# Add the source tree for direct script execution.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from feelies.bootstrap import build_platform
from feelies.cli.env import MASSIVE_API_KEY_ERROR, load_dotenv_optional, massive_api_key_from_env
from feelies.core.errors import ConfigurationError
from feelies.core.events import OrderAck, Signal
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.harness.backtest_cli import ConfigNotFoundError, load_platform_config
from feelies.kernel.macro import MacroState
from feelies.monitoring.paper_session_recorder import (
    PaperSessionRecorder,
    trade_records_to_dicts,
)

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
        "--config",
        default="platform.yaml",
        help="PlatformConfig YAML path (default: platform.yaml)",
    )
    p.add_argument(
        "--ib-ready-timeout-s",
        type=float,
        default=10.0,
        help="Seconds to wait for IB ``nextValidId`` handshake (default: 10.0)",
    )
    p.add_argument(
        "--max-runtime-s",
        type=float,
        default=None,
        help="Auto-halt after N seconds (calls orchestrator.halt())",
    )
    p.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Session output directory for JSONL artefacts",
    )
    p.add_argument(
        "--emit-order-acks-jsonl",
        action="store_true",
        help="Write order_acks.jsonl to --run-dir",
    )
    p.add_argument(
        "--emit-signals-jsonl",
        action="store_true",
        help="Write signals.jsonl to --run-dir",
    )
    p.add_argument(
        "--emit-fills-jsonl",
        action="store_true",
        help="Write fills.jsonl from trade journal to --run-dir",
    )
    p.add_argument(
        "--emit-timing-jsonl",
        action="store_true",
        help="Write timing.jsonl to --run-dir",
    )
    p.add_argument(
        "--strict-config",
        action="store_true",
        help=(
            "Fail closed on unrecognized config keys (a misspelled override "
            "aborts the run instead of silently keeping the default)."
        ),
    )
    return p.parse_args(argv)


def _wire_session_recorder(
    orchestrator: object,
    args: argparse.Namespace,
    config: PlatformConfig,
) -> PaperSessionRecorder | None:
    if args.run_dir is None:
        return None
    run_dir = args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    recorder = PaperSessionRecorder(
        run_dir=run_dir,
        emit_signals=args.emit_signals_jsonl,
        emit_order_acks=args.emit_order_acks_jsonl,
        emit_timing=args.emit_timing_jsonl,
    )
    metadata = {
        "mode": config.mode.name,
        "symbols": sorted(config.symbols),
        "session_start_ns": int(datetime.now(UTC).timestamp() * 1_000_000_000),
        "config_path": str(args.config),
        "session_open_ns": config.session_open_ns,
    }
    recorder.write_metadata(metadata)
    orchestrator.set_paper_session_recorder(recorder)  # type: ignore[attr-defined]
    bus = orchestrator._bus  # type: ignore[attr-defined]

    def _on_event(event: object) -> None:
        recorder.on_event(event)  # type: ignore[arg-type]

    if args.emit_signals_jsonl:
        bus.subscribe(Signal, _on_event)
    if args.emit_order_acks_jsonl:
        bus.subscribe(OrderAck, _on_event)
    return recorder


def _flush_session_recorder(
    orchestrator: object,
    recorder: PaperSessionRecorder | None,
    args: argparse.Namespace,
) -> None:
    if recorder is None:
        return
    if args.emit_fills_jsonl:
        journal = orchestrator.trade_journal  # type: ignore[attr-defined]
        if journal is not None:
            records = list(journal.query())
            recorder.write_fills(trade_records_to_dicts(records))
    metadata_path = args.run_dir / "metadata.json"  # type: ignore[union-attr]
    if metadata_path.is_file():
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        data["session_end_ns"] = int(datetime.now(UTC).timestamp() * 1_000_000_000)
        metadata_path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    recorder.flush()


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)

    load_dotenv_optional()

    if massive_api_key_from_env() is None:
        print(MASSIVE_API_KEY_ERROR, file=sys.stderr)
        return 1

    try:
        config = load_platform_config(args.config, strict=args.strict_config)
    except ConfigNotFoundError as exc:
        print(f"ERROR: Config file not found: {exc.path}", file=sys.stderr)
        return 1
    except ConfigurationError as exc:
        print(f"ERROR: Invalid config: {exc}", file=sys.stderr)
        return 1
    if config.mode != OperatingMode.PAPER:
        print(
            f"ERROR: {args.config} has mode={config.mode.name}; run_paper.py requires mode: PAPER",
            file=sys.stderr,
        )
        return 1

    logger.info(
        "Booting PAPER platform: symbols=%s ib=%s:%d cid=%d ws=%s",
        sorted(config.symbols),
        config.ib_host,
        config.ib_port,
        config.ib_client_id,
        config.massive_ws_url,
    )

    orchestrator, _ = build_platform(config)
    live_feed = orchestrator.live_feed  # type: ignore[attr-defined]
    ib_connection = orchestrator.ib_connection  # type: ignore[attr-defined]
    assert live_feed is not None, "PAPER bootstrap must attach live_feed"
    assert ib_connection is not None, "PAPER bootstrap must attach ib_connection"

    session_recorder = _wire_session_recorder(orchestrator, args, config)

    _halt_requested = threading.Event()
    _max_runtime_timer: threading.Timer | None = None

    def _handle_sigint(signum: int, frame: FrameType | None) -> None:
        logger.warning("SIGINT received → orchestrator.halt()")
        _halt_requested.set()
        try:
            orchestrator.halt()
        except Exception:
            logger.exception("halt() raised")

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _handle_sigint)
    else:
        logger.debug("Skipping SIGINT handler (not main thread)")

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
        if args.max_runtime_s is not None and args.max_runtime_s > 0:

            def _timer_halt() -> None:
                logger.info(
                    "max-runtime-s=%s elapsed → orchestrator.halt()",
                    args.max_runtime_s,
                )
                _halt_requested.set()
                try:
                    orchestrator.halt()
                except Exception:
                    logger.exception("max-runtime timer halt() raised")

            _max_runtime_timer = threading.Timer(
                args.max_runtime_s,
                _timer_halt,
            )
            _max_runtime_timer.daemon = True
            _max_runtime_timer.start()
        if not _halt_requested.is_set():
            orchestrator.run_paper()
    except Exception:
        logger.exception("PAPER session failed")
        return 1
    finally:
        if _max_runtime_timer is not None:
            _max_runtime_timer.cancel()
        try:
            orchestrator.shutdown()
        except Exception:
            logger.exception("orchestrator.shutdown() raised")
        try:
            live_feed.stop()
        except Exception:
            logger.exception("live_feed.stop() raised")
        try:
            ib_connection.disconnect_and_stop()
        except Exception:
            logger.exception("ib_connection.disconnect_and_stop() raised")
        try:
            _flush_session_recorder(orchestrator, session_recorder, args)
        except Exception:
            logger.exception("session recorder flush raised")

    logger.info("PAPER session complete; exit 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
