def initial_state():
    return {"ewma": None, "ema_var": 0.0, "n": 0}


def update(quote, state, params):
    mid = float((quote.bid + quote.ask) / 2)
    alpha = 2.0 / (params["ewma_span"] + 1)

    if state["ewma"] is None:
        state["ewma"] = mid
        state["n"] = 1
        return 0.0

    diff = mid - state["ewma"]
    state["ema_var"] = alpha * (diff * diff) + (1.0 - alpha) * state["ema_var"]
    state["ewma"] = alpha * mid + (1.0 - alpha) * state["ewma"]
    state["n"] += 1

    std = max(state["ema_var"] ** 0.5, 1e-12)
    return (mid - state["ewma"]) / std
