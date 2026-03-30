def initial_state():
    return {}


def update(quote, state, params):
    bid_size = float(quote.bid_size)
    ask_size = float(quote.ask_size)

    total_size = bid_size + ask_size
    if total_size <= 0:
        return 0.0

    # Raw instantaneous imbalance — no smoothing.
    # Positive = more resting bids (buy pressure), negative = more asks.
    return float((bid_size - ask_size) / total_size)
