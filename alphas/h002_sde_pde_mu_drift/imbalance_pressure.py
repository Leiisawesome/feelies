def initial_state():
    return {
        "imbalance_ema": 0.0,
    }


def update(quote, state, params):
    bid_size = float(quote.bid_size)
    ask_size = float(quote.ask_size)

    total_size = bid_size + ask_size
    if total_size <= 0:
        return state["imbalance_ema"]

    raw_imbalance = (bid_size - ask_size) / total_size

    alpha = params["imbalance_ema_alpha"]
    state["imbalance_ema"] = alpha * state["imbalance_ema"] + (1.0 - alpha) * raw_imbalance

    return float(state["imbalance_ema"])
