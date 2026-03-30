def initial_state():
    return {
        "ewma_spread": None,
        "ewma_var": 0.0,
    }


def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return 0.0

    spread_bp = (ask - bid) / mid * 10000.0

    alpha = params["spread_z_alpha"]

    if state["ewma_spread"] is None:
        state["ewma_spread"] = spread_bp
        return 0.0

    diff = spread_bp - state["ewma_spread"]

    # Update EWMA of spread and EWMA of variance
    state["ewma_var"] = alpha * state["ewma_var"] + (1.0 - alpha) * (diff * diff)
    state["ewma_spread"] = alpha * state["ewma_spread"] + (1.0 - alpha) * spread_bp

    std = max(state["ewma_var"] ** 0.5, 1e-12)

    # Z-score: negative = spread compressing (favorable), positive = widening
    return float((spread_bp - state["ewma_spread"]) / std)
