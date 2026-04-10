"""Trade intensity: EMA of trade arrival rate.

Measures clustering density - higher values indicate more trades per quote,
suggesting self-exciting flow patterns.
"""


def initial_state():
    return {"ema": 0.0}


def update_trade(trade, state, params):
    """On each trade, increment intensity (original behavior)."""
    alpha = params.get("intensity_alpha", 0.91)
    state["ema"] = alpha * state["ema"] + (1.0 - alpha) * 1.0
    return float(state["ema"])


def update(quote, state, params):
    """On each quote, return current intensity."""
    return float(state.get("ema", 0.0))