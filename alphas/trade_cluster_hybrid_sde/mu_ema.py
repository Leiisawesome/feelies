def initial_state():
    return {"prev_microprice": None, "prev_spread": None, "ewma_var": 0.0, "mu_ema": 0.0}

def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    bid_sz = float(quote.bid_size)
    ask_sz = float(quote.ask_size)
    spread = ask - bid
    total = bid_sz + ask_sz
    mp = (bid * ask_sz + ask * bid_sz) / total if total > 0 else (bid + ask) / 2.0
    if state["prev_microprice"] is None:
        state["prev_microprice"] = mp
        state["prev_spread"] = spread
        return 0.0
    spread_vel = spread - state["prev_spread"]
    micro_vel = mp - state["prev_microprice"]
    raw_mu = spread_vel * micro_vel
    vol_alpha = params.get("ewma_vol_alpha", 0.94)
    state["ewma_var"] = vol_alpha * state["ewma_var"] + (1.0 - vol_alpha) * (micro_vel ** 2)
    local_vol = state["ewma_var"] ** 0.5 + 1e-12
    mu_norm = raw_mu / local_vol
    ema_alpha = params.get("drift_confirm_alpha", 0.98)
    state["mu_ema"] = ema_alpha * state["mu_ema"] + (1.0 - ema_alpha) * mu_norm
    state["prev_microprice"] = mp
    state["prev_spread"] = spread
    return float(state["mu_ema"])