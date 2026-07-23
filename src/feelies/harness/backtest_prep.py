"""Single-pass backtest event-log preparation.

Combines RTH filtering, ingest counts, session metadata, corporate-action
spans, and regime-calibration quotes in one replay scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import time

from feelies.core.events import Event, NBBOQuote, Trade
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.storage.memory_event_log import InMemoryEventLog
from feelies.storage.reference.corporate_actions import (
    exchange_timestamp_to_ny_date,
)

__all__ = [
    "BacktestEventLogPrep",
    "QuoteReplayObserver",
    "QuoteTraceEntry",
    "QuoteTraceIndex",
    "prepare_backtest_event_log",
]

_TZ_ET = ZoneInfo("America/New_York")
_RTH_OPEN_H, _RTH_OPEN_M = 9, 30
_RTH_CLOSE_H, _RTH_CLOSE_M = 16, 0
_RTH_OPEN_SECS = _RTH_OPEN_H * 3600 + _RTH_OPEN_M * 60
_RTH_CLOSE_SECS = _RTH_CLOSE_H * 3600 + _RTH_CLOSE_M * 60


@dataclass(frozen=True, slots=True)
class QuoteTraceEntry:
    """Minimal quote fields for latency-spike forensics."""

    symbol: str
    exchange_timestamp_ns: int
    tick_index: int


class QuoteTraceIndex:
    """Lightweight NBBO index — avoids storing full quotes in ``BusRecorder``."""

    __slots__ = ("quote_count", "by_correlation_id")

    def __init__(self) -> None:
        self.quote_count = 0
        self.by_correlation_id: dict[str, QuoteTraceEntry] = {}

    def __call__(self, event: Event) -> None:
        if isinstance(event, NBBOQuote):
            self.quote_count += 1
            self.by_correlation_id[event.correlation_id] = QuoteTraceEntry(
                symbol=event.symbol,
                exchange_timestamp_ns=event.exchange_timestamp_ns,
                tick_index=self.quote_count,
            )


class QuoteReplayObserver:
    """Single NBBO subscriber: quote trace index + CLI progress lines."""

    __slots__ = ("trace", "_total", "_interval", "_count", "_t0")

    def __init__(self, total_events: int, interval: int = 100_000) -> None:
        self.trace = QuoteTraceIndex()
        self._total = total_events
        self._interval = interval
        self._count = 0
        self._t0 = time.monotonic()

    def __call__(self, event: Event) -> None:
        if not isinstance(event, NBBOQuote):
            return
        self.trace(event)
        self._count += 1
        if self._count % self._interval == 0:
            elapsed = time.monotonic() - self._t0
            pct = self._count / self._total * 100.0 if self._total else 0.0
            rate = self._count / elapsed if elapsed > 0 else 0.0
            remaining = (self._total - self._count) / rate if rate > 0 else 0.0
            print(
                f"  [{pct:5.1f}%]  {self._count:>10,} / {self._total:,} quotes  "
                f"({rate:,.0f} q/s, ~{remaining:.0f}s remaining)",
                flush=True,
            )

    def summary(self) -> str:
        elapsed = time.monotonic() - self._t0
        rate = self._count / elapsed if elapsed > 0 else 0.0
        return f"{self._count:,} quotes in {elapsed:.1f}s ({rate:,.0f} q/s)"


@dataclass(frozen=True, slots=True)
class BacktestEventLogPrep:
    """Outputs of the fused pre-replay scan."""

    event_log: InMemoryEventLog
    first_event_ts_ns: int | None
    n_quotes: int
    n_trades: int
    rth_dropped: int
    calendar_spans: dict[str, tuple[date, date]]
    regime_calibration_quotes: tuple[NBBOQuote, ...] | None


def _in_rth(exchange_timestamp_ns: int) -> bool:
    dt = datetime.fromtimestamp(exchange_timestamp_ns / 1e9, tz=_TZ_ET)
    event_secs = dt.hour * 3600 + dt.minute * 60 + dt.second
    return _RTH_OPEN_SECS <= event_secs < _RTH_CLOSE_SECS


def _update_calendar_span(
    spans_ns: dict[str, tuple[int, int]],
    symbol: str,
    exchange_timestamp_ns: int,
) -> None:
    sym = symbol.upper()
    existing = spans_ns.get(sym)
    if existing is None:
        spans_ns[sym] = (exchange_timestamp_ns, exchange_timestamp_ns)
    else:
        spans_ns[sym] = (
            min(existing[0], exchange_timestamp_ns),
            max(existing[1], exchange_timestamp_ns),
        )


def prepare_backtest_event_log(
    config: PlatformConfig,
    event_log: InMemoryEventLog,
) -> BacktestEventLogPrep:
    """Single pass: optional RTH filter + counts + spans + calibration prefix."""
    filter_rth = config.session_kind == "RTH"
    max_cal = (
        config.regime_calibration_max_quotes if config.mode == OperatingMode.BACKTEST else None
    )

    kept: list[Event] = []
    first_ts: int | None = None
    n_quotes = 0
    n_trades = 0
    rth_dropped = 0
    spans_ns: dict[str, tuple[int, int]] = {}
    cal_quotes: list[NBBOQuote] = []

    for ev in event_log.replay():
        if filter_rth:
            ts_ns: int | None = getattr(ev, "exchange_timestamp_ns", None)
            if ts_ns is not None and not _in_rth(ts_ns):
                rth_dropped += 1
                continue
            kept.append(ev)

        if first_ts is None:
            first_ts = int(ev.timestamp_ns)

        if isinstance(ev, NBBOQuote):
            n_quotes += 1
            _update_calendar_span(spans_ns, ev.symbol, ev.exchange_timestamp_ns)
            if max_cal is not None and len(cal_quotes) < max_cal:
                cal_quotes.append(ev)
        elif isinstance(ev, Trade):
            n_trades += 1
            _update_calendar_span(spans_ns, ev.symbol, ev.exchange_timestamp_ns)

    if filter_rth:
        filtered = InMemoryEventLog()
        filtered.append_batch(kept)
        out_log = filtered
    else:
        out_log = event_log

    calendar_spans = {
        sym: (
            exchange_timestamp_to_ny_date(lo),
            exchange_timestamp_to_ny_date(hi),
        )
        for sym, (lo, hi) in spans_ns.items()
    }

    return BacktestEventLogPrep(
        event_log=out_log,
        first_event_ts_ns=first_ts,
        n_quotes=n_quotes,
        n_trades=n_trades,
        rth_dropped=rth_dropped,
        calendar_spans=calendar_spans,
        regime_calibration_quotes=tuple(cal_quotes) if max_cal is not None else None,
    )
