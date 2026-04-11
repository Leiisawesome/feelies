"""Drift detection via continuous-time microprice-spread dynamics.

Measures spread_vel * micro_vel (structural second derivative of price
within spread), normalized by local volatility, then smoothed via an
exponentially-weighted EMA whose half-life is fixed in wall-clock time.

Two improvements over the tick-space v1.0.0 formulation:

1. BBO-change gating: size-only refreshes and duplicate quotes that
   leave both bid and ask prices unchanged contribute zero new velocity
   information.  Applying an EMA step on such ticks only erodes the
   accumulated drift signal.  We skip them entirely.

2. Continuous-time decay: the EMA decay factor is computed from the
   actual elapsed nanoseconds between BBO changes:

       decay = exp(−dt / τ)

   This fixes the half-life at τ seconds regardless of quote arrival
   rate — critical for cross-symbol consistency (AAPL ~1K q/s vs
   NVDA ~2.5K q/s would otherwise produce 2.5× different half-lives
   from the same alpha parameter).

   Requires math.exp(), which is available in the sandboxed exec
   namespace via _SAFE_BUILTINS (no import statement needed).
"""


def initial_state():
    return {
        "prev_microprice": None,
        "prev_spread": None,
        "prev_bid": None,
        "prev_ask": None,
        "prev_ts_ns": None,
        "ewma_var": 0.0,
        "mu_ema": 0.0,
    }


def update(quote, state, params):
    """Compute vol-normalized drift; skip ticks with unchanged BBO prices."""
    bid = float(quote.bid)
    ask = float(quote.ask)
    bid_sz = float(quote.bid_size)
    ask_sz = float(quote.ask_size)
    ts_ns = quote.exchange_timestamp_ns
    spread = ask - bid
    total = bid_sz + ask_sz

    mp = (bid * ask_sz + ask * bid_sz) / total if total > 0 else (bid + ask) * 0.5

    if state["prev_microprice"] is None:
        state["prev_microprice"] = mp
        state["prev_spread"] = spread
        state["prev_bid"] = bid
        state["prev_ask"] = ask
        state["prev_ts_ns"] = ts_ns
        return 0.0

    # Gate: skip when bid/ask prices unchanged (size-only or duplicate refresh).
    # Microprice can only change if bid or ask price changes.
    if bid == state["prev_bid"] and ask == state["prev_ask"]:
        return float(state["mu_ema"])

    spread_vel = spread - state["prev_spread"]
    micro_vel = mp - state["prev_microprice"]

    # Structural signal: spread dynamics confirm price direction.
    raw_mu = spread_vel * micro_vel

    # Continuous-time decay proportional to elapsed real time.
    dt = max((ts_ns - state["prev_ts_ns"]) / 1e9, 1e-9)

    tau_vol = params.get("vol_tau_seconds", 2.0)
    decay_vol = math.exp(-dt / tau_vol)
    state["ewma_var"] = decay_vol * state["ewma_var"] + (1.0 - decay_vol) * micro_vel * micro_vel
    local_vol = state["ewma_var"] ** 0.5 + 1e-12
    mu_norm = raw_mu / local_vol

    tau_mu = params.get("drift_tau_seconds", 1.0)
    decay_mu = math.exp(-dt / tau_mu)
    state["mu_ema"] = decay_mu * state["mu_ema"] + (1.0 - decay_mu) * mu_norm

    state["prev_microprice"] = mp
    state["prev_spread"] = spread
    state["prev_bid"] = bid
    state["prev_ask"] = ask
    state["prev_ts_ns"] = ts_ns

    return float(state["mu_ema"])
