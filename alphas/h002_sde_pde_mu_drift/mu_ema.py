def initial_state():
    return {
        "prev_microprice": None,
        "prev_spread": None,
        "ewma_var": 0.0,
        "mu_ema": 0.0,
    }


def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    bid_size = float(quote.bid_size)
    ask_size = float(quote.ask_size)

    current_spread = ask - bid
    total_size = bid_size + ask_size
    if total_size > 0:
        current_microprice = (bid * ask_size + ask * bid_size) / total_size
    else:
        current_microprice = (bid + ask) / 2.0

    if state["prev_microprice"] is None:
        state["prev_microprice"] = current_microprice
        state["prev_spread"] = current_spread
        return 0.0

    spread_vel = current_spread - state["prev_spread"]
    micro_vel = current_microprice - state["prev_microprice"]
    raw_mu = spread_vel * micro_vel

    vol_alpha = params["ewma_vol_alpha"]
    state["ewma_var"] = vol_alpha * state["ewma_var"] + (1.0 - vol_alpha) * (micro_vel ** 2)
    local_vol = state["ewma_var"] ** 0.5 + 1e-12
    mu_norm = raw_mu / local_vol

    ema_alpha = params["mu_ema_alpha"]
    state["mu_ema"] = ema_alpha * state["mu_ema"] + (1.0 - ema_alpha) * mu_norm

    state["prev_microprice"] = current_microprice
    state["prev_spread"] = current_spread

    return float(state["mu_ema"])
