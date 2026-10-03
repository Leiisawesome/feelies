"""P-10 STUB — stage C (P-40) replaces ages, absence, window, warm-up, slippage."""

from __future__ import annotations

from decimal import Decimal

from feelies.core.events import MarkRailUpdate, NBBOQuote, RailOrientation
from feelies.core.identifiers import SequenceGenerator
from feelies.core.mark_rail import MarkRailProtocol


def _cents(symbol: str, price: Decimal) -> int:
    scaled = price * 100
    if scaled != scaled.to_integral_value():
        raise ValueError(symbol)
    return int(scaled)


class MarkRail(MarkRailProtocol):
    """P-10 STUB. contracts.md §1. S=0 and D=0: forced equals worst side, dwelled equals valuation."""

    def __init__(self, sequence_generator: SequenceGenerator) -> None:
        self._seq = sequence_generator
        self._prev_exchange_ns: dict[str, int] = {}

    def on_quote(self, quote: NBBOQuote) -> MarkRailUpdate:
        bid = _cents(quote.symbol, quote.bid)
        ask = _cents(quote.symbol, quote.ask)
        long_side = RailOrientation(
            paying_mark_cents=ask,
            valuation_mark_cents=bid,
            worst_side_mark_cents=min(bid, ask),
            forced_exit_mark_cents=min(bid, ask),
            dwelled_exit_mark_cents=bid,
            paying_size=quote.ask_size,
            valuation_size=quote.bid_size,
            paying_age_ns=0,
            valuation_age_ns=0,
            paying_absent_for_ns=0,
            valuation_absent_for_ns=0,
            paying_side_absent=False,
            valuation_side_absent=False,
            dwell_window_clean=False,
        )
        short_side = RailOrientation(
            paying_mark_cents=bid,
            valuation_mark_cents=ask,
            worst_side_mark_cents=max(bid, ask),
            forced_exit_mark_cents=max(bid, ask),
            dwelled_exit_mark_cents=ask,
            paying_size=quote.bid_size,
            valuation_size=quote.ask_size,
            paying_age_ns=0,
            valuation_age_ns=0,
            paying_absent_for_ns=0,
            valuation_absent_for_ns=0,
            paying_side_absent=False,
            valuation_side_absent=False,
            dwell_window_clean=False,
        )
        prev = self._prev_exchange_ns.get(quote.symbol)
        quiet = 0 if prev is None else quote.exchange_timestamp_ns - prev
        self._prev_exchange_ns[quote.symbol] = quote.exchange_timestamp_ns
        return MarkRailUpdate(
            timestamp_ns=quote.timestamp_ns,
            correlation_id=quote.correlation_id,
            sequence=self._seq.next(),
            source_layer="PORTFOLIO",
            symbol=quote.symbol,
            quote_sequence=quote.sequence,
            event_timestamp_ns=quote.exchange_timestamp_ns,
            long=long_side,
            short=short_side,
            symbol_quiet_ns=quiet,
            locked=bid == ask,
            crossed=bid > ask,
            feed_gap_before=False,
            warmed_up=False,
        )
