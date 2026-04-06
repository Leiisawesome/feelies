def initial_state():
    return {"ema": 0.0}

def update(quote, state, params):
    total = float(quote.bid_size + quote.ask_size)
    if total <= 0:
        return state["ema"]
    raw = float(quote.bid_size - quote.ask_size) / total
    alpha = params.get("imbalance_alpha", 0.96)
    state["ema"] = alpha * state["ema"] + (1.0 - alpha) * raw
    return float(state["ema"])