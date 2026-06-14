# Feelies SIGNAL-Layer Alpha Audit — 2026-06-14

Read-only, evidence-based audit of the Layer-2 (SIGNAL) edge-claim
surface: `HorizonSignalEngine`, the `HorizonSignal` protocol, the G12
cost-arithmetic gate, G16 mechanism↔horizon binding, and every shipped
`layer: SIGNAL` alpha. No production code was modified.

**Method.** Built the alpha inventory from YAML + `evaluate` bodies;
recomputed every `cost_arithmetic` block; traced one alpha end-to-end
(YAML → loader → engine → `Signal`); read the load-time gates
(`cost_arithmetic.py`, `layer_validator.py`) and the runtime engine
(`horizon_engine.py`); cross-checked the runtime B4 edge gate in the
orchestrator. Read-only test runs:

- `tests/signals/test_horizon_signal_engine.py tests/alpha/test_gate_g16.py tests/alpha/test_cost_arithmetic_gate.py` → **110 passed**.
- `tests/determinism/test_signal_replay.py tests/acceptance/test_inv12_stress_gate.py` → **15 passed**.

Convention used throughout: **one-way cost** `c₁ = half_spread + impact + fee`
(the disclosed `cost_total_bps`); **round-trip cost** `c_RT ≈ 2·c₁`
(entry crossing + exit crossing + both fees), which is what the runtime
estimator `estimate_round_trip_cost_bps` actually prices
(`src/feelies/execution/cost_model.py:526`). `edge/c_RT ≈ margin_ratio / 2`.

---

## 1. Executive summary

**Top capital risks**

1. **G12 discloses one-way cost but Inv-12 demands 1.5× round-trip.** The
   gate computes `margin = edge / (half_spread + impact + fee)`
   (`cost_arithmetic.py:206-225`) — a *single* crossing — while the
   runtime estimator and Inv-12 speak of round-trip (`cost_model.py:526`,
   `SKILL.md:274`). Every shipped alpha's disclosed margin (1.6–2.5)
   therefore corresponds to a true `edge/round-trip` of only **0.8–1.0×**.
   On a round-trip basis, `sig_hawkes_burst_v1` and `sig_inventory_revert_v1`
   (≈0.80) **do not cover their own round-trip cost**, and none clears the
   1.5× bar. G12 reconciles arithmetically but measures the wrong thing.
2. **No per-signal edge floor in 4 of 5 alphas.** The engine publishes any
   non-FLAT `Signal` regardless of `edge_estimate_bps`
   (`horizon_engine.py:483-500`). `sig_kyle_drift_v1` can emit a directional
   entry with **`edge_estimate_bps == 0.0`** (`...kyle_drift_v1.alpha.yaml:142-146`:
   `max(magnitude,0)` with an unbounded `lam_z`). Only
   `sig_inventory_revert_v1` self-gates (`cost_floor_bps`,
   `...inventory_revert_v1.alpha.yaml:239`). The SIGNAL layer relies entirely
   on the downstream B4 gate to suppress sub-cost entries.
3. **Reference `platform.yaml` sets the runtime B4 gate to 1.0× round-trip**
   (`platform.yaml:148 signal_min_edge_cost_ratio: 1.0`) — break-even, not
   Inv-12's 1.5×. Only the `configs/*.yaml` deployment overrides raise it to
   1.5 (`configs/paper_run.yaml:51` et al.). A reference-config deployment
   admits entries at break-even.
4. **G16 fingerprint binding is cosmetic.** Neither §20.6.1 nor
   `layer_validator.py` requires the family fingerprint to appear in
   `depends_on_sensors` or to be read by `evaluate` — rule 4/5 only check
   `l1_signature_sensors` against the platform registry
   (`layer_validator.py:941-961`). `sig_benign_midcap_v1` declares
   `kyle_lambda_60s` as its KYLE_INFO fingerprint but **never depends on or
   reads it** (`...benign_midcap_v1.alpha.yaml:51-56,124-134,144-152`); its
   logic is an OFI-zscore + book-imbalance signal, not a Kyle-λ signal. This
   violates the spirit of Inv-1.
5. **`sig_moc_imbalance_v1` direction is config-sourced, not L1-derived.**
   `flow_direction_prior` comes from a static `EventCalendar` YAML
   (`sensors/impl/scheduled_flow_window.py:160-170`), not from any L1 NBBO
   observable. The hypothesis claims a prior "derived from exchange
   imbalance feeds" (`...moc_imbalance_v1.alpha.yaml:15-25`) — the platform
   is L1-only, so the directional edge is exogenous and unfalsifiable from
   L1 data.
6. **Parameter `min`/`max` bounds are dead metadata.** The loader parses
   only `range:` (`loader.py:1222-1225`); every shipped alpha uses
   `min:`/`max:`, so `ParameterDef.range` is `None`
   (`module.py:77-80`) and no bound is enforced. The §8.5 free-parameter cap
   (≤3 `range` params, `docs/three_layer_architecture.md:1094-1099`) is
   **vacuously satisfied** by all alphas while `sig_inventory_revert_v1`
   carries 8 tunable knobs.
7. **Warm/stale guard suppresses fail-safe exits.** On a stale required
   feature the engine returns before gate evaluation
   (`horizon_engine.py:348-368`), so the ON→OFF FLAT exit
   (`_publish_gate_close`) is never reached — contradicting the documented
   "entry suppressed, exits permitted" contract (`SKILL.md:294-297`,
   feature-engine `SKILL.md:229`).
8. **Crowding masquerading as diversification.** `pro_kyle_benign_v1`
   combines two KYLE_INFO alphas (`sig_kyle_drift_v1`, `sig_benign_midcap_v1`)
   both of which take direction from the sign of `ofi_ewma` — one L1
   observable. The "orthogonal conditioning sets" claim
   (`...kyle_benign_v1.alpha.yaml:25-37`) is weak; the diversification is
   largely illusory.
9. `sig_hawkes_burst_v1` discloses `margin_ratio: 1.6`
   (`...hawkes_burst_v1.alpha.yaml:110`); under 1.5× cost stress the
   effective margin is ≈1.07 — fails the "survive 1.5× cost" leg of Inv-12.

**Top opportunities**

10. Adopt `sig_inventory_revert_v1`'s explicit `realized_capture_ratio` +
    `cost_floor_bps` pattern (`...inventory_revert_v1.alpha.yaml:100-141`)
    fleet-wide so disclosed edge = *capturable* edge, not peak.
11. Add a G-rule (or G12 extension) that `l1_signature_sensors ⊆
    depends_on_sensors` and that the fingerprint key appears in the
    `evaluate` source (the loader already retains `signal_source` for static
    inspection, `signal_layer_module.py:159-168`).
12. Reconcile G12 to a round-trip basis (or rename to `one_way_cost_bps` and
    require `margin_ratio ≥ 3.0`) so the load-time contract matches the
    runtime B4 gate.
13. Add a runtime/engine assertion (or per-alpha test) that emitted
    `edge_estimate_bps ≥ disclosed cost`, closing the sub-cost-emission gap
    independent of orchestrator config.
14. Offline IC-by-bucket validation on cached NBBO (AAPL/MSFT/NVDA) keyed by
    signal bucket — methodology in §9.

**Net:** The engine's purity, determinism, and causality are sound. The
economic-honesty layer (G12 + G16) is where capital leaks: the gates pass
arithmetic checks while measuring one-way cost and cosmetic fingerprints,
and the per-signal edge is unconstrained at the SIGNAL layer.

---

## 2. SIGNAL alpha inventory

| alpha_id | family | horizon_s | half-life_s | h/hl ratio | disclosed edge / c₁ = margin | edge/c_RT (≈margin/2) | fingerprint used in `evaluate`? | regime gate summary |
|---|---|---|---|---|---|---|---|---|
| `sig_kyle_drift_v1` | KYLE_INFO | 300 | 600 | 0.50 (floor) | 11.7 / 6.5 = **1.8** | ≈0.90 | partial — reads `kyle_lambda_60s_*`; **`micro_price` unused** | P(normal)>0.6 ∧ spread_z≤1.0 |
| `sig_benign_midcap_v1` | KYLE_INFO | 120 | 120 | 1.00 | 9.0 / 5.0 = **1.8** | ≈0.90 | **no** — declares `kyle_lambda_60s` fingerprint, reads `ofi_ewma_zscore`+`book_imbalance_mean` | P(normal)>0.5 ∧ spread_z<1.5 |
| `sig_hawkes_burst_v1` | HAWKES_SELF_EXCITE | 30 | 30 | 1.00 | 8.0 / 5.0 = **1.6** | ≈0.80 | yes — `hawkes_intensity_zscore` | P(normal)>0.6 ∧ spread_z<1.0 |
| `sig_inventory_revert_v1` | INVENTORY | 30 | 20 | 1.50 | 8.8 / 5.5 = **1.6** | ≈0.80 | yes — `quote_replenish_asymmetry_zscore` | inventory-dominant; rich off-condition |
| `sig_moc_imbalance_v1` | SCHEDULED_FLOW | 120 | 240 | 0.50 (floor) | 12.0 / 6.0 = **2.0** | ≈1.00 | yes (window) but **direction from static config prior** | schedule-only (no regime ids) |
| `paper_smoke_v1` | — (no `trend_mechanism`) | 30 | — | — | 10.0 / 2.5 = 4.0 | ≈2.0 | n/a — smoke alpha, gate `True/False` | regime-independent |

All disclosed `margin_ratio` values reconcile with components within ±5%
(verified by `compute_margin_ratio`, `cost_arithmetic.py:206`). Two of the
five mechanism alphas sit at the half-life/horizon ratio **floor of 0.5**
(`kyle_drift`, `moc`) — G16-legal but the maximum-decay edge of the band.

---

## 3. Engine audit (`horizon_engine.py`)

**A.1 Purity of `evaluate` — PASS.** All `evaluate` bodies read only
`snapshot.values` + `params` (e.g. `...kyle_drift_v1.alpha.yaml:129-157`);
none reads a clock, module state, or the regime object. They are compiled
in a restricted namespace with no `__builtins__`
(`signal_layer_module.py:222-260`). The `regime` argument is passed but
unused by every alpha (by design — "regime in, not consulted internally",
`horizon_protocol.py:24-31`). `_CompiledHorizonSignal` is stateless
(`signal_layer_module.py:240-260`).

**A.2 Causality (Inv-6) — PASS.** The engine consumes the boundary
`HorizonFeatureSnapshot` and a `_sensor_cache` populated incrementally from
`SensorReading` events (`horizon_engine.py:275-320`). At dispatch the cache
reflects only readings published **before** the snapshot event, so all
bindings are ≤ T. `_build_bindings` gives `snapshot.values` priority over
the cache (`horizon_engine.py:625-629`) — no lookahead. Note: gate
evaluation legitimately reads `_sensor_cache` (documented purity boundary,
`SKILL.md:206-216`); this is engine state, not an `evaluate` impurity.

**A.3 Warm/stale handling — PARTIAL (fail-safe gap).** Entry suppression on
`warm=False`/`stale=True` works (`horizon_engine.py:348-368`). **But the
guard returns before gate evaluation**, so a stale required feature also
blocks the ON→OFF `_publish_gate_close` FLAT exit (`horizon_engine.py:461-462`,
`502-536`). The documented contract is "entry suppressed; exits permitted
(conservative)" (`SKILL.md:294-297`). A position opened while ON can be
orphaned while a required feature stays stale. Mitigations exist (hazard-exit
controller; cold-sensor `UnknownIdentifierError` unwind at
`horizon_engine.py:380-410`), but the latter is *also* behind the warm/stale
guard, and staleness ≠ cold (a stale feature keeps its last warm cache
value). **Severity P1.**

**A.4 One-`Signal`-per-`(alpha,symbol,boundary)` — PASS (with caveat).** The
engine dispatches once per registered signal per matching-horizon snapshot
(`horizon_engine.py:322-329`); `register` rejects duplicate `alpha_id`
(`horizon_engine.py:217-221`). Iteration order is sorted by
`(horizon_seconds, alpha_id)` (`horizon_engine.py:224-226`) and sequence
numbers come from a dedicated generator (`horizon_engine.py:668-669`) —
deterministic, replay-stable (locked by `test_signal_replay.py`, 15 passed).
Caveat: there is **no** explicit dedup keyed on `boundary_index`; uniqueness
relies on the aggregator emitting one snapshot per `(symbol, horizon,
boundary)`. Acceptable but undefended at this layer.

**A.5 Fail-safe error handling — STRONG.** Every gate exception class forces
the latch OFF and unwinds an open position (`horizon_engine.py:380-459`),
including the P1-1 `RegimeGateError` and G-1 arithmetic/type branches.
FLAT/None returns are correctly not published (`horizon_engine.py:483-497`).

---

## 4. Per-alpha audit

### 4.1 `sig_kyle_drift_v1` (KYLE_INFO, 300 s)

- **Mechanism honesty — partial.** Declared: informed-trader permanent
  impact via Kyle's λ. `evaluate` (`...kyle_drift_v1.alpha.yaml:129-157`)
  gates on `kyle_lambda_60s_percentile ≥ 0.7` and `|ofi| ≥ 0.5`, takes
  direction from `sign(ofi)`, sizes edge by `lam_z`. The λ fingerprint is
  genuinely consumed — honest. **But** `micro_price` is declared in both
  `depends_on_sensors` and `l1_signature_sensors` yet never read — cosmetic.
  Direction is pure OFI sign; the "λ→drift" causal chain only sets
  *magnitude*. Half-life=600 s is asserted, not derived: the signal reads a
  *60 s* λ estimate and an OFI EWMA whose own decay (not 600 s) governs
  persistence.
- **Cost — disclosed 1.8 on one-way (≈0.90 round-trip).** Does not clear
  1.5× round-trip. **No edge floor**: with `lam_z ≤ 0`,
  `edge_bps = min(max(lam_z,0)·6, 25) = 0` while still emitting a directional
  entry (`...:142-146`). This is the worst sub-cost case in the fleet —
  pure-noise entries with `edge=0.0` rely entirely on the B4 gate.
- **Falsifiability — good (prose).** Four mechanism-tied criteria including
  a Spearman-correlation kill and a half-life-drift kill (`...:27-42`). Stated
  only in YAML, not asserted by any test.

### 4.2 `sig_benign_midcap_v1` (KYLE_INFO, 120 s)

- **Mechanism honesty — FAIL (Inv-1).** Declared KYLE_INFO with fingerprint
  `kyle_lambda_60s` (`...benign_midcap_v1.alpha.yaml:124-134`), but
  `depends_on_sensors` omits `kyle_lambda_60s` (`...:51-56`) and `evaluate`
  reads `ofi_ewma_zscore` + `book_imbalance_mean` (`...:144-152`). The alpha
  measures **order-flow imbalance with book-imbalance confirmation**, not
  Kyle's λ. G16 rule 5 passes only because the *declared* (unused) fingerprint
  list contains `kyle_lambda_60s`/`micro_price`. This is the canonical
  cosmetic-G16 case. The honest family is closer to a generic OFI-persistence
  signal; the hypothesis's "Kyle-style footprint" language is aspirational.
- **Cost — disclosed 1.8 (≈0.90 round-trip).** No edge floor: at the entry
  threshold `mag=0.8`, `edge = 0.8·4 = 3.2 bps` vs c₁=5.0, c_RT≈10
  (`...:169-170`). Sub-cost entries fire freely.
- **Falsifiability — good (prose, `...:28-46`).** Note the SEC/FINRA
  criterion is non-operational (cannot be measured from L1).

### 4.3 `sig_hawkes_burst_v1` (HAWKES_SELF_EXCITE, 30 s)

- **Mechanism honesty — good.** Fingerprint `hawkes_intensity` consumed;
  `z ≥ 2`, `ttr ≥ 0.6` gate a momentum-follow over 30 s
  (`...hawkes_burst_v1.alpha.yaml:135-164`). Half-life=30 matches horizon
  (ratio 1.0). Minor: direction is taken from `sign(ofi)` rather than the
  available `hawkes_intensity_buy/sell` asymmetry (tuple-expanded at
  `horizon_engine.py:117-122`) — a cleaner self-excitation direction signal
  exists and is unused (P2).
- **Cost — disclosed 1.6 (≈0.80 round-trip) — fails Inv-12 both ways.** On a
  round-trip basis the edge does not cover cost; under 1.5× cost stress the
  margin is ≈1.07. No edge floor: at `z=2`, `edge=6.0` vs c₁=5.0, c_RT≈10.
- **Falsifiability — good (prose).** Hazard-exit wired
  (`hazard_score_threshold: 0.30`, `...:130-132`) — the only alpha with an
  active hazard exit.

### 4.4 `sig_inventory_revert_v1` (INVENTORY, 30 s) — reference-quality

- **Mechanism honesty — strong, with an admitted open question.** Fingerprint
  `quote_replenish_asymmetry` consumed; fades displacement
  (`...inventory_revert_v1.alpha.yaml:197-251`). Crucially, the author flags
  the **direction sign convention as empirically unconfirmed** ("must be
  re-confirmed against forward 30 s micro-price returns before relying live",
  `...:209-214`) — honest, but it means the core directional claim is
  untested (edge-vs-alpha risk).
- **Cost — best-engineered in the fleet.** `realized_capture_ratio = 0.646`
  taxes peak edge for the 30/20 horizon/half-life gap (`...:100-118`), and an
  explicit `cost_floor_bps = 5.5` blocks sub-cost emission (`...:239`). This
  is the only alpha that self-enforces an edge floor. Still, the floor equals
  *one-way* cost; on a round-trip basis (≈11 bps) the 8.8 bps edge does not
  cover the round trip.
- **Parameter surface — 8 tunable knobs** (`...:47-141`), the largest in the
  fleet. Per §8.5 these should be capped at 3 "free" params; because the
  loader ignores `min`/`max` (see §1.6) the cap never bites. Overfitting
  surface is real.
- **Falsifiability — strongest (prose).** Half-life-band, hit-rate, and
  regime-shift kills (`...:23-37`).

### 4.5 `sig_moc_imbalance_v1` (SCHEDULED_FLOW, 120 s)

- **Mechanism honesty — FAIL on L1 identifiability.** The *window* is real
  and L1-derivable, but **direction comes from `flow_direction_prior`, a
  static `CalendarWindow` field** read from a reference YAML
  (`sensors/impl/scheduled_flow_window.py:160-170`,
  `...moc_imbalance_v1.alpha.yaml:154-163`). The platform is L1-NBBO-only;
  there is no L1 mechanism producing the sign. OFI only *confirms* the prior.
  If the calendar prior is stale or wrong, the alpha trades blind. The
  hypothesis's "derived from exchange imbalance feeds" is not what the code
  does.
- **Cost — disclosed 2.0 (≈1.00 round-trip).** No edge floor: at the
  `min_seconds_to_close=60` boundary, `remaining≈1 min → edge=1.5 bps`
  (`...:164-168`) vs c₁=6.0, c_RT≈12 — a 0.25× round-trip entry. The largest
  per-signal/disclosed edge gap in the fleet.
- **Falsifiability — good (prose), but two of four criteria are
  non-operational** (exchange-feed retirement; `...:26-42`).

---

## 5. Multi-alpha interaction

- **Arbitration (`arbitration.py`, wired at `orchestrator.py:584-585`).**
  `EdgeWeightedArbitrator.arbitrate` selects `max(edge·strength)` with FLAT
  privileged as a non-outvotable exit (`arbitration.py:60-79`). Deterministic
  given the engine's stable buffered order; `max` ties resolve to the first
  element (implicit, not an economic rule — P2). Economically coherent for
  exit-priority; for entries it picks the single loudest claim and discards
  the rest (no netting at the SIGNAL tier — netting is downstream in
  `aggregation.py`/`PortfolioNetter`).
- **Aggregation (`aggregation.py`).** Exit-priority two-bucket netting with an
  exhaustiveness guard (`aggregation.py:37-61`) — Inv-11 fail-safe sound.
- **Crowding — real.** `sig_kyle_drift_v1` and `sig_benign_midcap_v1` both
  derive direction from `sign(ofi_ewma)`; at the LCM boundary (600 s) both can
  fire on the same symbol and the arbitrator collapses them to one (no
  double-trade), but `pro_kyle_benign_v1`'s diversification thesis
  (`...kyle_benign_v1.alpha.yaml:25-37`) is weak — both legs crowd into one L1
  observable. `pro_burst_revert_v1` (HAWKES ⟂ INVENTORY) is a genuinely
  decorrelated pairing. Both PORTFOLIO alphas are `lifecycle_state: RESEARCH`
  (`...:9`), so this is not a live exposure today.

---

## 6. Cost & stress matrix

| alpha_id | edge_bps (disclosed) | c₁ (one-way) | margin (G12) | edge/c_RT | min realized edge at entry | self edge-floor? | survives 1.5× cost (margin/1.5 ≥ 1.5)? |
|---|---|---|---|---|---|---|---|
| `sig_kyle_drift_v1` | 11.7 | 6.5 | 1.8 | 0.90 | **0.0** | no | no (1.20) |
| `sig_benign_midcap_v1` | 9.0 | 5.0 | 1.8 | 0.90 | 3.2 | no | no (1.20) |
| `sig_hawkes_burst_v1` | 8.0 | 5.0 | 1.6 | 0.80 | 6.0 | no | no (1.07) |
| `sig_inventory_revert_v1` | 8.8 | 5.5 | 1.6 | 0.80 | >5.5 | **yes** | no (1.07) |
| `sig_moc_imbalance_v1` | 12.0 | 6.0 | 2.0 | 1.00 | 1.5 | no | no (1.33) |

"Survives 1.5× cost" interprets Inv-12 as "disclosed margin still ≥ 1.5 after
multiplying cost by 1.5" → requires disclosed margin ≥ 2.25. **No mechanism
alpha clears it.** `test_inv12_stress_gate.py` (15 passed) verifies the stress
*harness* mechanics (1.5× / 2× factors, `cost_model.py` scaling, deferred-fill
latency) — it does **not** assert per-alpha survival; that is explicitly left
to "the BT-12 bar" (`test_inv12_stress_gate.py:11-13`). So no shipped test
fails on the table above.

---

## 7. Test gap matrix

| Invariant / property | Covered by | Status |
|---|---|---|
| `evaluate` purity / determinism | `test_signal_replay.py`, `test_emit_signals_jsonl.py` | **Covered** |
| Causality (≤ T) | implied by replay parity; no direct lookahead test | Partial |
| One-signal-per-boundary, ordering | `test_horizon_signal_engine.py`, `test_signal_replay.py` | **Covered** |
| Gate fail-safe (OFF + unwind on error) | `test_horizon_signal_engine.py` | Covered |
| Warm/stale **exit** permitted | — | **Missing** (and the behavior is wrong — §3.A.3) |
| G16 rules 1–9 (pass+fail) | `test_gate_g16.py`, `test_gate_g16_props.py`, `test_g16_rule_completeness.py` | **Covered** (but rules don't include fingerprint∈depends_on_sensors) |
| G12 reconciliation (±5%, ≥1.5) | `test_cost_arithmetic_gate.py` | Covered (one-way basis only) |
| Per-signal emitted `edge ≥ cost` | — | **Missing** |
| Per-alpha behavioral/economic asserts | `test_sig_*.py` | Partial — assert direction + `0 < edge ≤ cap` (`test_sig_kyle_drift_v1.py:172,224`) and that the load-time margin reconciles (`test_sig_benign_midcap_v1.py:67-69`); **none asserts edge ≥ cost or economic sign correctness** |
| Parameter bound enforcement | — | **Missing** (bounds are dead, §1.6) |
| Stress-family entry prohibition | `test_gate_g16.py` Rule 7 | Covered (no stress alpha shipped → vacuous in fleet) |
| Arbitration determinism/conflict | `test_arbitration.py`, `test_aggregation.py` | Covered |

**Proposed minimal new tests (specs only):**

- **T1 (golden, per alpha):** at the *entry threshold* parameter values,
  assert `emitted.edge_estimate_bps ≥ disclosed cost_total_bps` — would fail
  today for 4/5 alphas, surfacing the sub-cost gap.
- **T2 (property):** for random in-range snapshots that pass the gate, the
  emitted `edge` is monotone in the driving feature and never negative; and
  `direction` matches `sign(driver)`.
- **T3 (engine):** stale required feature with a previously-ON gate emits a
  FLAT `_publish_gate_close` (encodes the corrected §3.A.3 contract).
- **T4 (G16):** load a spec whose fingerprint is absent from
  `depends_on_sensors` → reject (encodes the proposed rule).
- **T5 (params):** an override outside a parameter's `min`/`max` is rejected
  (once bounds are honored).

---

## 8. Prioritized backlog

Severity: **P0** correctness/safety · **P1** economic soundness · **P2**
research/product. Effort: S/M/L.

### P0

*(No P0s found.* No purity violation, lookahead, non-determinism, stress-family
entry, or G12 reconciliation failure. The cost-honesty issues are real but
backstopped at runtime by the B4 gate, so they are graded P1.)

### P1

| # | alpha/module | `file:line` | one-sentence fix | expected impact |
|---|---|---|---|---|
| P1-1 | G12 contract | `cost_arithmetic.py:206-225`; `SKILL.md:246-259` | Reconcile the disclosed cost to a **round-trip** basis (or rename `cost_total_bps`→`one_way_cost_bps` and require `margin_ratio ≥ 3.0`) so G12 matches the runtime round-trip gate. | Load-time gate stops over-stating survival margin ~2×. |
| P1-2 | engine / all alphas | `horizon_engine.py:483-500` | Add a SIGNAL-layer assertion (or per-alpha `cost_floor_bps` like inventory) that emitted `edge ≥ disclosed cost`, independent of orchestrator config. | Stops `edge=0.0` and sub-cost entries at the source. |
| P1-3 | platform default | `platform.yaml:148` | Raise reference `signal_min_edge_cost_ratio` to 1.5 to match Inv-12 and the `configs/*` overrides. | Reference-config deployments stop admitting break-even entries. |
| P1-4 | G16 rule | `layer_validator.py:941-961` | Add a rule: `l1_signature_sensors ⊆ depends_on_sensors` **and** the fingerprint key appears in `signal_source` (already retained, `signal_layer_module.py:159-168`). | Eliminates cosmetic fingerprints (e.g. `sig_benign_midcap_v1`). |
| P1-5 | `sig_benign_midcap_v1` | `...benign_midcap_v1.alpha.yaml:124-134` | Re-tag honestly (either add+consume `kyle_lambda_60s`, or relabel the mechanism) so Inv-1 holds. | Mechanism claim becomes falsifiable. |
| P1-6 | `sig_moc_imbalance_v1` | `...moc_imbalance_v1.alpha.yaml:15-25,154-163` | State plainly that direction is an exogenous calendar prior, not L1-derived; add a falsification criterion on prior-vs-realized sign agreement that is actually measured. | Removes an unfalsifiable L1 claim. |
| P1-7 | engine warm/stale | `horizon_engine.py:348-368` | Permit the ON→OFF FLAT exit when only `stale` (not `warm=False`) trips, restoring the documented "exits permitted" contract. | Prevents orphaned positions during staleness. |
| P1-8 | loader / params | `loader.py:1222-1225`; `module.py:77-80` | Parse `min`/`max` into `ParameterDef.range` (or reject specs that use `min`/`max` without `range`) and enforce the §8.5 cap. | Restores bound enforcement + overfitting cap. |

### P2

| # | alpha/module | `file:line` | one-sentence fix | expected impact |
|---|---|---|---|---|
| P2-1 | `sig_inventory_revert_v1` | `...:209-214` | Run the documented forward-return sign confirmation and pin the result; reduce the 8-knob surface. | Confirms the core directional claim; cuts overfit risk. |
| P2-2 | `sig_hawkes_burst_v1` | `...:151-152` | Use `hawkes_intensity_buy/sell` asymmetry for direction instead of OFI sign. | Direction derived from the declared mechanism. |
| P2-3 | arbitration | `arbitration.py:71-79` | Document/encode an explicit deterministic tie-break (e.g. by `alpha_id`). | Removes implicit-order reliance. |
| P2-4 | crowding | `...kyle_benign_v1.alpha.yaml:25-37` | Add an OFI-correlation diagnostic before claiming diversification; consider a same-observable crowding cap. | Honest IR claim for the composite. |
| P2-5 | falsifiability | all `test_sig_*.py` | Promote the YAML falsification criteria into executable backtests/monitors. | Inv-2 enforced, not just narrated. |

---

## 9. Appendix — open questions needing data runs

All on cached L1 NBBO; suggested universe AAPL / MSFT / NVDA (the
PORTFOLIO universe), RTH only.

1. **Edge realism (all alphas).** Conditional forward-return / IC by signal
   bucket: bucket emitted `Signal`s by `edge_estimate_bps` decile and measure
   realized forward return over `horizon_seconds`; overlay modeled round-trip
   cost. *Metric:* fraction of emitted signals whose realized return exceeds
   round-trip cost. *Hypothesis to kill:* the low-edge buckets (which the
   SIGNAL layer happily emits) have realized return < cost.
2. **`sig_kyle_drift_v1` half-life.** Estimate the empirical decay of
   `kyle_lambda_60s × sign(ofi)` → forward return; is the 600 s declared
   half-life supported, or is it really the OFI-EWMA timescale (tens of s)?
3. **`sig_benign_midcap_v1` mechanism.** Does adding `kyle_lambda_60s` change
   the signal at all? If IC is unchanged with λ removed, the KYLE_INFO tag is
   confirmed cosmetic.
4. **`sig_inventory_revert_v1` sign.** The author's open question: regress
   `quote_replenish_asymmetry_zscore` on forward 30 s micro-price return;
   confirm or flip the LONG-on-positive-asym convention (`...:209-214`).
5. **`sig_moc_imbalance_v1` prior quality.** Sign-agreement rate between the
   calendar `flow_direction_prior` and realized forward-120 s return across
   sessions; if ≤ 0.55 the directional edge is absent (matches the alpha's own
   falsification criterion, `...:32-36`).
6. **Crowding.** Time-series correlation of `sig_kyle_drift_v1` vs
   `sig_benign_midcap_v1` direction/strength on shared symbols; quantify the
   diversification the PORTFOLIO layer actually buys.

---

*Prepared read-only. No production code modified. Distinctions used:
**implementation bug** (P1-7 warm/stale exit, P1-8 dead param bounds);
**modeling choice / contract** (P1-1 cost basis, P1-2/P1-3 edge gate,
P1-4/P1-5 cosmetic fingerprint); **L1 identifiability limit** (P1-6 MOC
direction prior). Literature anchor for the stress-family exit-only rule:
Kyle, A. (1985), "Continuous Auctions and Insider Trading," Econometrica
53(6) — the `λ` permanent-impact basis the KYLE_INFO family names.*
