"""Deterministic merge-sort for cached / multi-symbol event streams."""

from __future__ import annotations

from decimal import Decimal

from feelies.core.events import NBBOQuote, Trade
from feelies.storage.event_resequence import event_merge_sort_key, resequence_event_list


def _q(symbol: str, ts: int, seq: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id="x",
        sequence=seq,
        symbol=symbol,
        bid=Decimal("10"),
        ask=Decimal("10.1"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts,
    )


def _t(symbol: str, ts: int, seq: int) -> Trade:
    return Trade(
        timestamp_ns=ts,
        correlation_id="x",
        sequence=seq,
        symbol=symbol,
        price=Decimal("10.05"),
        size=1,
        exchange=1,
        trade_id=f"t-{symbol}-{seq}",
        exchange_timestamp_ns=ts,
        tape=1,
    )


def test_resequence_order_independent_of_input_concat_order() -> None:
    """Same timestamp ties break on (symbol, type, sequence), not list order."""
    msft = _q("MSFT", 1000, 5)
    aapl = _q("AAPL", 1000, 3)
    out_a = resequence_event_list([msft, aapl])
    out_b = resequence_event_list([aapl, msft])
    assert [e.symbol for e in out_a] == [e.symbol for e in out_b] == ["AAPL", "MSFT"]
    assert [e.sequence for e in out_a] == [0, 1]


def test_quote_before_trade_at_same_exchange_ts() -> None:
    q = _q("AAPL", 2000, 1)
    t = _t("AAPL", 2000, 2)
    out = resequence_event_list([t, q])
    assert isinstance(out[0], NBBOQuote)
    assert isinstance(out[1], Trade)


def test_merge_sort_key_orders_types() -> None:
    q = _q("AAPL", 500, 9)
    tr = _t("AAPL", 500, 1)
    assert event_merge_sort_key(q) < event_merge_sort_key(tr)


def test_resequence_leaves_input_list_order_unchanged() -> None:
    a = _q("AAPL", 1000, 1)
    b = _q("MSFT", 2000, 2)
    events = [b, a]
    before_ids = [id(events[0]), id(events[1])]
    _ = resequence_event_list(events)
    assert events[0] is b and events[1] is a
    assert [id(events[0]), id(events[1])] == before_ids
