def initial_state():
    return {"prev_microprice": None, "streak": 0, "last_sign": 0}


def update(quote, state, params):
    """Count consecutive ticks where microprice velocity maintains direction.

    Tracks the same microprice that mu_ema uses as its input, but instead
    of smoothing it into an EMA, counts how many ticks in a row the
    velocity has stayed positive or negative. A long streak means the
    drift is structurally persistent, not just a smoothed echo of one
    large move.
    """
    bid = float(quote.bid)
    ask = float(quote.ask)
    bid_sz = float(quote.bid_size)
    ask_sz = float(quote.ask_size)
    total = bid_sz + ask_sz
    if total <= 0:
        return float(state["streak"])

    mp = (bid * ask_sz + ask * bid_sz) / total

    if state["prev_microprice"] is None:
        state["prev_microprice"] = mp
        return 0.0

    micro_vel = mp - state["prev_microprice"]
    state["prev_microprice"] = mp

    min_vel = params.get("persistence_min_velocity", 1e-4)

    if micro_vel > min_vel:
        current_sign = 1
    elif micro_vel < -min_vel:
        current_sign = -1
    else:
        state["streak"] = 0
        state["last_sign"] = 0
        return 0.0

    if current_sign == state["last_sign"]:
        state["streak"] += 1
    else:
        state["streak"] = 1
        state["last_sign"] = current_sign

    return float(state["streak"])
