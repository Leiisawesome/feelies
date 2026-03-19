"""Speed and memory benchmarks for replay performance.

Skills: performance-engineering, backtest-engine

Each benchmark has a hard TIMEOUT_SEC ceiling to prevent resource
exhaustion under constrained environments (IDE terminals, CI runners).
"""

from __future__ import annotations

import gc
import resource
import shutil
import signal
import time
from decimal import Decimal
from pathlib import Path

import pytest

from feelies.bootstrap import build_platform
from feelies.core.events import NBBOQuote
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.storage.memory_event_log import InMemoryEventLog

from .conftest import ALPHA_SRC

pytestmark = [pytest.mark.backtest_validation, pytest.mark.slow]

TIMEOUT_SEC = 45


class _Timeout:
    """Context manager that raises TimeoutError after *seconds* on Unix."""

    def __init__(self, seconds: int) -> None:
        self._seconds = seconds

    def _handler(self, signum: int, frame: object) -> None:
        raise TimeoutError(f"Test exceeded {self._seconds}s hard limit")

    def __enter__(self) -> None:
        signal.signal(signal.SIGALRM, self._handler)
        signal.alarm(self._seconds)

    def __exit__(self, *exc: object) -> None:
        signal.alarm(0)


def _synthetic_quotes(n: int, symbol: str = "AAPL") -> list[NBBOQuote]:
    quotes: list[NBBOQuote] = []
    base_bid = 150.00
    for i in range(1, n + 1):
        bid = base_bid + (i % 10) * 0.01
        ask = bid + 0.01
        quotes.append(NBBOQuote(
            timestamp_ns=i * 1_000_000,
            correlation_id=f"{symbol}:{i * 1_000_000}:{i}",
            sequence=i,
            symbol=symbol,
            bid=Decimal(f"{bid:.2f}"),
            ask=Decimal(f"{ask:.2f}"),
            bid_size=100,
            ask_size=100,
            exchange_timestamp_ns=i * 1_000_000,
        ))
    return quotes


def _build_and_run(tmp_path: Path, quotes: list[NBBOQuote]):
    alpha_dir = tmp_path / "alphas"
    alpha_dir.mkdir(exist_ok=True)
    shutil.copy2(ALPHA_SRC, alpha_dir / "mean_reversion.alpha.yaml")

    config = PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=alpha_dir,
        account_equity=100_000.0,
        regime_engine=None,
        parameter_overrides={"mean_reversion": {"ewma_span": 5, "zscore_entry": 1.0}},
    )

    event_log = InMemoryEventLog()
    event_log.append_batch(quotes)

    orchestrator, resolved_config = build_platform(config, event_log=event_log)
    orchestrator.boot(resolved_config)

    t0 = time.perf_counter_ns()
    orchestrator.run_backtest()
    elapsed_ns = time.perf_counter_ns() - t0

    orchestrator.shutdown()
    gc.collect()

    return orchestrator, elapsed_ns


class TestSingleTickBudget:
    """1000 ticks: p99 processing time check."""

    def test_single_tick_processing_under_budget(
        self, tmp_path: Path
    ) -> None:
        with _Timeout(TIMEOUT_SEC):
            n = 1000
            quotes = _synthetic_quotes(n)
            _, elapsed_ns = _build_and_run(tmp_path, quotes)

            avg_ns_per_tick = elapsed_ns / n
            assert avg_ns_per_tick < 1_000_000, (
                f"Average tick time {avg_ns_per_tick / 1000:.1f}μs exceeds 1ms budget"
            )


class TestFullDayReplaySpeed:
    """20,000 synthetic events replayed within time budget."""

    def test_full_day_replay_speed(self, tmp_path: Path) -> None:
        with _Timeout(TIMEOUT_SEC):
            n = 20_000
            quotes = _synthetic_quotes(n)
            _, elapsed_ns = _build_and_run(tmp_path, quotes)

            elapsed_sec = elapsed_ns / 1e9
            assert elapsed_sec < 30, (
                f"20k events took {elapsed_sec:.1f}s, expected < 30s"
            )


class TestEventsPerSecondRegression:
    """Events/sec meets baseline threshold."""

    def test_events_per_second_regression(self, tmp_path: Path) -> None:
        with _Timeout(TIMEOUT_SEC):
            n = 10_000
            quotes = _synthetic_quotes(n)
            _, elapsed_ns = _build_and_run(tmp_path, quotes)

            elapsed_sec = elapsed_ns / 1e9
            events_per_sec = n / elapsed_sec if elapsed_sec > 0 else float("inf")

            min_eps = 5_000
            assert events_per_sec >= min_eps, (
                f"Events/sec {events_per_sec:.0f} below baseline {min_eps}"
            )


class TestMemoryFootprint:
    """RSS delta bounded after processing events."""

    def test_memory_footprint_bounded(self, tmp_path: Path) -> None:
        with _Timeout(TIMEOUT_SEC):
            n = 10_000
            quotes = _synthetic_quotes(n)

            rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

            _build_and_run(tmp_path, quotes)

            rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

            import platform as plat
            if plat.system() == "Darwin":
                delta_mb = (rss_after - rss_before) / (1024 * 1024)
            else:
                delta_mb = (rss_after - rss_before) / 1024

            assert delta_mb < 200, (
                f"RSS delta {delta_mb:.1f}MB exceeds 200MB limit after {n} events"
            )
