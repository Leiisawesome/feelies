"""Continuous-time latent drift filter for microprice dynamics.

State equation:
    dmu_t = -kappa * mu_t dt + q_t dW_t

Observation equation:
    dM_t / dt = mu_t + eps_t

The feature maintains a latent drift estimate mu_t, its posterior variance,
and an observation-noise estimate driven by realized microprice velocity.
All trade decisions downstream are derived from this state alone.
"""


def initial_state():
    return {
        "prev_microprice": None,
        "prev_ts_ns": None,
        "mu": 0.0,
        "state_var": 1e-6,
        "obs_var": 1e-4,
        "last_mid": None,
    }


def update(quote, state, params):
    bid = float(quote.bid)
    ask = float(quote.ask)
    bid_sz = float(quote.bid_size)
    ask_sz = float(quote.ask_size)
    total = bid_sz + ask_sz
    ts_ns = quote.exchange_timestamp_ns

    mid = (bid + ask) * 0.5
    microprice = (
        (bid * ask_sz + ask * bid_sz) / total
        if total > 0
        else mid
    )

    if state["prev_microprice"] is None:
        state["prev_microprice"] = microprice
        state["prev_ts_ns"] = ts_ns
        state["last_mid"] = mid
        return [0.0, 0.0, 0.0, 0.0]

    dt = max((ts_ns - state["prev_ts_ns"]) / 1e9, 1e-6)

    drift_half_life = max(params.get("drift_half_life_seconds", 1.5), 1e-6)
    vol_half_life = max(params.get("vol_half_life_seconds", 5.0), 1e-6)

    kappa = math.log(2.0) / drift_half_life
    phi = math.exp(-kappa * dt)
    vol_decay = math.exp(-math.log(2.0) * dt / vol_half_life)

    observed_velocity = (microprice - state["prev_microprice"]) / dt

    residual = observed_velocity - state["mu"]
    state["obs_var"] = (
        vol_decay * state["obs_var"]
        + (1.0 - vol_decay) * residual * residual
    )
    obs_var = max(state["obs_var"], 1e-12)

    prior_mu = phi * state["mu"]
    process_var = obs_var * (1.0 - phi * phi)
    prior_var = max(phi * phi * state["state_var"] + process_var, 1e-12)

    measurement_var = max(obs_var / dt, 1e-12)
    gain = prior_var / (prior_var + measurement_var)
    innovation = observed_velocity - prior_mu

    state["mu"] = prior_mu + gain * innovation
    state["state_var"] = max((1.0 - gain) * prior_var, 1e-12)

    if kappa > 1e-12:
        horizon = drift_half_life
        horizon_factor = (1.0 - math.exp(-kappa * horizon)) / kappa
    else:
        horizon_factor = drift_half_life

    expected_move = state["mu"] * horizon_factor
    expected_move_std = (state["state_var"] ** 0.5) * abs(horizon_factor)

    edge_bps = expected_move / max(mid, 1e-9) * 1e4
    edge_uncertainty_bps = expected_move_std / max(mid, 1e-9) * 1e4
    drift_z = state["mu"] / max(state["state_var"] ** 0.5, 1e-9)

    state["prev_microprice"] = microprice
    state["prev_ts_ns"] = ts_ns
    state["last_mid"] = mid

    return [
        float(state["mu"]),
        float(drift_z),
        float(edge_bps),
        float(edge_uncertainty_bps),
    ]