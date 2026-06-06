"""IB ``Contract`` factory helpers.

A single entry point per asset class keeps the contract-construction
logic out of the router.  The ``primary_exchange`` argument exists
because SMART routing requires it whenever a symbol is ambiguous
(e.g. ``MSFT`` cross-listed) — defaults to None for US large caps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ibapi.contract import Contract  # type: ignore[import-untyped]


def stock_contract(
    symbol: str,
    *,
    exchange: str = "SMART",
    currency: str = "USD",
    primary_exchange: str | None = None,
) -> "Contract":
    """Build an ``ibapi.contract.Contract`` for a US-listed common stock."""
    from ibapi.contract import Contract

    c = Contract()
    c.symbol = symbol
    c.secType = "STK"
    c.exchange = exchange
    c.currency = currency
    if primary_exchange:
        c.primaryExchange = primary_exchange
    return c
