# `sig_dislocation_lambda_drift_v1` — architecture and operator knobs

This note documents the shipped SIGNAL alpha [`alphas/sig_dislocation_lambda_drift_v1/sig_dislocation_lambda_drift_v1.alpha.yaml`](../../alphas/sig_dislocation_lambda_drift_v1/sig_dislocation_lambda_drift_v1.alpha.yaml): **micro-price dislocation × Kyle-λ** continuation on a **300 s (5 min)** horizon. See [`docs/three_layer_architecture.md`](../three_layer_architecture.md) for global architecture.

**Normative artifacts (read-only inputs; the spec is the record):**
[`docs/research/sig_dislocation_lambda_drift_v1_formal_spec.md`](../research/sig_dislocation_lambda_drift_v1_formal_spec.md) (frozen spec, incl. the §16 deviation table with D-1),
[`docs/research/sig_dislocation_lambda_drift_v1_validation_protocol.md`](../research/sig_dislocation_lambda_drift_v1_validation_protocol.md) (pre-registered step 0–8 protocol),
[`docs/research/sig_dislocation_lambda_drift_v1_impl_plan.md`](../research/sig_dislocation_lambda_drift_v1_impl_plan.md) (Task-9 plan + rulings),
census artifacts [`docs/research/artifacts/dislocation_lambda_census_2026-07-12.json`](../research/artifacts/dislocation_lambda_census_2026-07-12.json) / [`docs/research/artifacts/dislocation_lambda_census_expanded_2026-07-13.json`](../research/artifacts/dislocation_lambda_census_expanded_2026-07-13.json)
(instrument: [`scripts/research/dislocation_lambda_census.py`](../../scripts/research/dislocation_lambda_census.py)).

---

## 1. Mechanism (G16: KYLE_INFO, hl 150 s, H 300 s)

A 300 s micro-price dislocation produced by **impact-elevated** flow
(`kyle_lambda_60s` above its trailing-window median) is information
being incorporated — the Kyle pricing rule steepens when informed
intensity rises — and incomplete incorporation leaks into L1 as
**continuation** over the next 300 s.  The identical dislocation with
baseline λ is a liquidity shock and is expected to **revert**; that
λ-contrast IS the falsifier (F2), not a nuance.  `expected_half_life_seconds:
150` sits in the KYLE_INFO envelope [60, 1800]; horizon/hl = 300/150 =
2.0 ∈ [0.5, 4.0].  Both G16 rule-5 fingerprints (`kyle_lambda_60s`,
`micro_price`) are declared and load-bearing.

## 2. Dataflow — sensor → feature → gate → evaluate

```
NBBO + Trades ──> SensorRegistry ──> SensorReading
                     kyle_lambda_60s (2.0.0 causal, min_samples 30)
                     micro_price (1.1.0), realized_vol_30s (1.3.0)
HorizonTick(300s) ─> HorizonAggregator ──> HorizonFeatureSnapshot h=300
RegimeEngine(hmm_3state_fractional) ──> RegimeState (P(vol_breakout))
Snapshot + RegimeState ──> HorizonSignalEngine
   ├─ required-warm set (all four consumed ids warm & not stale)
   ├─ RegimeGate (latched ON/OFF, §4 below)
   └─ evaluate() ──> Signal LONG/SHORT ──> RiskEngine ──> ExecutionBackend
```

The four consumed feature ids at h = 300 (spec §1.3) — all in
`required_warm_feature_ids`, so a cold/stale row suppresses the whole
boundary (entries only; Inv-11):

| feature id | consumed by | role |
|---|---|---|
| `micro_price_drift` | gate + `evaluate()` | the 300 s dislocation (signed) |
| `micro_price` | gate + `evaluate()` | level normaliser (dislocation as a fraction of price) |
| `kyle_lambda_60s_percentile` | gate + `evaluate()` | the λ median split — the mechanism discriminator |
| `realized_vol_30s_zscore` | gate only | vol-blowup backstop for the HMM dwell weakness |

`ofi_ewma` is deliberately absent (spec §16 row 5 — offline diagnostic
only); `spread_z_30d` is banned (§1.1 — census warm 0.03–0.16 on thin
names).

## 3. Frozen constants (spec-frozen; varying any is +1 N)

| constant | value | where |
|---|---|---|
| `disloc_min` (fraction of level) | APP `2.53563e-3`, RMBS `2.37165e-3` (= 0.75 × pack-05 median σ₃₀₀) | `evaluate()` literal dict; gate arms on the weaker RMBS constant |
| EV floor `floor_bps` | APP `4.6809`, RMBS `5.4645` (single-stress 2.25 × (2.0 + fee)) | `evaluate()` literal dict |
| λ split | `0.5` (median; param `lambda_percentile_min` can only tighten, range [0.5, 0.7]) | gate + `evaluate()` |
| gate posterior arm | `P(vol_breakout) < 0.7`, release `> 0.85` (`posterior_margin: 0.15`) | `regime_gate` |
| gate λ release | `< 0.35` (`percentile_margin: 0.15`) — mechanism-lapse exit | `regime_gate` |
| vol backstop | `realized_vol_30s_zscore <= 3.0` (both conditions) | `regime_gate` |
| session knobs | `no_entry_first_seconds: 300`; flatten ON, 600 s before close | [`configs/bt_sig_dislocation_lambda_drift_v1.yaml`](../../configs/bt_sig_dislocation_lambda_drift_v1.yaml) |
| risk budget | 80-share anchor (APP p50 displayed depth) as the binding constraint; 80 % / 80 % at the $100k evidence base | alpha `risk_budget` + impl plan §7.1 ruling record |

Free parameters (≤ 3, spec §6.1): `lambda_percentile_min`,
`edge_scale_bps` (provisional pending Task-8 §3.2 calibration),
`edge_cap_bps`.

## 4. EV gate / B4 interaction (one-way disclosure)

`evaluate()` emits only when the posterior edge clears the per-symbol
single-stress floor (`edge_bps < floor_bps → None`) — never a bare
threshold.  Downstream, **B4** (`signal_min_edge_cost_ratio: 1.5` in
the run config) re-checks the emitted edge against the **modeled round
trip**: the G12 block discloses one-way costs (half-spread 0.0 maker
entry, impact 2.0, fee 0.08 at the 80-share APP anchor), and B4
effectively doubles onto the round-trip basis at ratio 1.5.  The G12
`edge_estimate_bps: 6.4` is the design value (κ 0.190 × APP median
σ₃₀₀); the Task-8 §2.3 **measured** D-set-minimum conditional edge
supersedes it on measurement (00b one-way ratchet — re-disclosure is
its own reviewed edit).  Deviation **D-1** (spec §16 row 8): a minimal
fail-safe finiteness guard on the three consumed inputs — NaN/inf
suppresses the entry (`None`), never creates exposure (Inv-11);
behavior on every finite input is bit-identical to the §6.2 draft.

## 5. Hazard exit

`hazard_exit.enabled: true`, threshold 0.85, min age 30 s;
`hard_exit_age_seconds: null` → bootstrap derives **2 × hl = 300 s**
(HM-1), bounding θ₃ tail exposure.  Exits also fire on gate OFF —
including the λ mechanism-lapse release (`percentile < 0.35`) — and
are never blocked by B4 (exits are always allowed; Inv-11).

## 6. Deployable set and evidence scope

**D = {APP}.**  RMBS is **evidence-only** at protocol step 2 (harness
grid coverage — it never enters a run config; the config-scope guard
in [`tests/acceptance/test_bt_dislocation_lambda_config_guard.py`](../../tests/acceptance/test_bt_dislocation_lambda_config_guard.py)
pins `symbols == ["APP"]` exactly).  OLN is **tick-artifact
evidence only** (§2.4 spread-in-ticks / quantum-mass reporting; never
an episode count, never in D — enforced as the evidence-only guard in
the `scripts/sensor_feature_ic.py` H8 row).

## 7. Two-axis validity statement

No number produced by the Task-9 tests is a result.  Steps 1–6 of the
protocol are **statistical-axis** evidence only; steps 7–8 (execution
overlay) evidence exists **only under the P0-6 precondition** (Task
12-P AXIS-1 router/fill-timing parity, re-verified green at execution
time), with AXIS-2 residuals reported alongside per the parity-gap
register.  First outcome contact belongs to Task 8 step 2 and is the
pre-registered primary trial's own contact (N-ledger discipline; N =
10 at freeze).

## 8. Test map (Task 9)

| concern | test |
|---|---|
| load / G2–G16 / strength rider / NaN goldens | [`tests/alpha/test_sig_dislocation_lambda_drift_v1.py`](../../tests/alpha/test_sig_dislocation_lambda_drift_v1.py) |
| run-config 00c pin + scope guard | [`tests/acceptance/test_bt_dislocation_lambda_config_guard.py`](../../tests/acceptance/test_bt_dislocation_lambda_config_guard.py) |
| protocol §2.1 sign-goldens + H8 harness smoke | [`tests/research/test_gas_dislocation_lambda_sign.py`](../../tests/research/test_gas_dislocation_lambda_sign.py) |
| Inv-6 no-lookahead (consumed set) | [`tests/causality/test_dislocation_lambda_no_lookahead.py`](../../tests/causality/test_dislocation_lambda_no_lookahead.py) |
| census-consistency smoke (functional, one cell) | [`tests/research/test_dislocation_lambda_census_consistency.py`](../../tests/research/test_dislocation_lambda_census_consistency.py) |
| run-twice parity (Inv-5, no locked baseline) | [`tests/harness/test_dislocation_lambda_parity.py`](../../tests/harness/test_dislocation_lambda_parity.py) |
