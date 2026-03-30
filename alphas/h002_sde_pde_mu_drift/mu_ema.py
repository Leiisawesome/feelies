def initial_state():
    return {
        "prev_microprice": None,
        "ewma_drift": 0.0,
        "ewma_abs_drift": 1e-12,
    }


def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    bid_size = float(quote.bid_size)
    ask_size = float(quote.ask_size)

    # Size-weighted microprice — best L1 proxy for true price
    total_size = bid_size + ask_size
    if total_size > 0:
        microprice = (bid * ask_size + ask * bid_size) / total_size
    else:
        microprice = (bid + ask) / 2.0

    if state["prev_microprice"] is None:
        state["prev_microprice"] = microprice
        return 0.0

    # Tick-by-tick microprice change — the actual SDE drift increment dS
    delta = microprice - state["prev_microprice"]
    state["prev_microprice"] = microprice

    ema_alpha = params["mu_ema_alpha"]

    # EWMA of drift (signed) — Fokker-Planck first moment estimator
    state["ewma_drift"] = ema_alpha * state["ewma_drift"] + (1.0 - ema_alpha) * delta

    # EWMA of |drift| for normalization — same units as numerator
    state["ewma_abs_drift"] = ema_alpha * state["ewma_abs_drift"] + (1.0 - ema_alpha) * abs(delta)

    # Normalized drift: dimensionless, bounded roughly in [-1, 1]
    norm = state["ewma_abs_drift"] + 1e-12
    return float(state["ewma_drift"] / norm)
