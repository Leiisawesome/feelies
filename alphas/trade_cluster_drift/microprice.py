"""Microprice: volume-weighted mid-price.

The microprice adjusts the mid-price by weighting toward the side with
more volume. It captures the immediate fair value more accurately than
the simple mid-price, especially during imbalanced order books.

Formula: (bid * ask_size + ask * bid_size) / (bid_size + ask_size)
"""


def initial_state():
    return {"prev_microprice": None}


def update(quote, state, params):
    """Compute microprice from quote."""
    bid = float(quote.bid)
    ask = float(quote.ask)
    bid_sz = float(quote.bid_size)
    ask_sz = float(quote.ask_size)
    total = bid_sz + ask_sz
    
    if total <= 0:
        return state.get("prev_microprice", (bid + ask) / 2.0)
    
    # Volume-weighted mid (microprice)
    mp = (bid * ask_sz + ask * bid_sz) / total
    state["prev_microprice"] = mp
    
    return float(mp)