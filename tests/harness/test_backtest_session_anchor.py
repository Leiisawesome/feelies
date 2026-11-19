"""Unset backtest session_open resolves to the exchange regular-session open."""

from __future__ import annotations

from datetime import datetime, timezone

from feelies.core.platform_config import PlatformConfig
from feelies.core.session_clock import rth_open_ns
from feelies.harness.backtest_runner import _ensure_backtest_session_anchor

_NS = 1_000_000_000


def _session_probe_ns() -> int:
    """A 2026-03-26 UTC instant, whole seconds, so the ET date is that session."""
    return int(datetime(2026, 3, 26, 16, 0, tzinfo=timezone.utc).timestamp()) * _NS


def test_unset_backtest_session_open_equals_rth_open_ns() -> None:
    """An unset backtest grid anchors at rth_open_ns for the session date."""
    first_event_ts_ns = rth_open_ns(_session_probe_ns()) + 25_823_081
    anchored = _ensure_backtest_session_anchor(
        PlatformConfig(symbols=frozenset({"APP"}), session_open_ns=None),
        first_event_ts_ns=first_event_ts_ns,
    )
    assert anchored.session_open_ns == rth_open_ns(first_event_ts_ns)
