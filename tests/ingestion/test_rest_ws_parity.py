"""REST versus WebSocket normalization parity.

A logically-identical quote/trade must normalize to equal canonical fields
regardless of whether it arrives via the REST backfill wire format
(``massive_rest``) or the live WebSocket wire format (``massive_ws``).  Only
the boundary-assigned provenance fields (``correlation_id``, internal
``sequence``) are allowed to differ.
"""

from __future__ import annotations

import json

from feelies.core.clock import SimulatedClock
from feelies.core.events import NBBOQuote, Trade
from feelies.ingestion.massive_normalizer import MassiveNormalizer

_RECEIVED_NS = 1_700_000_000_000_000_000
_TS_MS = 1_700_000_000_000  # milliseconds
_TS_NS = _TS_MS * 1_000_000  # same instant in nanoseconds


def _normalize_one(source: str, payload: object) -> NBBOQuote | Trade:
    norm = MassiveNormalizer(SimulatedClock(_RECEIVED_NS))
    raw = json.dumps(payload).encode("utf-8")
    out = norm.on_message(raw, _RECEIVED_NS, source)
    assert len(out) == 1, out
    return out[0]


def test_quote_field_parity_rest_vs_ws() -> None:
    ws_msg = [
        {
            "ev": "Q",
            "sym": "AAPL",
            "t": _TS_MS,
            "q": 1,
            "bp": 150.01,
            "ap": 150.03,
            "bs": 9,
            "as": 12,
            "bx": 11,
            "ax": 12,
            "z": 3,
            "c": [1, 2],
            "i": [4],
        }
    ]
    rest_rec = {
        "ticker": "AAPL",
        "sip_timestamp": _TS_NS,
        "sequence_number": 1,
        "bid_price": 150.01,
        "ask_price": 150.03,
        "bid_size": 9,
        "ask_size": 12,
        "bid_exchange": 11,
        "ask_exchange": 12,
        "tape": 3,
        "conditions": [1, 2],
        "indicators": [4],
    }

    q_ws = _normalize_one("massive_ws", ws_msg)
    q_rest = _normalize_one("massive_rest", rest_rec)
    assert isinstance(q_ws, NBBOQuote) and isinstance(q_rest, NBBOQuote)

    canonical = (
        "symbol",
        "bid",
        "ask",
        "bid_size",
        "ask_size",
        "bid_exchange",
        "ask_exchange",
        "tape",
        "conditions",
        "indicators",
        "exchange_timestamp_ns",
        "sequence_number",
    )
    for field in canonical:
        assert getattr(q_ws, field) == getattr(q_rest, field), (
            f"quote field {field!r} differs: ws={getattr(q_ws, field)!r} "
            f"rest={getattr(q_rest, field)!r}"
        )


def test_trade_field_parity_rest_vs_ws() -> None:
    ws_msg = [
        {
            "ev": "T",
            "sym": "MSFT",
            "t": _TS_MS,
            "q": 1,
            "p": 410.55,
            "s": 500,
            "x": 4,
            "i": "abc",
            "z": 1,
            "c": [12, 14],
        }
    ]
    rest_rec = {
        "ticker": "MSFT",
        "sip_timestamp": _TS_NS,
        "sequence_number": 1,
        "price": 410.55,
        "size": 500,
        "exchange": 4,
        "id": "abc",
        "tape": 1,
        "conditions": [12, 14],
    }

    t_ws = _normalize_one("massive_ws", ws_msg)
    t_rest = _normalize_one("massive_rest", rest_rec)
    assert isinstance(t_ws, Trade) and isinstance(t_rest, Trade)

    canonical = (
        "symbol",
        "price",
        "size",
        "exchange",
        "trade_id",
        "tape",
        "conditions",
        "exchange_timestamp_ns",
        "sequence_number",
    )
    for field in canonical:
        assert getattr(t_ws, field) == getattr(t_rest, field), (
            f"trade field {field!r} differs: ws={getattr(t_ws, field)!r} "
            f"rest={getattr(t_rest, field)!r}"
        )
