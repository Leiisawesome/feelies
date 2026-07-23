"""Tests for fused backtest event-log preparation."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from feelies.core.events import NBBOQuote, Trade
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.harness.backtest_prep import (
    QuoteReplayObserver,
    QuoteTraceIndex,
    prepare_backtest_event_log,
)
from feelies.storage.memory_event_log import InMemoryEventLog

_TZ_ET = ZoneInfo("America/New_York")


def _quote(
    *,
    symbol: str = "APP",
    ts_ns: int,
    seq: int,
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q:{seq}",
        sequence=seq,
        source_layer="INGESTION",
        symbol=symbol,
        exchange_timestamp_ns=ts_ns,
        bid=Decimal("100.00"),
        ask=Decimal("100.10"),
        bid_size=100,
        ask_size=100,
    )


def _trade(*, symbol: str = "APP", ts_ns: int, seq: int) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"t:{seq}",
        sequence=seq,
        source_layer="INGESTION",
        symbol=symbol,
        exchange_timestamp_ns=ts_ns,
        price=Decimal("100.05"),
        size=10,
        conditions=(),
    )


def test_prepare_backtest_event_log_counts_and_spans() -> None:
    log = InMemoryEventLog()
    log.append_batch(
        [
            _quote(ts_ns=1_000, seq=1),
            _trade(ts_ns=2_000, seq=2),
            _quote(ts_ns=3_000, seq=3),
        ]
    )
    config = PlatformConfig(
        symbols=frozenset({"APP"}),
        mode=OperatingMode.BACKTEST,
        session_kind="EXT",
        regime_calibration_max_quotes=10,
    )
    prep = prepare_backtest_event_log(config, log)
    assert prep.n_quotes == 2
    assert prep.n_trades == 1
    assert prep.first_event_ts_ns == 1_000
    assert prep.calendar_spans["APP"][0] == prep.calendar_spans["APP"][1]
    assert len(prep.regime_calibration_quotes) == 2


def test_prepare_backtest_event_log_rth_filter_drops_extended_hours() -> None:
    pre_market_ns = int(datetime(2026, 3, 26, 8, 0, 0, tzinfo=_TZ_ET).timestamp() * 1e9)
    rth_ns = int(datetime(2026, 3, 26, 10, 0, 0, tzinfo=_TZ_ET).timestamp() * 1e9)
    log = InMemoryEventLog()
    log.append_batch(
        [
            _quote(ts_ns=pre_market_ns, seq=1),
            _quote(ts_ns=rth_ns, seq=2),
        ]
    )
    config = PlatformConfig(
        symbols=frozenset({"APP"}),
        mode=OperatingMode.BACKTEST,
        session_kind="RTH",
    )
    prep = prepare_backtest_event_log(config, log)
    assert prep.rth_dropped == 1
    assert prep.n_quotes == 1
    assert prep.first_event_ts_ns == rth_ns


def test_prepare_backtest_event_log_calibration_respects_cap() -> None:
    log = InMemoryEventLog()
    log.append_batch([_quote(ts_ns=i, seq=i) for i in range(1, 6)])
    config = PlatformConfig(
        symbols=frozenset({"APP"}),
        mode=OperatingMode.BACKTEST,
        session_kind="EXT",
        regime_calibration_max_quotes=3,
    )
    prep = prepare_backtest_event_log(config, log)
    assert len(prep.regime_calibration_quotes) == 3


def test_quote_replay_observer_shares_trace_with_progress() -> None:
    observer = QuoteReplayObserver(total_events=2, interval=10_000)
    q1 = _quote(ts_ns=1, seq=1)
    q2 = _quote(ts_ns=2, seq=2)
    observer(q1)
    observer(q2)
    assert observer.trace.quote_count == 2
    assert "2 quotes" in observer.summary()


def test_quote_trace_index_tracks_tick_index() -> None:
    idx = QuoteTraceIndex()
    q1 = _quote(ts_ns=1, seq=1)
    q2 = _quote(ts_ns=2, seq=2)
    idx(q1)
    idx(q2)
    assert idx.quote_count == 2
    assert idx.by_correlation_id[q2.correlation_id].tick_index == 2


def test_prepare_reuses_log_when_not_filtering_rth() -> None:
    log = InMemoryEventLog()
    log.append_batch([_quote(ts_ns=1, seq=1)])
    config = PlatformConfig(
        symbols=frozenset({"APP"}),
        mode=OperatingMode.BACKTEST,
        session_kind="EXT",
    )
    prep = prepare_backtest_event_log(config, log)
    assert prep.event_log is log


def test_prepare_rebuilds_log_when_filtering_rth() -> None:
    pre_market_ns = int(datetime(2026, 3, 26, 8, 0, 0, tzinfo=_TZ_ET).timestamp() * 1e9)
    log = InMemoryEventLog()
    log.append_batch([_quote(ts_ns=pre_market_ns, seq=1)])
    config = replace(
        PlatformConfig(symbols=frozenset({"APP"}), mode=OperatingMode.BACKTEST),
        session_kind="RTH",
    )
    prep = prepare_backtest_event_log(config, log)
    assert prep.event_log is not log
