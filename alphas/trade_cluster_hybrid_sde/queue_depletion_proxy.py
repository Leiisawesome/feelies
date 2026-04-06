def initial_state():
    return {"prev_micro": None, "prev_imb": None, "proxy": 0.0}

def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    bid_sz = float(quote.bid_size)
    ask_sz = float(quote.ask_size)
    total = bid_sz + ask_sz
    mp = (bid * ask_sz + ask * bid_sz) / total if total > 0 else (bid + ask) / 2.0
    imb = (bid_sz - ask_sz) / total if total > 0 else 0.0
    if state["prev_micro"] is None:
        state["prev_micro"] = mp
        state["prev_imb"] = imb
        return 0.0
    vel = mp - state["prev_micro"]
    imb_accel = imb - state["prev_imb"]
    state["proxy"] = vel * imb_accel
    state["prev_micro"] = mp
    state["prev_imb"] = imb
    return float(state["proxy"])