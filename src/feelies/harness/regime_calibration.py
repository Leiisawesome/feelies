"""Prior-session regime calibration quotes.

Pure given its loader: the loader returns the prior session's events, or None
when that session is absent. The replayed session is never read.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, timedelta

from feelies.core.events import NBBOQuote, Trade
from feelies.harness.backtest_prep import _in_rth
from feelies.storage.cache_replay import iter_trading_dates

CalibrationLoader = Callable[[Sequence[str], str], Sequence[NBBOQuote | Trade] | None]


def prior_trading_date(session_date: str) -> str:
    """Previous weekday from ``iter_trading_dates`` strictly before ``session_date``."""
    session = date.fromisoformat(session_date)
    end = session - timedelta(days=1)
    start = end - timedelta(days=6)
    dates = iter_trading_dates(start.isoformat(), end.isoformat())
    if not dates:
        raise ValueError(f"no weekday before {session_date}")
    return dates[-1]


def prior_session_calibration_quotes(
    *,
    symbols: Sequence[str],
    session_date: str,
    max_quotes: int,
    loader: CalibrationLoader,
) -> tuple[tuple[NBBOQuote, ...], tuple[str | None, int]]:
    """RTH quotes of the prior session, capped, in loader order.

    Returns ``(quotes, provenance)`` where provenance is ``(source_date or None, n)``.
    Missing data or no RTH quotes yields ``((), (None, 0))``.
    """
    prior = prior_trading_date(session_date)
    loaded = loader(symbols, prior)
    if not loaded:
        return (), (None, 0)
    kept: list[NBBOQuote] = []
    for event in loaded:
        if not isinstance(event, NBBOQuote):
            continue
        if not _in_rth(event.exchange_timestamp_ns):
            continue
        kept.append(event)
        if len(kept) >= max_quotes:
            break
    if not kept:
        return (), (None, 0)
    return tuple(kept), (prior, len(kept))
