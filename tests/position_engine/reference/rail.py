"""Reference mark rail. contracts.md §1 and §9 (D-62, D-41, D-82). P-22a1.

Constructor matches ``MarkRail(sequence_generator)``. ``D`` and ``S`` are read from
``FEELIES_RAIL_DWELL_NS`` and ``FEELIES_RAIL_SLIPPAGE_TICKS`` (default 0) so a fresh
process sees them. ``feed_gap_before`` stays false; the battery seam sets it.
"""

from __future__ import annotations

import os

from feelies.core.events import MarkRailUpdate, NBBOQuote, RailOrientation
from feelies.core.identifiers import SequenceGenerator
from feelies.core.mark_rail import MarkRailProtocol
from feelies.core.quote_quality import QuoteQuality, classify


def _cents(symbol: str, price: object) -> int:
    scaled = price * 100  # type: ignore[operator]
    if scaled != scaled.to_integral_value():
        raise ValueError(symbol)
    return int(scaled)


class _Book:
    """Per-symbol carry. contracts.md §1, carries between events."""

    __slots__ = (
        "first_ns",
        "prev_ns",
        "last_usable_ns",
        "bid",
        "ask",
        "bid_changed_ns",
        "ask_changed_ns",
        "window",
    )

    def __init__(self) -> None:
        self.first_ns: int | None = None
        self.prev_ns: int | None = None
        self.last_usable_ns: int | None = None
        self.bid: int | None = None
        self.ask: int | None = None
        self.bid_changed_ns: int | None = None
        self.ask_changed_ns: int | None = None
        # (exchange_timestamp_ns, bid, ask, usable)
        self.window: list[tuple[int, int | None, int | None, bool]] = []


class ReferenceRail(MarkRailProtocol):
    """Both orientations, every quote. Absent sides hold the last present price."""

    def __init__(self, sequence_generator: SequenceGenerator) -> None:
        self._seq = sequence_generator
        self.dwell_ns = int(os.environ.get("FEELIES_RAIL_DWELL_NS", "0"))
        self.slippage_ticks = int(os.environ.get("FEELIES_RAIL_SLIPPAGE_TICKS", "0"))
        self._books: dict[str, _Book] = {}

    def on_quote(self, quote: NBBOQuote) -> MarkRailUpdate:
        timestamp = quote.exchange_timestamp_ns
        bid_cents = _cents(quote.symbol, quote.bid)
        ask_cents = _cents(quote.symbol, quote.ask)
        book = self._books.get(quote.symbol)
        if book is None:
            book = _Book()
            self._books[quote.symbol] = book
        if book.first_ns is None:
            book.first_ns = timestamp
        usable = (
            classify(quote.bid, quote.ask, quote.bid_size, quote.ask_size) is QuoteQuality.VALID
        )
        if usable:
            if book.bid != bid_cents:
                book.bid = bid_cents
                book.bid_changed_ns = timestamp
            if book.ask != ask_cents:
                book.ask = ask_cents
                book.ask_changed_ns = timestamp
            book.last_usable_ns = timestamp
        quiet = 0 if book.prev_ns is None else timestamp - book.prev_ns
        book.prev_ns = timestamp
        if usable:
            absent_for = 0
        elif book.last_usable_ns is not None:
            absent_for = timestamp - book.last_usable_ns
        else:
            absent_for = timestamp - book.first_ns
        book.window.append((timestamp, book.bid, book.ask, usable))
        cutoff = timestamp - self.dwell_ns
        book.window = [row for row in book.window if row[0] > cutoff or row[0] == timestamp]
        bid_age = 0 if book.bid_changed_ns is None else timestamp - book.bid_changed_ns
        ask_age = 0 if book.ask_changed_ns is None else timestamp - book.ask_changed_ns
        if book.bid is None or book.ask is None:
            long_worst = None
            short_worst = None
        else:
            long_worst = min(book.bid, book.ask)
            short_worst = max(book.bid, book.ask)
        slip = self.slippage_ticks
        long_forced = None if long_worst is None else long_worst - slip
        short_forced = None if short_worst is None else short_worst + slip
        long_dwelled = _extreme(book.window, index=1, pick=min)
        short_dwelled = _extreme(book.window, index=2, pick=max)
        clean = all(row[3] for row in book.window)
        warmed = self.dwell_ns == 0 or timestamp - book.first_ns >= self.dwell_ns
        absent = not usable
        long_side = _orientation(
            paying=book.ask,
            valuation=book.bid,
            paying_size=quote.ask_size,
            valuation_size=quote.bid_size,
            paying_age=ask_age,
            valuation_age=bid_age,
            absent=absent,
            absent_for=absent_for,
            worst=long_worst,
            forced=long_forced,
            dwelled=long_dwelled,
            clean=clean,
        )
        short_side = _orientation(
            paying=book.bid,
            valuation=book.ask,
            paying_size=quote.bid_size,
            valuation_size=quote.ask_size,
            paying_age=bid_age,
            valuation_age=ask_age,
            absent=absent,
            absent_for=absent_for,
            worst=short_worst,
            forced=short_forced,
            dwelled=short_dwelled,
            clean=clean,
        )
        return MarkRailUpdate(
            timestamp_ns=quote.timestamp_ns,
            correlation_id=quote.correlation_id,
            sequence=self._seq.next(),
            source_layer="PORTFOLIO",
            symbol=quote.symbol,
            quote_sequence=quote.sequence,
            event_timestamp_ns=timestamp,
            long=long_side,
            short=short_side,
            symbol_quiet_ns=quiet,
            locked=bid_cents == ask_cents,
            crossed=bid_cents > ask_cents,
            feed_gap_before=False,
            warmed_up=warmed,
        )


def _extreme(
    window: list[tuple[int, int | None, int | None, bool]],
    *,
    index: int,
    pick: object,
) -> int | None:
    values = [row[index] for row in window if row[index] is not None]
    if not values:
        return None
    return pick(values)  # type: ignore[operator]


def _orientation(
    *,
    paying: int | None,
    valuation: int | None,
    paying_size: int,
    valuation_size: int,
    paying_age: int,
    valuation_age: int,
    absent: bool,
    absent_for: int,
    worst: int | None,
    forced: int | None,
    dwelled: int | None,
    clean: bool,
) -> RailOrientation:
    return RailOrientation(
        paying_mark_cents=paying,
        valuation_mark_cents=valuation,
        worst_side_mark_cents=worst,
        forced_exit_mark_cents=forced,
        dwelled_exit_mark_cents=dwelled,
        paying_size=paying_size,
        valuation_size=valuation_size,
        paying_age_ns=paying_age,
        valuation_age_ns=valuation_age,
        paying_absent_for_ns=0 if not absent else absent_for,
        valuation_absent_for_ns=0 if not absent else absent_for,
        paying_side_absent=absent,
        valuation_side_absent=absent,
        dwell_window_clean=clean,
    )
