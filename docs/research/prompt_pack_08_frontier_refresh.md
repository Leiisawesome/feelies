<!--
  File:   docs/research/prompt_pack_08_frontier_refresh.md
  Status: NORMATIVE — OPERATIVE-grid frontier refresh (Task FQ-9,
          2026-07-15). Census-legal only (no forward returns / IC).
          Deterministic rerun verified (bit-identical artifact).
          Discharges retrospective S-2 / item-4 "pending map recompute"
          on the 20-session {APP, RMBS} + 10-session six-others cache.
          Pack-05 remains the frozen 80-cell (10×8) record; this file
          is the operative pre-filter for slate C.
  Owner:  research-workflow (slate C pre-filter) / microstructure-alpha
          (consumer); prompt-pack Task FQ-9.

  Provenance (FQ-3 template): see §5.
-->

# Task FQ-9 — OPERATIVE-grid frontier refresh

**What this is.** Recompute of the pack-05 horizon-feasibility map on
the **operative** cache (03c AMENDMENT 1): 20 sessions for {APP, RMBS},
10 original sessions for {OLN, ENSG, DIOD, PCTY, MLI, CROX} — 100
ingested cells. Same estimator, same floor arithmetic, same κ ≤ 0.30
FEASIBLE flag and central-κ ≈ 0.16 shrinkage lens. Plus: H ∈ {900, 1800}
boundary-density basis (current + projected if the 60
DRAWN-NOT-INGESTED cells are ingested), and an ingestion decision table
for the six thin symbols. **Census legality throughout: no forward
returns, no IC, no signal evaluation.** Trial ledger: **N = 11,
unchanged** — no hypothesis was evaluated.

---

## 1. Method (unchanged estimator; operative session set)

Identical to pack-05 §1 / `scripts/research/horizon_feasibility_map.py`
(FQ-8 → FQ-9: session set only):

- Direct `DiskEventCache` read; RTH filter on `exchange_timestamp_ns`;
  sort by `(timestamp_ns, sequence)`; fresh state per (symbol, session).
- σ_H = Bessel-corrected sample std of non-overlapping H-second mid
  log returns on the 09:30-ET-anchored grid (`rth_open_ns`), in bps.
- Measured `n_returns` per session (all 100 cells uniform): 779 (H=30),
  194 (120), 77 (300), **25 (900)**, **12 (1800)**. (Pack-05 prose
  cited theoretical maxima 26/13; the artifact has always carried
  25/12 — used as the density basis below, matching pack-06 §0.)
- Quantiles: Hyndman–Fan type 7 over that symbol's operative sessions
  (20 for APP/RMBS, 10 for the six).
- Floors: grid-median fee-in-bps (median-of-per-session-medians),
  passive and taker, `floor = 2.25 × C_ow` (Inv-12 × stress).

Session sets (03c A1.1 / A1.5):

| symbol | n | dates |
|---|---|---|
| APP, RMBS | 20 | original 10 + expansion `{2025-12-01, 2025-12-02, 2025-12-26, 2025-12-30, 2026-01-12, 2026-01-20, 2026-01-22, 2026-04-02, 2026-04-07, 2026-04-16}` |
| OLN, ENSG, DIOD, PCTY, MLI, CROX | 10 | original 10 only (expansion cells DRAWN-NOT-INGESTED) |

---

## 2. Feasibility map — operative results and deltas vs pack-05

### 2.1 Cost floors

| symbol | med bid ($) | half-spread (bps) | **floor P** | **floor T** | ΔP vs FQ-8 | ΔT vs FQ-8 |
|---|---|---|---|---|---|---|
| APP  | 553.72 | 5.37  | **4.68** | **14.64** | 0.00 | −0.53 |
| RMBS | 97.56  | 11.28 | **5.51** | **31.57** | +0.04 | +1.19 |
| OLN  | 23.48  | 4.26  | **8.69** | **18.90** | 0 | 0 |
| ENSG | 181.16 | 13.25 | **5.04** | **35.22** | 0 | 0 |
| DIOD | 56.89  | 15.82 | **6.23** | **43.01** | 0 | 0 |
| PCTY | 143.66 | 10.44 | **5.19** | **29.15** | 0 | 0 |
| MLI  | 120.41 | 8.31  | **5.32** | **24.57** | 0 | 0 |
| CROX | 85.12  | 6.46  | **5.66** | **18.74** | 0 | 0 |

The six non-expanded symbols are **bit-identical** to pack-05 on both
floors and every (H, quantile) κ_req cell (same 10 sessions). Only
{APP, RMBS} move.

### 2.2 σ_H / κ_req (operative)

Full precision in the artifact. FEASIBLE = κ_req ≤ 0.30. Rounded
display:

| sym | H | n | σ med | σ p75 | σ p90 | κP med | κP p90 | κT med | κT p90 | FEASIBLE P | FEASIBLE T |
|---|---|---|---|---|---|---|---|---|---|---|---|
| APP | 30 | 20 | 11.2 | 11.8 | 12.8 | 0.419 | 0.366 | 1.310 | 1.144 | — | — |
| APP | 120 | 20 | 21.2 | 23.5 | 26.8 | 0.220 | 0.175 | 0.689 | 0.546 | **p50,p75,p90** | — |
| APP | 300 | 20 | 34.0 | 36.9 | 38.6 | 0.138 | 0.121 | 0.430 | 0.380 | **p50,p75,p90** | — |
| APP | 900 | 20 | 47.7 | 58.9 | 70.1 | 0.098 | 0.067 | 0.307 | 0.209 | **p50,p75,p90** | **p75,p90** |
| APP | 1800 | 20 | 62.8 | 72.9 | 89.3 | 0.074 | 0.052 | 0.233 | 0.164 | **p50,p75,p90** | **p50,p75,p90** |
| RMBS | 30 | 20 | 11.3 | 12.7 | 15.0 | 0.486 | 0.366 | 2.783 | 2.098 | — | — |
| RMBS | 120 | 20 | 22.8 | 25.9 | 30.8 | 0.242 | 0.179 | 1.387 | 1.026 | **p50,p75,p90** | — |
| RMBS | 300 | 20 | 31.7 | 38.7 | 44.1 | 0.174 | 0.125 | 0.995 | 0.717 | **p50,p75,p90** | — |
| RMBS | 900 | 20 | 47.3 | 54.0 | 68.2 | 0.117 | 0.081 | 0.668 | 0.463 | **p50,p75,p90** | — |
| RMBS | 1800 | 20 | 63.8 | 78.5 | 101.2 | 0.086 | 0.054 | 0.495 | 0.312 | **p50,p75,p90** | — |
| OLN…CROX | * | 10 | *(identical to pack-05 §3)* | | | | | | | | |

### 2.3 Material deltas vs pack-05 (APP/RMBS only)

| cell | Δσ med / p75 / p90 (bps) | ΔκP med | FEASIBLE-flag change |
|---|---|---|---|
| APP 30 | +0.50 / +0.04 / +0.45 | −0.020 | none |
| APP 120 | +0.20 / +1.04 / −0.01 | −0.002 | none |
| APP 300 | +0.19 / +1.56 / +1.75 | −0.001 | none |
| APP 900 | **+5.24 / +9.36 / +10.65** | −0.012 | T: p90 → **p75,p90** (opens) |
| APP 1800 | +2.17 / +5.76 / +11.74 | −0.003 | none (T already all-q) |
| RMBS 30 | −0.21 / +0.39 / +2.42 | +0.013 | none |
| RMBS 120 | +0.00 / +0.76 / +3.97 | +0.002 | none |
| RMBS 300 | +0.11 / +0.36 / +4.19 | +0.001 | none |
| RMBS 900 | −1.39 / +1.23 / +6.29 | +0.004 | none |
| RMBS 1800 | −4.34 / +6.52 / −10.71 | +0.006 | T: **p90 → closed** (κT p90 0.272 → 0.312) |

### 2.4 Open regions at κ ≤ 0.30 and at central κ ≈ 0.16

**At the 0.30 ceiling (median session, passive):** unchanged topology
vs pack-05 — H=30 closed universe-wide; H=120 open only {APP, RMBS};
H=300 open on {APP, RMBS, ENSG, DIOD, PCTY, CROX} (OLN at p75+; MLI
closed); H=900 and H=1800 open on all 8. Taker median-open only at
**APP H=1800** (κT 0.233); APP H=900 now opens at p75+ (was p90-only).

**At central κ ≈ 0.16 (median session, passive) — the honest screen:**

| symbol | open at median | notes |
|---|---|---|
| APP | ≥ 300 s | unchanged class; κP_300 med 0.138 |
| RMBS | ≥ 900 s | H=300 med 0.174 still closed; H=900 med 0.117 open |
| OLN | 1800 only | med 0.153; H=900 med 0.198 closed |
| DIOD | 1800 only | med 0.131; H=900 med 0.179 closed (p75 opens) |
| PCTY | 1800 only | med 0.140; H=900 med 0.181 closed |
| CROX | 1800 only | med 0.136; H=900 med 0.170 closed |
| ENSG | — at median | 1800 med 0.169; opens at p75 (0.156) |
| MLI | — at median | 1800 med 0.187; opens only at p90 (0.129) |

Taker at central κ: still closed everywhere (minimum κT anywhere =
APP 1800 p90 = 0.164 > 0.16).

---

## 3. Item-4 exclusion list — hold / fall after recompute

Retrospective §4 "pending map recompute" rows, now resolved against
this map (κ-class) or confirmed as pure session-count arithmetic
(power-class; map not required):

| slate-B exclusion | class | verdict after FQ-9 |
|---|---|---|
| H=900 tail conditioning jointly unsatisfiable on {APP, RMBS} | power (+ κ contingent) | **DOES NOT HOLD** — confirmed. 25 × 20 = 500/symbol; decile-tail 0.20 ⇒ 100/symbol (exactly the floor); gate×warm (0.90×0.95) ⇒ ≈ 85.5 (straddle from below). Pooled {APP ∪ RMBS} decile ⇒ 200. κ_req surfaces recomputed: APP/RMBS H=900 passive open at central κ (0.098 / 0.117). On the six non-expanded symbols the 10-session arithmetic **holds unchanged** (250 → fraction ≥ 0.40 for floor-100). |
| SCHEDULED_FLOW single-window ≪ power | power | **HOLDS** (20/symbol on APP/RMBS still 5× short of 100; six unchanged at 10). |
| SCHEDULED_FLOW algo-clock needs ≥ 0.83 fraction | power | **WEAKENED** (unchanged from §4.2 hand arithmetic: 240/symbol ⇒ fraction ≥ 0.417; κ-vs-fraction tension remains). Map does not alter this. |
| RMBS tail-episode exclusion (H6/H7 ≈ 33 → ≈ 66) | power | **HOLDS** (≈ 66 < 100; number still stale-as-stated but direction unchanged). |
| INVENTORY / HAWKES closed at honest κ; H=30 closed; taker closed at design; micro-price level-drift kill | κ-class (magnitude) | **HOLD.** APP/RMBS H=120 κP at every quantile still > 0.16 (APP best p90 0.175; RMBS 0.179). H=30 best cell APP p90 κP 0.366 — closed. Taker H=300 APP med κT 0.430 (≥ 1.5× above 0.30). Level-drift: honest κ ≈ 0.11 vs APP/300 p90 κP **0.121** (was 0.127) — still fails. |
| H6/H7 design-central ≈ 52 < 100 | power | **DOES NOT HOLD** as computed (retrospective §4.5: ≈ 104 on 20-session basis). Revival still requires a NEW drafted variant per pack-06 DISPOSITIONS 2 — not authorized by this map. |

---

## 4. H ∈ {900, 1800} density basis

**Convention (pack-06 §0 / measured `n_returns`):** in-window boundaries
per session = 25 (H=900), 12 (H=1800). Two-sided conditioning
fractions: **decile-tail = 0.20**, **quintile-tail = 0.40**. Optional
slate multipliers gate × warm = 0.90 × 0.95 shown as `_gw`. Floor =
100 episodes/symbol (power bar). **No outcome statistic.**

### 4.1 Current cache

| symbol | sess | H | raw | decile | quintile | decile_gw | vs floor (decile / quintile) |
|---|---|---|---|---|---|---|---|
| APP | 20 | 900 | 500 | **100** | 200 | 85.5 | =100 / ≥100 (gw straddles below) |
| APP | 20 | 1800 | 240 | 48 | 96 | 41.0 | **<100 / <100** |
| RMBS | 20 | 900 | 500 | **100** | 200 | 85.5 | =100 / ≥100 (gw straddles below) |
| RMBS | 20 | 1800 | 240 | 48 | 96 | 41.0 | **<100 / <100** |
| each of six | 10 | 900 | 250 | 50 | **100** | 42.8 | <100 / =100 (gw 85.5 below) |
| each of six | 10 | 1800 | 120 | 24 | 48 | 20.5 | **<100 / <100** |

Pooled current:

| pool | H | raw | decile | quintile | decile_gw |
|---|---|---|---|---|---|
| APP ∪ RMBS | 900 | 1000 | 200 | 400 | 171.0 |
| APP ∪ RMBS | 1800 | 480 | 96 | 192 | 82.1 |
| six (10 each) | 900 | 1500 | 300 | 600 | 256.5 |
| six (10 each) | 1800 | 720 | 144 | 288 | 123.1 |

### 4.2 Projected if 60 DRAWN-NOT-INGESTED cells ingested

Each of the six → 20 sessions (APP/RMBS already at 20). Per-symbol
projected:

| symbol | H | raw | decile | quintile | decile_gw | vs floor (decile / quintile) |
|---|---|---|---|---|---|---|
| each of six | 900 | 500 | **100** | 200 | 85.5 | =100 / ≥100 (gw straddles) |
| each of six | 1800 | 240 | 48 | 96 | 41.0 | **still <100 / <100** |
| APP, RMBS | * | *(unchanged — already ingested)* | | | | |

Pooled projected:

| pool | H | raw | decile | quintile | decile_gw |
|---|---|---|---|---|---|
| six (20 each) | 900 | 3000 | 600 | 1200 | 513.0 |
| six (20 each) | 1800 | 1440 | 288 | 576 | 246.2 |
| all 8 (20 each) | 900 | 4000 | 800 | 1600 | 684.0 |
| all 8 (20 each) | 1800 | 1920 | 384 | 768 | 328.3 |

**Density arithmetic summary (no recommendation):** per-symbol
decile-tail at H=900 hits the floor exactly at 20 sessions and
straddles below it under gate×warm; at H=1800, even quintile-tail
at 20 sessions is 96 < 100 per symbol — pooling is required for any
H=1800 tail-conditioned design to clear 100 on this boundary basis.

---

## 5. Ingestion decision table (six DRAWN-NOT-INGESTED symbols)

Arithmetic only — **ingestion call is Lei's.** Each row is 10 cells
(the ratified expansion dates). Cost reference: 03c A1.3 ingested 20
{APP, RMBS} cells in ~6 min wall on the platform path; 60 cells is
3× that cell count under the same bar (health, guards, ex-date check).

| symbol | honest-κ deployability @900 (med) | honest-κ deployability @1800 (med) | pooling-only / evidence value | ingestion cost | HOLIDAY-THIN / L5 notes |
|---|---|---|---|---|---|
| OLN | closed (κP 0.198); p90 opens (0.154) | **open** (0.153) | H=900: 50→100 decile episodes if ingested (per-symbol floor contact); adds to any multi-symbol pool. Tick-discreteness caveat carries (half-tick ≈ 2.1 bps). | 10 cells | HOLIDAY-THIN dates `2025-12-26`, `2025-12-30` would inherit the A1.4 tag (never exclude). L5 elevated-A week concentration applies once expansion dates join. |
| ENSG | closed (0.221); no central-κ quantile open at 900 | closed at med (0.169); **p75 opens** (0.156) | Same H=900 decile 50→100 lift; weakest central-κ median of the six at 1800. | 10 cells | same HOLIDAY-THIN + L5 |
| DIOD | closed (0.179); p75 opens (0.129) | **open** (0.131) | Same density lift; wide half-spread (15.8 bps) → taker floor 43.0 bps (taker irrelevant at central κ anyway). | 10 cells | same HOLIDAY-THIN + L5 |
| PCTY | closed (0.181); p90 opens (0.135) | **open** (0.140) | Same density lift. | 10 cells | same HOLIDAY-THIN + L5; quote-indicator-2 disposition (03b/V-3) already admissible |
| MLI | closed all-q at 0.16 (best p90 0.181) | closed at med/p75; **p90 only** (0.129) | Density lift identical; **least** honest-κ deployable of the six at both horizons. Pooling is the only path that uses MLI at central κ without a session-tail park rule. | 10 cells | same HOLIDAY-THIN + L5 |
| CROX | closed (0.170); p90 opens (0.119) | **open** (0.136) | Same density lift; among the stronger 1800 median cells of the six. | 10 cells | same HOLIDAY-THIN + L5 |

**Cross-cutting arithmetic (still not a recommendation):**

- Ingesting any subset of the six does **not** change APP/RMBS σ or κ
  (already at 20). It only extends the thin symbols' own maps and any
  pooled evidence set.
- H=1800 per-symbol power remains below 100 under both tail fractions
  even after full 60-cell ingest; H=900 per-symbol decile lands on the
  floor.
- Vendor V-1 (T5-OQ-3) still caps any *new* date draw at pre-2026-04-27;
  these 60 cells are already ratified inside that cap — ingestion does
  not require a new draw.

---

## 6. Operative rule (slate C pre-filter)

Pack-05 §6 stands, with this file as the σ-side surface:

> A hypothesis card may enter slate ranking only if its (mechanism
> family × horizon × symbol set × execution variant) intersects a
> FEASIBLE region of §2 **at the card's own derived κ** (falling back
> to the 0.30 ceiling only when the card has no derivation yet, and
> saying so).

Density (§4) remains a separate pre-filter; the H=900 {APP, RMBS}
decile-tail case is now a measurable straddle, not a closure. N is
unchanged by this task.

---

## 7. Determinism and provenance (FQ-3)

```yaml
os: "Windows 11 (win32 10.0.26200)"
cpu_arch: "AMD64"
python_build: "3.14.2 (tags/v3.14.2:df79316, Dec 5 2025, 17:18:21) [MSC v.1944 64 bit (AMD64)]"
libm: "Microsoft UCRT (linked by MSC v.1944; platform.libc_ver() = ('', '') on Windows)"
git_sha: "e1201404b9f2c4966cd451baf03fb1aaf258a055"  # HEAD at task start
config_checksum: "n/a — no PlatformConfig loaded; direct DiskEventCache read"
pythonhashseed: "0 (set in session for every scripted run)"
worktree_clean: "yes at task start for research outputs; script edit +
  this record + artifact are the only outputs"
command: "PYTHONHASHSEED=0 uv run python
  scripts/research/horizon_feasibility_map.py --json
  docs/research/artifacts/horizon_feasibility_map_operative_2026-07-15.json"
artifact: "docs/research/artifacts/horizon_feasibility_map_operative_2026-07-15.json
  sha256=981cf7e3dd2c4d5e812080605cb7c696403536b7fe8918e81dfef8d602874b08"
determinism: "full-grid rerun bit-identical (SHA-256 equal on both runs)"
script: "scripts/research/horizon_feasibility_map.py (operative session
  set: 20 for APP/RMBS, 10 for others; already registered in
  docs/prompts/README.md coverage map, research_validation)"
n_cells: 100
normative_inputs: "prompt_pack_05_horizon_feasibility_map.md (+ FQ-8
  artifact), prompt_pack_07_program_retrospective.md §4 (exclusion
  list), prompt_pack_03c_universe_and_cache.md AMENDMENT 1 (operative
  grid, DRAWN-NOT-INGESTED, HOLIDAY-THIN, L5), prompt_pack_06 §0
  (H=900 in-window = 25 convention), inventory_fade_census.py
  estimator, 00c cost pins, G16 envelopes"
multiple_testing_ledger: "N = 11, unchanged — census-class map; no
  hypothesis evaluated"
```

*Task FQ-9 stops here. Status: NORMATIVE. Lei decides ingestion scope;
slate C launches on this map.*
