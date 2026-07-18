<!--
  File:   docs/research/artifacts/h9_h10_adjudication_package.md
  Status: EXTRACTION — verbatim adjudication package for Lei's final
          H9-vs-H10 selection (slate C). Source texts unedited; no new
          analysis except §G (census-legal κ/edge quantity census for
          H9 horizon-magnitude calibration).
  Owner:  research-workflow bookkeeping; prompt-pack H9/H10 adjudication.
-->

# H9 / H10 adjudication package

Sources: `docs/research/prompt_pack_09_hypothesis_slate_c.md` (cards,
ranking, override — verbatim) and
`docs/research/prompt_pack_09a_slate_c_review.md` (dossier verdicts,
distinctness, RISKS, reconciliation, questions — verbatim).
Context: slate C recommends H9 over formula H10-first; dossier
reconciles H10 > H9; Lei decides.

---

## A. H9 card — verbatim from prompt_pack_09

## H9. ALPHA_ID (proposed): `sig_ofi_kyle_drift_h900_v1`

**HYPOTHESIS.** An institution working a parent order through
limit-order-heavy execution algos persistently imbalances the L1 book
**because** top-of-book participation minimizes crossing cost under a
completion schedule spanning tens of minutes, **which must leak into
L1 as** persistent signed order-flow imbalance (Cont–Kukanov–Stoikov
OFI) integrated over a 900 s window. Part of the price impact is
permanent (KYLE); while the parent remains in flight the unrealized
remainder continues to arrive — drift in the flow direction over the
next **H = 900 s**.

Conditional-distribution statement: with `ofi_integrated` = Σ of
per-event L1 OFI over the trailing 900 s (`ofi_raw` + `sum` reducer at
h = 900): `E[mid log-return over the next H = 900 s |
ofi_integrated percentile ≥ 0.90 and P(vol_breakout) < 0.7] > 0`
(symmetric short for ≤ 0.10), magnitude κ_frozen × σ₉₀₀ with κ
central 0.16 ≈ **7.6 bps one-way at the APP median session**
(pack-08 σ₉₀₀ med 47.7).

**ARCHETYPE & COUNTERPARTY (R2).** Informed/committed-flow-following.
Structural actor: schedule-bound institutional parent. Counterparties:
latency-constrained LPs; the parent's own implementation-shortfall
pool. Conservation: integrated edge ≤ aggregate temporary + permanent
impact of scheduled parents.

**FAMILY & MIRAGE RISK (R3).** `KYLE_INFO`.
`expected_half_life_seconds = 450` (envelope 60–1800 ✓);
`horizon_seconds = 900`; ratio 2.0 ∈ [0.5, 4.0] ✓.
`l1_signature_sensors: [kyle_lambda_60s]` (G16 rule-5 KYLE primary).
Mirage: **MIXED (M = 1.5)** — quote-delta OFI is revocable /
manufacturable (L5); F2 λ-elevation tests KYLE attribution.

**OBSERVABLE STATE.** Existing: `ofi_raw` / `ofi_integrated`,
`kyle_lambda_60s` (F2 only), `realized_vol_30s`. Needed: percentile
view of `ofi_integrated` at h = 900 (factory line — H3/H6 pattern).
**No new sensor. No `spread_z_30d`.**

**EXPECTED BEHAVIOR.** Continuation with flow; hl 450 s. Sketch:

```
on_condition:  "P(vol_breakout) < 0.7 and ofi_integrated_percentile > 0.90
                and realized_vol_30s_zscore <= 3.0"
off_condition: "P(vol_breakout) > 0.7 or realized_vol_30s_zscore > 3.0"
hysteresis:    {posterior_margin: 0.15, percentile_margin: 0.20}
```

### H9 · 1. FEASIBILITY (pack-08 §2 / §6; κ FROZEN)

Map κ_req passive H = 900 (med/p75/p90): APP **0.098**/0.079/0.067;
RMBS **0.117**/0.102/0.081 (pack-08 §2.2). Both median-open at
κ ≤ 0.16. p75/p90 not required (H2 lesson).

Derived κ (H2-spec factor style; **FROZEN** — ratchet down only):

| factor | central | grounding |
|---|---|---|
| `c_D` | 1.2 | extreme-OFI windows ~1σ contemporaneous (CKS) |
| `f_perm` | 0.55 | Kyle/GM scheduled-flow permanent share |
| `r_rem` | 0.50 | uniform detection along parent schedule |
| `f_H` | 0.75 | 1 − e^(−900/τ), τ = 450/ln 2 ≈ 649 |
| `f_pass` | 0.65 | passive same-side pullback fill haircut |

    κ ∈ [0.03, 0.30], central ≈ 1.2×0.55×0.50×0.75×0.65 ≈ **0.161** — FROZEN

**Park arithmetic (single-stress anchor, pack-08 floors):**

| symbol | κ·σ₉₀₀,med | floor | κ_req med | verdict |
|---|---|---|---|---|
| APP | 0.161 × 47.7 ≈ **7.68** | 4.68 | 0.098 | OPEN — headroom ≈ 1.64× |
| RMBS | 0.161 × 47.3 ≈ **7.62** | 5.51 | 0.117 | OPEN — headroom ≈ 1.38× |
| six others | κ_req med 0.170–0.221 | — | — | CLOSED at median honest κ (pack-08 §2.4) — not deployable |

Short-side rider (APP): floor ≈ 2.25 × (2.0 + 0.08 + 0.507) ≈ 5.82 ⇒
κ_req 5.82/47.7 ≈ 0.122 ≤ 0.161 — **APP short clears at median**.
RMBS short: ≈ 6.60/47.3 ≈ 0.140 ≤ 0.161 — **clears, thin**. Pre-stated:
if census-measured short edge fails rider-inclusive floor on a symbol,
that symbol restates long-only and power is re-checked under the
pooled structure (block 3) — no threshold tuning.

### H9 · 2. DENSITY WITH MARGIN (≥ 130 contamination-excluded)

**Occupancy pre-read (backlog 15):** conditioning fraction = two-sided
**decile-tail 0.20** — percentile-by-construction, **exempt** from
distributional occupancy pre-read.

Basis (pack-08 §4.1): 25 × 20 = 500 in-window boundaries/symbol on
{APP, RMBS}. HT = 0.90. Gate × warm = 0.90 × 0.95 (permissive
breakout gate; warm block 4). Quote-fed conditioner ⇒ Class-B print
contamination structurally absent ⇒ contamination-excluded multiplier
= 1.0 at design (census reports co-occurrence diagnostics only).

| set | arithmetic | expectation | vs ≥ 130 |
|---|---|---|---|
| APP alone | 500 × 0.90 × 0.20 × 0.90 × 0.95 | **76.9** | FAIL per-symbol |
| RMBS alone | same | **76.9** | FAIL per-symbol |
| **APP ∪ RMBS pooled** | 1000 × 0.90 × 0.20 × 0.90 × 0.95 | **153.9** | **PASS** |

Design-central = **153.9 ≥ 130** on the pooled deployable set.
Conditioning fraction stated: **0.20** (decile). Per-symbol floor
contact without pool is impossible at decile — that is why block 3
freezes pooling.

### H9 · 3. POWER STRUCTURE DECLARED AT DESIGN (backlog 13 prospective)

| role | symbols | basis |
|---|---|---|
| **Deployable** | {APP, RMBS} | both median-open at κ_frozen (block 1) |
| **Evidence-only** | — | none at design; six others closed at honest κ @900 |
| **Evidence structure** | **pooled** APP ∪ RMBS | primary RankIC / power counts on the pool; per-symbol diagnostics reported but **do not** govern the step-2 power bar |

**Consequence-precedence sketch (must be copied into the protocol
freeze before any instrument runs):**

1. Primary §9 gate rows outrank safeguards on the same statistic
   (safeguard may tighten a pass, never loosen a primary fail).
2. Pooled power bar governs census PROCEED/PARK; a single-symbol
   shortfall inside the pool does **not** park the card if the pool
   clears ≥ 130 contamination-excluded — unless that symbol also
   fails deployability park arithmetic, in which case it drops from
   D and the pool is re-checked (A-2.1-class axis split, stated now).
3. Magnitude-class IC bars (when frozen) are `n-invariant` →
   REJECTED-terminal; power-class census misses → PARK
   evidence-infrastructure only when the freeze says so.
4. Undefined intersection = freeze-blocking defect — no post-outcome
   adjudication.

### H9 · 4. WARM REALITY

| sensor | census / characterization | basis |
|---|---|---|
| `realized_vol_30s_zscore` | **measured** 0.94–0.995 (H2 C.5) | gate — safe |
| `ofi_raw` / `ofi_integrated` | unmeasured at h=900; 03c §5.1 APP 1.6–3.0 quotes/s ⇒ 900 s window ~1.4k–2.7k quotes | warm ~always on APP/RMBS; census-stage verification pre-registered (warm < 0.5 on > 2 sessions drops that symbol — coverage, not tuning) |
| `kyle_lambda_60s` | unmeasured; proxy `inventory_pressure` ≥ 0.985 | F2 only; APP warm ~always; RMBS marginal at 30 trades/60 s — F2 diagnostic, not entry |
| `spread_z_30d` | 0.03–0.16 thin names | **NOT USED** |

### H9 · 5. CONTAMINATION POSTURE

Conditioning observable is **quote-fed** — Class-B prints never enter
`ofi_raw`. DI-09 extreme-print finding does not apply to entry.
`kyle_lambda_60s` inherited unfiltered for **F2 only** (not entry
extremes); Class-A-filtered NEW λ variant pre-registered fallback
(ledger appendix). L5 cancel/replenishment conflation is the residual
hazard — tested by F2, not filterable by sale conditions.

### H9 · 6. REJECTED-CLAIM ADJACENCY

| claim | relation |
|---|---|
| (a) H8 elevated-λ continuation @ H=300 | **Not that claim.** No dislocation arm; no λ entry conditioner; horizon 900 not 300. Shared family (KYLE_INFO) and continuation sign only — mechanism conditioner is integrated OFI, not impact-elevated dislocation. |
| (b) Contaminated baseline-reversion observation | **Not that claim.** This card is flow-continuation, not fade. Does not condition on baseline λ; does not reuse H8 step-2b cells as a reversion sample. |

**FAILURE MODES (≥3).** (a) Tick-grid artifact at long horizon —
mandatory spread-in-ticks report. (b) Adversarial quote-size
manufacture of OFI (free cancels) — negative tail; F2 print-volume
monitor. (c) L2 passive fill adversity + L5 cancel conflation →
trap-quadrant. (d) Horizon-magnitude generalization of H8's
sub-bar effect sizes — F1 / honest-N ceiling.

**FALSIFICATION.** F1: RankIC(ofi_integrated, 900 s forward) on
pre-registered pooled boundaries ≤ 0 or below honest-N ceiling.
F2: no λ elevation / no same-direction print volume in signal windows.
F3: regime/stratum sign flip. F4: passive realism / `--inv12-stress`
→ trap-quadrant. F5: structural boundaries §0.1.

**IMPLEMENTATION.** YAML + percentile factory line. No new sensor.

---

## B. H10 card — verbatim from prompt_pack_09

## H10. ALPHA_ID (proposed): `sig_sweep_kyle_drift_h900_v1`

**HYPOTHESIS.** An institutional trader with short-half-life information
executes with intermarket sweep orders **because** paying take fees and
through-prices is rational only when immediacy value exceeds patience —
urgency reveals information — **which must leak into L1 as** clusters of
condition-14 prints. Permanent impact (KYLE) continues over **H = 900 s**;
a **passive same-side entry** harvests the remainder at maker cost.

Conditional-distribution statement: `SFI(t; 900 s)` = signed
sweep-flow imbalance over eligible condition-14 prints in the trailing
900 s (NEW sensor, Class-A filtered): `E[mid log-return over next
H = 900 s | SFI percentile ≥ 0.90 and P(vol_breakout) < 0.7] > 0`
(symmetric short), magnitude κ_frozen × σ₉₀₀ ≈ **7.5 bps** at APP
median.

**ARCHETYPE & COUNTERPARTY (R2).** Informed-flow-following; actor =
informed sweeper (exchange-stamped ISO); counterparty = resting LPs
lifted across venues. Conservation: edge ≤ sweep volume × permanent
impact; id 14 ≈ 17.6 % of tape volume (03b §2).

**FAMILY & MIRAGE RISK (R3).** `KYLE_INFO`. hl = 450; H = 900; ratio
2.0 ✓. `l1_signature_sensors: [kyle_lambda_60s, sweep_flow_imbalance]`.
Mirage: **LOW (M = 1.0)** — irrevocable certified prints. F2 still
required (delta-hedger sweeps identically).

**OBSERVABLE STATE.** **NEW** `sweep_flow_imbalance` (Trade-fed,
900 s window): Class-A ∩ id 14; `drop_correction_records = {10,11,12}`;
no retroactive correction conditioning (03b §4.3); unknown-id guard.
Existing: `kyle_lambda_60s`, `realized_vol_30s`. **No `spread_z_30d`.**

### H10 · 1. FEASIBILITY (pack-08; κ FROZEN)

Same map cells as H9 (APP/RMBS H=900 median-open at κ ≤ 0.16).

| factor | central | vs H9 |
|---|---|---|
| `c_D` | 1.2 | same order |
| `f_perm` | **0.65** | ISO urgency skews permanent (above H9) |
| `r_rem` | 0.45 | sweep parents complete faster |
| `f_H` | 0.75 | same τ construction |
| `f_pass` | 0.60 | sharper bursts → more adverse pullbacks |

    κ central ≈ 1.2×0.65×0.45×0.75×0.60 ≈ **0.158** — FROZEN

Park arithmetic:

| symbol | κ·σ_med | floor | verdict |
|---|---|---|---|
| APP | 0.158 × 47.7 ≈ **7.54** | 4.68 | OPEN (κ_req 0.098) |
| RMBS | 0.158 × 47.3 ≈ **7.47** | 5.51 | OPEN (κ_req 0.117) |

Short-side rider: APP κ_req 0.122 ≤ 0.158 clears; RMBS 0.140 ≤ 0.158
clears thinly — same restatement chain as H9.

### H10 · 2. DENSITY WITH MARGIN

Percentile decile 0.20 — **occupancy pre-read exempt**. Same boundary
basis as H9. Contamination posture (block 5): Class-A filter makes
entry episodes filter-clean by construction; contamination-excluded
multiplier = 1.0 at design (census reports residual non-A co-travel).

Additional ISO-availability multiplier: design prior 0.95 (APP ISO
print rate from 03b characterization — **not** a frozen-grid occupancy
read; census-stage verification mandatory; if measured eligible-print
warm drives joint fraction materially below design, park on power —
no tuning).

| set | arithmetic | expectation | vs ≥ 130 |
|---|---|---|---|
| APP alone | 500 × 0.90 × 0.20 × 0.90 × 0.95 × 0.95 | **73.1** | FAIL |
| **APP ∪ RMBS** | 1000 × 0.90 × 0.20 × 0.90 × 0.95 × 0.95 | **146.2** | **PASS** |

Conditioning fraction stated: **0.20** × ISO-warm **0.95**.

### H10 · 3. POWER STRUCTURE DECLARED AT DESIGN

Identical axis split to H9: deployable {APP, RMBS}; evidence **pooled**
APP ∪ RMBS; per-symbol cannot clear ≥ 130. Consequence-precedence
sketch: copy H9 block 3 verbatim into the protocol freeze (primary
gates > safeguards; pooled power governs; n-invariant magnitude →
REJECTED; symbol drop from D re-checks pool).

### H10 · 4. WARM REALITY

| sensor | basis |
|---|---|
| `sweep_flow_imbalance` (NEW) | design warm ≥ 20 eligible prints / 900 s; APP ISO ≈ 0.285 × (3.6–6.3 trades/s) ⇒ ample; RMBS thinner — census verification; warm < 0.5 drops symbol |
| `kyle_lambda_60s` | F2; as H9 |
| `realized_vol_30s_zscore` | measured 0.94–0.995 — safe |
| `spread_z_30d` | **NOT USED** |

### H10 · 5. CONTAMINATION POSTURE

NEW trade-fed sensor at distribution extremes — **exemplary 03b case**.
Class-A filter + §4.4 correction netting are **explicit NEW-sensor
parameters**, load-bearing. No unfiltered trade-fed sensor at entry
extremes. `kyle_lambda_60s` F2-only inheritance justified as H9.

### H10 · 6. REJECTED-CLAIM ADJACENCY

| claim | relation |
|---|---|
| (a) H8 elevated-λ continuation @ H=300 | **Not that claim.** Conditioner = certified sweep flow, not dislocation×λ; H = 900. Related only by KYLE family / continuation sign. (Passive redesign of parked H1/H7 is a pointer to mechanics, not an economic prior — session constraint 6.) |
| (b) Contaminated baseline-reversion | **Not that claim.** Continuation with sweeps, not fade of baseline-λ dislocations. |

**FAILURE MODES.** (a) Tick-grid. (b) Momentum-ignition via cheap odd-lot
ISOs — negative tail; min aggregate sweep-volume floor REGISTERED-
UNEVALUATED. (c) L6 signing errors in fast markets + L2 passive
adversity. (d) Same horizon-magnitude risk as H9.

**IMPLEMENTATION.** New sensor module + registration + YAML. Only
new-module card on this slate.

---

## C. Slate ranking + override-rationale — verbatim from prompt_pack_09

## (1) Ranking

### (1a) Hard pre-filters FIRST (cost-floor AND density-margin)

| card | family × H × mode × set | κ_frozen | κ_req (med, set) | density (design-central) | cost | density | enter? |
|---|---|---|---|---|---|---|---|
| SEED | (excluded) | 0.114 | APP/300 0.138 | n/a | **FAIL** | — | **EXCLUDED** |
| H9 | KYLE × 900 × pas × {APP,RMBS} pool | 0.161 | 0.098 / 0.117 | 153.9 | PASS | PASS | **YES** |
| H10 | KYLE × 900 × pas × {APP,RMBS} pool | 0.158 | 0.098 / 0.117 | 146.2 | PASS | PASS | **YES** |
| H11 | SCHED × 1800 × pas × {APP,RMBS} pool | 0.121 | 0.074 / 0.086 | 147.7 | PASS | PASS | **YES** |

### (1b) S × F ÷ M on survivors — with known blind spots (pack-07 item 2)

Blind spots, stated before scores: the formula measures narrative /
implementation quality and **cannot see** (i) short-side × power
interactions (H6/H7 miss), (ii) cost-floor contact disguised by
illustrative edges (H1 miss), (iii) design-vs-realized occupancy
gaps when non-percentile priors are used (H8 miss — mitigated here by
percentile-only fractions), (iv) soft σ₁₈₀₀ sampling error (H11).
Cold-read review remains load-bearing.

| # | candidate | S | F | M | S×F÷M | notes |
|---|---|---|---|---|---|---|
| H10 | `sig_sweep_kyle_drift_h900_v1` | 5 | 3 | 1.0 | **15.0** | Certified conditioner; new sensor costs F; ISO-warm prior is the residual power risk |
| H9 | `sig_ofi_kyle_drift_h900_v1` | 4 | 5 | 1.5 | **13.3** | YAML-only; densest design-central (153.9); mirage penalty; answers §12(a) horizon-magnitude calibration on this universe |
| H11 | `sig_halfhour_clock_drift_v1` | 3 | 5 | 1.5 | **10.0** | Family diversification; soft σ₁₈₀₀; quintile weakens c_D; clock crowding |

Formula ranking: **H10 > H9 > H11.**

---

## (2) Recommendation — ONE candidate

**H9, `sig_ofi_kyle_drift_h900_v1`.** Override of the formula's
H10-first ranking is explicit and pre-registered in rationale (not
hidden): among survivors that clear both hard pre-filters, H9 has the
largest design-consistent density margin (153.9 vs 146.2 / 147.7),
requires no new sensor and no non-exempt occupancy prior, opens with
the strongest median headroom on APP at H = 900 (κ_req 0.098 vs
frozen 0.161), and is the cheapest instrument that answers the
result-doc §12(a) question — whether this universe's effect-magnitude
regime improves at H ≥ 900 after H8's n-invariant miss at H = 300.
H10 remains the structural runner-up (certified ISO; formula favorite);
H11 is the diversification / long-horizon option with the softest σ
basis.

Stated for review: if Lei weighs exchange-certified conditioning over
density margin and implementation cost, overriding to H10 is
defensible; the slate recommends H9.

---

## D. Dossier verdict rows (a–k) — verbatim from prompt_pack_09a

Note: the per-card matrices in 09a label checks **a–i** then **k**
(no literal `j.` row). **Distinctness (j)** is the dossier's §4
section, reproduced after the matrices.

### H9 — `sig_ofi_kyle_drift_h900_v1`

| Check | Verdict | Evidence |
|---|---|---|
| a. Family & form | PASS | KYLE_INFO; hl 450 ∈ [60, 1800]; H = 900; ratio 2.0; `kyle_lambda_60s` is a rule-5 KYLE primary; conditional dist fully stated (ofi_integrated pct ≥ 0.90 / ≤ 0.10, vol gate); no unreformalized residue. |
| b. Archetype & counterparty | PASS | Informed/committed-flow-following; losing pool = latency-constrained LPs + the parent's own IS — persists because completion schedules force continued impact payment over tens of minutes at these horizons. |
| c. Feasibility | PASS | Recomputed κ = 1.2×0.55×0.50×0.75×0.65 = **0.1609 ≈ 0.161** ≤ 0.30; pack-08 κ_req med APP 0.098 / RMBS 0.117 — both median-open; park 0.161×47.7 ≈ 7.68 > 4.68 (1.64×), RMBS 7.62 > 5.51; short rider APP 0.122 / RMBS 0.140 ≤ 0.161; **honest-κ only** (no p75/p90 dependence). |
| d. Density margin | **CONCERN** | Actuals give pooled 153.9 ≥ 130 with stated decile 0.20 (occupancy-exempt); **per-symbol 76.95 < 130** — §0 "per deployable symbol" bar is met only under the pooled structure of block 3, not per symbol. Not projection-only. |
| e. Power structure | PASS | Deployable {APP, RMBS}; evidence pooled; per-symbol diagnostic-only; consequence-precedence sketch copies backlog-13 defaults + A-2.1-class D-drop recheck — freeze-ready. |
| f. Warm reality | **CONCERN** | `realized_vol_30s_zscore` measured (H2 C.5); `ofi_integrated` @900 and `kyle_lambda_60s` warm **asserted** from quote/trade rates / inventory_pressure proxy — census verification pre-registered, not measured. Four NEW symbols not in D (N/A). No `spread_z_30d`. |
| g. Contamination | PASS | Quote-fed entry (Class-B absent); unfiltered `kyle_lambda_60s` F2-only with Class-A NEW-λ fallback — H8 Appendix-A / §2 precedent fits (λ not at entry extremes). |
| h. Falsification & regime | PASS | ≥ 3 dual-form (F1–F5); L1–L5 via §0.1; NEW-SENSOR count **0** (YAML + percentile factory). |
| i. Rejected-claim adjacency | **CONCERN** | Conditioner/horizon differ from H8 elevated-λ continuation — **not** "H8 again" mechanistically. Dominant failure mode (d) is still the **same population kill**: n-invariant sub-bar continuation magnitude on this universe. Distinguishing falsifier = OFI-specific F2 (λ elevation / same-direction print volume in OFI windows), not a dislocation×λ contrast. |
| k. No anchoring / peeking | PASS | No outcome stats; CKS/Kyle citations are literature; map/census characterization only. |

### H10 — `sig_sweep_kyle_drift_h900_v1`

| Check | Verdict | Evidence |
|---|---|---|
| a. Family & form | PASS | KYLE_INFO; hl 450; H = 900; ratio 2.0; `kyle_lambda_60s` rule-5 primary (+ NEW SFI listed); SFI conditional dist with Class-A ∩ id-14; no residue. |
| b. Archetype & counterparty | PASS | Informed sweeper; losing pool = resting LPs lifted cross-venue before repricing — persists because display obligations + ISO urgency leave permanent impact on the tape at 900 s. |
| c. Feasibility | PASS | κ = 1.2×0.65×0.45×0.75×0.60 = **0.15795 ≈ 0.158**; same map cells; park OPEN both symbols; short riders clear thinly; honest median only. |
| d. Density margin | **CONCERN** | Pooled actuals 146.2 ≥ 130; per-symbol 73.1 < 130 (same pool dependency as H9). **Plus:** ISO-warm 0.95 is a **non-percentile occupancy prior** inside the selection density headline — backlog 15 / 3-M requires census-legal pre-read before such headlines (percentile tails exempt; this multiplier is not). Card discloses census-stage verification; still a selection-headline defect relative to H9's percentile-only arithmetic. |
| e. Power structure | PASS | Identical axis split / precedence sketch to H9 — freeze-ready. |
| f. Warm reality | **CONCERN** | NEW `sweep_flow_imbalance` warm **asserted** from 03b ISO rates × trade intensity (legacy characterization, not frozen-grid measured); λ/vol as H9; no `spread_z_30d`. |
| g. Contamination | PASS | Exemplary 03b case: Class-A + §4.4 netting as explicit NEW-sensor parameters; no unfiltered trade-fed entry extremes. |
| h. Falsification & regime | PASS | F1–F5 present; L1–L5 cited; NEW-SENSOR count **1** — sole Task-9 size driver on this slate. |
| i. Rejected-claim adjacency | **CONCERN** | Not H8's claim (sweep flow ≠ dislocation×λ; H = 900). Same dominant magnitude-regime failure mode as H9/H8 population. Distinguisher = certified irrevocable prints + ignition/volume-floor falsifiers. |
| k. No anchoring / peeking | PASS | H1/H7 used as mechanics pointers only (session constraint 6 stated); no outcome peeking. |

### j. Distinctness (H9 vs H10) — verbatim from 09a §4

Both are **KYLE_INFO @ H = 900, passive, pooled {APP, RMBS}, hl = 450,
decile-tail continuation**. Shared fingerprints at the family level:
`kyle_lambda_60s` (F2 / G16 primary), same regime gate shape, same
dominant failure mode (horizon-magnitude generalization of H8's
sub-bar continuation on this universe). Distinct observables:
**quote-integrated OFI** (revocable, MIXED mirage) vs **Class-A
condition-14 sweep imbalance** (irrevocable, LOW mirage); distinct
κ factor tilts (`f_perm` / `r_rem` / `f_pass`); implementation fork
(YAML-only vs NEW sensor).

**Verdict:** two hypotheses, not one card with two conditioning
variants — the observable class and contamination/mirage posture
differ enough to justify separate ledger rows. They are **weakly
independent trials**: an n-invariant magnitude miss on either is
strong prior that the sibling dies the same way; an OFI-manufacture
kill or an ISO-ignition kill can separate them.

---

## E. RISKS paragraph on H9 + reconciliation text — verbatim from prompt_pack_09a

### 6. RISKS — H9 specifically

H9 is the cheapest instrument that asks result-doc §12(a)
(horizon-magnitude calibration on this universe) — and that is also
why it is the **highest-adjacency** card to H8's kill. Selecting it
first concentrates cycle-2 risk on the same population failure mode
(continuation magnitude) with a *weaker* mirage posture (MIXED
quote-OFI) than H10, warm assertions unmeasured at h = 900, and a
density bar that clears only in pool. A clean H9 F1 miss teaches the
calibration lesson; it does not buy a better observable. Trap risk:
treating a second magnitude miss as "we learned the universe" while
never testing the certified-print conditioner (H10) that could have
separated manufacture from mechanism.

### 7. SLATE-LEVEL — pre-filters, S×F÷M, override audit (reconciliation)

**Hard pre-filters recomputed (cost-floor AND density-margin on
actuals):**

| card | κ_frozen vs κ_req med | density (pooled actuals) | enter? |
|---|---|---|---|
| SEED | 0.088 / 0.116 < 0.138 | n/a | **EXCLUDED** (confirm) |
| H9 | 0.161 > 0.098 / 0.117 | 153.9 ≥ 130 | YES |
| H10 | 0.158 > 0.098 / 0.117 | 146.2 ≥ 130 | YES |
| H11 | 0.121 > 0.074 / 0.086 | 147.7 ≥ 130 | YES on economics/density; **form FAIL** is outside these two pre-filters |

Agrees with slate (1a) on cost/density entry. H11's form FAIL should
block confirmation until reformalized — not invisible to ranking.

**S×F÷M arithmetic:** H10 = 5×3÷1.0 = **15.0**; H9 = 4×5÷1.5 = **13.3**;
H11 = 3×5÷1.5 = **10.0**. Formula order **H10 > H9 > H11** — correct.
Blind spots named (pack-07 item 2) — adequate disclosure.

**Independent order (recorded before reading slate §(1)–(3)):
H10 > H9 > H11.**

Basis: H10 has the cleanest mirage, exemplary contamination posture,
and the strongest observable separation from H8's kill population;
density ISO prior is a CONCERN but disclosed. H9 second — YAML-cheap
and occupancy-clean, but highest H8-adjacency and MIXED mirage. H11
last — G16 fingerprint / clock-predicate FAIL; soft σ₁₈₀₀; weakest
conditioning.

**Override audit (slate recommends H9 over formula H10-first):**
Rationale is coherent and pre-registered (largest percentile-only
density margin; no NEW sensor; no non-exempt occupancy prior; cheapest
§12(a) calibration shot). That is **program-strategy**, not the same
class as the H8 selection override (06a): H8 corrected a formula miss
of a hard economics/power interaction. Here the formula and this
review agree on H10-first; the slate demotes the cleaner conditioner
to buy a cheaper calibration experiment. **Principled as research
priority; taste relative to independent card-quality ranking.** Not
blind-spot-driven in the H8 sense.

### 9. RECONCILED RANKING (reviewer's; not a selection)

| Rank | Card | Role in reconciled view |
|---|---|---|
| 1 | **H10** | Best form + mirage + contamination; formula favorite; independent favorite |
| 2 | **H9** | Best cheap §12(a) probe; slate recommendation; highest H8-adjacency risk (§6) |
| 3 | **H11** | Hold for reformalization (G16 `scheduled_flow_window` + clock predicate) before any confirmation path |

I do **not** select. Lei decides.

---

## F. QUESTIONS FOR LEI — verbatim from prompt_pack_09a §10

1. **Override class.** Do you treat the H9-over-H10 override as a
   binding program priority (answer §12(a) cheapest first), or do you
   want the independent/formula order (certified conditioner first)
   given H9's explicit adjacency to the H8 magnitude kill?

2. **H11 reformalization bar.** Is H11's FAIL on
   `SCHEDULED_FLOW` without `scheduled_flow_window` (and without a
   clock predicate in the conditional) a confirmation blocker
   requiring a rewritten card before any Task 7 path, or an
   acceptable drafting debt?

3. **Tranche-1B vs H11 D.** With {OLN, DIOD, PCTY, CROX} now at 20
   sessions and median-open at H = 1800 honest κ (pack-08 §2.4 / §5),
   should any confirmed 1800 card pre-register a backlog-16
   disposition for those four as deployable or evidence-only — or
   stay frozen on {APP, RMBS} only for the first census?

---

## G. Addendum — H9 κ/edge derivation quantity census (census-legal)

Scope: every quantity entering H9's **horizon-magnitude calibration**
κ/edge arithmetic on the card face (H9 · 1 + the hypothesis magnitude
line). Classification: **map/census characterization** vs **design /
literature prior** vs **derived on the card**. Flag if any quantity
originates in H8's **STATISTICAL RESULTS** (outcome data: RankIC, n,
p, conditional returns in
`docs/research/sig_dislocation_lambda_drift_v1_result.md` §7 /
protocol S.1–S.7), as opposed to census/map artifacts.

| Quantity | Value (card) | Role | Source document | Class | H8 STATISTICAL RESULTS? |
|---|---|---|---|---|---|
| `c_D` | 1.2 | κ factor | Card grounding: "extreme-OFI windows ~1σ contemporaneous (CKS)"; Cont–Kukanov–Stoikov literature; design prior in pack-09 H9 · 1 | literature / design prior | **No** |
| `f_perm` | 0.55 | κ factor | Card grounding: "Kyle/GM scheduled-flow permanent share"; Kyle / Glosten–Milgrom literature | literature / design prior | **No** |
| `r_rem` | 0.50 | κ factor | Card grounding: "uniform detection along parent schedule" | design prior | **No** |
| `f_H` | 0.75 | κ factor | Card: `1 − e^(−900/τ)`, `τ = 450/ln 2 ≈ 649` (from card hl = 450). Algebraic partial-adjustment construction also appears in H8 **PROCESS MODEL** (`sig_dislocation_lambda_drift_v1_result.md` §4) at H=300/hl=150 — same formula class, different inputs; **not** §7 outcome stats | derived from card hl / design construction | **No** (process-model convention only) |
| `f_pass` | 0.65 | κ factor | Card grounding: "passive same-side pullback fill haircut"; H2-spec factor style (pack-09) | design prior | **No** |
| κ band | [0.03, 0.30] | envelope | Card H9 · 1 ("κ ∈ [0.03, 0.30]"); program central-κ ≈ 0.16 shrinkage lens (pack-08 header / pack-05) | design envelope / map lens | **No** |
| κ_frozen | ≈ 0.161 | product | Card: `1.2×0.55×0.50×0.75×0.65`; 09a recomputes 0.1609 ≈ 0.161 | derived on card | **No** |
| σ₉₀₀,med APP | 47.7 bps | edge = κ·σ | `prompt_pack_08_frontier_refresh.md` §2.2; artifact `horizon_feasibility_map_operative_2026-07-15.json` | **map / census characterization** | **No** |
| σ₉₀₀,med RMBS | 47.3 bps | edge = κ·σ | pack-08 §2.2 / same operative map artifact | **map / census characterization** | **No** |
| floor P APP | 4.68 bps | park bar | pack-08 §2.1 (`floor = 2.25 × C_ow`); method pack-05 §2 / pack-08 §1 | **map / census characterization** | **No** |
| floor P RMBS | 5.51 bps | park bar | pack-08 §2.1 | **map / census characterization** | **No** |
| κ_req med APP @900 | 0.098 | open/closed | pack-08 §2.2 (= floor/σ) | **map / census characterization** | **No** |
| κ_req med RMBS @900 | 0.117 | open/closed | pack-08 §2.2 | **map / census characterization** | **No** |
| edge APP (κ·σ) | ≈ 7.68 bps (hyp. line ~7.6) | magnitude claim | Card park table: `0.161 × 47.7` | derived (κ prior × map σ) | **No** |
| edge RMBS (κ·σ) | ≈ 7.62 bps | magnitude claim | Card: `0.161 × 47.3` | derived (κ prior × map σ) | **No** |
| passive AS | 2.0 bps | short-side C_ow | pack-05 §2 / 00c LEVEL-drain pin; carried in short rider `2.0 + …` | map method / platform pin | **No** |
| fee_P APP | 0.08 bps | short-side C_ow | pack-05 §2 fee_P at grid-median bid; H9 uses 0.08 (pack-06 rider convention); pack-08 APP med bid 553.72 keeps floor P 4.68 | **map / census characterization** | **No** |
| short rider | 0.507 bps | SELL add-on | pack-05 §2: `cost_sell_regulatory_bps = 0.5` + FINRA TAF ~0.007; H8 formal-spec §5.2 / pack-06 H6 disclosure use 0.507 | map method / design disclosure convention | **No** |
| short floor APP | ≈ 5.82 bps | rider-inclusive | Card: `2.25 × (2.0 + 0.08 + 0.507)`; same arithmetic as pack-06 H6 / H8 formal-spec §5.2 | derived (map method) | **No** |
| short κ_req APP | ≈ 0.122 | rider check | Card: `5.82 / 47.7` | derived | **No** |
| short floor RMBS | ≈ 6.60 bps | rider-inclusive | Card carry; H8 formal-spec §5.2 rider table (RMBS short 6.60); fee basis pack-05/08 | map method / prior-card disclosure | **No** |
| short κ_req RMBS | ≈ 0.140 | rider check | Card: `6.60 / 47.3` | derived | **No** |
| κ factor *template* | `κ = c_D × f_perm × r_rem × f_H × f_pass` | structure | Card: "H2-spec factor style"; also H8 result-doc **§4 PROCESS MODEL** (design), not §7 | design / process-model convention | **No** (not STATISTICAL RESULTS) |

**Verdict on outcome leakage:** **None** of the quantities in H9's
κ/edge derivation originate in H8's STATISTICAL RESULTS (RankIC /
Fisher-z / conditional markouts / stratum n). Map cells (σ, floors,
κ_req) are pack-08 / operative feasibility-map characterization.
Factor centrals are literature- or design-priors on the card.
The only H8-adjacent material is (i) the shared partial-adjustment
factor *template* from H8's process model / H2-spec style, and (ii)
narrative failure-mode adjacency to H8's sub-bar magnitude kill —
neither is an outcome datum plugged into κ or edge.

---

*End of extraction. Final H9-vs-H10 adjudication is Lei's; no selection
made here.*
