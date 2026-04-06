def initial_state():
    return {"ema": 0.0}

def update_trade(trade, state, params):
    if "last_mid" not in state:
        return state.get("ema", 0.0)
    mid = state["last_mid"]
    raw = 1.0 if trade.price > mid else (-1.0 if trade.price < mid else 0.0)
    alpha = params.get("aggressor_alpha", 0.96)
    state["ema"] = alpha * state["ema"] + (1.0 - alpha) * raw
    return float(state["ema"])

def update(quote, state, params):
    state["last_mid"] = float((quote.bid + quote.ask) / 2)
    return float(state.get("ema", 0.0))