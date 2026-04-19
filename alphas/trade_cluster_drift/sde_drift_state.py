"""Continuous-time latent drift filter for microprice dynamics.

State equation:
    dmu_t = -kappa(regime) * mu_t dt + q_t dW_t

Observation equation:
    dM_t / dt = mu_t + eps_t

The feature maintains a latent drift estimate mu_t, its posterior variance,
and an observation-noise estimate driven by realized microprice velocity.

Regime-adaptive kappa (Con 1) adjusts filter speed to market conditions.
Huberized innovations (Con 2) provide robustness to heavy-tailed jumps.
Innovation-variance tracking (Con 7) self-corrects process noise calibration.
Dynamic horizon (Con 6) uses expected first-passage time for edge estimation.
Crossing state (Con 4) is emitted as element 4 for pure signal evaluation.
"""

try:
    _regime_fn = regime_posteriors
except NameError:
    _regime_fn = None


def initial_state():
    return {
        "prev_microprice": None,
        "prev_ts_ns": None,
        "mu": 0.0,
        "state_var": 1e-6,
        "obs_var": 1e-4,
        "innov_var": 1.0,
        "prev_abs_z": 0.0,
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

    prev_abs_z = state["prev_abs_z"]

    if state["prev_microprice"] is None:
        state["prev_microprice"] = microprice
        state["prev_ts_ns"] = ts_ns
        state["last_mid"] = mid
        spread_bps = (ask - bid) / max(mid, 1e-9) * 1e4
        return [0.0, 0.0, 0.0, 0.0, prev_abs_z, float(spread_bps)]

    dt = max((ts_ns - state["prev_ts_ns"]) / 1e9, 1e-6)

    drift_half_life = max(params.get("drift_half_life_seconds", 1.5), 1e-6)
    vol_drift_ratio = max(params.get("vol_drift_ratio", 3.33), 1.0)
    vol_half_life = drift_half_life * vol_drift_ratio

    # Regime-adaptive kappa: blend per-regime half-lives by posterior
    # probability. compression → faster reversion (edge is fleeting),
    # vol_breakout → slower reversion (drift is persistent).
    base_kappa = math.log(2.0) / drift_half_life

    kappa = base_kappa
    if _regime_fn is not None:
        posteriors = _regime_fn(quote.symbol)
        if posteriors is not None and len(posteriors) >= 3:
            max_p = max(posteriors[0], posteriors[1], posteriors[2])
            if max_p < 0.99:
                blended_hl = (
                    posteriors[0] * drift_half_life * 0.5
                    + posteriors[1] * drift_half_life * 1.0
                    + posteriors[2] * drift_half_life * 2.5
                )
                kappa = math.log(2.0) / max(blended_hl, 1e-6)

    phi = math.exp(-kappa * dt)
    vol_decay = math.exp(-math.log(2.0) * dt / vol_half_life)

    observed_velocity = (microprice - state["prev_microprice"]) / dt

    residual = observed_velocity - state["mu"]
    state["obs_var"] = (
        vol_decay * state["obs_var"]
        + (1.0 - vol_decay) * residual * residual
    )
    obs_var = max(state["obs_var"], 1e-12)

    # Innovation-variance adaptive process noise: scale by the ratio of
    # empirical to expected innovation variance. Self-corrects when the
    # filter is miscalibrated (too sluggish or too jittery).
    innov_ratio = max(min(state["innov_var"], 5.0), 0.2)
    process_var = obs_var * (1.0 - phi * phi) * innov_ratio

    prior_mu = phi * state["mu"]
    prior_var = max(phi * phi * state["state_var"] + process_var, 1e-12)

    measurement_var = max(obs_var / dt, 1e-12)
    gain = prior_var / (prior_var + measurement_var)
    innovation = observed_velocity - prior_mu

    # Huberized innovation: clip the influence of outlier innovations at
    # huber_k standard deviations. Prevents the filter from chasing
    # heavy-tailed microprice jumps while preserving optimality under
    # near-Gaussian conditions.
    huber_k = params.get("huber_threshold", 3.0)
    innovation_std = max((prior_var + measurement_var) ** 0.5, 1e-12)
    normalized_innov = innovation / innovation_std

    if abs(normalized_innov) > huber_k:
        clipped_sign = 1.0 if innovation > 0.0 else -1.0
        clipped_innovation = huber_k * clipped_sign * innovation_std
    else:
        clipped_innovation = innovation

    state["mu"] = prior_mu + gain * clipped_innovation
    state["state_var"] = max((1.0 - gain) * prior_var, 1e-12)

    # Update innovation variance tracker (uses raw innovation, not clipped,
    # so the tracker sees the true tail behavior).
    innov_decay = math.exp(-math.log(2.0) * dt / vol_half_life)
    norm_innov_sq = normalized_innov * normalized_innov
    state["innov_var"] = (
        innov_decay * state["innov_var"]
        + (1.0 - innov_decay) * norm_innov_sq
    )

    # Dynamic horizon: expected time for |OU drift_z| to decay from current
    # level to the exit boundary. Uses deterministic OU decay approximation:
    # E[tau] ≈ (1/kappa) * ln(|z| / z_exit).
    drift_z = state["mu"] / max(state["state_var"] ** 0.5, 1e-9)
    abs_z = abs(drift_z)
    exit_z = params.get("entry_z", 1.5) * params.get("exit_fraction", 0.33)

    if abs_z > exit_z and kappa > 1e-12:
        expected_hold = min(
            math.log(abs_z / max(exit_z, 1e-9)) / kappa,
            3.0 * drift_half_life,
        )
        horizon_factor = (1.0 - math.exp(-kappa * expected_hold)) / kappa
    elif kappa > 1e-12:
        horizon_factor = (1.0 - math.exp(-kappa * drift_half_life)) / kappa
    else:
        horizon_factor = drift_half_life

    expected_move = state["mu"] * horizon_factor
    expected_move_std = (state["state_var"] ** 0.5) * abs(horizon_factor)

    edge_bps = expected_move / max(mid, 1e-9) * 1e4
    edge_uncertainty_bps = expected_move_std / max(mid, 1e-9) * 1e4

    state["prev_abs_z"] = abs(drift_z)

    state["prev_microprice"] = microprice
    state["prev_ts_ns"] = ts_ns
    state["last_mid"] = mid

    spread_bps = (ask - bid) / max(mid, 1e-9) * 1e4
    return [
        float(state["mu"]),
        float(drift_z),
        float(edge_bps),
        float(edge_uncertainty_bps),
        float(prev_abs_z),
        float(spread_bps),
    ]
