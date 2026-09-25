"""Synthetic NBBO tape. Stdlib and feelies.core only; no clock, no global RNG."""

from __future__ import annotations

import random
from dataclasses import replace
from decimal import Decimal

from feelies.core.events import NBBOQuote


def make_tape(
    *,
    seed: int,
    n: int,
    start_bid_cents: int = 10_000,
    spread_cents: int = 1,
    p_move: float = 0.25,
    symbol: str = "SYN",
    start_ns: int = 1_768_532_400_000_000_000,
    interval_ns: int = 100_000_000,
    start_sequence: int = 1,
    size: int = 100,
) -> list[NBBOQuote]:
    if not 0 < p_move <= 0.5:
        raise ValueError(f"p_move must be in (0, 0.5], got {p_move}")
    if spread_cents < 1:
        raise ValueError(f"spread_cents must be >= 1, got {spread_cents}")
    rng = random.Random(seed)
    bid_c = start_bid_cents
    quotes: list[NBBOQuote] = []
    for i in range(n):
        if i == 0:
            step = 0
        else:
            u = rng.random()
            if u < p_move:
                step = -1
            elif u < 2 * p_move:
                step = 1
            else:
                step = 0
        bid_c += step
        if bid_c <= 100:
            raise RuntimeError("tape left the penny-tick region")
        ask_c = bid_c + spread_cents
        ts = start_ns + i * interval_ns
        quotes.append(
            NBBOQuote(
                symbol=symbol,
                bid=Decimal(bid_c) / 100,
                ask=Decimal(ask_c) / 100,
                bid_size=size,
                ask_size=size,
                timestamp_ns=ts,
                exchange_timestamp_ns=ts,
                sequence=start_sequence + i,
                correlation_id=f"syn-q-{seed}-{i}",
                source_layer="INGESTION",
            )
        )
    return quotes


def bid_path_cents(tape: list[NBBOQuote]) -> list[int]:
    return [int(quote.bid * 100) for quote in tape]


def lattice_barrier(price_cents: int, ticks: int) -> int:
    return price_cents + ticks


def hold(tape: list[NBBOQuote], index: int, count: int) -> list[NBBOQuote]:
    if count < 0 or index < 0 or index >= len(tape) or index + count >= len(tape):
        raise IndexError(index)
    src = tape[index]
    out = list(tape)
    for j in range(index + 1, index + count + 1):
        quote = tape[j]
        out[j] = replace(
            quote,
            bid=src.bid,
            ask=src.ask,
            bid_size=src.bid_size,
            ask_size=src.ask_size,
        )
    return out


def remove_side(tape: list[NBBOQuote], index: int, side: str) -> list[NBBOQuote]:
    if side not in ("bid", "ask"):
        raise ValueError(side)
    quote = tape[index]
    out = list(tape)
    if side == "bid":
        out[index] = replace(quote, bid_size=0)
    else:
        out[index] = replace(quote, ask_size=0)
    return out


def cross(tape: list[NBBOQuote], index: int, bid_cents: int, ask_cents: int) -> list[NBBOQuote]:
    if bid_cents <= ask_cents:
        raise ValueError("bid_cents must be greater than ask_cents")
    quote = tape[index]
    out = list(tape)
    out[index] = replace(
        quote,
        bid=Decimal(bid_cents) / 100,
        ask=Decimal(ask_cents) / 100,
    )
    return out
