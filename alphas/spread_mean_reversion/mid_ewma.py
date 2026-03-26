def initial_state():
    return {"ewma": None, "n": 0}


def update(quote, state, params):
    mid = float((quote.bid + quote.ask) / 2)
    alpha = 2.0 / (params["ewma_span"] + 1)
    if state["ewma"] is None:
        state["ewma"] = mid
    else:
        state["ewma"] = alpha * mid + (1.0 - alpha) * state["ewma"]
    state["n"] += 1
    return state["ewma"]
