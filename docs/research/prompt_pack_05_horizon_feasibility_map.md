<!--
  File:   docs/research/prompt_pack_05_horizon_feasibility_map.md
  Status: NORMATIVE — measured horizon-feasibility map on the frozen
          80-cell grid (Task FQ-8, 2026-07-11). Deterministic rerun
          verified (bit-identical artifact). Discharges the σ-side of
          backlog entry 7 (extension): this map is the hard
          hypothesis-slate pre-filter for vol-vs-cost viability.
          Episode density remains gate-specific per candidate (§6).
  Owner:  research-workflow (slate pre-filter) / microstructure-alpha
          (consumer); prompt-pack Task FQ-8.

  Provenance (FQ-3 template): see §7.
-->

# Task FQ-8 — Horizon-feasibility map (unconditional σ_H vs stressed cost floors)

**What this is.** For every (symbol, horizon) on the frozen 80-cell
grid (8 symbols × 10 sessions, 03c §5.1), the unconditional session
σ_H distribution at every registered horizon H ∈ {30, 120, 300, 900,
1800} s, crossed with spec-§4.2-style stressed one-way cost floors
(passive and taker variants side by side) to give the implied minimum
capture coefficient κ_req = floor / σ_H. Cells with κ_req ≤ 0.30 (the
H2 spec §4.1 honest-band ceiling — the derivation ceiling) are flagged
FEASIBLE. **Census legality throughout: no forward returns, no IC, no
signal evaluation — the only return-like quantity is unconditional
session vol at horizon boundaries.** No outcome statistic exists in
this document; nothing here is a result in the Rule-5 sense (these are
cost floors and unconditional vol, not edge measurements). **Trial
ledger: N = 10, unchanged** — no hypothesis was evaluated.

## 1. Method (census machinery, H-generalized)

Estimator and replay conventions are those of the Task 8-C census
(`scripts/research/inventory_fade_census.py`, commit `642d12d`),
implemented in `scripts/research/horizon_feasibility_map.py`:

- Direct `DiskEventCache` read (`~/.feelies/cache`), RTH filter on
  `exchange_timestamp_ns` (09:30 ≤ t < 16:00 ET, mirroring
  `prepare_backtest_event_log`), sort by `(timestamp_ns, sequence)`,
  fresh state per (symbol, session).
- σ_H = Bessel-corrected sample std of **non-overlapping H-second mid
  log returns** on the 09:30-ET-anchored grid (`rth_open_ns`, audit
  P1-8 — the identical nominal boundary grid the `HorizonScheduler`
  emits), last-mid-at-or-before sampling, positive two-sided quotes,
  in bps. Returns per session: 780 (H=30), 195 (120), 78 (300),
  26 (900), 13 (1800).
- **Scope decision (recorded, not hidden):** unconditional σ_H reads
  only the RTH mid series — no sensor output enters any number, so the
  `SensorRegistry → HorizonScheduler → HorizonAggregator` stack is not
  constructed. Everything that defines the estimator (cache read, RTH
  filter, sort, RTH-open boundary grid, mid sampling, Bessel std) is
  reused verbatim from the census. **Reproduction check:** the σ₁₂₀
  column reproduces the census values (APP/2026-04-10 = 32.31 vs
  census 32.3; MLI/2026-04-10 = 7.69 vs 7.7; per-cell values in the
  artifact match throughout).
- Quantiles over the 10 sessions per symbol: median/p75/p90,
  Hyndman–Fan type 7 (linear interpolation; the numpy default),
  computed in stdlib.

## 2. Cost side — recomputed fee-in-bps and stressed floors

Floor formula (spec §4.2 / adjudication §D.2 arithmetic, 00b one-way
per-fill bps convention): `floor = 1.5 × C_ow,stressed = 1.5 × 1.5 ×
C_ow = 2.25 × C_ow` (cost_stress_multiplier 1.5 on variable costs,
then the Inv-12 1.5× margin). Two variants:

- **Passive (maker):** `C_ow = 2.0 + fee_passive` — half-spread 0,
  adverse selection 2.0 bps (00c LEVEL/drain pin), fee = $0.35
  min-commission on the 80-share reference fill.
- **Taker:** `C_ow = half_spread + impact + fee_taker` (adjudication
  §D.1 method) — impact 1.0 bps when half-spread < 8 bps else 2.0 bps;
  fee = $0.35 commission + $0.24 taker exchange (0.003/sh × 80).

Fee-in-bps **recomputed from the full grid cache** (per-session median
RTH bid and quoted spread, positive two-sided quotes; then
median-of-per-session-medians across the 10 sessions — the 03c §7
pooling convention), rather than quoted from the 03c §3.1 one-session
samples. The recomputed bids differ from §3.1 where the symbol's price
moved across the grid (APP: 544.08 recomputed vs 615.05 sampled on
2026-01-15); floors below use the recomputed basis.

| symbol | med bid ($) | med spread ($) | half-spread (bps) | impact | fee_P (bps) | fee_T (bps) | C_ow P | C_ow T | **floor P** | **floor T** |
|---|---|---|---|---|---|---|---|---|---|---|
| APP  | 544.08 | 0.61 | 5.61  | 1.0 | 0.08 | 0.14 | 2.08 | 6.74  | **4.68** | **15.17** |
| RMBS | 102.06 | 0.22 | 10.78 | 2.0 | 0.43 | 0.72 | 2.43 | 13.50 | **5.46** | **30.38** |
| OLN  | 23.48  | 0.02 | 4.26  | 1.0 | 1.86 | 3.14 | 3.86 | 8.40  | **8.69** | **18.90** |
| ENSG | 181.16 | 0.48 | 13.25 | 2.0 | 0.24 | 0.41 | 2.24 | 15.66 | **5.04** | **35.22** |
| DIOD | 56.89  | 0.18 | 15.82 | 2.0 | 0.77 | 1.30 | 2.77 | 19.12 | **6.23** | **43.01** |
| PCTY | 143.66 | 0.30 | 10.44 | 2.0 | 0.30 | 0.51 | 2.30 | 12.96 | **5.19** | **29.15** |
| MLI  | 120.41 | 0.20 | 8.31  | 2.0 | 0.36 | 0.61 | 2.36 | 10.92 | **5.32** | **24.57** |
| CROX | 85.12  | 0.11 | 6.46  | 1.0 | 0.51 | 0.87 | 2.51 | 8.33  | **5.66** | **18.74** |

Riders (matching §4.2, not folded into the floors): SELL legs add
`cost_sell_regulatory_bps = 0.5` + FINRA TAF (~0.007 bps at this
scale). OLN carries the discreteness caveat: half-tick quantum ≈ 2.1
bps at its price point — H2's Amendment-G exclusion was card-specific
(passive-fade economics), so OLN is **included** in this generic map
with that caveat standing for any passive design. The B4 runtime
figure is quote-dependent and can exceed disclosure arithmetic (00b
qualification 1).

## 3. σ_H distributions and κ_req (the feasibility table)

σ in bps over the 10 grid sessions; κ_req = floor / σ_H per variant
(P = passive, T = taker). FEASIBLE (bold flag) = κ_req ≤ 0.30 at that
quantile. Full precision in the artifact; the artifact's boolean flags
are authoritative at rounding boundaries.

| sym | H | σ med | σ p75 | σ p90 | κP med | κP p75 | κP p90 | κT med | κT p75 | κT p90 | FEASIBLE P | FEASIBLE T |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| APP | 30 | 10.7 | 11.7 | 12.3 | 0.438 | 0.399 | 0.379 | 1.421 | 1.291 | 1.228 | — | — |
| APP | 120 | 21.0 | 22.5 | 26.8 | 0.222 | 0.208 | 0.175 | 0.721 | 0.674 | 0.566 | **p50,p75,p90** | — |
| APP | 300 | 33.8 | 35.4 | 36.8 | 0.139 | 0.132 | 0.127 | 0.449 | 0.429 | 0.412 | **p50,p75,p90** | — |
| APP | 900 | 42.5 | 49.5 | 59.4 | 0.110 | 0.095 | 0.079 | 0.357 | 0.306 | 0.255 | **p50,p75,p90** | **p90** |
| APP | 1800 | 60.6 | 67.1 | 77.6 | 0.077 | 0.070 | 0.060 | 0.250 | 0.226 | 0.196 | **p50,p75,p90** | **p50,p75,p90** |
| RMBS | 30 | 11.6 | 12.3 | 12.6 | 0.473 | 0.445 | 0.433 | 2.629 | 2.472 | 2.406 | — | — |
| RMBS | 120 | 22.8 | 25.2 | 26.8 | 0.240 | 0.217 | 0.204 | 1.334 | 1.206 | 1.133 | **p50,p75,p90** | — |
| RMBS | 300 | 31.6 | 38.3 | 39.9 | 0.173 | 0.143 | 0.137 | 0.961 | 0.793 | 0.762 | **p50,p75,p90** | — |
| RMBS | 900 | 48.7 | 52.8 | 61.9 | 0.112 | 0.104 | 0.088 | 0.624 | 0.575 | 0.491 | **p50,p75,p90** | — |
| RMBS | 1800 | 68.1 | 71.9 | 111.9 | 0.080 | 0.076 | 0.049 | 0.446 | 0.422 | 0.272 | **p50,p75,p90** | **p90** |
| OLN | 30 | 9.5 | 10.5 | 11.0 | 0.917 | 0.829 | 0.792 | 1.994 | 1.803 | 1.723 | — | — |
| OLN | 120 | 19.6 | 19.9 | 22.3 | 0.444 | 0.438 | 0.390 | 0.966 | 0.952 | 0.848 | — | — |
| OLN | 300 | 25.2 | 33.0 | 35.4 | 0.345 | 0.263 | 0.245 | 0.749 | 0.572 | 0.534 | **p75,p90** | — |
| OLN | 900 | 44.0 | 47.7 | 56.4 | 0.198 | 0.182 | 0.154 | 0.430 | 0.396 | 0.335 | **p50,p75,p90** | — |
| OLN | 1800 | 56.8 | 67.9 | 90.8 | 0.153 | 0.128 | 0.096 | 0.333 | 0.278 | 0.208 | **p50,p75,p90** | **p75,p90** |
| ENSG | 30 | 6.2 | 7.3 | 8.8 | 0.816 | 0.689 | 0.576 | 5.698 | 4.812 | 4.024 | — | — |
| ENSG | 120 | 11.4 | 12.7 | 14.4 | 0.442 | 0.398 | 0.349 | 3.084 | 2.776 | 2.439 | — | — |
| ENSG | 300 | 16.9 | 19.6 | 20.9 | 0.299 | 0.258 | 0.241 | 2.090 | 1.799 | 1.682 | **p50,p75,p90** | — |
| ENSG | 900 | 22.9 | 26.0 | 30.7 | 0.221 | 0.194 | 0.164 | 1.541 | 1.354 | 1.147 | **p50,p75,p90** | — |
| ENSG | 1800 | 29.8 | 32.4 | 35.4 | 0.169 | 0.156 | 0.142 | 1.182 | 1.087 | 0.994 | **p50,p75,p90** | — |
| DIOD | 30 | 8.2 | 9.0 | 9.6 | 0.761 | 0.696 | 0.650 | 5.255 | 4.805 | 4.485 | — | — |
| DIOD | 120 | 16.0 | 19.4 | 19.9 | 0.389 | 0.322 | 0.314 | 2.688 | 2.220 | 2.166 | — | — |
| DIOD | 300 | 25.2 | 27.2 | 29.0 | 0.247 | 0.229 | 0.215 | 1.707 | 1.579 | 1.482 | **p50,p75,p90** | — |
| DIOD | 900 | 34.8 | 48.1 | 53.4 | 0.179 | 0.129 | 0.117 | 1.236 | 0.893 | 0.806 | **p50,p75,p90** | — |
| DIOD | 1800 | 47.4 | 58.8 | 66.8 | 0.131 | 0.106 | 0.093 | 0.907 | 0.731 | 0.643 | **p50,p75,p90** | — |
| PCTY | 30 | 7.4 | 8.7 | 9.9 | 0.702 | 0.595 | 0.524 | 3.946 | 3.345 | 2.945 | — | — |
| PCTY | 120 | 15.6 | 17.4 | 18.3 | 0.333 | 0.298 | 0.283 | 1.874 | 1.675 | 1.593 | **p75,p90** | — |
| PCTY | 300 | 21.6 | 26.0 | 26.8 | 0.240 | 0.200 | 0.194 | 1.348 | 1.122 | 1.089 | **p50,p75,p90** | — |
| PCTY | 900 | 28.7 | 30.8 | 38.3 | 0.181 | 0.168 | 0.135 | 1.016 | 0.945 | 0.761 | **p50,p75,p90** | — |
| PCTY | 1800 | 37.2 | 41.6 | 56.2 | 0.140 | 0.125 | 0.092 | 0.784 | 0.700 | 0.519 | **p50,p75,p90** | — |
| MLI | 30 | 4.5 | 4.8 | 5.4 | 1.179 | 1.099 | 0.978 | 5.446 | 5.078 | 4.518 | — | — |
| MLI | 120 | 9.0 | 9.6 | 11.6 | 0.593 | 0.554 | 0.458 | 2.740 | 2.557 | 2.116 | — | — |
| MLI | 300 | 12.8 | 14.3 | 16.3 | 0.414 | 0.371 | 0.325 | 1.912 | 1.716 | 1.503 | — | — |
| MLI | 900 | 18.6 | 25.2 | 29.4 | 0.286 | 0.211 | 0.181 | 1.323 | 0.974 | 0.835 | **p50,p75,p90** | — |
| MLI | 1800 | 28.4 | 30.7 | 41.2 | 0.187 | 0.173 | 0.129 | 0.864 | 0.801 | 0.596 | **p50,p75,p90** | — |
| CROX | 30 | 7.4 | 7.6 | 8.1 | 0.765 | 0.748 | 0.694 | 2.535 | 2.477 | 2.300 | — | — |
| CROX | 120 | 15.5 | 16.1 | 17.2 | 0.366 | 0.352 | 0.329 | 1.211 | 1.167 | 1.090 | — | — |
| CROX | 300 | 24.8 | 26.5 | 30.5 | 0.228 | 0.214 | 0.185 | 0.756 | 0.708 | 0.613 | **p50,p75,p90** | — |
| CROX | 900 | 33.3 | 35.2 | 47.4 | 0.170 | 0.161 | 0.119 | 0.563 | 0.532 | 0.395 | **p50,p75,p90** | — |
| CROX | 1800 | 41.5 | 43.5 | 48.5 | 0.136 | 0.130 | 0.117 | 0.452 | 0.431 | 0.387 | **p50,p75,p90** | — |

## 4. Mechanism-class × horizon legality (G16) and open regions

Horizon H is legal for family F iff H ∈ [0.5 × hl_min(F),
4.0 × hl_max(F)] (G16 rules 2–3, `alpha/layer_validator.py`
`_FAMILY_HALF_LIFE_RANGES_SECONDS`, ratio bounds [0.5, 4.0]):

| family | hl envelope (s) | legal registered horizons |
|---|---|---|
| KYLE_INFO | 60–1800 | 30, 120, 300, 900, 1800 |
| INVENTORY | 5–60 | 30, 120 |
| HAWKES_SELF_EXCITE | 5–60 | 30, 120 |
| LIQUIDITY_STRESS | 30–600 | 30–1800 — **EXIT-ONLY**, no entry region |
| SCHEDULED_FLOW | 60–1800 | 30, 120, 300, 900, 1800 |

**Open regions at the κ ≤ 0.30 ceiling (median session, i.e.
unconditional deployability):**

- **H = 30 s is CLOSED on the entire universe, both execution
  variants** (best cell: APP passive κ_req 0.379 even at p90). Any
  30 s candidate on this universe fails the vol-vs-cost precondition
  outright.
- **INVENTORY / HAWKES_SELF_EXCITE (legal only at 30/120):** open only
  as **passive at H=120 on {APP, RMBS}** at the median (PCTY joins in
  the p75+ session tail). Taker: closed. This is a narrow, thin-margin
  region — see the central-κ shrinkage below and the H2 park record.
- **KYLE_INFO / SCHEDULED_FLOW (legal at all horizons), passive:**
  open at **H=120 on {APP, RMBS}**; **H=300 on {APP, RMBS, ENSG, DIOD,
  PCTY, CROX}** (OLN joins at p75+; MLI closed); **H=900 and H=1800 on
  all 8 symbols**.
- **Taker (any family): effectively closed.** Median-session
  feasibility exists only at **APP H=1800** (κ_req 0.250). The session
  tail (p90) adds APP 900, RMBS 1800, OLN 1800(p75+). Taker
  mechanisms at H ≤ 300 fail everywhere by 1.4×–19×.
- **LIQUIDITY_STRESS:** exit-only (`EXIT_ONLY_MECHANISMS`); no entry
  feasibility claim applies.

**Shrinkage at the H2 central κ = 0.16 (disclosure, same measured σ —
no new trial):** the 0.30 flag is the *optimistic top* of the honest
derivation band; a candidate whose own derivation lands at a central
≈ 0.16 sees a much smaller passive map at the median session — APP
≥ 300 s; RMBS ≥ 900 s; OLN, DIOD, PCTY, CROX at 1800 s only; ENSG and
MLI closed at the median (ENSG opens at p75, MLI only at p90, both at
1800 s). Taker at
central κ: closed everywhere (minimum κT anywhere = APP 1800 p90 =
0.196). Consequence: **any new candidate must clear this map with its
own mechanism-derived κ band, not the 0.30 ceiling alone.**

## 5. Caveats (binding on any consumer of this map)

1. **10 sessions per symbol** — p75/p90 interpolate 10 points; the
   upper quantiles largely reflect the elevated strata (grid mix:
   5 calm / 2 elevated-A / 3 elevated-B). L1 carries verbatim: calm
   cells are evidence about calm-as-realized Dec-2025–Jan-2026 only.
2. **σ_1800 rests on 13 returns/session** (σ_900 on 26) — wide
   per-session sampling error; the long-horizon feasibility calls are
   correspondingly soft.
3. **The 0.30 ceiling is H2-derivation-specific** (INVENTORY fade at
   H=120: κ = c_D × f_temp × f_surv × f_capt / √2). As a generic
   screen it is the permissive bound; §4's central-κ shrinkage is the
   honest counterweight.
4. **This map measures vol-vs-cost only.** Eligible-episode density —
   the census's second park axis (power ≥ 100 episodes/symbol) — is
   gate-specific and must be measured per candidate; the h=120
   census density numbers (max 35/symbol) are the only measured
   density on this grid to date. A cell open here can still park on
   power.
5. Floors are **disclosure arithmetic** at the 80-share reference fill
   and grid-median quotes; runtime B4 is quote-dependent (00b
   qualification 1). Nothing here is presentable as a result (Rule 5).
6. **OLN** carries the tick-discreteness caveat (half-tick ≈ 2.1 bps);
   **SELL legs** add 0.5 bps regulatory + TAF, not folded in.
7. Sensor-side constraints measured elsewhere still bind any design:
   `spread_z_30d` warm starvation on thin names (backlog 9) and DI-09
   contamination-at-extremes for trade-fed conditioning (backlog 10).
8. The grid is screened away from calendar-event days (H4 park
   record); SCHEDULED_FLOW feasibility here says nothing about
   event-day economics.

## 6. Operative rule (slate pre-filter — backlog entry 7 extension)

A hypothesis card may enter slate ranking only if its (mechanism
family × horizon × symbol set × execution variant) intersects a
FEASIBLE region of §3/§4 **at the card's own derived κ** (falling back
to the 0.30 ceiling only when the card has no derivation yet, and
saying so). Cards whose region is closed at the median session may
pre-register a σ-conditional (session-tail) region only with the park
rule armed, H2-style. This is the σ-side hard pre-filter; the density
pre-filter remains per-candidate (caveat 4).

## 7. Determinism and provenance (FQ-3)

    os: "Windows 11 (win32 10.0.26200)"
    cpu_arch: "AMD64"
    python_build: "3.14.2 (tags/v3.14.2:df79316, Dec 5 2025, 17:18:21) [MSC v.1944 64 bit (AMD64)]"
    libm: "Microsoft UCRT (linked by MSC v.1944; platform.libc_ver() = ('', '') on Windows)"
    git_sha: "12afd8d83740881285789f644213a10742429b72" (HEAD at task
      start; this task's outputs are the first commit after it)
    config_checksum: "n/a — no PlatformConfig loaded; direct
      DiskEventCache read (census precedent)"
    pythonhashseed: "0 (set in session for every scripted run)"
    worktree_clean: "yes at task start (git status --porcelain empty)"
    command: "PYTHONHASHSEED=0 uv run python
      scripts/research/horizon_feasibility_map.py --json
      docs/research/artifacts/horizon_feasibility_map_2026-07-11.json"
    artifact: "docs/research/artifacts/horizon_feasibility_map_2026-07-11.json
      sha256=362c42cafd07659a9d0bdf51e1c72f8495ccfa78502b349f12a17ca52a51f3fd"
    determinism: "full-grid rerun bit-identical (SHA-256 equal on both
      runs)"
    script: "scripts/research/horizon_feasibility_map.py (committed
      with this record; registered in docs/prompts/README.md coverage
      map, research_validation)"
    sigma120_reproduction: "matches census 642d12d per-cell values
      (spot: APP/2026-04-10 32.31, MLI/2026-04-10 7.69)"
    normative_inputs: "inventory_fade_census.py + protocol CENSUS
      RESULTS (estimator), sig_inventory_fade_v1_formal_spec.md §4.1-4.2
      (κ band, floor formula), h2_h4_adjudication_package.md §D.1-D.2
      (taker method, stress arithmetic), prompt_pack_00c_eval_canon.md
      (cost pins), prompt_pack_03c_universe_and_cache.md (grid, pooling
      convention), alpha/layer_validator.py (G16 envelopes)"
