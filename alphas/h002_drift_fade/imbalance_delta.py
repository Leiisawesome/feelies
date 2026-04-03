def initial_state():
    return {
        "prev_imbalance": None,
        "ewma_delta": 0.0,
    }


def update(quote, state, params):
    bid_size = float(quote.bid_size)
    ask_size = float(quote.ask_size)

    total_size = bid_size + ask_size
    if total_size <= 0:
        return float(state["ewma_delta"])

    raw_imbalance = (bid_size - ask_size) / total_size

    if state["prev_imbalance"] is None:
        state["prev_imbalance"] = raw_imbalance
        return 0.0

    # Tick-by-tick change in imbalance — captures flow of liquidity
    # replenishment/depletion.  Positive delta = buy pressure accelerating.
    delta = raw_imbalance - state["prev_imbalance"]
    state["prev_imbalance"] = raw_imbalance

    alpha = params["imbalance_delta_alpha"]
    state["ewma_delta"] = alpha * state["ewma_delta"] + (1.0 - alpha) * delta

    return float(state["ewma_delta"])
