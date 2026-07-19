# Universe Draw Expansion Evidence — +10 Shared Dates (2026-07-13)

<!-- File: docs/research/artifacts/universe_draw_expansion_evidence_2026-07-13.md
     Status: RATIFIED (Lei, 2026-07-13) — C1–C3 conventions upheld, no veto;
             {APP,RMBS} × 10 cells ingested same day (see
             prompt_pack_03c_universe_and_cache.md AMENDMENTS);
             remaining 6 symbols registered DRAWN-NOT-INGESTED
     Owner: Lei -->

Grid-expansion draw (+10 shared dates; one-shot; Lei-authorized 03c
amendment). This artifact extends — and references, but never modifies —
the frozen draw evidence at
`docs/research/artifacts/universe_draw_evidence_2026-07-10.md` ("the
original artifact") and the closed-list inventory in
`docs/research/prompt_pack_03c_universe_and_cache.md` (§1(f): additions
after Task 8 freeze require a protocol amendment — this draw is that
amendment's evidence package, authorized by Lei, effective only after
Lei's review of the dates below; **no ingestion happens in this task**).

Steps 1–2 of the original procedure are NOT recomputed: the SPY rv20
series, band thresholds (calm < 11.617, elevated > 14.296), and the
run inventory are inherited verbatim from the original artifact. The
three qualifying windows are unchanged:

- calm: 2025-12-19 → 2026-02-05 (32 sessions)
- elevated shorter: 2025-11-21 → 2025-12-04 (9 sessions)
- elevated longer: 2026-03-26 → 2026-04-24 (21 sessions)

Part A below was written and saved to disk BEFORE any price data was
pulled this session (the only data consulted for Part A is the original
artifact itself and the public NYSE holiday/half-day calendar). Parts
B–D record execution.

---

## Part A — PRE-REGISTRATION (no price data touched)

### A.1 Session-index calendars for the three runs

Index→date mappings derived from the NYSE trading calendar; every index
marked † is anchored verbatim to an (idx, date) pair recorded in the
original artifact's redraw log or draw list — 15/32 calm, 4/9 shorter,
9/21 longer anchors, which pin the calendar (including the half-day
counting convention: 2025-12-24 = calm idx 4 and 2025-11-28 = shorter
idx 5 count as sessions, confirmed by the idx-9† anchors of both runs).
Precedence rule: indices are primary; if the pulled daily-bar calendar
in Part B contradicts a derived (non-anchored) date, the index governs
and the correction is reported.

Calm (32): 1 2025-12-19†, 2 2025-12-22†, 3 2025-12-23, 4 2025-12-24
(HALF-DAY), 5 2025-12-26, 6 2025-12-29, 7 2025-12-30, 8 2025-12-31,
9 2026-01-02†, 10 2026-01-05†, 11 2026-01-06, 12 2026-01-07,
13 2026-01-08, 14 2026-01-09, 15 2026-01-12, 16 2026-01-13,
17 2026-01-14†, 18 2026-01-15†, 19 2026-01-16, 20 2026-01-20,
21 2026-01-21, 22 2026-01-22, 23 2026-01-23, 24 2026-01-26†,
25 2026-01-27†, 26 2026-01-28†, 27 2026-01-29†, 28 2026-01-30†,
29 2026-02-02†, 30 2026-02-03†, 31 2026-02-04†, 32 2026-02-05†.

Elevated shorter (9): 1 2025-11-21†, 2 2025-11-24†, 3 2025-11-25†,
4 2025-11-26, 5 2025-11-28 (HALF-DAY), 6 2025-12-01, 7 2025-12-02,
8 2025-12-03, 9 2025-12-04†.

Elevated longer (21): 1 2026-03-26†, 2 2026-03-27†, 3 2026-03-30†,
4 2026-03-31†, 5 2026-04-01†, 6 2026-04-02, 7 2026-04-06, 8 2026-04-07,
9 2026-04-08, 10 2026-04-09, 11 2026-04-10†, 12 2026-04-13,
13 2026-04-14, 14 2026-04-15, 15 2026-04-16, 16 2026-04-17,
17 2026-04-20, 18 2026-04-21, 19 2026-04-22†, 20 2026-04-23†,
21 2026-04-24†.

### A.2 Ineligibility sets (task rule: already-drawn and already-excluded
dates are ineligible; half-days drop; run bounds bind)

- Originally DRAWN (10, final grid): 2025-11-25, 2025-12-04,
  2025-12-22, 2026-01-05, 2026-01-15, 2026-01-26, 2026-01-27,
  2026-04-01, 2026-04-10, 2026-04-22.
- Originally EXCLUDED (18, incl. redraw-hop exclusions, from the
  original `excluded_dates` list): 2025-11-21, 2025-11-24, 2025-12-19,
  2026-01-02, 2026-01-14, 2026-01-28, 2026-01-29, 2026-01-30,
  2026-02-02, 2026-02-03, 2026-02-04, 2026-02-05, 2026-03-26,
  2026-03-27, 2026-03-30, 2026-03-31, 2026-04-23, 2026-04-24.
- HALF-DAYS in-run: 2025-12-24 (calm idx 4), 2025-11-28 (shorter idx 5).
- Plus: dates assigned to any expansion slot in A.4, and dates accepted
  by an earlier expansion walk (processing order in C4 below).

Untouched calm indices (neither drawn nor excluded):
{3,4,5,6,7,8,11,12,13,14,15,16,19,20,21,22,23}. Untouched shorter:
{4,5,6,7,8}. Untouched longer: {6,7,8,9,10,12,13,14,15,16,17,18}.

### A.3 Pre-registered conventions (flagged for Lei veto at review —
recording the convention, not asking permission, per the Part-A
precedent of the original draw)

- **C1 (midpoint arithmetic).** midpoint(a, b) = floor((a + b) / 2).
  This matches the task's own enumeration: the calm gap (17, 24) has
  midpoint 20.5 and the task pre-registers index 20 — floor, not the
  Step-4 round_half_up. Applied uniformly to all midpoints here.
  Discrepancy with the original Step-4 rounding convention is noted
  honestly; the task's explicit {5,13,20,28} governs.
- **C2 (tie-break for "largest remaining untouched gap").** Earliest
  (lowest-index) gap wins. Deterministic; no data dependence.
- **C3 (elevated anchor slots).** "Originally drawn/excluded slots" =
  the original Step-4 draw POSITIONS — shorter {1, 9} (first/last),
  longer {1, 11, 21} (first/middle/last) — each of which was either
  drawn clean or excluded-and-redrawn. This follows the original
  artifact's vocabulary, where "slot" always means a Step-4 position
  ("replacements step inward/outward from the excluded slot") and hop
  candidates are never called slots. Midpoints between consecutive
  anchor slots supply 1 (shorter) and 2 (longer) indices; each run's
  quota (2 and 3) is completed by the same "largest remaining untouched
  gap midpoint" top-up the task's calm clause specifies — the exact
  structural parallel of calm's 4 midpoints + 1 top-up = 5.
  *Alternative reading rejected:* anchoring on ALL originally touched
  dates (slots + hops) would give shorter {6}, longer {8, 15} + top-ups
  — recorded so Lei can veto C3 with full information.
- **C4 (redraw walk).** From an invalid/excluded slot, candidates
  alternate +1, −1, +2, −2, … in session-index space, clamped to run
  bounds. Ineligible candidates (A.2) are SKIPPED WITHOUT SCREENING and
  logged as skips; eligible candidates are screened in walk order;
  first clean candidate is accepted. This reproduces every walk in the
  original redraw log (idx-1 → +1; idx-32 → effectively single-direction
  backward, as its note states). Processing order: calm slots ascending,
  then shorter ascending, then longer ascending. If a walk exhausts the
  run, REPORT THE SHORTFALL — no relaxation.
- **C5 (gap geometry).** Half-day sessions count as untouched sessions
  for gap geometry (consistent with the original indexation) but are
  ineligible to draw (Step-6 half-day drop).
- **C6 (top-up inventory).** All slots are fixed by index arithmetic
  first (this section), removing each slot at its pre-registered index
  from the untouched inventory; walks execute afterward. Top-up
  midpoints therefore never depend on screen outcomes.

### A.4 Pre-registered expansion slots (fixed before any data)

**Calm — task-enumerated {5, 13, 20, 28} + top-up.**
Gap midpoints of original indices {1,9,17,24,32}: (1,9)→5, (9,17)→13,
(17,24)→20 (C1), (24,32)→28. Top-up: untouched inventory minus
{5,13,20} → gaps {3,4}, {6,7,8}, {11,12}, {14,15,16}, {19},
{21,22,23}; largest = size-3 three-way tie; C2 → {6,7,8}; midpoint 7.

| slot idx | date | status at pre-registration |
|---|---|---|
| 5 | 2025-12-26 | eligible — screen directly (holiday-thin belt) |
| 7 | 2025-12-30 | top-up; eligible — screen directly (holiday-thin belt) |
| 13 | 2026-01-08 | eligible — screen directly |
| 20 | 2026-01-20 | eligible — screen directly |
| 28 | 2026-01-30 | **ineligible (already excluded in original draw)** → immediate C4 walk |

Walk from calm slot 28 (candidate order, skips pre-determined):
+1→29 skip(excl), −1→27 skip(excl), +2→30 skip(excl), −2→26 skip(excl),
+3→31 skip(excl), −3→25 skip(drawn), +4→32 skip(excl), −4→24
skip(drawn), +5→33 invalid(out of run), −5→**23 (2026-01-23) SCREEN**;
if excluded continue −6→22, −7→21, −8→20 skip(slot), −9→19, −10→18
skip(drawn), −11→17 skip(excl), −12→16, −13→15, −14→14, −15→13
skip(slot), … until clean or exhaustion.

**Elevated shorter — anchor slots {1, 9} (C3).**
Midpoint (1,9)→5. Top-up: untouched {4,5,6,7,8} minus slot 5 → gaps
{4}, {6,7,8}; largest {6,7,8}; midpoint 7.

| slot idx | date | status at pre-registration |
|---|---|---|
| 5 | 2025-11-28 | **HALF-DAY** → immediate C4 walk |
| 7 | 2025-12-02 | top-up; eligible — screen directly |

Walk from shorter slot 5: +1→**6 (2025-12-01) SCREEN**; if excluded
−1→**4 (2025-11-26) SCREEN**; then +2→7 skip(slot), −2→3 skip(drawn),
+3→**8 (2025-12-03) SCREEN**, −3→2 skip(excl), +4→9 skip(drawn),
−4→1 skip(excl); exhaustion after idx 8 ⇒ shortfall report.

**Elevated longer — anchor slots {1, 11, 21} (C3).**
Midpoints (1,11)→6, (11,21)→16. Top-up: untouched
{6..10, 12..18} minus slots {6,16} → gaps {7,8,9,10}, {12,13,14,15},
{17,18}; largest = size-4 tie; C2 → {7,8,9,10}; midpoint floor(17/2)=8.

| slot idx | date | status at pre-registration |
|---|---|---|
| 6 | 2026-04-02 | eligible — screen directly |
| 8 | 2026-04-07 | top-up; eligible — screen directly |
| 16 | 2026-04-17 | eligible — screen directly (opex third Friday — tag-if-accepted; tags never exclude) |

Walks from any excluded longer slot follow C4 (e.g. from 6: +1→7, −1→5
skip(drawn), +2→8 skip(slot), −2→4 skip(excl), +3→9, −3→3 skip(excl),
+4→10, …).

### A.5 Screens — original Step-5, unchanged

- Threshold: abs(adjusted close-to-close return) ≥ 5%, ANY of the 8
  symbols (APP, RMBS, OLN, ENSG, DIOD, PCTY, MLI, CROX).
- Calm rule: ANY trip (1–8 symbols) ⇒ exclude and redraw; ≥4-symbol
  co-move additionally flagged as a classification contradiction.
- Elevated rule: 1–3 trips ⇒ exclude and redraw; ≥4 trips ⇒ SYSTEMIC,
  retain and document.
- Endpoint ban: price data only; the filings/earnings-calendar endpoint
  stays banned per the 2026-07-09 finding. This session pulls ONLY
  `/v2/aggs/ticker/{sym}/range/1/day/...` `adjusted=true` for the 8
  symbols (buffer from 2025-11-14 for prior-close; end 2026-04-24). No
  SPY pull (Steps 1–2 frozen). Ex-dividend reference is REUSED from
  03c §3.2 (pulled 2026-07-10): OLN 2025-11-28 / 2026-03-03, ENSG
  2025-12-31 / 2026-03-31, MLI 2025-12-05 / 2026-03-13, none for the
  other five in [2025-11-01, 2026-05-01] — no new dividends pull.
- Return convention: simple percent return (C_t/C_{t−1} − 1) × 100 on
  adjusted closes, presumed to match the original screen table; the
  overlap check (A.6) validates it empirically. If simple-return
  deviations exceed tolerance and log-return deviations do not, the
  convention finding is reported and the matching convention is used;
  if neither matches, STOP.

### A.6 Overlap validation (pre-registered acceptance)

Before any expansion screening, recompute returns for the original
screen table's fully-populated rows (2025-11-21, 2025-12-04, 2025-12-19,
2026-01-02, 2026-01-14, 2026-01-26, 2026-02-05, 2026-03-26, 2026-04-10,
2026-04-24 — 80 values) plus all bolded sparse-row trip values.
Tolerance: max abs deviation ≤ 0.05 percentage points (2-dp published
values + adjusted-history drift allowance). Any value out of tolerance
⇒ STOP and report (possible retroactive split/adjustment between
2026-07-10 and today); do not proceed to screening.

### A.7 Tags and floor check (original Step-7 + holiday-thin amendment)

- HOLIDAY-THIN: any accepted date in 2025-12-24 → 2026-01-02 (slots 5
  and 7 of calm are in the belt). Tags never exclude.
- opex: third Fridays in-run: 2026-01-16 (calm idx 19, walk-reachable),
  2026-04-17 (longer slot 16). index_rebalance: rebalance trade dates
  (third Friday of Dec/Mar) — 2025-12-19 (already excluded), 2026-03-20
  (not in any run) — cannot be drawn; convention follows the original
  artifact's outcome (2025-12-22 untagged there).
- ex_dividend: only walk-reachable in-run ex-date is ENSG 2025-12-31
  (calm idx 8). Tag if drawn; note for Lei that 03c §1(b) would exclude
  the ENSG cell at INGESTION stage — a draw-stage tag here, per the
  original convention (tags never exclude).
- Untagged-cell floor: recompute ≥4-untagged-cells-per-stratum floor
  over the combined 20-date grid (10 original + 10 expansion).

### A.8 Statistical accounting note

Grid expansion is data augmentation of the evidence grid — no
hypothesis is evaluated, no parameter variant tested; the
multiple-testing ledger N is unchanged by this task (consistent with
the original draw's accounting). All expansion dates are pre-2026-04-27
(admissibility amendment A holds by construction: latest reachable
index is longer idx 18 = 2026-04-21).

### A.9 STOP conditions

1. Overlap validation failure (A.6).
2. Any window exhausts its walk candidates before filling its quota ⇒
   report the shortfall; no threshold or rule relaxation.
3. Pulled calendar contradicts an ANCHORED index/date pair ⇒ STOP
   (would mean the frozen artifact and vendor data disagree).

*Pre-registration complete and saved before any price data pull.
Execution follows in Part B.*

---

## Part B — EXECUTION RECORD (2026-07-13)

### B.1 Data pull

`/v2/aggs/ticker/{APP,RMBS,OLN,ENSG,DIOD,PCTY,MLI,CROX}/range/1/day/`
`2025-11-14/2026-04-24`, `adjusted=true`, via `massive.RESTClient`
(constructed as `ingestion/massive_ingestor.py` builds it), pulled
2026-07-13, `PYTHONHASHSEED=0`. 110 daily bars per symbol; the 8
per-symbol calendars are identical (no missing-bar warnings). No SPY
pull, no dividends pull, no intraday/signal/PnL/IC data touched, no
banned endpoint touched.

### B.2 Calendar and anchor validation (A.1 / A.9-3)

Session counts from the pulled calendar: calm 32, shorter 9, longer 21
— all match the frozen run inventory. All 28 anchored (idx, date)
pairs match the derived calendars exactly. No STOP.

### B.3 Overlap validation (A.6)

All **102** original screen-table values recomputed under the simple
percent-return convention: **all within tolerance; max abs deviation
0.0049 pp** (OLN 2025-12-19: original −0.88, recomputed −0.8751).
Return convention confirmed = simple percent on adjusted closes; no
retroactive adjustment drift between the 2026-07-10 pull and today.
No STOP.

### B.4 Draw execution

All ten pre-registered slots processed in the C4 order. Outcome
summary (full log in Part C):

- 7 slots accepted on direct screen (calm 5, 7, 20; shorter 7; longer
  6, 8) or first walk hop (shorter 5 → idx 6).
- calm slot 13 (2026-01-08) excluded on screen; walk accepted idx 15
  (2026-01-12) on the 3rd screened hop.
- calm slot 28 (2026-01-30, pre-registered as already-excluded) walked
  per the A.4 skip sequence; first screened candidate idx 23
  (2026-01-23) excluded (RMBS −7.58); idx 22 (2026-01-22) accepted.
- longer slot 16 (2026-04-17) excluded on screen (RMBS 5.75, OLN
  −6.75); walk hop idx 17 (2026-04-20) excluded (CROX 5.03); idx 15
  (2026-04-16) accepted.

**Quotas: calm 5/5, elevated shorter 2/2, elevated longer 3/3 — NO
SHORTFALL.** No systemic (≥4-trip) day encountered; no calm
classification contradiction (no calm candidate reached 4 trips).

---

## Part C — OUTPUTS

### C.1 `volatility_regime_windows` expansion fragments

```yaml
volatility_regime_windows_expansion:   # 2026-07-13 draw; extends, never replaces, the 2026-07-10 fragments
  - name: regime_calm                  # same window as original artifact
    range: [2025-12-19, 2026-02-05]
    sessions_drawn_expansion: [2025-12-26, 2025-12-30, 2026-01-12, 2026-01-20, 2026-01-22]
    draw_method: >
      gap-midpoint indices {5,13,20,28} of the original even-spacing
      draw slots {1,9,17,24,32} (task-enumerated), plus largest
      remaining untouched gap midpoint (idx 7; three-way size-3 tie
      broken earliest per convention C2); floor-midpoint arithmetic
      per C1; slot 28 pre-registered ineligible (originally excluded)
      and redrawn per Step-6 walk (C4); slot 13 and the slot-28 walk
      candidate 2026-01-23 excluded on screen and redrawn
    limitation_note: >
      Single-calm-episode limitation L1 of the original draw carries
      unchanged — the expansion adds within-episode dispersion only.
      Expansion slots 5 and 7 (2025-12-26, 2025-12-30) sit in the
      holiday-thin belt (tagged HOLIDAY-THIN, tags never exclude).
      Combined calm stratum is now 10 sessions in one episode.

  - name: regime_elevated_A            # shorter run, same window
    range: [2025-11-21, 2025-12-04]
    sessions_drawn_expansion: [2025-12-01, 2025-12-02]
    draw_method: >
      midpoint of original Step-4 anchor slots {1,9} = idx 5
      (2025-11-28, half-day, dropped; Step-6 walk accepted idx 6),
      plus largest remaining untouched gap midpoint idx 7 (gap {6,7,8}
      after slot-5 removal; C1/C2/C6); anchor-slot reading per
      pre-registered convention C3
    adjacency_note: >
      2025-12-01/2025-12-02 are adjacent sessions — deterministic
      artifact of the half-day drop at idx 5 walking +1 into idx 6
      while the top-up sat at idx 7 (same class as original L2).

  - name: regime_elevated_B            # longer run, same window
    range: [2026-03-26, 2026-04-24]
    sessions_drawn_expansion: [2026-04-02, 2026-04-07, 2026-04-16]
    draw_method: >
      midpoints of original Step-4 anchor slots {1,11,21} = indices
      {6,16}, plus largest remaining untouched gap midpoint idx 8
      (size-4 tie {7..10}/{12..15} broken earliest); slot 16
      (2026-04-17, opex) excluded on screen; walk excluded idx 17
      (2026-04-20) then accepted idx 15 (2026-04-16)
```

### C.2 `idiosyncratic_event_screen` expansion fragment

```yaml
idiosyncratic_event_screen_expansion:
  threshold: "abs(adjusted close-to-close return) >= 5%, any of the 8 symbols"   # unchanged
  scope: "price data only; filings/earnings-calendar endpoint stays banned"      # unchanged
  calm_rule: unchanged
  elevated_rule: unchanged
  systemic_exception_rule_applied: "not triggered this expansion — no candidate reached >=4 tripping symbols"
  classification_contradictions_flagged: "none — no calm candidate reached >=4 trips"

  excluded_dates_expansion:
    - {date: 2026-01-08, band: calm, trips: [OLN: 5.27]}
    - {date: 2026-01-07, band: calm, trips: [RMBS: -5.52], context: "hop candidate for slot idx 13"}
    - {date: 2026-01-09, band: calm, trips: [APP: 5.06, OLN: 5.76], context: "hop candidate for slot idx 13"}
    - {date: 2026-01-23, band: calm, trips: [RMBS: -7.58], context: "walk candidate for slot idx 28"}
    - {date: 2026-04-17, band: elevated, trips: [RMBS: 5.75, OLN: -6.75]}
    - {date: 2026-04-20, band: elevated, trips: [CROX: 5.03], context: "hop candidate for slot idx 16"}

  systemic_retained: []   # none this expansion
```

### C.3 `redraw_log` expansion (in C4 processing order)

```yaml
redraw_log_expansion:
  - band: calm
    slot: {idx: 5, date: 2025-12-26}
    result: accepted clean, no redraw

  - band: calm
    slot: {idx: 7, date: 2025-12-30}
    result: accepted clean, no redraw

  - band: calm
    slot: {idx: 13, date: 2026-01-08}
    excluded: {trips: [OLN: 5.27]}
    hops:
      - {date: 2026-01-09, idx: 14, result: "excluded (APP 5.06, OLN 5.76)"}
      - {date: 2026-01-07, idx: 12, result: "excluded (RMBS -5.52)"}
      - {date: 2026-01-12, idx: 15, result: clean, accepted: true}
    replacement: 2026-01-12

  - band: calm
    slot: {idx: 20, date: 2026-01-20}
    result: accepted clean, no redraw

  - band: calm
    slot: {idx: 28, date: 2026-01-30}
    slot_invalid: "originally excluded (task rule: already-excluded ineligible)"
    hops:
      - {date: 2026-02-02, idx: 29, result: "skip (originally excluded)"}
      - {date: 2026-01-29, idx: 27, result: "skip (originally excluded)"}
      - {date: 2026-02-03, idx: 30, result: "skip (originally excluded)"}
      - {date: 2026-01-28, idx: 26, result: "skip (originally excluded)"}
      - {date: 2026-02-04, idx: 31, result: "skip (originally excluded)"}
      - {date: 2026-01-27, idx: 25, result: "skip (originally drawn)"}
      - {date: 2026-02-05, idx: 32, result: "skip (originally excluded)"}
      - {date: 2026-01-26, idx: 24, result: "skip (originally drawn)"}
      - {date: 2026-01-23, idx: 23, result: "excluded (RMBS -7.58)"}
      - {date: 2026-01-22, idx: 22, result: clean, accepted: true}
    replacement: 2026-01-22
    note: "skips are ineligible dates passed over without screening (C4); only idx 23 and 22 were screened"

  - band: elevated
    run: shorter (2025-11-21 to 2025-12-04)
    slot: {idx: 5, date: 2025-11-28}
    slot_invalid: "half-day (Step-6 drop)"
    hops:
      - {date: 2025-12-01, idx: 6, result: clean, accepted: true}
    replacement: 2025-12-01

  - band: elevated
    run: shorter
    slot: {idx: 7, date: 2025-12-02}
    result: accepted clean, no redraw

  - band: elevated
    run: longer (2026-03-26 to 2026-04-24)
    slot: {idx: 6, date: 2026-04-02}
    result: accepted clean, no redraw

  - band: elevated
    run: longer
    slot: {idx: 8, date: 2026-04-07}
    result: accepted clean, no redraw

  - band: elevated
    run: longer
    slot: {idx: 16, date: 2026-04-17}
    excluded: {trips: [RMBS: 5.75, OLN: -6.75]}
    hops:
      - {date: 2026-04-20, idx: 17, result: "excluded (CROX 5.03)"}
      - {date: 2026-04-16, idx: 15, result: clean, accepted: true}
    replacement: 2026-04-16

no_exhaustion: true   # every window filled its quota; SHORTFALL condition not triggered
```

### C.4 Screen table — every candidate touched this expansion

8 symbols × simple percent return on adjusted closes, ≥5% trips bolded.

| Date | APP | RMBS | OLN | ENSG | DIOD | PCTY | MLI | CROX | Trips |
|---|---|---|---|---|---|---|---|---|---|
| 2025-12-01 | 4.02 | -1.44 | 2.23 | -1.03 | -0.09 | -0.35 | -0.18 | 1.94 | 0 (clean) |
| 2025-12-02 | 4.72 | 2.14 | -1.53 | -1.35 | 1.41 | -0.65 | 0.98 | -1.59 | 0 (clean) |
| 2025-12-26 | -1.82 | -0.39 | 1.36 | -0.12 | 0.30 | 0.87 | -0.16 | 1.13 | 0 (clean) |
| 2025-12-30 | -0.73 | 1.20 | -0.29 | 0.22 | -0.26 | -0.55 | -1.10 | 0.86 | 0 (clean) |
| 2026-01-07 | 2.54 | **-5.52** | -3.99 | -0.71 | -1.97 | 0.43 | -0.69 | -4.02 | 1 |
| 2026-01-08 | -2.59 | -0.34 | **5.27** | -1.22 | 2.16 | 0.33 | 1.89 | 1.25 | 1 |
| 2026-01-09 | **5.06** | 2.23 | **5.76** | -1.33 | 0.29 | -2.17 | 1.87 | -0.58 | 2 |
| 2026-01-12 | 1.69 | -0.51 | -2.47 | 1.64 | -1.43 | -0.71 | 0.65 | 1.19 | 0 (clean) |
| 2026-01-20 | -0.57 | 1.95 | -3.67 | -1.75 | -0.98 | -1.74 | -1.29 | -0.96 | 0 (clean) |
| 2026-01-22 | -1.99 | -0.92 | 2.60 | -1.62 | -1.24 | 4.94 | -0.56 | 1.22 | 0 (clean) |
| 2026-01-23 | 0.47 | **-7.58** | -1.88 | 0.27 | -3.16 | -1.05 | -0.29 | -0.56 | 1 |
| 2026-04-02 | -0.38 | 3.42 | -2.29 | -1.74 | -0.49 | 0.91 | -1.61 | 0.12 | 0 (clean) |
| 2026-04-07 | -0.54 | -0.38 | 3.11 | 1.22 | -0.46 | -0.48 | 0.13 | 1.64 | 0 (clean) |
| 2026-04-16 | 0.31 | 0.01 | 0.79 | -0.10 | 4.09 | 0.14 | -2.00 | -0.26 | 0 (clean) |
| 2026-04-17 | 2.38 | **5.75** | **-6.75** | 1.21 | 0.95 | 0.12 | 3.28 | 3.54 | 2 |
| 2026-04-20 | 2.88 | -0.05 | 3.03 | -1.28 | 1.92 | 2.34 | -1.01 | **5.03** | 1 |

### C.5 Tags on the 10 expansion dates and combined floor check

```yaml
tags_expansion:
  opex: []              # 2026-01-16 and 2026-04-17 (third Fridays) were not accepted
                        # (04-17 excluded on screen; 01-16 never reached by any walk)
  index_rebalance: []   # rebalance trade dates 2025-12-19 / 2026-03-20 not drawable
  ex_dividend: []       # reused 03c §3.2 reference (pulled 2026-07-10): OLN 2025-11-28 /
                        # 2026-03-03, ENSG 2025-12-31 / 2026-03-31, MLI 2025-12-05 /
                        # 2026-03-13 — none coincide with the 10 expansion dates
  holiday_thin:
    - 2025-12-26        # calm slot 5, in the 2025-12-24 -> 2026-01-02 belt
    - 2025-12-30        # calm slot 7, in the belt
                        # tags never exclude

untagged_cell_floor_check:   # combined 20-date grid (10 original + 10 expansion)
  status: PASS
  detail: >
    calm stratum 10 sessions, 2 tagged HOLIDAY-THIN => 8 untagged cells
    per symbol; elevated stratum 10 sessions, 0 tags => 10 untagged
    cells per symbol; floor of >=4 satisfied for all 8 symbols in both
    strata
```

### C.6 Observations for Lei (not rule violations)

1. **Elevated-shorter adjacency:** 2025-12-01/2025-12-02 are adjacent
   sessions (half-day drop at idx 5 walked +1 to idx 6; top-up sat at
   idx 7). Combined with the original draw the shorter elevated window
   now contributes 2025-11-25, 2025-12-01, 2025-12-02, 2025-12-04 —
   three of four dates in one calendar week. Same class as original
   limitation L2; benign for intraday horizons, but the elevated-A
   stratum is now materially early-December-weighted.
2. **Calm mid-January cluster:** 2026-01-20 (slot) and 2026-01-22
   (slot-28 walk landing) are one session apart (2026-01-21 between
   them, untouched). Combined calm grid covers 7 distinct weeks.
3. **RMBS again dominates exclusions** (3 of 6 new exclusions carry an
   RMBS trip), consistent with original limitation L3 — the combined
   grid remains conditioned on RMBS-quiet days.
4. All 10 expansion dates are full NYSE sessions, pre-2026-04-27
   (amendment-A admissible by construction).

---

## Part D — PROVENANCE

```yaml
git_sha: "fb225ae219a1ef74f8a8dea173b83756cf7ced93"
worktree_clean_at_run_start: "yes — porcelain empty (0 entries) before
  this artifact was created"
pythonhashseed: "0 (set in the session for the scripted run)"
host_fingerprint:
  os: "Windows-11-10.0.26200-SP0"
  cpu_arch: "AMD64"
  python_build: "3.14.2 (tags/v3.14.2:df79316, Dec  5 2025, 17:18:21) [MSC v.1944 64 bit (AMD64)]"
env_check: "MASSIVE_API_KEY absent from ambient shell, present in repo
  .env; loaded via feelies.cli.env.load_dotenv_optional; key never
  echoed or persisted"
data_pull: "/v2/aggs/ticker/{APP,RMBS,OLN,ENSG,DIOD,PCTY,MLI,CROX}/range/1/day/2025-11-14/2026-04-24,
  adjusted=true, pulled 2026-07-13 via massive.RESTClient; 110 bars per
  symbol; NO SPY pull (Steps 1-2 frozen), NO dividends pull (03c §3.2
  reference reused), no intraday/signal/PnL/IC data touched"
steps_1_2: "NOT recomputed — rv20 series, band thresholds, and run
  inventory inherited verbatim from
  docs/research/artifacts/universe_draw_evidence_2026-07-10.md"
overlap_validation: "102/102 original screen-table values reproduced
  within 0.05pp (max dev 0.0049pp) — simple-percent convention and
  adjustment stability confirmed before any expansion screening"
one_off_script: "%TEMP%/grid_expansion/pull_and_draw.py (uncommitted,
  governance carve-out; verbatim in the appendix below); output JSON
  %TEMP%/grid_expansion/draw_result.json"
multiple_testing_ledger: "N unchanged — grid expansion is data
  augmentation; no hypothesis or parameter variant evaluated (A.8)"
ingestion: "NOT performed — Lei reviews the dates before ingestion"
```

### Appendix — draw driver (verbatim)

```python
"""Grid-expansion draw (+10 shared dates), 2026-07-13. Uncommitted one-off.

Executes Part B of universe_draw_expansion_evidence_2026-07-13.md strictly
per its Part-A pre-registration (written to disk before this script ran):
pull daily aggs (8 symbols, adjusted), validate calendar anchors and the
overlap of recomputed returns against the original screen table, then run
the pre-registered slot/walk draw mechanically. No SPY pull; no dividends
pull; no intraday, signal, or PnL data touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from feelies.cli.env import load_dotenv_optional, massive_api_key_from_env

SYMBOLS = ["APP", "RMBS", "OLN", "ENSG", "DIOD", "PCTY", "MLI", "CROX"]
PULL_START, PULL_END = "2025-11-14", "2026-04-24"

RUNS = {
    "calm": ("2025-12-19", "2026-02-05", 32),
    "shorter": ("2025-11-21", "2025-12-04", 9),
    "longer": ("2026-03-26", "2026-04-24", 21),
}
# (run, idx) -> date anchors recorded verbatim in the original artifact.
ANCHORS = {
    ("calm", 1): "2025-12-19", ("calm", 2): "2025-12-22", ("calm", 9): "2026-01-02",
    ("calm", 10): "2026-01-05", ("calm", 17): "2026-01-14", ("calm", 18): "2026-01-15",
    ("calm", 24): "2026-01-26", ("calm", 25): "2026-01-27", ("calm", 26): "2026-01-28",
    ("calm", 27): "2026-01-29", ("calm", 28): "2026-01-30", ("calm", 29): "2026-02-02",
    ("calm", 30): "2026-02-03", ("calm", 31): "2026-02-04", ("calm", 32): "2026-02-05",
    ("shorter", 1): "2025-11-21", ("shorter", 2): "2025-11-24",
    ("shorter", 3): "2025-11-25", ("shorter", 9): "2025-12-04",
    ("longer", 1): "2026-03-26", ("longer", 2): "2026-03-27", ("longer", 3): "2026-03-30",
    ("longer", 4): "2026-03-31", ("longer", 5): "2026-04-01", ("longer", 11): "2026-04-10",
    ("longer", 19): "2026-04-22", ("longer", 20): "2026-04-23", ("longer", 21): "2026-04-24",
}

ORIG_DRAWN = {
    "2025-11-25", "2025-12-04", "2025-12-22", "2026-01-05", "2026-01-15",
    "2026-01-26", "2026-01-27", "2026-04-01", "2026-04-10", "2026-04-22",
}
ORIG_EXCLUDED = {
    "2025-11-21", "2025-11-24", "2025-12-19", "2026-01-02", "2026-01-14",
    "2026-01-28", "2026-01-29", "2026-01-30", "2026-02-02", "2026-02-03",
    "2026-02-04", "2026-02-05", "2026-03-26", "2026-03-27", "2026-03-30",
    "2026-03-31", "2026-04-23", "2026-04-24",
}
HALF_DAYS = {"2025-12-24", "2025-11-28"}

# Pre-registered slots (A.4), processing order: calm asc, shorter asc, longer asc.
SLOTS = [
    ("calm", 5), ("calm", 7), ("calm", 13), ("calm", 20), ("calm", 28),
    ("shorter", 5), ("shorter", 7),
    ("longer", 6), ("longer", 8), ("longer", 16),
]
BAND = {"calm": "calm", "shorter": "elevated", "longer": "elevated"}

# Original screen table values (percent), for A.6 overlap validation.
OVERLAP = {
    "2025-11-21": {"APP": -0.11, "RMBS": 1.00, "OLN": 7.15, "ENSG": 3.15, "DIOD": 5.62, "PCTY": 3.51, "MLI": 1.97, "CROX": 3.73},
    "2025-12-04": {"APP": 3.26, "RMBS": 0.80, "OLN": -4.71, "ENSG": -0.59, "DIOD": 0.70, "PCTY": 0.34, "MLI": 1.27, "CROX": -1.24},
    "2025-12-19": {"APP": 3.89, "RMBS": 5.36, "OLN": -0.88, "ENSG": 2.51, "DIOD": 0.08, "PCTY": 0.76, "MLI": 2.50, "CROX": -0.17},
    "2026-01-02": {"APP": -8.24, "RMBS": 8.04, "OLN": 3.46, "ENSG": -0.16, "DIOD": 4.24, "PCTY": -4.46, "MLI": 1.75, "CROX": 1.67},
    "2026-01-14": {"APP": -7.61, "RMBS": 5.38, "OLN": 2.36, "ENSG": -0.16, "DIOD": 2.86, "PCTY": -2.98, "MLI": 2.03, "CROX": -2.14},
    "2026-01-26": {"APP": 2.10, "RMBS": -0.97, "OLN": -1.67, "ENSG": 1.53, "DIOD": 0.67, "PCTY": -0.23, "MLI": 0.82, "CROX": -2.16},
    "2026-02-05": {"APP": -3.13, "RMBS": -2.72, "OLN": -7.98, "ENSG": 13.85, "DIOD": 0.73, "PCTY": 0.32, "MLI": 0.53, "CROX": -2.61},
    "2026-03-26": {"APP": -10.41, "RMBS": -4.68, "OLN": 2.00, "ENSG": -0.93, "DIOD": -3.36, "PCTY": 1.30, "MLI": -2.23, "CROX": -0.19},
    "2026-04-10": {"APP": 3.23, "RMBS": 4.60, "OLN": 1.94, "ENSG": -1.26, "DIOD": 0.95, "PCTY": -0.08, "MLI": 0.24, "CROX": -2.15},
    "2026-04-24": {"APP": -1.29, "RMBS": 14.37, "OLN": 2.10, "ENSG": -0.10, "DIOD": 3.98, "PCTY": 2.11, "MLI": 0.21, "CROX": -1.82},
    # sparse bold trip values
    "2025-11-24": {"APP": 7.60, "RMBS": 5.22},
    "2026-01-28": {"RMBS": 7.54},
    "2026-01-29": {"PCTY": -6.07},
    "2026-01-30": {"APP": -16.89, "RMBS": -6.39, "OLN": -6.85},
    "2026-02-02": {"OLN": 6.54},
    "2026-02-03": {"RMBS": -13.42, "PCTY": -6.13, "MLI": -11.16},
    "2026-02-04": {"APP": -16.12, "OLN": 10.95, "MLI": -7.28},
    "2026-03-27": {"PCTY": -5.08},
    "2026-03-30": {"RMBS": -11.14, "DIOD": -5.67},
    "2026-03-31": {"APP": 6.97, "RMBS": 7.90, "DIOD": 6.11},
    "2026-04-23": {"APP": -6.11, "RMBS": 5.28},
}
TOL = 0.05

OUT = Path(sys.argv[1])

load_dotenv_optional()
api_key = massive_api_key_from_env()
assert api_key, "MASSIVE_API_KEY missing"

from massive import RESTClient  # noqa: E402

client = RESTClient(api_key=api_key)

# ---- pull daily aggs ----
closes: dict[str, dict[str, float]] = {}
for sym in SYMBOLS:
    bars = list(client.list_aggs(sym, 1, "day", PULL_START, PULL_END, adjusted=True, limit=5000))
    per: dict[str, float] = {}
    for b in bars:
        from datetime import datetime, timezone
        d = datetime.fromtimestamp(b.timestamp / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        per[d] = float(b.close)
    closes[sym] = per
    print(f"PULL {sym}: {len(per)} daily bars {min(per)}..{max(per)}", flush=True)

# ---- calendar: intersection check ----
cal_sets = {sym: set(per) for sym, per in closes.items()}
common = set.intersection(*cal_sets.values())
union = set.union(*cal_sets.values())
if common != union:
    for sym, s in cal_sets.items():
        missing = sorted(union - s)
        if missing:
            print(f"CALENDAR WARNING {sym} missing: {missing}", flush=True)
calendar = sorted(common)

# ---- run session lists + anchor validation ----
run_dates: dict[str, list[str]] = {}
anchor_fail = []
for run, (start, end, n_expected) in RUNS.items():
    sess = [d for d in calendar if start <= d <= end]
    run_dates[run] = sess
    print(f"RUN {run}: {len(sess)} sessions (expected {n_expected})", flush=True)
    if len(sess) != n_expected:
        anchor_fail.append(f"{run}: session count {len(sess)} != {n_expected}")
for (run, idx), date in ANCHORS.items():
    actual = run_dates[run][idx - 1] if idx <= len(run_dates[run]) else None
    if actual != date:
        anchor_fail.append(f"{run} idx {idx}: derived {actual} != anchored {date}")
if anchor_fail:
    print("STOP: ANCHOR/CALENDAR FAILURE"); [print(" ", f) for f in anchor_fail]
    sys.exit(2)
print("ANCHORS: all pass", flush=True)

# ---- returns (simple pct on adjusted closes) ----
rets: dict[str, dict[str, float]] = {sym: {} for sym in SYMBOLS}
for sym in SYMBOLS:
    per = closes[sym]
    days = sorted(per)
    for prev, cur in zip(days, days[1:]):
        rets[sym][cur] = (per[cur] / per[prev] - 1.0) * 100.0

# ---- A.6 overlap validation ----
max_dev, dev_at = 0.0, ""
n_checked = 0
for date, row in OVERLAP.items():
    for sym, expected in row.items():
        got = rets[sym].get(date)
        if got is None:
            print(f"STOP: no recomputed return {sym} {date}"); sys.exit(2)
        dev = abs(got - expected)
        n_checked += 1
        if dev > max_dev:
            max_dev, dev_at = dev, f"{sym} {date} (orig {expected}, recomputed {got:.4f})"
        if dev > TOL:
            print(f"STOP: OVERLAP FAIL {sym} {date}: orig {expected} recomputed {got:.4f}")
            sys.exit(2)
print(f"OVERLAP: {n_checked} values pass, max dev {max_dev:.4f}pp at {dev_at}", flush=True)

# ---- draw engine ----
def screen(date: str) -> dict[str, float]:
    """Return {symbol: ret} trips (abs >= 5%)."""
    return {sym: round(rets[sym][date], 2) for sym in SYMBOLS if abs(rets[sym][date]) >= 5.0}


def full_row(date: str) -> dict[str, float]:
    return {sym: round(rets[sym][date], 2) for sym in SYMBOLS}


slot_dates = {(run, idx): run_dates[run][idx - 1] for run, idx in SLOTS}
assigned = set(slot_dates.values())
accepted: list[dict] = []
accepted_dates: set[str] = set()
screen_rows: dict[str, dict] = {}
redraw_log: list[dict] = []
shortfalls: list[dict] = []
contradictions: list[str] = []
systemic: list[dict] = []


def ineligible_reason(run: str, date: str, slot_date: str) -> str | None:
    if date in ORIG_DRAWN:
        return "originally drawn"
    if date in ORIG_EXCLUDED:
        return "originally excluded"
    if date in HALF_DAYS:
        return "half-day"
    if date in accepted_dates:
        return "accepted earlier this expansion"
    if date in assigned and date != slot_date:
        return "assigned expansion slot"
    return None


def screen_candidate(run: str, date: str) -> tuple[bool, dict[str, float], str]:
    """Returns (accept, trips, verdict)."""
    trips = screen(date)
    screen_rows[date] = {"row": full_row(date), "n_trips": len(trips), "band": BAND[run]}
    if not trips:
        return True, trips, "clean"
    if BAND[run] == "calm":
        if len(trips) >= 4:
            contradictions.append(date)
            return False, trips, "excluded (classification contradiction, >=4 co-move)"
        return False, trips, "excluded"
    if len(trips) >= 4:
        systemic.append({"date": date, "trips": trips})
        return True, trips, "SYSTEMIC retained"
    return False, trips, "excluded"


for run, idx in SLOTS:
    dates = run_dates[run]
    n = len(dates)
    slot_date = dates[idx - 1]
    entry: dict = {"band": BAND[run], "run": run, "slot_idx": idx, "slot_date": slot_date}
    reason = ineligible_reason(run, slot_date, slot_date)
    hops: list[dict] = []
    result_date: str | None = None

    if reason is None:
        ok, trips, verdict = screen_candidate(run, slot_date)
        if ok:
            entry["outcome"] = f"slot accepted ({verdict})"
            result_date = slot_date
        else:
            entry["slot_excluded"] = {"trips": trips, "verdict": verdict}
    else:
        entry["slot_invalid"] = reason

    if result_date is None:
        step = 1
        while step < n:
            for j in (idx + step, idx - step):
                if not (1 <= j <= n):
                    continue
                cand = dates[j - 1]
                r = ineligible_reason(run, cand, slot_date)
                if r is not None:
                    hops.append({"date": cand, "idx": j, "result": f"skip ({r})"})
                    continue
                ok, trips, verdict = screen_candidate(run, cand)
                if ok:
                    hops.append({"date": cand, "idx": j, "result": verdict, "accepted": True})
                    result_date = cand
                else:
                    hops.append({"date": cand, "idx": j, "result": f"{verdict} {trips}"})
                if result_date:
                    break
            if result_date:
                break
            step += 1
        entry["hops"] = hops
        if result_date is None:
            entry["outcome"] = "SHORTFALL — walk exhausted run"
            shortfalls.append(entry)

    if result_date:
        entry["final"] = result_date
        accepted_dates.add(result_date)
        accepted.append({"band": BAND[run], "run": run, "slot_idx": idx, "date": result_date})
    redraw_log.append(entry)
    print(json.dumps(entry), flush=True)

out = {
    "accepted": accepted,
    "redraw_log": redraw_log,
    "screen_rows": screen_rows,
    "shortfalls": shortfalls,
    "classification_contradictions": contradictions,
    "systemic_retained": systemic,
    "overlap_check": {"n": n_checked, "max_dev_pp": round(max_dev, 4), "at": dev_at, "tol": TOL},
}
OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
print(f"\nACCEPTED ({len(accepted)}):", flush=True)
for a in accepted:
    print(f"  {a['band']:9s} {a['run']:8s} slot {a['slot_idx']:>2} -> {a['date']}", flush=True)
print(f"shortfalls={len(shortfalls)} contradictions={contradictions} systemic={systemic}", flush=True)
```

---

**STOP — the +10 expansion dates above await Lei's review before any
ingestion or 03c closed-list amendment. Conventions C1–C3 (floor
midpoints, earliest-gap tie-break, anchor-slot reading of the elevated
clause) are Lei-vetoable; the C3 alternative reading and its would-be
slots are recorded in A.3 so a veto can be executed without re-deriving.**

