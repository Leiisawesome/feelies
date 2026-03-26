def initial_state():
    return {}


def update(quote, state, params):
    return float(quote.ask - quote.bid)
