# `sig_inventory_revert_v1` — strong-edge audit

Adversarial audit of `alphas/sig_inventory_revert_v1/sig_inventory_revert_v1.alpha.yaml`
against the attached architecture spec
(`docs/uploads/c20cebbf-sig_inventory_revert_v1_architecture.md`) and the
shipped Layer-1 / Layer-2 wiring under `src/feelies/`.

Scope: identify defects, design weaknesses, and mis-calibrations that prevent
this alpha from being a strong-edge SIGNAL. No backtest evidence in scope; all
findings are evidence-backed from source.

Audit branch: `claude/audit-alpha-architecture-9D02K`.

---

## Executive summary

| # | Severity | Area | Headline |
|---|----------|------|----------|
| F1 | BLOCKER | tests / cost gate | Shipped `cost_floor_bps: 3.0` contradicts the alpha's own disclosure (one-way cost = 5.5 bps); the acceptance test that encodes the 5.5 bps floor (`test_no_emission_below_cost_floor`) currently FAILS on `main`. |
| F2 | HIGH | edge calibration | At default `edge_per_z_bps=3.5` and `edge_cap_bps=14.0`, the largest possible edge is reached at \|z\| ≈ 6 σ; under disclosed costs the B4 round-trip gate (`signal_min_edge_cost_ratio: 1.5`) requires edge ≥ 16.5 bps — the alpha cannot clear B4 at any z-score given the disclosed cost model. |
| F3 | HIGH | gate / param coupling | `on_condition` uses a hard literal `abs(...zscore) > 2.0`; `evaluate()` reads `params["asymmetry_z_threshold"]`. Any `parameter_overrides` divergence silently breaks the gate↔signal contract. The declared `posterior_margin` / `percentile_margin` hysteresis values are loaded but unreferenced — there is no actual hysteresis band. |
| F4 | HIGH | mechanism semantics | The sensor `quote_replenish_asymmetry` only counts **positive** depth deltas (additions), so the docstring/`evaluate` comment claiming "bid drained > ask drained" is misleading. The sign convention that produces the documented LONG-on-positive-z direction is fragile and undocumented. |
| F5 | HIGH | regime gate redundancy | The HMM emission is purely log-relative-spread (`regime_engine.py`); `P(normal)` is largely a smoothed view of the same statistic the gate already filters via `spread_z_30d > 2.0`. The gate double-counts spread information and adds no orthogonal regime signal. |
| F6 | MEDIUM | HMM calibration risk | `RegimeEngine._DEFAULT_EMISSION` is centered at log-spread −4.5…−2.5 (≈ 1–10% relative spread). AAPL trades at log-relative spread ≈ −10. Without `calibrate()` the HMM concentrates probability on `compression_clustering` and `P(normal)` will sit near 0 — the gate never arms. `regime_calibration_max_quotes=100000` mitigates this in BACKTEST but the alpha will silently fail in LIVE without explicit calibration. |
| F7 | MEDIUM | hazard floor calibration | `quote_hazard_rate` returns quotes-per-second (typical AAPL ≈ 10–200 Hz). `hazard_floor: 0.05` is so loose that any liquid name is "actively quoting" — the floor adds no real protection. |
| F8 | MEDIUM | warm/stale required set | The required-warm set includes `realized_vol_30s_zscore` because it appears in `off_condition`, even though `evaluate()` does not use it. A cold `realized_vol_30s` after a session boundary will suppress every emission, including ones the alpha would otherwise want to issue based on the asymmetry/hazard pair alone. |
| F9 | LOW | sensor double-counts adds only | `quote_replenish_asymmetry` ignores withdrawals entirely; a one-sided sweep with **no** rebuild on either side produces asymmetry ≈ 0 (both sides have low add-rates). The sensor cannot distinguish "depleted, not rebuilding" from "calm market" — exactly the regime the hypothesis cares most about. |
| F10 | LOW | hazard featurisation | `quote_hazard_rate` is exposed only as a `SensorPassthroughFeature`; there is no z-score / percentile companion. The `failure_signature` uses a raw threshold `quote_hazard_rate < 0.05` which does not adapt across symbols or sessions. |
| F11 | LOW | strength heuristic | `strength = min(|asym_z| / (thr * 2), 1.0)`: saturates at `|z| = 2 * thr` (=4 σ). Downstream sizing therefore caps strength well before the edge cap (at z ≈ 6 σ); the two scale parameters disagree. |
| F12 | LOW | provenance | `consumed_features` is populated from `depends_on_sensors` (sensor ids), not the snapshot feature_ids actually consumed (`quote_replenish_asymmetry_zscore`, `quote_hazard_rate`). Forensic parity checks that match on `consumed_features` may miss the gate-only sensor `spread_z_30d` and `realized_vol_30s`. |

Decision recommendation: **RESEARCH_MORE / NOT_READY_FOR_PROMOTION** until F1–F5 are remediated; F6–F8 must be calibrated before LIVE.

---

## Detailed findings

### F1. BLOCKER — `cost_floor_bps` default contradicts disclosed cost (and breaks the shipped test)

- YAML (`sig_inventory_revert_v1.alpha.yaml:76-84`):
  - `cost_floor_bps.default: 3.0`
  - Description claims: `half_spread_bps + impact_bps + fee_bps = 2.5 + 2.0 + 1.0 = 5.5` (one-way).
- `cost_arithmetic` block (`sig_inventory_revert_v1.alpha.yaml:108-113`) confirms `cost_total_bps = 5.5`.
- Test (`tests/alpha/test_sig_inventory_revert_v1.py:241-249`) asserts no emission for `asym_z=3.5` → edge = `1.5 * 3.5 = 5.25`, expecting `cost_floor = 5.5`. This test **fails on the current branch**:

  ```
  test_no_emission_below_cost_floor — AssertionError: assert [Signal(...)] == []
  ```

  Reproduced via `uv run --extra dev python -m pytest tests/alpha/test_sig_inventory_revert_v1.py`.

- Consequence: the alpha currently emits signals with edge as low as **3 bps**, below its own disclosed one-way cost of 5.5 bps. Every such emission contradicts the G12 disclosure stamped onto `Signal.disclosed_cost_total_bps`.

**Fix**: set `cost_floor_bps.default: 5.5` (or wire it from `cost_arithmetic.cost_total_bps` at load time so it cannot drift). Re-run `tests/alpha/test_sig_inventory_revert_v1.py`.

---

### F2. HIGH — Edge ceiling cannot beat the B4 round-trip gate at any z-score

- Spec: `edge_estimate_bps = excess * edge_per_z_bps`, capped at `edge_cap_bps = 14.0`.
- Maximum edge requires `excess = |z| - 2.0 = 14.0 / 3.5 = 4` σ → `|z| ≥ 6.0`.
- Disclosed `cost_total_bps = 5.5` (one-way). The orchestrator B4 gate
  (`orchestrator.py:2931-2944`, `signal_min_edge_cost_ratio: 1.5`) requires
  `edge ≥ 1.5 × round_trip_cost`. Round-trip under disclosed costs = 11 bps;
  required edge ≥ **16.5 bps**. The cap is **14.0 bps** — strictly less.
- Under the platform's actual modeled costs (`passive_limit` entry, taker exit,
  `cost_commission_per_share = 0.0035`, etc.) round-trip is ~3–6 bps for liquid
  large-caps, so B4 can be cleared at `|z| ≳ 4 σ` in practice — but the alpha's
  own disclosure refutes its tradability.

**Fix options** (pick one, do not stack):
1. Raise `edge_cap_bps` to `>= 1.5 × 2 × cost_total_bps` (≥ 16.5 bps with current disclosure) and re-validate via realised half-life back-tests.
2. Tighten the disclosure: if empirical impact on the contrarian leg is <1 bp, drop `impact_bps` and `cost_total_bps` to ~3 bps, which compresses the B4 threshold to ~9 bps — well within the current cap.
3. Raise `edge_per_z_bps` (research-only): with `edge_per_z_bps = 8.5`, a 2-σ excess hits 17 bps and clears B4 under disclosure.

Each option needs empirical edge-per-σ calibration; the current numbers look chosen by inspection, not measurement.

---

### F3. HIGH — Gate threshold hard-codes the same number `evaluate()` parameterises

```yaml
on_condition: abs(quote_replenish_asymmetry_zscore) > 2.0 and P(normal) > 0.5
parameters:
  asymmetry_z_threshold:
    default: 2.0
```

- Two independent literals; nothing keeps them in sync under `platform.yaml.parameter_overrides`. Lower `asymmetry_z_threshold` to 1.5 and the gate still requires 2.0 → the alpha becomes strictly the gate's threshold, undoing the override.
- The `hysteresis:` block declares `posterior_margin: 0.20` and `percentile_margin: 0.30`. `RegimeGate.evaluate` injects these as named bindings (`regime_gate.py:594-606`), but neither identifier appears in `on_condition`/`off_condition`. The intent of "wider band to enter than to leave" is **not** realised — the gate has no hysteresis besides the trivial latch.

**Fix**:
- Either parameterise the gate (`asymmetry_z_threshold + posterior_margin`) using the binding-injection path, e.g.

  ```yaml
  on_condition: |
    abs(quote_replenish_asymmetry_zscore) > 2.0 + posterior_margin
    and P(normal) > 0.5 + posterior_margin
  off_condition: |
    P(normal) < 0.5 - posterior_margin
    or spread_z_30d > 2.0
    or realized_vol_30s_zscore > 3.5
  ```
  This both wires the declared hysteresis margins and makes the gate strictly stricter than `evaluate()`.
- Or drop the redundant evaluate-side threshold check entirely and let the gate be the single source of truth (more brittle; not recommended).
- Add a load-time validator that fails when the gate's numeric literal disagrees with the parameter default (or document the relation explicitly in a comment that cross-references the parameter).

---

### F4. HIGH — Sensor semantics ≠ the alpha's directional comment

`QuoteReplenishAsymmetrySensor` (sensors/impl/quote_replenish_asymmetry.py:106-115):

```python
if d_bid > 0:
    state["bid_adds"].append((ts, d_bid))
if d_ask > 0:
    state["ask_adds"].append((ts, d_ask))
```

Only **positive** depth deltas (replenishment additions) are tracked. The
ratio `(bid_add_rate - ask_add_rate) / (bid_add_rate + ask_add_rate)` is the
asymmetry of *re-quoting*, not of *depletion*.

The `evaluate()` comment (`sig_inventory_revert_v1.alpha.yaml:141-142`) says:

```python
# Contrarian: if asymmetry is positive (bid drained > ask drained),
# micro-price drifts low; we fade by going LONG.
```

This is wrong twice over:
1. The sensor does not measure drains.
2. "Bid drained more than ask" would produce asymmetry of *withdrawals*, which the sensor never observes.

The directional code may still be right under the alternative reading
("bid was depleted, so makers are now busy rebuilding the bid — high
bid-add rate after a hit"), but this is exactly the opposite of the
hypothesis docstring on the sensor itself, which says inventory-stressed
MMs **delay** rebuilding the hit side. Under that hypothesis a bid-hit
event produces *low* bid_add_rate and ask_add_rate ≈ baseline → asymmetry
**negative** → the current `LONG if asym_z > 0` rule fades the wrong way.

**Fix** (in priority order):
1. Add a unit test that injects a synthetic bid-side sweep + delayed-replenish quote stream and asserts the emitted `Signal.direction`. The current acceptance test only stamps `asym_z = +3.6` directly into the snapshot, bypassing the sensor — so it does not exercise the sign convention at all.
2. Decide which hypothesis the alpha bets on (informed-flow rebuild-fast vs inventory-stressed rebuild-slow) and update either the sensor math, the alpha's `evaluate()` direction line, or the comment so the three agree.
3. Consider extending the sensor to expose `(add_asym, drain_asym)` as a tuple feature, so the alpha can name the signature explicitly.

---

### F5. HIGH — `P(normal)` is redundant with `spread_z_30d`

`RegimeEngine._DEFAULT_EMISSION` (services/regime_engine.py:139-159) is a
three-state log-normal mixture over `log(spread / mid)`. There is no
volume, no return path, no order-flow input. `P(normal)` therefore
co-moves almost mechanically with the spread distribution.

The gate's three filters all read the same statistic:
- ON: `P(normal) > 0.5`  ← spread distribution
- OFF: `P(normal) < 0.3` ← spread distribution
- OFF: `spread_z_30d > 2.0` ← spread distribution

`realized_vol_30s_zscore > 3.5` is the only orthogonal gate condition.

**Fix**: either
- Replace the HMM filter with a feature that brings new information (e.g. `ofi_ewma_zscore`, `kyle_lambda_60s_zscore`, hawkes burst, trade-through rate). The inventory mechanism is most degraded when *informed* flow is high — gate on a Kyle/Hawkes burst as an OFF condition.
- Or drop `P(normal)` from the gate and rely on `spread_z_30d` alone for the spread axis, freeing the HMM dependency for alphas that actually need state-conditioning.

---

### F6. MEDIUM — HMM emission defaults are uncalibrated for liquid US equities

`_DEFAULT_EMISSION` means span log-spread of −4.5 (≈ 1.1% relative
spread) down to −2.5 (≈ 8%). Liquid US equities have log-relative
spreads near −10 (1 cent on a $200 name → log(0.01/200) ≈ −9.9).

In an uncalibrated deployment the posterior concentrates on
`compression_clustering` and `P(normal)` stays near 0. The gate's
`on_condition` then never fires. The repo `platform.yaml` sets
`regime_calibration_max_quotes: 100000` which patches this for BACKTEST,
but operators starting from a fresh PAPER/LIVE config without that key
will see zero signals and no diagnostic.

**Fix**: 
- Add a boot-time warning when an alpha's gate references `P(<state>)` and the engine reports `_calibrated=False` and `regime_calibration_max_quotes` is unset.
- Document that this alpha requires either explicit calibration or the calibration knob in any non-BACKTEST mode.

---

### F7. MEDIUM — `hazard_floor` and `quote_hazard_rate` are uncalibrated

`QuoteHazardRateSensor` emits `len(window) / window_seconds` (units:
quotes per second). For AAPL on a normal day this is in the tens to
hundreds. The shipped `hazard_floor: 0.05` (0.05 quotes/sec ≈ one
quote every 20 s) is satisfied by every listed equity at all times.

The `failure_signature` also uses the raw threshold `quote_hazard_rate < 0.05`. Even on the quietest mid-cap, this almost never trips.

**Fix**:
- Either raise `hazard_floor` to something meaningful (e.g. a per-symbol percentile threshold via `quote_hazard_rate_percentile < p20`) — needs a new horizon feature.
- Or replace the raw hazard with a deviation feature: `quote_hazard_rate_zscore < -1.5` would mean "ladder is unusually quiet *for this symbol*".

Add a `RollingZscoreFeature("quote_hazard_rate", horizon)` in
`bootstrap.py:_horizon_features_for` to make this possible without
operator-side wiring.

---

### F8. MEDIUM — `realized_vol_30s_zscore` gates the *gate*, not the trade thesis

`HorizonSignalEngine._on_snapshot` (signals/horizon_engine.py:350-373)
suppresses the entire evaluation when any required-warm feature is
cold/stale. `_required_warm_feature_ids_for_signal_alpha`
(bootstrap.py:731-756) adds every identifier ending in `_zscore` from
the gate. Because `off_condition` references `realized_vol_30s_zscore`,
this feature is *required-warm* even though `evaluate()` never reads it.

After a session boundary or a >30 s data gap, `realized_vol_30s` un-warms
(its window-bounded `len(history)` falls below `warm_after=16`), and the
alpha emits nothing — even when the asymmetry/hazard pair is clearly
extreme. Per Inv-11 the latch will also force OFF and unwind any open
position, which is correct for safety but unwanted churn.

**Fix**:
- Make `realized_vol_30s` an *advisory* OFF condition that does not pull its z-score into `required_warm_feature_ids` when only used in `off_condition`. This is a platform change; alternatively, drop it from the gate and add it to `evaluate()` as a soft suppressor on edge magnitude (e.g. scale `edge_per_z_bps` down when `realized_vol_30s_zscore > 3`).

---

### F9. LOW — `quote_replenish_asymmetry` cannot see drains

Same source as F4: the sensor's `if d_bid > 0` / `if d_ask > 0` filters
discard withdrawals. A bid-side sweep that leaves the depleted side
*flat* (no rebuild for several seconds) registers as asymmetry ≈ 0
because both add rates are tiny. The inventory-stress story relies
exactly on this regime — and the alpha cannot detect it.

**Fix**: add a companion sensor `quote_drain_asymmetry` that tracks the
negative-delta side, or extend the existing sensor to emit a tuple
`(add_asym, drain_asym, net_asym)`. Then the alpha can fade on
`drain_asym > 2 σ` (one-sided depletion) **and** `add_asym < 0`
(failure-to-rebuild on the hit side) for a much stronger inventory
fingerprint.

---

### F10. LOW — `quote_hazard_rate` has no rolling normalisation

`bootstrap.py:_horizon_features_for("quote_hazard_rate", horizon)`
returns only `SensorPassthroughFeature` — raw quotes/sec. There is no
z-score or percentile companion. Cross-symbol portability and
session-time conditioning are therefore impossible without operator
edits in `bootstrap.py`.

**Fix**: extend the mapping to
```python
return [
    SensorPassthroughFeature("quote_hazard_rate", horizon),
    RollingZscoreFeature("quote_hazard_rate", horizon),
]
```
so any alpha can reference `quote_hazard_rate_zscore` immediately. This
also enables F7's recommended `_zscore < -1.5` floor.

---

### F11. LOW — `strength` saturates before edge does

```python
strength = min(abs(asym_z) / (thr * 2.0), 1.0)         # saturates at |z| = 4σ
edge_bps = min(excess * params["edge_per_z_bps"], 14)  # saturates at |z| ≈ 6σ
```

Downstream position sizing will treat `|z| = 4.1` and `|z| = 6.0` as
identical strength even though `edge_estimate_bps` doubles between them.
Align the two scales (or document that strength is intentionally a
plateau).

**Fix**: pick one normaliser; e.g. `strength = min((|z| - thr) / 4.0, 1.0)`
(saturates at the same `|z|` the edge cap saturates at).

---

### F12. LOW — `consumed_features` reports sensor ids, not feature ids

`AlphaLoader._load_signal` (alpha/loader.py:666) sets
`consumed_features=depends_on_sensors`. The actual snapshot keys the
alpha reads are `quote_replenish_asymmetry_zscore` and
`quote_hazard_rate` (feature ids, per `_horizon_features_for`).
Forensic parity tooling that joins on `consumed_features` will not see
the gate-only sensors at all — those flow via `_sensor_cache`, not
through `depends_on_sensors` in any feature-id sense.

**Fix**: emit two distinct fields — `depends_on_sensors` (sensor ids)
and `consumed_features` (snapshot feature_ids + cache-resolved
sensor_ids). This is a platform-level change; mention it in the audit
log so it can be planned.

---

## Strong-edge redesign checklist

To make this alpha a credible strong-edge SIGNAL the following are jointly
necessary; each one alone is insufficient:

1. **Reconcile disclosed cost ↔ `cost_floor_bps` ↔ `edge_cap_bps`** so the
   alpha can clear B4 under its own disclosure (F1, F2).
2. **Empirically calibrate `edge_per_z_bps`** against realised half-life
   reverts on the contrarian leg. Drop the `cost_arithmetic.edge_estimate_bps`
   to the realised median; let `edge_cap_bps` track the realised 99-percentile.
3. **Replace the single-axis spread gate** (`P(normal)` + `spread_z_30d`) with
   one orthogonal regime check, e.g. `kyle_lambda_60s_zscore < 1.5` to suppress
   information-driven sweeps (F5).
4. **Make the gate strictly stricter than `evaluate()`** by wiring the
   declared `posterior_margin` / `percentile_margin` into the DSL expressions,
   not just the binding table (F3).
5. **Rebuild the mechanism signature**: add a drain-side companion to
   `quote_replenish_asymmetry`, and require both `drain_asym > k σ` and
   `add_asym < -k σ` (slow rebuild on the hit side) before arming (F4, F9).
6. **Calibrate or replace the hazard floor** with a z-score / percentile
   feature so it adapts across symbols and sessions (F7, F10).
7. **Add an empirical falsification harness** that measures the 5-/20-/60-s
   half-life envelope from emitted signals and trips a kill switch if the
   realised envelope drifts outside `expected_half_life_seconds = 20 ± 2σ`.
8. **Cover the directional sign convention with a sensor-level test** that
   replays a synthetic bid-sweep stream and asserts the emitted
   `Signal.direction`. The current acceptance suite stamps z-scores
   directly into snapshots and bypasses the sensor, so the F4 bug class is
   invisible to CI.

---

## Reproduction commands

```bash
# F1 — broken acceptance test on the shipped YAML.
uv run --extra dev python -m pytest \
  tests/alpha/test_sig_inventory_revert_v1.py::test_no_emission_below_cost_floor -x

# F2 — verify B4 gate threshold for the shipped cost block:
python - <<'PY'
edge_cap = 14.0
disclosed_cost_one_way = 2.5 + 2.0 + 1.0
ratio = 1.5
required_edge = ratio * 2 * disclosed_cost_one_way
print(f"required_edge={required_edge}  edge_cap={edge_cap}  feasible={edge_cap >= required_edge}")
PY

# F4 — confirm sensor add-only math:
grep -n "if d_bid > 0\|if d_ask > 0" \
  src/feelies/sensors/impl/quote_replenish_asymmetry.py
```
