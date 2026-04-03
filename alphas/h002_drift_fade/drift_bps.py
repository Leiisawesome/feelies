def initial_state():
    return {
        "prev_microprice": None,
        "ewma_drift_bps": 0.0,
    }


def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    bid_size = float(quote.bid_size)
    ask_size = float(quote.ask_size)

    mid = (bid + ask) / 2.0
    if mid <= 0:
        return 0.0

    total_size = bid_size + ask_size
    if total_size > 0:
        microprice = (bid * ask_size + ask * bid_size) / total_size
    else:
        microprice = mid

    if state["prev_microprice"] is None:
        state["prev_microprice"] = microprice
        return 0.0

    # Microprice change in basis points of mid — properly scaled
    delta_bps = (microprice - state["prev_microprice"]) / mid * 10000.0
    state["prev_microprice"] = microprice

    alpha = params["mu_ema_alpha"]
    state["ewma_drift_bps"] = alpha * state["ewma_drift_bps"] + (1.0 - alpha) * delta_bps

    return float(state["ewma_drift_bps"])
