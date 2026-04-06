def initial_state():
    return {"buy_vol": 0.0, "sell_vol": 0.0, "vpin": 0.0}

def update_trade(trade, state, params):
    alpha = params.get("vpin_alpha", 0.999)
    if "last_mid" not in state:
        return state.get("vpin", 0.0)
    mid = state["last_mid"]
    vol = float(trade.size)
    if trade.price > mid:
        state["buy_vol"] = alpha * state["buy_vol"] + (1 - alpha) * vol
        state["sell_vol"] = alpha * state["sell_vol"]
    elif trade.price < mid:
        state["sell_vol"] = alpha * state["sell_vol"] + (1 - alpha) * vol
        state["buy_vol"] = alpha * state["buy_vol"]
    total = state["buy_vol"] + state["sell_vol"]
    state["vpin"] = abs(state["buy_vol"] - state["sell_vol"]) / total if total > 0 else 0.0
    return float(state["vpin"])

def update(quote, state, params):
    return float(state.get("vpin", 0.0))