def initial_state():
    return {
        "prev_microprice": None,
        "ewma_drift": 0.0,
        "ewma_drift_var": 1e-12,
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

    # Innovation: deviation from PRIOR drift estimate (computed before update)
    diff = delta - state["ewma_drift"]

    # EWMA of drift (signed) — Fokker-Planck first moment estimator
    state["ewma_drift"] = ema_alpha * state["ewma_drift"] + (1.0 - ema_alpha) * delta

    # EWMA of squared innovation — noise variance estimator
    state["ewma_drift_var"] = ema_alpha * state["ewma_drift_var"] + (1.0 - ema_alpha) * (diff * diff)

    # Proper EWMA z-score with variance correction.
    # SE(EWMA(X)) = σ · √((1-α)/(1+α)) when Var(X) = σ².
    # z = EWMA(X) / SE(EWMA(X)) = EWMA(X) · √((1+α)/(1-α)) / σ
    # With α=0.995: correction factor ≈ 20 (effective n ≈ 399).
    noise_std = max(state["ewma_drift_var"] ** 0.5, 1e-12)
    variance_correction = ((1.0 + ema_alpha) / (1.0 - ema_alpha)) ** 0.5
    return float(state["ewma_drift"] / noise_std * variance_correction)
