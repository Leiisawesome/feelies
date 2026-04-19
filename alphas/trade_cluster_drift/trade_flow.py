"""EWMA-decayed signed trade flow imbalance.

Classifies each trade print as buy or sell relative to the prevailing
midpoint, then accumulates exponentially decaying signed flow.  Output
is a normalized imbalance in [-1, +1]:  +1 = all recent flow is buying,
-1 = all recent flow is selling, 0 = balanced or no data.

The signal layer uses this as a directional confirmation gate: entries
are suppressed when trade flow actively opposes the inferred drift
direction.
"""


def initial_state():
    return {
        "buy_flow": 0.0,
        "sell_flow": 0.0,
        "last_ts_ns": None,
        "last_mid": None,
        "prev_trade_price": None,
    }


def update(quote, state, params):
    """Quote update: track the current mid for trade classification."""
    bid = float(quote.bid)
    ask = float(quote.ask)
    state["last_mid"] = (bid + ask) * 0.5
    state["last_ts_ns"] = quote.exchange_timestamp_ns

    total = state["buy_flow"] + state["sell_flow"]
    if total < 1e-12:
        return 0.0

    return (state["buy_flow"] - state["sell_flow"]) / total


def update_trade(trade, state, params):
    """Trade update: classify by Lee-Ready and accumulate decaying flow."""
    if state["last_mid"] is None or state["last_ts_ns"] is None:
        return None

    price = float(trade.price)
    mid = state["last_mid"]
    size = float(trade.size)
    ts_ns = trade.exchange_timestamp_ns

    dt = max((ts_ns - state["last_ts_ns"]) / 1e9, 1e-6)
    half_life = max(params.get("drift_half_life_seconds", 1.5), 1e-6)
    decay = math.exp(-math.log(2.0) * dt / half_life)

    state["buy_flow"] *= decay
    state["sell_flow"] *= decay

    if price > mid:
        state["buy_flow"] += size
    elif price < mid:
        state["sell_flow"] += size
    else:
        # Tick test (Lee-Ready): at-mid trades classified by prior trade
        # direction. Prevents buy-bias from internalized at-mid flow.
        prev = state["prev_trade_price"]
        if prev is not None and price < prev:
            state["sell_flow"] += size
        elif prev is not None:
            state["buy_flow"] += size

    state["prev_trade_price"] = price
    state["last_ts_ns"] = ts_ns

    total = state["buy_flow"] + state["sell_flow"]
    if total < 1e-12:
        return 0.0
    return (state["buy_flow"] - state["sell_flow"]) / total
