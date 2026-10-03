"""Prior-session regime calibration quotes. Pure given the loader."""

from __future__ import annotations

import time
from collections import Counter
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from feelies.core.events import NBBOQuote, Trade
from feelies.harness.regime_calibration import prior_session_calibration_quotes
from feelies.kernel.orchestrator import Orchestrator
from feelies.storage.memory_event_log import InMemoryEventLog

_TZ = ZoneInfo("America/New_York")


def _ns(day: int, hour: int, minute: int) -> int:
    return int(datetime(2026, 3, day, hour, minute, tzinfo=_TZ).timestamp() * 1e9)


def _quote(day: int, hour: int, minute: int, seq: int) -> NBBOQuote:
    ts = _ns(day, hour, minute)
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q:{seq}",
        sequence=seq,
        symbol="APP",
        exchange_timestamp_ns=ts,
        bid=Decimal("100.00"),
        ask=Decimal("100.10"),
        bid_size=100,
        ask_size=100,
    )


def _trade(day: int, hour: int, minute: int, seq: int) -> Trade:
    ts = _ns(day, hour, minute)
    return Trade(
        timestamp_ns=ts,
        correlation_id=f"t:{seq}",
        sequence=seq,
        symbol="APP",
        exchange_timestamp_ns=ts,
        price=Decimal("100.05"),
        size=10,
        conditions=(),
    )


def test_prior_date_is_the_previous_weekday_and_keeps_rth_order() -> None:
    seen: dict[str, object] = {}

    def loader(symbols: tuple[str, ...] | list[str], day: str):
        seen["symbols"] = tuple(symbols)
        seen["day"] = day
        return (
            _quote(25, 10, 0, 1),
            _quote(25, 8, 0, 2),
            _trade(25, 10, 1, 3),
            _quote(25, 10, 2, 4),
        )

    quotes, provenance = prior_session_calibration_quotes(
        symbols=("ZZZ", "APP"),
        session_date="2026-03-26",
        max_quotes=10,
        loader=loader,
    )
    assert seen["day"] == "2026-03-25"
    assert seen["symbols"] == ("ZZZ", "APP")
    assert [quote.sequence for quote in quotes] == [1, 4]
    assert provenance == ("2026-03-25", 2)


def test_monday_selects_the_previous_friday() -> None:
    seen: dict[str, object] = {}

    def loader(symbols: tuple[str, ...] | list[str], day: str):
        del symbols
        seen["day"] = day
        return (_quote(27, 10, 0, 1),)

    quotes, provenance = prior_session_calibration_quotes(
        symbols=("APP",),
        session_date="2026-03-30",
        max_quotes=10,
        loader=loader,
    )
    assert seen["day"] == "2026-03-27"
    assert [quote.sequence for quote in quotes] == [1]
    assert provenance == ("2026-03-27", 1)


def test_missing_prior_session_is_empty() -> None:
    def loader(symbols: tuple[str, ...] | list[str], day: str):
        del symbols, day
        return None

    quotes, provenance = prior_session_calibration_quotes(
        symbols=("APP",),
        session_date="2026-03-26",
        max_quotes=10,
        loader=loader,
    )
    assert quotes == ()
    assert provenance == (None, 0)


def test_cap_keeps_the_first_rth_quotes_in_loader_order() -> None:
    events = (
        _quote(25, 9, 30, 1),
        _quote(25, 8, 0, 2),
        _quote(25, 9, 31, 3),
        _quote(25, 9, 32, 4),
        _quote(25, 9, 33, 5),
    )

    def loader(symbols: tuple[str, ...] | list[str], day: str):
        del symbols, day
        return events

    quotes, provenance = prior_session_calibration_quotes(
        symbols=("APP",),
        session_date="2026-03-26",
        max_quotes=3,
        loader=loader,
    )
    assert [quote.sequence for quote in quotes] == [1, 3, 4]
    assert provenance == ("2026-03-25", 3)


def _named_quote(
    symbol: str,
    seq: int,
    minute: int,
    *,
    bid: str = "100.00",
    ask: str = "100.10",
) -> NBBOQuote:
    ts = _ns(25, 10, minute)
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"{symbol}:{seq}",
        sequence=seq,
        symbol=symbol,
        exchange_timestamp_ns=ts,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=100,
        ask_size=100,
    )


def _run_with_prior(
    monkeypatch,
    tmp_path,
    *,
    by_symbol: dict[str, tuple[NBBOQuote, ...]],
    max_quotes: int,
) -> object:
    """Boot a multi-symbol backtest whose prior session is ``by_symbol``."""
    from dataclasses import replace

    from tests.harness.test_backtest_runner import (
        _build_phase_inputs,
        _cache_args,
        _load_smoke,
    )

    def _load(symbols_in, start_date, end_date, cache_dir=None, **kwargs):
        del start_date, end_date, cache_dir, kwargs
        log = InMemoryEventLog()
        events: list[NBBOQuote] = []
        for symbol in symbols_in:
            events.extend(by_symbol.get(str(symbol), ()))
        log.append_batch(events)
        return log, None, []

    monkeypatch.setattr(
        "feelies.harness.backtest_runner.load_event_log_from_disk_cache",
        _load,
    )
    monkeypatch.setattr(Orchestrator, "run_backtest", lambda self: None)

    mod = _load_smoke()
    config, event_log, symbols, ingest_result = _build_phase_inputs(mod, tmp_path)
    config = replace(config, regime_calibration_max_quotes=max_quotes)
    from feelies.harness.backtest_runner import _run_backtest_phases_2_7
    from feelies.bootstrap import build_platform

    return _run_backtest_phases_2_7(
        _cache_args(),
        event_log,
        ingest_result,
        [],
        config,
        list(symbols),
        ", ".join(symbols),
        "2026-03-26",
        time.monotonic(),
        platform_factory=build_platform,
    )


def test_multi_symbol_run_keeps_a_capped_prefix_per_symbol(monkeypatch, tmp_path) -> None:
    """The cap is a prefix of each symbol's own prior session, not of the merge."""
    by_symbol = {
        symbol: tuple(
            _named_quote(symbol, seq=index + 1 + offset, minute=index) for index in range(5)
        )
        for offset, symbol in ((0, "AAPL"), (100, "MSFT"), (200, "NVDA"))
    }
    outcome = _run_with_prior(monkeypatch, tmp_path, by_symbol=by_symbol, max_quotes=2)
    quotes = tuple(outcome.orchestrator._regime_calibration_quotes or ())
    counts = Counter(quote.symbol for quote in quotes)
    assert counts == Counter({"AAPL": 2, "MSFT": 2, "NVDA": 2})
    assert outcome.orchestrator.regime_calibration_provenance == ("2026-03-25", 6)


def test_symbol_without_prior_quotes_uses_the_stated_fallback(monkeypatch, tmp_path) -> None:
    """A symbol with no own prior-session quotes uses the pooled emission."""

    def _series(symbol: str, bid: str, width: str, start: int) -> tuple[NBBOQuote, ...]:
        rows: list[NBBOQuote] = []
        base = Decimal(bid)
        step = Decimal(width)
        for index in range(40):
            ask = base + step + Decimal(index % 5) * step
            rows.append(
                _named_quote(
                    symbol,
                    seq=start + index,
                    minute=index % 50,
                    bid=bid,
                    ask=str(ask),
                )
            )
        return tuple(rows)

    by_symbol = {
        "AAPL": _series("AAPL", "150.00", "0.02", 1),
        "MSFT": _series("MSFT", "300.00", "0.40", 1000),
    }
    outcome = _run_with_prior(monkeypatch, tmp_path, by_symbol=by_symbol, max_quotes=100)
    quotes = tuple(outcome.orchestrator._regime_calibration_quotes or ())
    assert quotes
    assert "NVDA" not in {quote.symbol for quote in quotes}
    engine = outcome.orchestrator._regime_engine
    assert engine is not None
    assert engine.calibrated is True
    assert "NVDA" not in engine._emission_by_symbol
    assert engine._emission_for_symbol("NVDA") == engine._emission
