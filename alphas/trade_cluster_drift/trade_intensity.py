def initial_state():
    return {"ema": 0.0}

def update_trade(trade, state, params):
    alpha = params.get("intensity_alpha", 0.94)
    state["ema"] = alpha * state["ema"] + (1.0 - alpha) * 1.0
    return float(state["ema"])

def update(quote, state, params):
    return float(state.get("ema", 0.0))