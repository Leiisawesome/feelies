"""Mark rail. contracts.md §1 and §9. D-41, D-62, D-82, D-201, D-204."""

from __future__ import annotations

from collections import deque
from decimal import Decimal

from feelies.core.events import MarkRailUpdate, NBBOQuote, RailOrientation
from feelies.core.identifiers import SequenceGenerator
from feelies.core.mark_rail import MarkRailProtocol
from feelies.core.quote_quality import QuoteQuality


def _cents(symbol: str, price: Decimal) -> int:
    scaled = price * 100
    if scaled != scaled.to_integral_value():
        raise ValueError(symbol)
    return int(scaled)


class _Side:
    """One quoted side carried between events."""

    __slots__ = ("absent", "absent_since_ts", "changed_ts", "price", "size")

    def __init__(self) -> None:
        self.price: int | None = None
        self.size: int = 0
        self.changed_ts: int = 0
        self.absent_since_ts: int = 0
        self.absent: bool = True


class _WindowQuote:
    """Published prices for one quote retained in the dwell window."""

    __slots__ = ("ask", "bid", "feed_gap", "ts", "valid")

    def __init__(
        self,
        ts: int,
        bid: int | None,
        ask: int | None,
        *,
        valid: bool,
        feed_gap: bool,
    ) -> None:
        self.ts = ts
        self.bid = bid
        self.ask = ask
        self.valid = valid
        self.feed_gap = feed_gap


class _Book:
    """Per-symbol carry. contracts.md §1, nothing else."""

    __slots__ = ("ask", "bid", "first_quote_ts", "last_quote_ts", "window")

    def __init__(self) -> None:
        self.bid = _Side()
        self.ask = _Side()
        self.last_quote_ts: int | None = None
        self.first_quote_ts: int | None = None
        self.window: deque[_WindowQuote] = deque()

    def note_first_quote(self, t: int) -> None:
        if self.first_quote_ts is None:
            self.first_quote_ts = t
            self.bid.changed_ts = t
            self.ask.changed_ts = t

    def quiet_ns(self, t: int) -> int:
        if self.last_quote_ts is None:
            quiet = 0
        else:
            quiet = t - self.last_quote_ts
        self.last_quote_ts = t
        return quiet

    def push(self, quote: _WindowQuote, cutoff: int) -> None:
        self.window.append(quote)
        self.window = deque(item for item in self.window if item is quote or item.ts > cutoff)

    def reset(self) -> None:
        self.bid = _Side()
        self.ask = _Side()
        self.last_quote_ts = None
        self.first_quote_ts = None
        self.window = deque()


class MarkRail(MarkRailProtocol):
    """One update per quote. ``slippage_ticks`` is S and ``dwell_ns`` is D (D-40)."""

    def __init__(
        self,
        sequence_generator: SequenceGenerator,
        *,
        slippage_ticks: int = 0,
        dwell_ns: int = 0,
    ) -> None:
        self._seq = sequence_generator
        self.slippage_ticks = slippage_ticks
        self.dwell_ns = dwell_ns
        self._books: dict[str, _Book] = {}

    def on_quote(self, quote: NBBOQuote, *, quality: QuoteQuality) -> MarkRailUpdate:
        """Publish one update. Step order is fixed (contracts.md §1).

        feed-gap flag, then update book sides, then update timers, then push
        this quote and trim every retained quote with timestamp <= t - D
        (the current quote stays, D-41), then both orientations, then emit.
        """
        bid_c = _cents(quote.symbol, quote.bid)
        ask_c = _cents(quote.symbol, quote.ask)
        book = self._books.get(quote.symbol)
        if book is None:
            book = _Book()
            self._books[quote.symbol] = book
        t = quote.exchange_timestamp_ns
        feed_gap = False
        self._update_sides(book, t, bid_c, ask_c, quote.bid_size, quote.ask_size, quality)
        quiet, bid_age, ask_age, bid_absent_for, ask_absent_for, warmed = self._timers(book, t)
        self._push_window(book, t, feed_gap, quality)
        long_side, short_side = self._orientations(
            book,
            bid_age,
            ask_age,
            bid_absent_for,
            ask_absent_for,
        )
        return MarkRailUpdate(
            timestamp_ns=quote.timestamp_ns,
            correlation_id=quote.correlation_id,
            sequence=self._seq.next(),
            source_layer="PORTFOLIO",
            symbol=quote.symbol,
            quote_sequence=quote.sequence,
            event_timestamp_ns=t,
            long=long_side,
            short=short_side,
            symbol_quiet_ns=quiet,
            locked=bid_c == ask_c,
            crossed=bid_c > ask_c,
            feed_gap_before=feed_gap,
            warmed_up=warmed,
        )

    def _update_sides(
        self,
        book: _Book,
        t: int,
        bid_c: int,
        ask_c: int,
        bid_size: int,
        ask_size: int,
        quality: QuoteQuality,
    ) -> None:
        book.note_first_quote(t)
        if quality is QuoteQuality.VALID:
            if book.bid.price != bid_c:
                book.bid.changed_ts = t
            if book.ask.price != ask_c:
                book.ask.changed_ts = t
            book.bid.price = bid_c
            book.ask.price = ask_c
            book.bid.size = bid_size
            book.ask.size = ask_size
            book.bid.absent = False
            book.ask.absent = False
            book.bid.absent_since_ts = t
            book.ask.absent_since_ts = t
            return
        book.bid.size = 0
        book.ask.size = 0
        book.bid.absent = True
        book.ask.absent = True
        if book.bid.price is None:
            origin = t if book.first_quote_ts is None else book.first_quote_ts
            book.bid.absent_since_ts = origin
            book.ask.absent_since_ts = origin

    def _timers(self, book: _Book, t: int) -> tuple[int, int, int, int, int, bool]:
        quiet = book.quiet_ns(t)
        first = t if book.first_quote_ts is None else book.first_quote_ts
        warmed = (t - first) >= self.dwell_ns
        bid_absent_for = t - book.bid.absent_since_ts if book.bid.absent else 0
        ask_absent_for = t - book.ask.absent_since_ts if book.ask.absent else 0
        return (
            quiet,
            t - book.bid.changed_ts,
            t - book.ask.changed_ts,
            bid_absent_for,
            ask_absent_for,
            warmed,
        )

    def _push_window(
        self,
        book: _Book,
        t: int,
        feed_gap: bool,
        quality: QuoteQuality,
    ) -> None:
        current = _WindowQuote(
            t,
            book.bid.price,
            book.ask.price,
            valid=quality is QuoteQuality.VALID,
            feed_gap=feed_gap,
        )
        book.push(current, t - self.dwell_ns)

    def _orientations(
        self,
        book: _Book,
        bid_age: int,
        ask_age: int,
        bid_absent_for: int,
        ask_absent_for: int,
    ) -> tuple[RailOrientation, RailOrientation]:
        bids = [item.bid for item in book.window if item.bid is not None]
        asks = [item.ask for item in book.window if item.ask is not None]
        long_dwelled = min(bids) if bids else None
        short_dwelled = max(asks) if asks else None
        bid = book.bid.price
        ask = book.ask.price
        if bid is None or ask is None:
            long_worst: int | None = None
            short_worst: int | None = None
        else:
            long_worst = min(bid, ask)
            short_worst = max(bid, ask)
        long_forced = None if long_worst is None else long_worst - self.slippage_ticks
        short_forced = None if short_worst is None else short_worst + self.slippage_ticks
        clean = all(item.valid and not item.feed_gap for item in book.window)
        long_side = RailOrientation(
            paying_mark_cents=ask,
            valuation_mark_cents=bid,
            worst_side_mark_cents=long_worst,
            forced_exit_mark_cents=long_forced,
            dwelled_exit_mark_cents=long_dwelled,
            paying_size=book.ask.size,
            valuation_size=book.bid.size,
            paying_age_ns=ask_age,
            valuation_age_ns=bid_age,
            paying_absent_for_ns=ask_absent_for,
            valuation_absent_for_ns=bid_absent_for,
            paying_side_absent=book.ask.absent,
            valuation_side_absent=book.bid.absent,
            dwell_window_clean=clean,
        )
        short_side = RailOrientation(
            paying_mark_cents=bid,
            valuation_mark_cents=ask,
            worst_side_mark_cents=short_worst,
            forced_exit_mark_cents=short_forced,
            dwelled_exit_mark_cents=short_dwelled,
            paying_size=book.bid.size,
            valuation_size=book.ask.size,
            paying_age_ns=bid_age,
            valuation_age_ns=ask_age,
            paying_absent_for_ns=bid_absent_for,
            valuation_absent_for_ns=ask_absent_for,
            paying_side_absent=book.bid.absent,
            valuation_side_absent=book.ask.absent,
            dwell_window_clean=clean,
        )
        return long_side, short_side
