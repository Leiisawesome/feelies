def initial_state():
    return {"ema": 0.0}


def update(quote, state, params):
    """Order Book Imbalance: (bid_size - ask_size) / (bid_size + ask_size)
    
    Positive = bid pressure (buying)
    Negative = ask pressure (selling)
    Zero = balanced
    
    Uses EMA smoothing to reduce noise.
    """
    bid_sz = float(quote.bid_size)
    ask_sz = float(quote.ask_size)
    total = bid_sz + ask_sz
    
    if total <= 0:
        return float(state.get("ema", 0.0))
    
    raw_obi = (bid_sz - ask_sz) / total
    
    alpha = params.get("obi_alpha", 0.95)
    state["ema"] = alpha * state["ema"] + (1 - alpha) * raw_obi
    
    return float(state["ema"])