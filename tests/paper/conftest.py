"""Shared fixtures for paper-RTH integration and functional tests."""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pytest

from tests._ib_client_id import unique_ib_client_id

if TYPE_CHECKING:
    from feelies.bus.event_bus import EventBus
    from feelies.kernel.orchestrator import Orchestrator

_ET = ZoneInfo("America/New_York")
_DEFAULT_IB_HOST = "127.0.0.1"
_DEFAULT_IB_PORT = 4002


def require_rth_window() -> None:
    """Skip unless inside US regular trading hours (or override set)."""
    if os.getenv("PAPER_RTH_FORCE", "").strip() == "1":
        return
    if os.getenv("PAPER_RTH_EXTENDED", "").strip() == "1":
        now = datetime.now(_ET)
        open_t = now.replace(hour=4, minute=0, second=0, microsecond=0)
        close_t = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if not (open_t <= now <= close_t):
            pytest.skip("Outside extended RTH window (4:00–20:00 ET)")
        return
    now = datetime.now(_ET)
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if not (open_t <= now <= close_t):
        pytest.skip("Outside US RTH (9:30–16:00 ET); set PAPER_RTH_FORCE=1 to override")


def require_ib_gateway(
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Skip when IB Gateway is not reachable on the configured port."""
    h = host or os.getenv("IB_FUNCTIONAL_HOST", _DEFAULT_IB_HOST)
    p = port or int(os.getenv("IB_FUNCTIONAL_PORT", str(_DEFAULT_IB_PORT)))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    try:
        sock.connect((h, p))
    except OSError as exc:
        pytest.skip(
            f"IB Gateway not reachable at {h}:{p} ({exc}). "
            "Start IB Gateway (paper) and enable API connections.",
        )
    finally:
        sock.close()


def require_massive_api_key() -> str:
    key = (os.getenv("MASSIVE_API_KEY") or "").strip()
    if not key:
        pytest.skip("Set MASSIVE_API_KEY to run Massive functional tests.")
    return key


@pytest.fixture
def ib_client_id() -> int:
    return unique_ib_client_id()


@pytest.fixture
def paper_rth_guards() -> None:
    require_rth_window()
    require_ib_gateway()
    require_massive_api_key()


def session_open_ns_for_today() -> int:
    """9:30 America/New_York anchor for the current calendar day."""
    today = datetime.now(_ET).date()
    open_dt = datetime(
        today.year,
        today.month,
        today.day,
        9,
        30,
        tzinfo=_ET,
    )
    return int(open_dt.timestamp() * 1_000_000_000)


@pytest.fixture
def paper_session(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[
    tuple[Orchestrator, EventBus, Path, threading.Thread],
    None,
    None,
]:
    """Run ``run_paper.main`` in-process; capture orchestrator + bus."""
    require_rth_window()
    require_ib_gateway()
    require_massive_api_key()

    import importlib.util
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    run_paper_path = repo_root / "scripts" / "run_paper.py"
    spec = importlib.util.spec_from_file_location("run_paper", run_paper_path)
    assert spec is not None and spec.loader is not None
    run_paper = importlib.util.module_from_spec(spec)
    sys.modules["run_paper"] = run_paper
    spec.loader.exec_module(run_paper)

    from feelies import bootstrap
    from feelies.kernel.macro import MacroState

    captured: dict[str, Any] = {}
    orig_build = bootstrap.build_platform

    def capturing_build(config: object) -> tuple[object, object]:
        orchestrator, returned_config = orig_build(config)
        captured["orchestrator"] = orchestrator
        captured["bus"] = orchestrator._bus
        return orchestrator, returned_config

    monkeypatch.setattr("run_paper.build_platform", capturing_build)

    run_dir = tmp_path / "paper_run"
    run_dir.mkdir()
    config_path = repo_root / "configs" / "paper_smoke_rth.yaml"
    if not config_path.is_file():
        pytest.skip(f"Missing smoke config: {config_path}")

    max_runtime_s = int(os.getenv("PAPER_E2E_MAX_RUNTIME_S", "60"))
    if request.node.get_closest_marker("slow") is not None:
        max_runtime_s = max(max_runtime_s, 130)
    errors: list[BaseException] = []

    def _run() -> None:
        try:
            rc = run_paper.main(
                [
                    "--config",
                    str(config_path),
                    "--run-dir",
                    str(run_dir),
                    "--max-runtime-s",
                    str(max_runtime_s),
                ]
            )
            captured["exit_code"] = rc
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=_run, name="paper-e2e", daemon=True)
    thread.start()

    orchestrator = None
    bus = None
    captured_at: float | None = None
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        orchestrator = captured.get("orchestrator")
        bus = captured.get("bus")
        if orchestrator is not None and captured_at is None:
            captured_at = time.monotonic()
        if orchestrator is not None:
            if orchestrator.macro_state == MacroState.PAPER_TRADING_MODE:
                break
            if captured_at is not None and time.monotonic() - captured_at > 90.0:
                break
        if not thread.is_alive() and orchestrator is not None:
            break
        time.sleep(0.1)

    if orchestrator is None or bus is None:
        thread.join(timeout=5.0)
        if errors:
            raise errors[0]
        pytest.fail("paper_session: orchestrator not captured from build_platform")

    if orchestrator.macro_state != MacroState.PAPER_TRADING_MODE:
        thread.join(timeout=5.0)
        if errors:
            raise errors[0]
        pytest.fail(
            "paper_session: macro never reached PAPER_TRADING_MODE "
            f"(state={orchestrator.macro_state.name}, "
            f"exit_code={captured.get('exit_code')})",
        )

    try:
        yield orchestrator, bus, run_dir, thread
    finally:
        try:
            orchestrator.halt()
        except Exception:
            pass
        thread.join(timeout=max_runtime_s + 30.0)
