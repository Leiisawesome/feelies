def initial_state():
    return {
        "ewma_spread_bp": None,
        "ewma_total_size": None,
    }


def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    bid_size = float(quote.bid_size)
    ask_size = float(quote.ask_size)

    mid = (bid + ask) / 2.0
    if mid <= 0:
        return 0.0

    spread_bp = (ask - bid) / mid * 10000.0
    total_size = bid_size + ask_size

    # Use spread_z_alpha for smoothing (same time scale as spread regime)
    alpha = params.get("spread_z_alpha", 0.99)

    if state["ewma_spread_bp"] is None:
        state["ewma_spread_bp"] = spread_bp
        state["ewma_total_size"] = max(float(total_size), 1.0)
        return 0.5  # neutral at initialization

    state["ewma_spread_bp"] = alpha * state["ewma_spread_bp"] + (1.0 - alpha) * spread_bp
    state["ewma_total_size"] = alpha * state["ewma_total_size"] + (1.0 - alpha) * float(total_size)

    # Spread health: current spread relative to its EWMA
    # Score = 1.0 when spread at or below average, decays as spread widens
    spread_ratio = spread_bp / max(state["ewma_spread_bp"], 1e-6)
    spread_health = max(0.0, min(1.0, (2.0 - spread_ratio) / 1.5))

    # Size health: current depth relative to its EWMA
    size_ratio = float(total_size) / max(state["ewma_total_size"], 1.0)
    size_health = max(0.0, min(1.0, (size_ratio - 0.25) / 0.75))

    # Composite tradability score
    return float(0.6 * spread_health + 0.4 * size_health)
