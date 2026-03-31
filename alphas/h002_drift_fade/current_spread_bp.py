def initial_state():
    return {}


def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return 9999.0
    return (ask - bid) / mid * 10000.0
