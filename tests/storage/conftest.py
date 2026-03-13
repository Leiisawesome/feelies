"""Shared fixtures for storage tests."""

from __future__ import annotations

from decimal import Decimal

from feelies.core.events import NBBOQuote, Trade


def make_quote(seq: int = 0, symbol: str = "AAPL") -> NBBOQuote:
    """Create a sample NBBOQuote for tests."""
    return NBBOQuote(
        timestamp_ns=1_700_000_000_000_000_000,
        correlation_id=f"{symbol}:1700000000000000000:{seq}",
        sequence=seq,
        symbol=symbol,
        bid=Decimal("150.00"),
        ask=Decimal("150.02"),
        bid_size=100,
        ask_size=50,
        exchange_timestamp_ns=1_700_000_000_000_000_000,
    )


def make_trade(seq: int = 0, symbol: str = "AAPL") -> Trade:
    """Create a sample Trade for tests."""
    return Trade(
        timestamp_ns=1_700_000_000_000_100_000,
        correlation_id=f"{symbol}:1700000000000100000:{seq}",
        sequence=seq,
        symbol=symbol,
        price=Decimal("150.01"),
        size=100,
        exchange_timestamp_ns=1_700_000_000_000_100_000,
    )
