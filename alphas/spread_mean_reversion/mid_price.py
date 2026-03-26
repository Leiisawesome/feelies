def initial_state():
    return {}


def update(quote, state, params):
    return float((quote.bid + quote.ask) / 2)
