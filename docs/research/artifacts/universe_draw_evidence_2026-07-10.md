# Universe Draw Evidence — Frozen Evidence Grid of 2026-07-10

<!-- File: docs/research/artifacts/universe_draw_evidence_2026-07-10.md
     Status: EVIDENCE-ARTIFACT (immutable once committed)
     Owner: Lei -->

Assembled verbatim from the two runner turns that produced the frozen
evidence-grid calendar referenced by prompt_pack_03c's UNIVERSE_DECISION:
Part A is the first turn (Steps 1–2 complete, mechanical STOP at Step 3);
Part B is the Lei-approved amendment resolving the STOP; Part C is the second
turn (Steps 3–7 executed under the amended rules). Nothing below this
preamble has been edited, summarized, or reformatted.

---

## Part A — Steps 1–2 and the Step-3 STOP report (first runner turn, verbatim)

## STOP at Step 3 — the calm band can't supply two windows from this span's realized data

Steps 1 and 2 are complete and mechanical, no judgment calls. Step 3 hits a real structural conflict between the window definition in Step 2 and the "two windows, different months" requirement in Step 3, given what the data actually did over this span. Per the task's own instruction — STOP and report rather than substitute a method — I'm not picking a resolution. Steps 4–7 are not run.

---

### STEP 1 — SPY RV20 distribution (admissible span, 2025-11-03 → 2026-04-24, n=119 sessions)

Pulled `/v2/aggs/ticker/SPY/range/1/day/2025-09-25/2026-04-24`, `adjusted=true`, to seed a 20-session trailing window before the span starts. `rv20(t) = sqrt(252) × sample_stdev(log-returns, trailing 20 sessions incl. t) × 100`, sample stdev (n−1), linear-interpolation percentile method (not specified in the task — flagging the convention, not asking permission, since it's a standard default).

| Stat | Value | Date |
|---|---|---|
| min | 6.966% | 2026-01-16 |
| 30th pct | 11.617% | interpolated (rank 36/37: 11.574 / 11.681) |
| median | 12.966% | 2026-02-26 |
| 70th pct | 14.296% | interpolated (rank 83/84: 14.281 / 14.306) |
| max | 20.672% | 2026-04-09 |

calm = rv20 < 11.617; elevated = rv20 > 14.296; both bands realized within-span, no fallback needed for band definition itself.

### STEP 2 — Full contiguous-run inventory (band, start, end, length, rv20 range)

| Band | Start | End | Length | rv20 range | Qualifies (≥5)? |
|---|---|---|---|---|---|
| elevated | 2025-11-03 | 2025-11-06 | 4 | 14.757–15.748 | No |
| mid | 2025-11-07 | 2025-11-20 | 10 | — | n/a |
| **elevated** | **2025-11-21** | **2025-12-04** | **9** | **14.332–15.379** | **Yes** |
| mid | 2025-12-05 | 2025-12-15 | 7 | — | n/a |
| calm | 2025-12-16 | 2025-12-16 | 1 | 11.545 | No |
| mid | 2025-12-17 | 2025-12-18 | 2 | — | n/a |
| **calm** | **2025-12-19** | **2026-02-05** | **32** | **6.966–11.410** | **Yes — only calm run in span** |
| mid | 2026-02-06 | 2026-02-11 | 4 | — | n/a |
| elevated | 2026-02-12 | 2026-02-12 | 1 | 14.327 | No |
| mid | 2026-02-13 | 2026-02-13 | 1 | — | n/a |
| elevated | 2026-02-17 | 2026-02-17 | 1 | 14.306 | No |
| mid | 2026-02-18 | 2026-03-09 | 14 | — | n/a |
| calm | 2026-03-10 | 2026-03-11 | 2 | 11.513–11.525 | No |
| mid | 2026-03-12 | 2026-03-12 | 1 | — | n/a |
| calm | 2026-03-13 | 2026-03-13 | 1 | 11.574 | No |
| mid | 2026-03-16 | 2026-03-25 | 8 | — | n/a |
| **elevated** | **2026-03-26** | **2026-04-24** | **21** | **14.417–20.672** | **Yes** |

**Qualifying runs total: 3.** Elevated: exactly 2, in different calendar-month pairs (Nov–Dec and Mar–Apr) — Step 3's elevated requirement is satisfiable cleanly, no issue. Calm: exactly 1, spanning three calendar months (Dec/Jan/Feb) internally, but it is a single inventory entry, not two.

### The blocker

Step 3 requires "select TWO calm... windows... in different calendar months," drawn from the Step-2 inventory. The inventory has one calm entry. The pre-registered fallback in Step 2 covers the case of *zero* qualifying runs at the percentile bar ("apply fallback... symmetrically for calm") — it does not cover *exactly one* qualifying run when two are required. That's a gap between what Step 2 defines ("window" = maximal contiguous run) and what Step 3 assumes (two distinct such runs will exist per band), and this span's realized volatility structure — one long calm stretch bracketed by two separate elevated episodes — doesn't fit that assumption.

I see three genuinely different ways to resolve it, and they're not equivalent — each changes what "calm regime" ends up meaning in the frozen grid:

1. **Split the single 32-session calm run into two sub-windows by calendar month** (e.g., a December sub-window and a January/February sub-window). This satisfies "different calendar months" but requires a splitting rule the task doesn't specify (split at month boundary? at the run's midpoint? which gets the 3-session vs 2-session draw?).
2. **Relax the run-length or percentile threshold** to see if a second, genuinely separate calm episode exists elsewhere in the span at a slightly less extreme cutoff — changes the definition of "calm" for both bands, not just this one gap.
3. **Accept one calm window** and revisit whether "two per band" is the right requirement for this span, vs. two elevated + one calm + a compensating rule.

I haven't touched the 8 symbols' price data, done any idiosyncratic screening, or drawn any dates — Steps 4–7 depend on this call. Data-pull provenance: `/v2/aggs/ticker/SPY/range/1/day/2025-09-25/2026-04-24`, `adjusted=true`, pulled this session (2026-07-09); no intraday or outcome/signal/PnL data was touched at any point.

---

## Part B — Lei-approved amendment resolving the Step-3 STOP (verbatim)

RESUME — STEPS 3–7 UNDER AMENDED RULES (approved by Lei). Steps 1–2 stand as
reported; the linear-interpolation percentile convention is approved — record
it in the evidence appendix. Do not recompute rv20.

STEP 3 (amended):
- ELEVATED: proceed as originally specified. The two qualifying runs
  (2025-11-21→2025-12-04 and 2026-03-26→2026-04-24) are the two elevated
  windows; different months satisfied; no fallback fired.
- CALM: the span contains exactly ONE qualifying calm run (2025-12-19→
  2026-02-05, 32 sessions). Pre-registered resolution: treat it as a SINGLE
  episode. Do NOT relax the percentile band; do NOT split at month
  boundaries. The two-window requirement is replaced for the calm band by
  the even-spacing draw in Step 4, which serves the same dispersion
  objective. Record in the output: "calm stratum = one episode (structural
  fact of the admissible span); external-validity limitation pre-registered
  — Task 8's calm-stratum definition must carry this note."

STEP 4 (amended draw rules):
- CALM (single run, N sessions): draw 5 dates at session indices
  round_half_up(1 + (k−1)·(N−1)/4) for k = 1..5 — i.e. for N=32: sessions
  1, 9, 17, 24, 32. Half-day drops and redraws per Step 6 as written (each
  redraw hop re-screens under Step 5).
- ELEVATED: unchanged — 3 from the longer run (first, middle, last), 2 from
  the shorter (first, last); half-day drops and redraws per Step 6.

STEP 5: unchanged. Reminder of the band-specific screen: calm dates — ANY
symbol tripping ≥5% ⇒ exclude and redraw (a ≥4-symbol co-move on a calm date
is additionally flagged as a classification contradiction); elevated dates —
1–3 trips ⇒ exclude and redraw, ≥4 trips ⇒ SYSTEMIC, retain and document.

STEP 6: unchanged, with one clarification for the calm band: replacements
step inward/outward from the excluded slot within the SINGLE calm run; the
"promote the next eligible run" clause cannot apply to calm (there is none)
— if the calm run somehow exhausts, STOP and report.

STEP 7 (one addition): add a HOLIDAY-THIN tag for any drawn session in the
2025-12-24 → 2026-01-02 belt (tags never exclude). All other tags and the
≥4-untagged-cells-per-stratum floor check as written.

OUTPUT: as originally specified (YAML fragments + redraw log + tags +
evidence appendix), plus the calm single-episode limitation note in the
volatility_regime_windows fragment. Then stop — Lei reviews before freeze.

---

## Part C — Steps 3–7 executed under amended rules (second runner turn, verbatim)

## Steps 3–7 executed under amended rules

### 1. `volatility_regime_windows`

```yaml
volatility_regime_windows:
  - name: regime_elevated_A
    range: [2025-11-21, 2025-12-04]
    basis: "SPY 20-session realized vol, annualized, sample stdev, linear-interpolation percentiles"
    realized_rv20_range_pct: [14.332, 15.379]
    length_sessions: 9
    role: shorter_elevated_run
    sessions_drawn: [2025-11-25, 2025-12-04]
    draw_method: "first + last of shorter run; first (2025-11-21) excluded on screen, redrawn"

  - name: regime_elevated_B
    range: [2026-03-26, 2026-04-24]
    basis: "SPY 20-session realized vol, annualized, sample stdev, linear-interpolation percentiles"
    realized_rv20_range_pct: [14.417, 20.672]
    length_sessions: 21
    role: longer_elevated_run
    sessions_drawn: [2026-04-01, 2026-04-10, 2026-04-22]
    draw_method: "first/middle/last of longer run; first (2026-03-26) and last (2026-04-24) excluded on screen, redrawn"

  - name: regime_calm
    range: [2025-12-19, 2026-02-05]
    basis: "SPY 20-session realized vol, annualized, sample stdev, linear-interpolation percentiles"
    realized_rv20_range_pct: [6.966, 11.410]
    length_sessions: 32
    role: single_calm_episode
    sessions_drawn: [2025-12-22, 2026-01-05, 2026-01-15, 2026-01-26, 2026-01-27]
    draw_method: "even-spacing indices 1,9,17,24,32 of the 32-session run (round_half_up(1+(k-1)*31/4)); 4 of 5 initial slots excluded on screen and redrawn per Step 6"
    limitation_note: >
      Calm stratum = one episode (structural fact of the admissible span: the
      entire 2025-11-03 to 2026-04-24 window contains exactly one contiguous
      calm-band run of >=5 sessions, versus two separate elevated runs).
      External-validity limitation pre-registered per Lei's Step-3 amendment —
      Task 8's calm-stratum definition must carry this note: dispersion across
      the calm stratum comes from even-spacing within a single regime episode,
      not from two independent episodes, unlike the elevated stratum.
```

### 2. `idiosyncratic_event_screen`

```yaml
idiosyncratic_event_screen:
  threshold: "abs(adjusted close-to-close return) >= 5%, any of the 8 symbols"
  scope: "price data only; filings/earnings-calendar endpoint stays banned per 2026-07-09 finding"
  calm_rule: "ANY trip (1-8 symbols) => exclude and redraw; >=4-symbol co-move additionally flagged as a classification contradiction"
  elevated_rule: "1-3 trips => exclude and redraw; >=4 trips => classify SYSTEMIC, retain, document"
  systemic_exception_rule_applied: "not triggered this draw — no candidate date (drawn or redraw-hop) reached >=4 tripping symbols"
  classification_contradictions_flagged: "none — no calm-date candidate reached >=4 trips"

  excluded_dates:
    - {date: 2025-11-21, band: elevated, trips: [DIOD: 5.62, OLN: 7.15]}
    - {date: 2026-03-26, band: elevated, trips: [APP: -10.41]}
    - {date: 2026-04-24, band: elevated, trips: [RMBS: 14.37]}
    - {date: 2025-12-19, band: calm, trips: [RMBS: 5.36]}
    - {date: 2026-01-02, band: calm, trips: [APP: -8.24, RMBS: 8.04]}
    - {date: 2026-01-14, band: calm, trips: [APP: -7.61, RMBS: 5.38]}
    - {date: 2026-02-05, band: calm, trips: [ENSG: 13.85, OLN: -7.98]}
    # also excluded as redraw-hop candidates before landing on final replacements:
    - {date: 2025-11-24, band: elevated, trips: [APP: 7.60, RMBS: 5.22], context: "hop candidate for 2025-11-21"}
    - {date: 2026-03-27, band: elevated, trips: [PCTY: -5.08], context: "hop candidate for 2026-03-26"}
    - {date: 2026-03-30, band: elevated, trips: [DIOD: -5.67, RMBS: -11.14], context: "hop candidate for 2026-03-26"}
    - {date: 2026-03-31, band: elevated, trips: [APP: 6.97, DIOD: 6.11, RMBS: 7.90], context: "hop candidate for 2026-03-26"}
    - {date: 2026-04-23, band: elevated, trips: [APP: -6.11, RMBS: 5.28], context: "hop candidate for 2026-04-24"}
    - {date: 2026-02-04, band: calm, trips: [APP: -16.12, MLI: -7.28, OLN: 10.95], context: "hop candidate for 2026-02-05"}
    - {date: 2026-02-03, band: calm, trips: [MLI: -11.16, PCTY: -6.13, RMBS: -13.42], context: "hop candidate for 2026-02-05"}
    - {date: 2026-02-02, band: calm, trips: [OLN: 6.54], context: "hop candidate for 2026-02-05"}
    - {date: 2026-01-30, band: calm, trips: [APP: -16.89, OLN: -6.85, RMBS: -6.39], context: "hop candidate for 2026-02-05"}
    - {date: 2026-01-29, band: calm, trips: [PCTY: -6.07], context: "hop candidate for 2026-02-05"}
    - {date: 2026-01-28, band: calm, trips: [RMBS: 7.54], context: "hop candidate for 2026-02-05"}

  systemic_retained: []   # none this draw
```

### 3. `redraw_log` (in order)

```yaml
redraw_log:
  - band: calm
    excluded: {date: 2025-12-19, idx: 1, trips: [RMBS: 5.36]}
    hops: [{date: 2025-12-22, idx: 2, result: clean, accepted: true}]
    replacement: 2025-12-22

  - band: calm
    excluded: {date: 2026-01-02, idx: 9, trips: [APP: -8.24, RMBS: 8.04]}
    hops: [{date: 2026-01-05, idx: 10, result: clean, accepted: true}]
    replacement: 2026-01-05

  - band: calm
    excluded: {date: 2026-01-14, idx: 17, trips: [APP: -7.61, RMBS: 5.38]}
    hops: [{date: 2026-01-15, idx: 18, result: clean, accepted: true}]
    replacement: 2026-01-15

  - band: calm
    excluded: {date: 2026-02-05, idx: 32, trips: [ENSG: 13.85, OLN: -7.98]}
    hops:
      - {date: 2026-02-04, idx: 31, result: "excluded (APP -16.12, MLI -7.28, OLN 10.95)"}
      - {date: 2026-02-03, idx: 30, result: "excluded (MLI -11.16, PCTY -6.13, RMBS -13.42)"}
      - {date: 2026-02-02, idx: 29, result: "excluded (OLN 6.54)"}
      - {date: 2026-01-30, idx: 28, result: "excluded (APP -16.89, OLN -6.85, RMBS -6.39)"}
      - {date: 2026-01-29, idx: 27, result: "excluded (PCTY -6.07)"}
      - {date: 2026-01-28, idx: 26, result: "excluded (RMBS 7.54)"}
      - {date: 2026-01-27, idx: 25, result: clean, accepted: true}
    replacement: 2026-01-27
    note: "7-hop walk, single-direction (t-1,t-2,...) since t+1..t+7 all invalid — index 32 is the run's last session, so only the inward/downward direction had valid candidates"

  - band: elevated
    run: shorter (2025-11-21 to 2025-12-04)
    excluded: {date: 2025-11-21, idx: 1, trips: [DIOD: 5.62, OLN: 7.15]}
    hops:
      - {date: 2025-11-24, idx: 2, result: "excluded (APP 7.60, RMBS 5.22)"}
      - {date: 2025-11-25, idx: 3, result: clean, accepted: true}
    replacement: 2025-11-25

  - band: elevated
    run: longer (2026-03-26 to 2026-04-24)
    excluded: {date: 2026-03-26, idx: 1, trips: [APP: -10.41]}
    hops:
      - {date: 2026-03-27, idx: 2, result: "excluded (PCTY -5.08)"}
      - {date: 2026-03-30, idx: 3, result: "excluded (DIOD -5.67, RMBS -11.14)"}
      - {date: 2026-03-31, idx: 4, result: "excluded (APP 6.97, DIOD 6.11, RMBS 7.90)"}
      - {date: 2026-04-01, idx: 5, result: clean, accepted: true}
    replacement: 2026-04-01

  - band: elevated
    run: longer (2026-03-26 to 2026-04-24)
    excluded: {date: 2026-04-24, idx: 21, trips: [RMBS: 14.37]}
    hops:
      - {date: 2026-04-23, idx: 20, result: "excluded (APP -6.11, RMBS 5.28)"}
      - {date: 2026-04-22, idx: 19, result: clean, accepted: true}
    replacement: 2026-04-22

no_exhaustion: true   # calm run never ran out of candidates; STOP condition not triggered
```

### 4. Tags on final 10 dates

```yaml
tags:
  opex: []              # no third-Friday expirations among final dates
  index_rebalance: []   # no S&P quarterly rebalance effective dates among final dates
  ex_dividend: []        # ENSG (2025-12-31, 2026-03-31), MLI (2025-12-05, 2026-03-13),
                         # OLN (2025-11-28, 2026-03-03) all checked — none coincide with final grid
  holiday_thin: []       # none of the 5 calm dates fall in 2025-12-24 -> 2026-01-02
                         # (closest is 2025-12-22, two sessions before the belt starts)

untagged_cell_floor_check:
  status: PASS
  detail: "zero tags fired on the final grid, so all 8 symbols retain 5/5 untagged cells per regime — floor of >=4 trivially satisfied"
```

### 5. Evidence appendix

**Steps 1–2:** stand as previously reported and approved (rv20 distribution: min 6.966%, p30 11.617%, median 12.966%, p70 14.296%, max 20.672%; sample-stdev/linear-interpolation convention recorded per Lei's note). Full run inventory as previously reported — restated here only for the three qualifying runs since those are what feed Steps 3–7.

**Per-drawn-date and per-hop screen table** (8 symbols × return %, ≥5% trips bolded) — this is the complete set of candidates actually touched during the draw and redraw process:

| Date | APP | RMBS | OLN | ENSG | DIOD | PCTY | MLI | CROX | Trips |
|---|---|---|---|---|---|---|---|---|---|
| 2025-11-21 | -0.11 | 1.00 | **7.15** | 3.15 | **5.62** | 3.51 | 1.97 | 3.73 | 2 |
| 2025-11-24 | **7.60** | **5.22** | — | — | — | — | — | — | 2 |
| 2025-11-25 | — | — | — | — | — | — | — | — | 0 (clean) |
| 2025-12-04 | 3.26 | 0.80 | -4.71 | -0.59 | 0.70 | 0.34 | 1.27 | -1.24 | 0 (clean) |
| 2025-12-19 | 3.89 | **5.36** | -0.88 | 2.51 | 0.08 | 0.76 | 2.50 | -0.17 | 1 |
| 2025-12-22 | — | — | — | — | — | — | — | — | 0 (clean) |
| 2026-01-02 | **-8.24** | **8.04** | 3.46 | -0.16 | 4.24 | -4.46 | 1.75 | 1.67 | 2 |
| 2026-01-05 | — | — | — | — | — | — | — | — | 0 (clean) |
| 2026-01-14 | **-7.61** | **5.38** | 2.36 | -0.16 | 2.86 | -2.98 | 2.03 | -2.14 | 2 |
| 2026-01-15 | — | — | — | — | — | — | — | — | 0 (clean) |
| 2026-01-26 | 2.10 | -0.97 | -1.67 | 1.53 | 0.67 | -0.23 | 0.82 | -2.16 | 0 (clean) |
| 2026-01-27 | — | — | — | — | — | — | — | — | 0 (clean) |
| 2026-01-28 | — | **7.54** | — | — | — | — | — | — | 1 |
| 2026-01-29 | — | — | — | — | — | **-6.07** | — | — | 1 |
| 2026-01-30 | **-16.89** | **-6.39** | **-6.85** | — | — | — | — | — | 3 |
| 2026-02-02 | — | — | **6.54** | — | — | — | — | — | 1 |
| 2026-02-03 | — | **-13.42** | — | — | — | **-6.13** | **-11.16** | — | 3 |
| 2026-02-04 | **-16.12** | — | **10.95** | — | — | — | **-7.28** | — | 3 |
| 2026-02-05 | -3.13 | -2.72 | **-7.98** | **13.85** | 0.73 | 0.32 | 0.53 | -2.61 | 2 |
| 2026-03-26 | **-10.41** | -4.68 | 2.00 | -0.93 | -3.36 | 1.30 | -2.23 | -0.19 | 1 |
| 2026-03-27 | — | — | — | — | — | **-5.08** | — | — | 1 |
| 2026-03-30 | — | **-11.14** | — | — | **-5.67** | — | — | — | 2 |
| 2026-03-31 | **6.97** | **7.90** | — | — | **6.11** | — | — | — | 3 |
| 2026-04-01 | — | — | — | — | — | — | — | — | 0 (clean) |
| 2026-04-10 | 3.23 | 4.60 | 1.94 | -1.26 | 0.95 | -0.08 | 0.24 | -2.15 | 0 (clean) |
| 2026-04-22 | — | — | — | — | — | — | — | — | 0 (clean) |
| 2026-04-23 | **-6.11** | **5.28** | — | — | — | — | — | — | 2 |
| 2026-04-24 | -1.29 | **14.37** | 2.10 | -0.10 | 3.98 | 2.11 | 0.21 | -1.82 | 1 |

**Data-pull provenance:** `/v2/aggs/ticker/{SPY,APP,RMBS,OLN,ENSG,DIOD,PCTY,MLI,CROX}/range/1/day/...`, `adjusted=true`, pulled 2026-07-10, covering 2025-11-14→2026-04-24 for the 8 symbols (buffer before 2025-11-21 for return calc) and 2025-09-25→2026-04-24 for SPY (unchanged from prior turn, not re-pulled). `/stocks/v1/dividends`, `ex_dividend_date.gte/lte` filters, `ticker.any_of=OLN,ENSG,MLI`, pulled 2026-07-10. No intraday, signal, PnL, or IC data was touched at any point in Steps 3–7.

**Observation for Lei, not a rule violation:** the calm stratum's final draw clusters on 2026-01-26/01-27, two adjacent sessions, purely as an artifact of the idx-32 redraw walking 7 hops backward through a contaminated late-Jan/early-Feb stretch. Worth knowing before freeze — it's a real consequence of how choppy this specific 8-symbol universe was even while SPY sat in its calmest stretch of the admissible span.
