"""Aggressor flow: EMA of signed trade size (buyer/seller initiated).

Positive = buy trades (aggressor), Negative = sell trades.
Uses sqrt(size) to dampen large trades while preserving order flow direction.
"""


def initial_state():
    return {"ema": 0.0, "last_mid": 0.0}


def _sqrt(x):
    """Fast integer sqrt using Newton's method."""
    if x <= 0:
        return 0.0
    # Simple approximation: for typical trade sizes, sqrt is well-approximated
    # by the integer square root
    return float(x ** 0.5)


def update_trade(trade, state, params):
    """Update EMA with signed trade size. Trade at mid decays toward zero."""
    mid = state.get("last_mid", 0.0)
    price = float(trade.price)
    size = float(trade.size)
    
    # Use sqrt(size) to dampen large trades - prevents single large trades
    # from overwhelming the flow signal
    signed_size = _sqrt(size)
    
    if price > mid:
        raw = signed_size  # Buy at ask = aggressive buyer
    elif price < mid:
        raw = -signed_size  # Sell at bid = aggressive seller
    else:
        # At mid-price: decay toward zero (no clear direction)
        raw = state.get("ema", 0.0) * 0.5
    
    alpha = params.get("aggressor_alpha", 0.93)
    state["ema"] = alpha * state["ema"] + (1.0 - alpha) * raw
    return float(state["ema"])


def update(quote, state, params):
    """Update last mid-price from quote."""
    state["last_mid"] = float((quote.bid + quote.ask) / 2)
    return float(state.get("ema", 0.0))