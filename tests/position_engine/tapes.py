"""Synthetic NBBO tape. Stdlib and feelies.core only; no clock, no global RNG."""

from __future__ import annotations

import random
from dataclasses import replace
from decimal import Decimal

from feelies.core.events import NBBOQuote
from feelies.core.quote_quality import QuoteQuality, classify


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


def set_quote(
    tape: list[NBBOQuote],
    index: int,
    *,
    bid_cents: int,
    ask_cents: int,
    bid_size: int | None = None,
    ask_size: int | None = None,
) -> list[NBBOQuote]:
    if not 0 < bid_cents < ask_cents:
        raise ValueError("require 0 < bid_cents < ask_cents")
    quote = tape[index]
    out = list(tape)
    out[index] = replace(
        quote,
        bid=Decimal(bid_cents) / 100,
        ask=Decimal(ask_cents) / 100,
        bid_size=quote.bid_size if bid_size is None else bid_size,
        ask_size=quote.ask_size if ask_size is None else ask_size,
    )
    return out


def shift_from(tape: list[NBBOQuote], index: int, delta_cents: int) -> list[NBBOQuote]:
    if index < 0 or index > len(tape):
        raise IndexError(index)
    out = list(tape)
    for j in range(index, len(tape)):
        quote = tape[j]
        bid_c = int(quote.bid * 100) + delta_cents
        ask_c = int(quote.ask * 100) + delta_cents
        if bid_c <= 0 or ask_c <= 0:
            raise ValueError(f"non-positive side at sequence {quote.sequence}")
        out[j] = replace(
            quote,
            bid=Decimal(bid_c) / 100,
            ask=Decimal(ask_c) / 100,
        )
    return out


def remove_side_run(tape: list[NBBOQuote], index: int, count: int, side: str) -> list[NBBOQuote]:
    if count < 1:
        raise ValueError(count)
    if index < 0 or index + count > len(tape):
        raise IndexError(index)
    out = list(tape)
    for j in range(index, index + count):
        out = remove_side(out, j, side)
    return out


def excise(tape: list[NBBOQuote], index: int, count: int) -> list[NBBOQuote]:
    if count < 1 or index < 0 or index + count > len(tape):
        if count < 1:
            raise ValueError(count)
        raise IndexError(index)
    return tape[:index] + tape[index + count :]


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


def force_class(tape: list[NBBOQuote], index: int, cls: str) -> list[NBBOQuote]:
    """Replace ``tape[index]`` with the canonical unusable-side example for ``cls``.

    Timestamp and sequence stay. The input list is not mutated. ``ValueError``
    if ``cls`` is unknown or ``classify`` does not return the class it names.
    """
    quote = tape[index]
    if cls == "NONPOS_BID":
        updated = replace(quote, bid=Decimal("0"), ask=Decimal("100.02"))
        expected = QuoteQuality.NONPOS
    elif cls == "NONPOS_ASK":
        updated = replace(quote, bid=Decimal("100.01"), ask=Decimal("0"))
        expected = QuoteQuality.NONPOS
    elif cls == "CROSSED":
        updated = replace(quote, bid=Decimal("100.50"), ask=Decimal("100.00"))
        expected = QuoteQuality.CROSSED
    elif cls == "LOCKED":
        updated = replace(quote, bid=Decimal("100.00"), ask=Decimal("100.00"))
        expected = QuoteQuality.LOCKED
    elif cls == "ZERO_SZ_BID":
        updated = replace(quote, bid_size=0, ask_size=1000)
        expected = QuoteQuality.ZERO_SZ
    elif cls == "ZERO_SZ_ASK":
        updated = replace(quote, bid_size=1000, ask_size=0)
        expected = QuoteQuality.ZERO_SZ
    else:
        raise ValueError(cls)
    got = classify(updated.bid, updated.ask, updated.bid_size, updated.ask_size)
    if got is not expected:
        raise ValueError(f"force_class {cls} classified {got}")
    out = list(tape)
    out[index] = updated
    return out
