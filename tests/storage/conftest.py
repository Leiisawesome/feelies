"""Shared fixtures for storage tests."""

from __future__ import annotations

from decimal import Decimal

from feelies.core.events import NBBOQuote, Trade

_DEFAULT_QUOTE_TS = 1_700_000_000_000_000_000
_DEFAULT_TRADE_TS = 1_700_000_000_000_100_000


def make_quote(
    seq: int = 0,
    symbol: str = "AAPL",
    exchange_ts_ns: int = _DEFAULT_QUOTE_TS,
) -> NBBOQuote:
    """Create a sample NBBOQuote for tests."""
    return NBBOQuote(
        timestamp_ns=exchange_ts_ns,
        correlation_id=f"{symbol}:{exchange_ts_ns}:{seq}",
        sequence=seq,
        symbol=symbol,
        bid=Decimal("150.00"),
        ask=Decimal("150.02"),
        bid_size=100,
        ask_size=50,
        exchange_timestamp_ns=exchange_ts_ns,
    )


def make_trade(
    seq: int = 0,
    symbol: str = "AAPL",
    exchange_ts_ns: int = _DEFAULT_TRADE_TS,
) -> Trade:
    """Create a sample Trade for tests."""
    return Trade(
        timestamp_ns=exchange_ts_ns,
        correlation_id=f"{symbol}:{exchange_ts_ns}:{seq}",
        sequence=seq,
        symbol=symbol,
        price=Decimal("150.01"),
        size=100,
        exchange_timestamp_ns=exchange_ts_ns,
    )
