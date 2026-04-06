def initial_state():
    return {"prev_spread_bps": None, "ema": 0.0}

def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return state.get("ema", 0.0)
    spread_bps = (ask - bid) / mid * 10000.0
    if state["prev_spread_bps"] is None:
        state["prev_spread_bps"] = spread_bps
        return 0.0
    vel = spread_bps - state["prev_spread_bps"]
    compression = max(-vel, 0.0)
    alpha = params.get("compression_alpha", 0.92)
    state["ema"] = alpha * state["ema"] + (1.0 - alpha) * compression
    state["prev_spread_bps"] = spread_bps
    return float(state["ema"])