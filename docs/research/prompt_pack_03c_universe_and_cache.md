<!--
  File:   docs/research/prompt_pack_03c_universe_and_cache.md
  Status: NORMATIVE — FROZEN WITH TASK 8 (Task FQ-5B, 2026-07-10).
          FQ-6A-R remediation 2026-07-11 complete: L1–L4 verbatim, ADV
          table, provenance correction, draw-evidence artifact landed.
          Task 8 grid inputs CLEARED.
          AMENDED 2026-07-13 (append-only AMENDMENTS section): grid
          expansion — +20 ingested cells ({APP,RMBS} × 10 Lei-ratified
          dates), 60 cells DRAWN-NOT-INGESTED, L5 added, C1–C3 ratified.
  Owner:  data-engineering (cache) / research-workflow (evidence grid);
          prompt-pack Task FQ-5B, Phase A.

  Provenance (FQ-3 template; completed in §9 at close-out):
    git_sha: "23813ed5de1e7cbef27b32b0e5e6f65f4ece3c2f"
    worktree_clean: "yes at run START (code path clean at 23813ed);
      FQ-5B outputs committed at FQ-6A-R close — see PROVENANCE CORRECTION"
    pythonhashseed: "0 (set in the session for all scripted runs)"
    env_check: "MASSIVE_API_KEY absent from the ambient shell; present in
      the repo-root .env; exported into the task session from .env (the
      same file `feelies.cli.env.load_dotenv_optional` reads). Both probes
      report set; key never echoed."
    normative_inputs: UNIVERSE_DECISION block (FROZEN 2026-07-10, pasted
      in the FQ-5B prompt; transcribed §2), prompt_pack_03_data_contract.md
      (§2.4 inventory, §8 OQs), prompt_pack_03b_print_eligibility.md
      (§6 guards, §7.3 vendor questions, amendments A/C/E),
      prompt_pack_00d_reproducibility_policy.md (fingerprint template).
-->

# Prompt-pack Task FQ-5B — Evaluation universe and cache

This doc pre-registers the session-selection policy and the exact
(symbol × date) evidence grid (§1–§2, written before any grid ingestion),
then records the ingestion of that grid through the platform's own path
(`MassiveHistoricalIngestor` → `MassiveNormalizer` → `DiskEventCache`),
the closed cache inventory Task 8 pre-registers from (§5), the per-session
data-quality guards (§6), the realized tick-constraint buckets (§7), and
the OQ-1 (WS size-units) resolution attempt (§8). No forward-return
computation is performed anywhere in this task.

---

## 1. SESSION-SELECTION POLICY (pre-registered before ingestion)

Written 2026-07-10, before any grid-cell ingestion. Characterization
samples (§3) are the only data touched before this section and §2 were
committed to disk, per the FQ-5B step-1 carve-out.

**(a) Admissibility span — amendment A in force.** Sessions dated before
2026-04-27 are the only sessions admissible for the evidence grid. The
original step-1(a) proviso (post-April sessions admissible if the FQ-5A
unknown-id guard reports clean) is **superseded** by amendment A: given
the 2026-06-29 vocabulary-switch finding (03b §5.1, §7.3 row 3),
post-2026-04-27 sessions are INADMISSIBLE until the vendor answers. They
may exist in cache but are flagged QUARANTINED in the §5 inventory and do
not count toward `target_sessions_per_symbol`.

**(b) Ex-date exclusion.** No session may sit on a symbol's dividend/split
ex-date. The platform anchor is the BT-18 ex-date guard
(`storage/reference/corporate_actions/ex_dates.yaml` + bootstrap hard
refusal); that calendar is currently **empty** (`entries: []`), so the
runtime guard is inert — the exclusion is therefore enforced at
pre-registration here: the frozen decision's `ex_dividend: []` tag (draw
screened against the dividends reference pulled 2026-07-10) is
re-verified independently in §3.2 against `/v3/reference/dividends`
before ingestion. Any hit ⇒ the cell is excluded and reported (no silent
substitution — closed list).

**(c) Dispersion requirements.**
- Per symbol: ≥2 distinct volatility periods. Satisfied by construction:
  the shared calendar spans regime_calm (5 sessions) and regime_elevated
  (5 sessions, two episodes ~4 months apart) for every symbol.
- Universe level: ≥2 tick-constraint buckets. Characterized pre-ingestion
  from small quote samples (§3.1: median quoted spread / tick — data-
  contract characterization, not peeking) and **recomputed post-ingestion
  from the full quote cache** (§7), per the frozen decision's
  `tick_constraint_bucket_status: UNVERIFIED` clause. If realized buckets
  collapse below 2 distinct buckets, STOP and report before Task 8 freeze.

**(d) Ingest health bar.** Every grid cell must terminate ingest with
per-symbol `DataHealth = HEALTHY` and a non-zero event count — the same
bar `platform.yaml` enforces at backtest boot
(`backtest_enforce_ingest_terminal_health: true`,
`backtest_reject_zero_ingest_events: true`). Failures are retried once;
a second failure flags the cell FAILED in §5 (never silently dropped,
never hand-patched — cache files are written only by `DiskEventCache.save`
on the platform ingest path).

**(e) Per-session guards (amendment E).** Every newly ingested session is
scanned offline (direct cache read, PYTHONHASHSEED=0) with the FQ-5A
units-sanity check (03b §6(b)) and, defensively, the unknown-id guard
(03b §6(a)). Any flag is reported immediately in §6 and the session is
marked accordingly in §5; UNKNOWN-ID ⇒ inadmissible until dispositioned.

**(f) Closed list.** The grid below is the CLOSED list. After Task 8
freezes its IC sessions and CPCV split from §5, additions or
substitutions require a protocol amendment.

## 2. THE FROZEN UNIVERSE DECISION AND THE EXACT GRID

Lei's UNIVERSE_DECISION (FROZEN 2026-07-10) is the authority; this
section transcribes the operative facts and instantiates the exact grid.
The decision's full text (rationales, regime windows, event screen, known
limitations L1–L4) travels with the FQ-5B prompt and is not re-derived
here. **Flag:** the decision references
`docs/research/artifacts/universe_draw_evidence_2026-07-10.md` as its
evidence artifact; that file is **not present in this worktree** at the
FQ-5B run — recorded as a provenance gap for Lei to close (the draw ran
outside this session; nothing here depends on its content, since the
grid is pasted verbatim in the prompt).

- Symbols (8, closed, no substitution):
  `APP, RMBS, OLN, ENSG, DIOD, PCTY, MLI, CROX`
- Shared calendar (10 sessions, all pre-2026-04-27, all NYSE/Nasdaq
  full trading weekdays — verified: no weekend, no US market holiday,
  no early close among them):
  - regime_calm: `2025-12-22, 2026-01-05, 2026-01-15, 2026-01-26, 2026-01-27`
  - regime_elevated: `2025-11-25, 2025-12-04` (episode A),
    `2026-04-01, 2026-04-10, 2026-04-22` (episode B)
- Grid = 8 symbols × 10 dates = **80 cells**, each one
  (symbol, date) `DiskEventCache` entry.
- `closed_list_declaration: true`
- `substitution_rule: none`
- Known limitations (pre-registered; Task 8 must carry all four):
  - "L1: calm stratum = ONE episode; calm-regime conclusions are evidence
    about calm-as-realized Dec-2025/Feb-2026, not calm-in-general"
  - "L2: calm dates 2026-01-26/01-27 are adjacent (deterministic redraw
    artifact of a contaminated late-Jan/early-Feb tail); effective calm
    diversity ~4 distinct weeks; benign for intraday horizons across the
    overnight boundary"
  - "L3: shared-calendar + any-symbol screen over-represents jointly-quiet
    days; RMBS (highest trip rate, incl. during SPY's calmest stretch) is
    the most heavily conditioned subsample — per-symbol diagnostics must
    flag RMBS; its tick-bucket prior is provisional"
  - "L4: elevated stratum spans two episodes ~4 months apart (mild
    Nov-Dec band vs severe April band incl. span rv20 max) — treat
    within-stratum heterogeneity as a feature, report per-window where
    sample permits"
- Amendment B (APP backfill) is satisfied by the shared calendar
  itself: APP's 10 grid dates are all pre-2026-04-27, restoring the
  per-symbol target without relying on its legacy cache (3 admissible
  March sessions, non-grid; 4 post-04-27 sessions QUARANTINED — §5.2).
- **ADV basis (recomputed, FQ-6A-R).** Amendment to the frozen decision's
  `adv_basis`: **"trailing-20-session median" → "grid-session median
  (n=10)"** — only the ten shared grid sessions are ingested per symbol;
  no off-grid trailing history exists in cache, so the capacity base is
  the median convention-eligible continuous **dollar volume** across those
  ten sessions (`prompt_pack_03b` §3.3 Class A + §4.4 correction drop;
  auction crosses and summary re-prints excluded per Class B). Filter
  applied per session then median across sessions.

| symbol | grid-session median eligible $ vol | grid-session median headline $ vol | exclusion share (headline − eligible) / headline |
|---|---|---|---|
| APP | $1,879,255,782 | $2,572,225,829 | 26.9% |
| RMBS | $143,276,599 | $256,772,327 | 44.2% |
| OLN | $38,943,545 | $76,475,629 | 49.1% |
| ENSG | $48,218,886 | $81,951,517 | 41.2% |
| DIOD | $16,336,361 | $25,796,416 | 36.7% |
| PCTY | $51,729,304 | $95,320,562 | 45.7% |
| MLI | $61,831,670 | $130,978,560 | 52.8% |
| CROX | $75,990,432 | $105,475,433 | 28.0% |

Sanity: APP exclusion share ≈ 27% is consistent with the 03b §3.3 ~25%
auction-cross headline-volume skew (APP-specific); higher-exclusion
symbols (OLN, MLI) reflect larger Class-B auction/derived share on
their tapes, not a filter defect. Recomputed from ingested cache
2026-07-11 (`PYTHONHASHSEED=0`, direct `DiskEventCache.load`).

## 3. PRE-INGESTION CHARACTERIZATION

*(filled after §1–§2 were written; small samples only)*

### 3.1 Tick-constraint bucket priors (small quote samples)

Sample: first ≤20,000 RTH `/v3/quotes` records per symbol on 2026-01-15
(mid-grid calm session), pulled 2026-07-10 via the repo's client
construction (`massive.RESTClient`, as `ingestion/massive_ingestor.py:202`
builds it), timestamp-ascending. Median quoted spread / tick ($0.01 for
all — every symbol trades > $1):

| symbol | n sampled | med bid ($) | med spread ($) | spread/tick | prior bucket |
|---|---|---|---|---|---|
| APP  | 20,000 | 615.05 | 0.6000 | 60.0 | wide/unconstrained |
| ENSG |  5,827 | 182.94 | 0.5800 | 58.0 | wide/unconstrained |
| PCTY |  6,210 | 140.80 | 0.3000 | 30.0 | wide/unconstrained |
| RMBS | 19,566 | 105.36 | 0.2400 | 24.0 | wide/unconstrained |
| MLI  |  5,324 | 130.62 | 0.2100 | 21.0 | wide/unconstrained |
| DIOD |  7,235 |  57.50 | 0.1400 | 14.0 | moderate |
| CROX | 11,706 |  83.28 | 0.0900 |  9.0 | moderate |
| OLN  | 20,000 |  23.67 | 0.0300 |  3.0 | discrete/near-constrained |

Bucket edges used here and in §7 (pre-registered now, before the full
recompute): **constrained** ≤ 1.5 ticks; **discrete** (1.5, 5]; **moderate**
(5, 15]; **wide/unconstrained** > 15. On the sample the universe spans
**three** distinct buckets — the ≥2 requirement holds on priors; §7 is
the binding recompute. Two observations for the record: (i) APP's median
bid ($615) sits in the $250.01–$1,000 MDI tier — 40-share round lot,
matching the 03b §6(b) baseline; every other symbol samples ≤ $250 ⇒
100-share round lot for the §6 units check. (ii) OLN's decision prior
said "tick-constrained"; the sample says ~3 ticks (discrete, not hard-
constrained) — it remains the key discreteness case, relabelled honestly.

### 3.2 Ex-date re-verification (policy 1(b))

`/v3/reference/dividends`, span [2025-11-01, 2026-05-01], pulled
2026-07-10: ex-dates exist for OLN (2025-11-28, 2026-03-03), ENSG
(2025-12-31, 2026-03-31), MLI (2025-12-05, 2026-03-13); none for APP,
RMBS, DIOD, PCTY, CROX in span. **Intersection with the 10 grid dates:
empty** — the decision's `ex_dividend: []` tag is confirmed. Nearest
miss: MLI ex-date 2025-12-05 is the day after grid date 2025-12-04;
single-session replays never span the boundary (BT-18 concerns spans,
not adjacency), so the cell stands.

## 4. INGESTION LOG

All 80 grid cells ingested 2026-07-10 (13:53:07–14:09:33 UTC) through the
platform path: per (symbol, date),
`feelies.harness.backtest_runner.ingest_data` — the exact function
`scripts/run_backtest.py` uses — which routes `MassiveHistoricalIngestor`
→ `MassiveNormalizer` → `InMemoryEventLog` →
`DiskEventCache.save(..., ingestion_health=...)` under
`~/.feelies/cache/{SYMBOL}/{DATE}.jsonl.gz` + manifest. No cache file was
hand-constructed; manifests carry `event_schema_hash`
`sha256:8ff53428a52107dc…` (schema semantic version 2 era),
`normalizer_version "1"`, `created_at` (WallClock provenance), and
`ingestion_health`.

Health bar (policy 1(d)): terminal `DataHealth == HEALTHY` and
`event_count > 0` per cell, else one retry (cache entry evicted first)
then FAILED. **Outcome: 80/80 OK on first attempt, zero retries, zero
failures, zero gap/CORRUPTED transitions.** Driver: uncommitted one-off
(verbatim in §10 appendix); command line in §9.

## 5. FINAL CACHE INVENTORY (CLOSED LIST)

This is the CLOSED list Task 8 pre-registers IC sessions and CPCV data
from; after Task 8 freezes, additions require a protocol amendment.
Cross-referenced from `prompt_pack_03_data_contract.md` §2.4 (whose
APP-only table remains the historical record). Counts are manifest
`quotes_count`/`trades_count`. "guards" summarizes §6 (unknown-id +
units-sanity).

### 5.1 The evidence grid (80 cells — all admissible)

| symbol | date | quotes | trades | ingest health | pre-2026-04-27 | guards |
|---|---|---|---|---|---|---|
| APP | 2025-11-25 | 46,688 | 89,261 | HEALTHY | yes | clean |
| APP | 2025-12-04 | 52,643 | 147,350 | HEALTHY | yes | clean |
| APP | 2025-12-22 | 37,666 | 102,506 | HEALTHY | yes | clean |
| APP | 2026-01-05 | 48,376 | 127,553 | HEALTHY | yes | clean |
| APP | 2026-01-15 | 55,500 | 137,781 | HEALTHY | yes | clean |
| APP | 2026-01-26 | 54,022 | 137,432 | HEALTHY | yes | clean |
| APP | 2026-01-27 | 41,981 | 108,391 | HEALTHY | yes | clean |
| APP | 2026-04-01 | 51,183 | 83,973 | HEALTHY | yes | clean |
| APP | 2026-04-10 | 70,353 | 134,146 | HEALTHY | yes | clean |
| APP | 2026-04-22 | 37,688 | 89,087 | HEALTHY | yes | clean |
| RMBS | 2025-11-25 | 12,330 | 22,951 | HEALTHY | yes | clean |
| RMBS | 2025-12-04 | 9,091 | 18,290 | HEALTHY | yes | clean |
| RMBS | 2025-12-22 | 10,676 | 19,432 | HEALTHY | yes | clean |
| RMBS | 2026-01-05 | 20,234 | 34,784 | HEALTHY | yes | clean |
| RMBS | 2026-01-15 | 20,105 | 42,651 | HEALTHY | yes | clean |
| RMBS | 2026-01-26 | 57,021 | 34,937 | HEALTHY | yes | clean |
| RMBS | 2026-01-27 | 16,786 | 31,280 | HEALTHY | yes | clean |
| RMBS | 2026-04-01 | 23,304 | 33,041 | HEALTHY | yes | clean |
| RMBS | 2026-04-10 | 23,371 | 39,557 | HEALTHY | yes | clean |
| RMBS | 2026-04-22 | 16,588 | 32,211 | HEALTHY | yes | clean |
| OLN | 2025-11-25 | 25,507 | 29,267 | HEALTHY | yes | clean |
| OLN | 2025-12-04 | 26,418 | 31,371 | HEALTHY | yes | clean |
| OLN | 2025-12-22 | 18,117 | 20,180 | HEALTHY | yes | clean |
| OLN | 2026-01-05 | 37,784 | 32,286 | HEALTHY | yes | clean |
| OLN | 2026-01-15 | 32,026 | 25,470 | HEALTHY | yes | clean |
| OLN | 2026-01-26 | 24,598 | 25,156 | HEALTHY | yes | clean |
| OLN | 2026-01-27 | 29,513 | 33,299 | HEALTHY | yes | clean |
| OLN | 2026-04-01 | 27,080 | 34,670 | HEALTHY | yes | clean |
| OLN | 2026-04-10 | 17,825 | 28,189 | HEALTHY | yes | clean |
| OLN | 2026-04-22 | 20,465 | 24,445 | HEALTHY | yes | clean |
| ENSG | 2025-11-25 | 3,633 | 11,139 | HEALTHY | yes | clean |
| ENSG | 2025-12-04 | 4,002 | 10,873 | HEALTHY | yes | clean |
| ENSG | 2025-12-22 | 3,670 | 12,773 | HEALTHY | yes | clean |
| ENSG | 2026-01-05 | 3,734 | 9,412 | HEALTHY | yes | clean |
| ENSG | 2026-01-15 | 6,422 | 10,224 | HEALTHY | yes | clean |
| ENSG | 2026-01-26 | 2,306 | 7,191 | HEALTHY | yes | clean |
| ENSG | 2026-01-27 | 2,822 | 9,123 | HEALTHY | yes | clean |
| ENSG | 2026-04-01 | 6,081 | 12,104 | HEALTHY | yes | clean |
| ENSG | 2026-04-10 | 6,791 | 8,069 | HEALTHY | yes | clean |
| ENSG | 2026-04-22 | 16,897 | 12,442 | HEALTHY | yes | clean |
| DIOD | 2025-11-25 | 7,155 | 13,057 | HEALTHY | yes | clean |
| DIOD | 2025-12-04 | 5,084 | 9,582 | HEALTHY | yes | clean |
| DIOD | 2025-12-22 | 5,748 | 7,036 | HEALTHY | yes | clean |
| DIOD | 2026-01-05 | 6,292 | 6,717 | HEALTHY | yes | clean |
| DIOD | 2026-01-15 | 7,320 | 9,334 | HEALTHY | yes | clean |
| DIOD | 2026-01-26 | 3,834 | 5,739 | HEALTHY | yes | clean |
| DIOD | 2026-01-27 | 3,169 | 5,752 | HEALTHY | yes | clean |
| DIOD | 2026-04-01 | 8,918 | 11,488 | HEALTHY | yes | clean |
| DIOD | 2026-04-10 | 8,902 | 13,418 | HEALTHY | yes | clean |
| DIOD | 2026-04-22 | 7,084 | 13,794 | HEALTHY | yes | clean |
| PCTY | 2025-11-25 | 5,067 | 12,929 | HEALTHY | yes | clean |
| PCTY | 2025-12-04 | 7,113 | 12,640 | HEALTHY | yes | clean |
| PCTY | 2025-12-22 | 6,388 | 9,696 | HEALTHY | yes | clean |
| PCTY | 2026-01-05 | 21,199 | 14,358 | HEALTHY | yes | clean |
| PCTY | 2026-01-15 | 6,581 | 14,693 | HEALTHY | yes | clean |
| PCTY | 2026-01-26 | 5,048 | 13,115 | HEALTHY | yes | clean |
| PCTY | 2026-01-27 | 4,688 | 11,252 | HEALTHY | yes | UNKNOWN-ID quote_indicator:2 — dispositioned §6.2 |
| PCTY | 2026-04-01 | 34,426 | 20,015 | HEALTHY | yes | clean |
| PCTY | 2026-04-10 | 12,302 | 22,460 | HEALTHY | yes | clean |
| PCTY | 2026-04-22 | 15,843 | 14,214 | HEALTHY | yes | UNKNOWN-ID quote_indicator:2 — dispositioned §6.2 |
| MLI | 2025-11-25 | 5,381 | 12,315 | HEALTHY | yes | clean |
| MLI | 2025-12-04 | 7,022 | 13,109 | HEALTHY | yes | clean |
| MLI | 2025-12-22 | 7,254 | 17,518 | HEALTHY | yes | clean |
| MLI | 2026-01-05 | 6,263 | 16,697 | HEALTHY | yes | clean |
| MLI | 2026-01-15 | 5,406 | 15,258 | HEALTHY | yes | clean |
| MLI | 2026-01-26 | 7,240 | 13,721 | HEALTHY | yes | clean |
| MLI | 2026-01-27 | 3,898 | 10,740 | HEALTHY | yes | clean |
| MLI | 2026-04-01 | 12,581 | 15,526 | HEALTHY | yes | clean |
| MLI | 2026-04-10 | 8,824 | 11,934 | HEALTHY | yes | clean |
| MLI | 2026-04-22 | 8,812 | 21,860 | HEALTHY | yes | clean |
| CROX | 2025-11-25 | 16,324 | 27,223 | HEALTHY | yes | clean |
| CROX | 2025-12-04 | 14,950 | 24,409 | HEALTHY | yes | clean |
| CROX | 2025-12-22 | 16,954 | 21,920 | HEALTHY | yes | clean |
| CROX | 2026-01-05 | 12,473 | 22,912 | HEALTHY | yes | clean |
| CROX | 2026-01-15 | 11,913 | 17,781 | HEALTHY | yes | clean |
| CROX | 2026-01-26 | 10,616 | 20,181 | HEALTHY | yes | clean |
| CROX | 2026-01-27 | 10,464 | 18,703 | HEALTHY | yes | clean |
| CROX | 2026-04-01 | 17,438 | 23,735 | HEALTHY | yes | clean |
| CROX | 2026-04-10 | 19,363 | 32,270 | HEALTHY | yes | clean |
| CROX | 2026-04-22 | 18,134 | 24,327 | HEALTHY | yes | clean |

Totals: 80/80 HEALTHY; 1,424,768 quotes; 2,477,725 trades. Each symbol
has 10/10 admissible sessions — `target_sessions_per_symbol` met for all
eight (amendment B satisfied by the shared pre-04-27 calendar itself).

### 5.2 Legacy (non-grid) cache on this host — NOT part of the closed list

| symbol | date | quotes | trades | ingest health | pre-2026-04-27 | flag |
|---|---|---|---|---|---|---|
| APP | 2026-03-20 | 52,489 | 89,794 | HEALTHY | yes | admissible, NON-GRID (reserve; not evidence unless amended in) |
| APP | 2026-03-21 | 0 | 0 | UNKNOWN | yes | EMPTY (weekend date) — unusable |
| APP | 2026-03-23 | 80,476 | 115,881 | HEALTHY | yes | admissible, NON-GRID (reserve) |
| APP | 2026-03-26 | 87,899 | 178,855 | HEALTHY | yes | admissible, NON-GRID (reserve; APP acceptance-baseline day) |
| APP | 2026-06-01 | 52,398 | 129,334 | HEALTHY | no | **QUARANTINED** (amendment A) |
| APP | 2026-06-02 | 50,292 | 91,537 | HEALTHY | no | **QUARANTINED** (amendment A) |
| APP | 2026-06-03 | 43,644 | 99,804 | HEALTHY | no | **QUARANTINED** (amendment A) |
| APP | 2026-06-29 | 54,748 | 112,961 | HEALTHY | no | **QUARANTINED** (amendment A + UNKNOWN-ID quote condition 34, 03b §5.3(b)) |

## 6. PER-SESSION GUARDS (amendment E)

Both 03b §6 checks ran over every grid cell and every legacy session
(direct JSONL.gz cache read, PYTHONHASHSEED=0), with the per-field
refinement that a condition id interprets a **trade** condition only if
the vendor artifact types it for `trade` data and a **quote** condition
only if typed `bbo`/`nbbo` (id 34's artifact row is trade-typed, so its
appearance as a *quote* condition on APP/2026-06-29 still flags — the
03b known-answer expectation holds).

### 6.1 Units-sanity (03b §6(b)) — **zero UNITS-SUSPECT flags**

Per-symbol pooled over the 10 grid sessions (nonzero displayed sizes,
both sides; `L` = MDI round lot from the session's median RTH bid —
$0–250 tier ⇒ 100, $250.01–1,000 ⇒ 40):

| symbol | L | median size (range over sessions) | min frac divisible by L | max frac < L | verdict |
|---|---|---|---|---|---|
| APP  | 40  | 40–80   | 1.0 | 0.0 | PASS |
| RMBS | 100 | 100     | 1.0 | 0.0 | PASS |
| OLN  | 100 | 200     | 1.0 | 0.0 | PASS |
| ENSG | 100 | 100     | 1.0 | 0.0 | PASS |
| DIOD | 100 | 100     | 1.0 | 0.0 | PASS |
| PCTY | 100 | 100–200 | 1.0 | 0.0 | PASS |
| MLI  | 100 | 100     | 1.0 | 0.0 | PASS |
| CROX | 100 | 100–200 | 1.0 | 0.0 | PASS |

Every session on every symbol is 100% round-lot-divisible with median ≥ L
— share-denominated NBBO sizes across the whole grid, consistent with the
§8 live-WS verdict.

### 6.2 Unknown-id guard (03b §6(a)) — one new id, dispositioned

Grid flags: **quote `indicators` id 2** on PCTY/2026-01-27 (1 record) and
PCTY/2026-04-22 (2 records). Nothing else: no unknown trade conditions,
no unknown quote conditions, no unknown correction values anywhere in the
80 cells. Legacy known-answer test reproduced exactly: quote condition 34
on APP/2026-06-29 is the only legacy flag (03b §6(a) acceptance).

**Disposition of quote indicator 2 (medium confidence — same basis as
03b §5.2's id-1 interpretation).** All three records sit at the 09:30:00
ET open, are SIP-transitional (two carry quote condition 82 "SIP
Generated"; all are ~$10-wide 300×300 records on PCTY, tape 3/UTP).
The NYSE Daily TAQ legacy **UTP numeric National BBO Indicator**
vocabulary (Daily TAQ Client Spec, Appendix G — the modern letter codes
are annotated "formerly 'n'") defines `2` = "Short Form NBBO Appendage —
a new NBBO is contained in the NBBO file": NBBO bookkeeping, exactly the
family 03b §5.2 used to interpret indicator id 1 (CTA numeric '1' →
modern G/602) and consistent with the vendor glossary's 604/605
short/long-appendage entries. **No firmness or eligibility semantics** —
the practical fill-sim exposure is 3 session-open records with quotes so
wide no entry gate passes. Ruling: id 2 **enters the interpreted table**
via this successor doc (per the 03b §6(a) update rule: by doc update
with a definition, never test-code whitelisting); both PCTY sessions are
**ADMISSIBLE-WITH-DISPOSITION**. Residual: vendor confirmation requested
(question 4 appended to the 03b §7.3 list):

> "On 2026-01-27 and 2026-04-22, `/v3/quotes` for PCTY returned three
> 09:30:00 ET records with `indicators: [2]` (wide, 300×300, two flagged
> SIP-generated). Is quote indicator 2 the legacy UTP numeric National
> BBO Indicator ('2' = short-form NBBO appendage), as indicator 1 is the
> legacy CTA numeric? Which glossary id replaces it going forward?"

Lei may veto this disposition; the fallback is dropping the two cells
(PCTY 8/10, still ≥2 volatility periods — grid otherwise unchanged).

## 7. REALIZED TICK-CONSTRAINT BUCKETS (recompute, per the frozen decision)

Median quoted spread / tick ($0.01 everywhere), RTH quotes only
(09:30–16:00 ET), positive two-sided records, per session and pooled.
Bucket edges pre-registered in §3.1.

| symbol | per-session spread/tick min..max | pooled median | realized bucket |
|---|---|---|---|
| APP  | 40–73 | 61 | wide/unconstrained |
| ENSG | 31–77 | 48 | wide/unconstrained |
| PCTY | 21–38 | 30 | wide/unconstrained |
| RMBS | 18–28 | 22 | wide/unconstrained |
| MLI  | 15–29 | 20 | wide/unconstrained |
| DIOD | 12–32 | 18 | wide/unconstrained (sample prior said moderate; realized median crosses the 15-tick edge) |
| CROX |  8–17 | 11 | moderate |
| OLN  |  2–4  |  2 | discrete/near-constrained |

**Universe spans 3 distinct realized buckets (discrete / moderate /
wide) — the ≥2 requirement PASSES; no STOP condition.** Notes for
Task 8: (i) no symbol is hard tick-constrained (spread pinned at 1 tick)
— OLN at 2–4 ticks is the discreteness case, as re-labelled in §3.1;
(ii) DIOD's bucket moved from moderate (one-session sample) to
wide-boundary (10-session recompute) — the realized table is binding;
(iii) per-symbol per-session values retained in the scan output for
Task 8's per-window diagnostics (L4).

## 8. OQ-1 RESOLUTION ATTEMPT (WS SIZE UNITS) — VERDICT: **SHARES**

Option A executed (session ran during US RTH: capture 2026-07-10
09:50:56–09:51:37 ET, ~20 minutes after the open).

**Method.** Uncommitted one-off (no file added to `scripts/`, per the
task's governance carve-out): `websockets` connection to
`wss://socket.massive.com/stocks` — the same library, URL, auth and
subscribe wire messages as the repo's live feed
(`ingestion/massive_ws.py`) — subscribed `Q.APP`, captured **100 raw
quote events** (36 frames) verbatim. Raw artifact:
`docs/research/artifacts/oq1_ws_quote_frames_APP_2026-07-10.jsonl`
(one WS frame per line with wall receipt ns; auth/status frames not
persisted — the key appears nowhere).

**Evidence, against the 03b §6(b) share-unit baseline (APP round lot
L = 40):**

| check | live WS `bs` | live WS `as` | cached-REST baseline |
|---|---|---|---|
| n | 100 | 100 | (all cached sessions) |
| min / p10 / median / p90 / max | 40 / 40 / 80 / 120 / 240 | 40 / 40 / 40 / 80 / 120 | p10/p50/p90 = 40/80/160–200 |
| frac divisible by 40 | 1.000 | 1.000 | 1.000 |
| frac < 40 | 0.000 | 0.000 | 0.000 |
| value support | {40, 80, 120, 160, 200, 240} | {40, 80, 120} | multiples of 40 |

Near-simultaneous REST cross-check (`/v3/quotes/APP` over the exact
capture window, matched on ms timestamp + bid/ask price): **98 of 100 WS
events matched; 80/98 size-identical on both sides** (the remainder
differ by exactly one 40-share lot — ms-timestamp tie ambiguity among
same-price updates, not a unit difference). REST window `bid_size`
median 80, divisibility by 40 = 1.0.

**Verdict: SHARES.** Under lots-of-40-orders semantics the observed
support would be small integers (1–6) with median 1–2; a distribution
with min 40 and 100% divisibility by the MDI round lot is impossible.
Live WS `bs`/`as` are share-denominated, identical to the REST/cached
path; the Massive WS doc's "number of round lot orders" wording is
stale documentation. The normalizer's no-conversion behavior
(`massive_normalizer.py:451-452, 634-635`) is **correct on both paths**
— no ×round-lot backtest/live divergence exists in depth-consuming
paths. Scope caveat, stated honestly: one symbol, one ~41 s window, one
session; the doc-vs-wire contradiction should still be flagged to the
vendor (question text in 03 §8 OQ-1 update), but the empirical verdict
is dispositive for parity accounting — see the AXIS-2 register entry
(`prompt_pack_00_architecture_verification.md` §(e), FQ-5B amendment).

## 9. PROVENANCE (fills the frozen decision's `<fill at FQ-5B run>` fields)

```yaml
git_sha: "23813ed5de1e7cbef27b32b0e5e6f65f4ece3c2f"
worktree_clean_at_run_start: "yes — porcelain empty for src/, tests/,
  configs/, alphas/, platform.yaml at ingest time (23813ed); only
  pre-existing untracked docs/artifacts from prior Phase-A tasks
  (03/03b/04 drafts, conditions dumps) — classified benign, see
  PROVENANCE CORRECTION below"
worktree_clean_at_run_close: "no — FQ-5B outputs uncommitted until
  FQ-6A-R (2026-07-11)"
host_fingerprint:
  os: "Windows-11-10.0.26200-SP0"
  cpu_arch: "AMD64"
  python_build: "3.14.2 (tags/v3.14.2:df79316, Dec  5 2025, 17:18:21) [MSC v.1944 64 bit (AMD64)]"
  libm: "Microsoft UCRT (linked by MSC v.1944)"
  pythonhashseed: "0"
vendor: Massive
conditions_table_artifact: "docs/research/artifacts/massive_conditions_2026-07-09.json
  (raw-fetch copy, authoritative per 03b §1; supersedes
  docs/research/massive_conditions_dump_2026-07-09.json whose SDK
  round-trip lost FINRA_TDDS sip-mapping keys — semantics identical)"
ingest_command: "uv run python %TEMP%\\fq5b\\ingest_grid.py
  %TEMP%\\fq5b\\ingest_summary.json   # driver verbatim in §10;
  per cell it calls feelies.harness.backtest_runner.ingest_data(api_key,
  [symbol], date, date) — the platform path"
ingest_window_utc: "2026-07-10T13:53:07Z .. 2026-07-10T14:09:33Z"
cache_dir: "~/.feelies/cache (DiskEventCache default)"
event_schema_hash: "sha256:8ff53428a52107dcaa808fec2be1a4377df8562ec5f2c6d79052bdf1909909a7"
normalizer_version: "1"
env_check: "MASSIVE_API_KEY absent from ambient shell, present in repo
  .env; loaded via feelies.cli.env.load_dotenv_optional in every one-off;
  key never echoed or persisted"
draw_evidence_gap: "RESOLVED 2026-07-11 — Lei supplied the full
  Steps 1–7 draw report (one-paste package); landed verbatim at
  docs/research/artifacts/universe_draw_evidence_2026-07-10.md;
  grid dates cross-checked against §2 (exact match)"
oq1_artifact: "docs/research/artifacts/oq1_ws_quote_frames_APP_2026-07-10.jsonl
  (100 raw Q.APP events, 36 frames, captured 2026-07-10
  13:50:56–13:51:37Z = 09:50:56–09:51:37 ET)"
```

One-off scripts (uncommitted, per the step-4 governance carve-out;
locations under the OS temp dir, contents preserved here and in §10):
`oq1_ws_capture.py` (WS capture, method in §8), `characterize_buckets.py`
(§3 samples + ex-date screen), `ingest_grid.py` (§10 verbatim),
`post_ingest_scan.py` (§5–§7 tables: manifest counts, unknown-id guard,
units-sanity, spread/tick recompute — direct JSONL.gz reads,
PYTHONHASHSEED=0).

## 10. APPENDIX — ingest driver (verbatim)

```python
"""FQ-5B step-2: ingest the frozen 80-cell grid through the platform path.

Uncommitted one-off driver. Per (symbol, date) it calls
feelies.harness.backtest_runner.ingest_data — the exact function
scripts/run_backtest.py uses — which routes MassiveHistoricalIngestor →
MassiveNormalizer → InMemoryEventLog → DiskEventCache.save(...,
ingestion_health=...). No cache file is hand-constructed.

Health bar (policy 1(d)): terminal DataHealth == HEALTHY and event_count
> 0, mirroring backtest_enforce_ingest_terminal_health /
backtest_reject_zero_ingest_events. One retry per failing cell (cache
entry evicted first so ingest_data re-fetches); second failure => FAILED.

Writes a JSON summary (one dict per cell) for the 03c inventory.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from feelies.cli.env import load_dotenv_optional, massive_api_key_from_env
from feelies.harness.backtest_runner import ingest_data
from feelies.storage.disk_event_cache import DiskEventCache

SYMBOLS = ["APP", "RMBS", "OLN", "ENSG", "DIOD", "PCTY", "MLI", "CROX"]
DATES = [
    "2025-11-25", "2025-12-04",
    "2025-12-22", "2026-01-05", "2026-01-15", "2026-01-26", "2026-01-27",
    "2026-04-01", "2026-04-10", "2026-04-22",
]
CACHE_DIR = Path.home() / ".feelies" / "cache"
OUT = Path(sys.argv[1])

load_dotenv_optional()
api_key = massive_api_key_from_env()
assert api_key, "MASSIVE_API_KEY missing"


def evict(symbol: str, day: str) -> None:
    for suffix in (".jsonl.gz", ".manifest.json"):
        p = CACHE_DIR / symbol / f"{day}{suffix}"
        if p.exists():
            p.unlink()


def run_cell(symbol: str, day: str) -> dict[str, object]:
    attempts = 0
    last_error = ""
    while attempts < 2:
        attempts += 1
        try:
            _, _, day_sources = ingest_data(api_key, [symbol], day, day)
            ds = day_sources[0]
            health = ds.ingestion_health or "UNKNOWN"
            if health == "HEALTHY" and ds.event_count > 0:
                cache = DiskEventCache(CACHE_DIR)
                manifest = cache.read_manifest(symbol, day) or {}
                return {
                    "symbol": symbol,
                    "date": day,
                    "events": ds.event_count,
                    "quotes": manifest.get("quotes_count"),
                    "trades": manifest.get("trades_count"),
                    "health": health,
                    "source": ds.source,
                    "attempts": attempts,
                    "status": "OK",
                }
            last_error = f"health={health} events={ds.event_count}"
        except Exception:
            last_error = traceback.format_exc(limit=3)
        print(f"  RETRY {symbol} {day} after: {last_error}", flush=True)
        evict(symbol, day)
    return {
        "symbol": symbol,
        "date": day,
        "events": 0,
        "quotes": None,
        "trades": None,
        "health": "FAILED",
        "source": "api",
        "attempts": attempts,
        "status": f"FAILED: {last_error}",
    }


rows: list[dict[str, object]] = []
for sym in SYMBOLS:
    for d in DATES:
        row = run_cell(sym, d)
        rows.append(row)
        print(f"CELL {row['symbol']} {row['date']} -> {row['status']} "
              f"q={row['quotes']} t={row['trades']}", flush=True)
        OUT.write_text(json.dumps(rows, indent=1), encoding="utf-8")

n_ok = sum(1 for r in rows if r["status"] == "OK")
print(f"DONE ok={n_ok}/{len(rows)}", flush=True)
```

**Task FQ-5B complete. §1–§2 are the pre-registered policy and closed
grid; §5 is the CLOSED inventory Task 8 pre-registers from; §6.2's
indicator-2 disposition is Lei-vetoable; §8 resolves T5-OQ-1 (SHARES);
the parity-gap register lives in
`prompt_pack_00_architecture_verification.md` §(e).**

## PROVENANCE CORRECTION (Task FQ-6A-R, 2026-07-11)

FQ-6A recorded `worktree_clean: NO` because FQ-5B closed with its own
outputs still uncommitted. Reclassification against the FQ-3 rule as
amended in `prompt_pack_00d_reproducibility_policy.md` §3:

**At ingest run START (2026-07-10, git SHA 23813ed):**

| path | state at start | classification | determinism relevance |
|---|---|---|---|
| `src/`, `tests/`, `configs/`, `alphas/`, `platform.yaml` | clean (no diff vs 23813ed) | **platform code path frozen** | ingest/normalizer/replay semantics unchanged |
| `docs/research/prompt_pack_03*.md`, `04*.md` (untracked drafts) | untracked | benign docs | none — not imported by ingest |
| `docs/research/artifacts/massive_conditions_2026-07-09.json` | untracked | benign artifact | none — reference table only |
| `docs/research/massive_conditions_dump_2026-07-09.json` | untracked | benign artifact (superseded) | none |
| `docs/research/prompt_pack_backlog.md` | modified (FQ-5A entry) | benign docs | none |
| `docs/research/prompt_pack_00_architecture_verification.md` | not yet modified at ingest start | — | parity register landed post-ingest |

**No `src/`, `tests/`, or `configs/` paths were dirty at start or close.**
STOP condition for determinism relevance did not trigger.

**Cache validity:** FQ-6A independently verified 80/80 manifest counts,
HEALTHY terminal health, merge-key ordering, and units-sanity on spot
cells — cache validity **stands** regardless of doc commit timing.

**At FQ-6A-R close:** all FQ-5B/FQ-6A research outputs committed in
logical commits; `worktree_clean: yes` restored for subsequent tasks.

---

## VERIFICATION (Task FQ-6A — fresh-session, zero-trust, 2026-07-11)

Method: independent session with no memory of the FQ-5B run. Frozen
`UNIVERSE_DECISION` block recovered from the FQ-5B task prompt (agent
transcript `316acf9b-8b1f-4e65-ab04-0cfe131e89ff`, 2026-07-10) — not
from 03c prose. All load-bearing numeric claims re-derived from
`~/.feelies/cache` via `DiskEventCache` (direct manifest read +
`load()`, `PYTHONHASHSEED=0`). Spot integrity checks on four cells
(OLN calm/elevated, APP calm, RMBS elevated). No files patched beyond
this section.

| # | Item | Verdict | Evidence / discrepancies |
|---|---|---|---|
| 1 | Frozen-grid integrity | **FAIL** | **Symbols (8) and shared dates (10) match** the frozen block and §2 exactly — no silent date drift. **Gaps:** (a) `closed_list_declaration: true` and `substitution_rule: none` appear only as prose (“closed list”, “no substitution”), not as the frozen YAML fields; (b) **L1–L4 are summarized in §2 (lines 129–134), not carried verbatim** as the frozen `known_limitations` block requires; (c) `docs/research/artifacts/universe_draw_evidence_2026-07-10.md` is **still absent** from the worktree (`Test-Path` → False; §9 `draw_evidence_gap` unchanged) — not committed, cannot cross-check the draw screen table. |
| 2 | Inventory completeness | **PASS** | All **80/80** grid cells present; manifest `ingestion_health=HEALTHY`, `quotes_count`/`trades_count` match §5.1 **exactly** (zero mismatches); totals **1,424,768 / 2,477,725**; all grid dates **pre-2026-04-27** (quarantine list empty for the closed grid). Legacy APP post-04-27 cells quarantined per §5.2 (2026-06-01/02/03/29 present, HEALTHY, non-grid). **Spot loads:** OLN/2026-01-15, OLN/2025-11-25, APP/2026-01-15, RMBS/2026-04-10 — merge-key order violations **0**, per-channel `exchange_timestamp_ns` regressions **0**, units-sanity **PASS** (median size ≥ L, 100% divisible by MDI round lot). Unknown-id guard with 03b/03c interpreted table: **zero grid flags** (PCTY indicator 2 admissible after §6.2 disposition). |
| 3 | Tick-bucket recompute | **PASS** (one numeric note) | Independent RTH recompute (positive two-sided quotes, $0.01 tick) on calm sample **2026-01-15** + elevated sample **2025-11-25** per symbol, plus 10-session pooled: **3 distinct realized buckets** (discrete / moderate / wide) — ≥2 requirement holds; **no STOP condition**. Per-session min..max matches §7 for all eight symbols. Pooled medians match §7 for 7/8 symbols; **APP pooled median: recomputed 58.0 ticks (all-quote median) vs §7 stated 61** — per-session medians median to 61.5; bucket label unchanged (wide/unconstrained). **OLN:** prior “tick-constrained” → realized **discrete** (2–4 ticks, pooled 2); stable across calm/elevated. **RMBS:** provisional prior → realized **wide/unconstrained** (pooled 21 ticks) — resolved, not still provisional. **MLI:** calm 21 vs elevated 15 spread/ticks (both wide bucket) — mild regime dependence, same bucket label. |
| 4 | ADV basis | **FAIL** (deferred in 03c) | §2/§9 declare ADV **PROVISIONAL** — **no recomputed ADV table or per-cell figures exist in 03c** to match. Independent 03b §3.3 filter on **OLN/2026-01-15:** eligible = **54.6%** of headline shares (45.4% excluded) — **not** the ~25% auction-cross exclusion cited in the frozen `adv_basis` note (that figure is APP-specific). On **APP legacy seven-session cache** (03b §2 population), the same filter yields **74.33%** eligible / **25.67%** excluded — consistent with 03b §3.3 (74.32%). Convention filter validated; **03c per-cell ADV accounting not performed.** |
| 5 | OQ-1 / AXIS-2 status | **PASS** (Option A) | **Option A ran:** live WS capture during RTH 2026-07-10; artifact present: `docs/research/artifacts/oq1_ws_quote_frames_APP_2026-07-10.jsonl` (36 frames, **100** `Q.APP` events). Sizes `{40,80,120,160,200,240}`, min 40, 100% divisible by APP round lot 40 → verdict **SHARES** (not LOTS — no STOP). Parity-gap register in `prompt_pack_00_architecture_verification.md` §(e): **AXIS-1 OPEN**, **AXIS-2 size-units RESOLVED — SHARES**; dissemination residuals OPEN; **Task 12/13 amendments present** (file modified, uncommitted in worktree). |
| 6 | Provenance closure | **FAIL** | `git_sha` **23813ed5de1e7cbef27b32b0e5e6f65f4ece3c2f** exists at HEAD (`git log -1` → docs-only commit; ingest code path unchanged). `host_fingerprint`, `ingest_command`, `conditions_table_artifact`, `event_schema_hash`, `normalizer_version` filled in §9. **`worktree_clean` recorded as NO**, not **yes** as FQ-6A requires; draw-evidence artifact still missing (item 1). |
| 7 | Docs guards | **PASS** | `uv run pytest tests/docs/ -q` → **101 passed**, 0 failed, 1 warning (`PYTHONHASHSEED` unset in pytest env). |

**Task 8 grid inputs: NOT CLEARED at FQ-6A close — draw-evidence
artifact was pending (FQ-6A-R blocker 1; resolved 2026-07-11, see
RE-CHECK below).**

---

## VERIFICATION — FQ-6A-R RE-CHECK (2026-07-11)

| # | Item | FQ-6A | FQ-6A-R | Evidence |
|---|---|---|---|---|
| 1 | Frozen-grid integrity | FAIL | **PASS** | L1–L4 verbatim, `closed_list_declaration`, `substitution_rule` now in §2. `universe_draw_evidence_2026-07-10.md` landed verbatim 2026-07-11 (Lei one-paste package: Part A Steps 1–2 + STOP, Part B approved amendment, Part C Steps 3–7). Internal consistency confirmed: artifact `sessions_drawn` — calm `[2025-12-22, 2026-01-05, 2026-01-15, 2026-01-26, 2026-01-27]`, elevated A `[2025-11-25, 2025-12-04]`, elevated B `[2026-04-01, 2026-04-10, 2026-04-22]` — match the frozen UNIVERSE_DECISION and §2 grid exactly; redraw log and screen table account for every excluded/hop candidate; tags all empty with stratum floor PASS, matching the frozen block's `tags` fragment. |
| 2 | Inventory completeness | PASS | **PASS** | Unchanged (80/80, counts match §5.1). |
| 3 | Tick-bucket recompute | PASS | **PASS** | Unchanged (3 buckets, no STOP). |
| 4 | ADV basis | FAIL | **PASS** | §2 ADV table recomputed; grid-session median (n=10) amendment recorded; APP exclusion 26.9% ≈ 03b ~25% sanity. |
| 5 | OQ-1 / AXIS-2 | PASS | **PASS** | Unchanged; parity register committed in `prompt_pack_00`. |
| 6 | Provenance closure | FAIL | **PASS** | `git_sha` valid; host/ingest fields filled; PROVENANCE CORRECTION + 00d §3 start-clean rule; FQ-5B outputs committed at close. |
| 7 | Docs guards | PASS | **PASS** | `PYTHONHASHSEED=0 uv run pytest tests/docs/ -q` → **101 passed**, 0 failed. |

**Task 8 grid inputs: CLEARED**

---

## AMENDMENTS (append-only; never edit sections above)

### AMENDMENT 1 — Grid expansion ingestion (2026-07-13, Lei-ratified)

Protocol amendment under §1(f): the closed list is extended by the +10
shared dates drawn 2026-07-13 and ratified by Lei the same day. Evidence
package:
`docs/research/artifacts/universe_draw_expansion_evidence_2026-07-13.md`
("the expansion artifact") — pre-registration (Part A), execution record
(Part B), outputs incl. redraw log and screen table (Part C), provenance
(Part D). The original 80-cell grid and all sections above are unchanged.

**A1.1 Ratifications (Lei, 2026-07-13).** The three Lei-vetoable
conventions pre-registered in the expansion artifact §A.3 are RATIFIED
as recorded, no veto:

- **C1 (floor-midpoint arithmetic)** — `midpoint(a,b) = floor((a+b)/2)`,
  matching the task's own calm enumeration {5,13,20,28}; the noted
  discrepancy with the original Step-4 round_half_up stands as recorded.
- **C2 (earliest-gap tie-break)** — lowest-index gap wins among
  equal-size untouched gaps.
- **C3 (anchor-slot reading of the elevated clause)** — anchors are the
  original Step-4 draw POSITIONS (shorter {1,9}, longer {1,11,21});
  the alternative all-touched-dates reading recorded in §A.3 was NOT
  exercised and is closed with this ratification.

The 10 ratified expansion dates (by stratum):

- regime_calm (5): `2025-12-26, 2025-12-30, 2026-01-12, 2026-01-20, 2026-01-22`
- regime_elevated A (2): `2025-12-01, 2025-12-02`
- regime_elevated B (3): `2026-04-02, 2026-04-07, 2026-04-16`

**A1.2 Step-1 checks (this task, 2026-07-13).**

- *Admissibility (mechanical):* 10/10 dates are pre-2026-04-27 full
  weekdays (latest = 2026-04-16; amendment A holds). Verified in the
  ingest driver before any pull.
- *Ex-dividend recheck (APP/RMBS):* `/v3/reference/dividends`, span
  [2025-11-01, 2026-05-01], re-pulled 2026-07-13 for the two ingested
  symbols: **zero ex-dates for APP, zero for RMBS** — both remain
  non-paying in span; intersection with the 10 expansion dates EMPTY.
  (§3.2 reference for the other six symbols unchanged; their ex-dates
  do not coincide with the expansion dates either — expansion artifact
  §C.5.)

**A1.3 Inventory addition — 20 ingested cells ({APP, RMBS} × 10).**
Ingested 2026-07-13 (~02:07–02:13:43 UTC, single run) through the
platform path (`feelies.harness.backtest_runner.ingest_data` →
`MassiveHistoricalIngestor` → `MassiveNormalizer` → `DiskEventCache.save`),
same health bar as §4 (policy 1(d): terminal `DataHealth == HEALTHY`,
`event_count > 0`, one retry): **20/20 OK on first attempt, zero
retries, zero failures.** Manifests carry the same `event_schema_hash`
(`sha256:8ff53428a52107dc…`) and `normalizer_version "1"` as the
original grid. Per-cell guards (policy 1(e)): 03b §6(b) units-sanity
and, defensively, 03b §6(a) unknown-id — **20/20 units PASS, zero
UNKNOWN-ID flags** (id table as amended by §6.2, indicator 2 included).

| symbol | date | quotes | trades | ingest health | pre-2026-04-27 | guards | tag |
|---|---|---|---|---|---|---|---|
| APP | 2025-12-01 | 66,580 | 136,211 | HEALTHY | yes | clean | |
| APP | 2025-12-02 | 56,261 | 154,717 | HEALTHY | yes | clean | |
| APP | 2025-12-26 | 26,525 | 63,560 | HEALTHY | yes | clean | HOLIDAY-THIN |
| APP | 2025-12-30 | 36,609 | 86,226 | HEALTHY | yes | clean | HOLIDAY-THIN |
| APP | 2026-01-12 | 44,535 | 116,013 | HEALTHY | yes | clean | |
| APP | 2026-01-20 | 101,756 | 256,221 | HEALTHY | yes | clean | |
| APP | 2026-01-22 | 52,123 | 154,828 | HEALTHY | yes | clean | |
| APP | 2026-04-02 | 43,771 | 80,196 | HEALTHY | yes | clean | |
| APP | 2026-04-07 | 46,944 | 78,303 | HEALTHY | yes | clean | |
| APP | 2026-04-16 | 81,765 | 125,617 | HEALTHY | yes | clean | |
| RMBS | 2025-12-01 | 12,724 | 19,656 | HEALTHY | yes | clean | |
| RMBS | 2025-12-02 | 10,714 | 19,212 | HEALTHY | yes | clean | |
| RMBS | 2025-12-26 | 5,667 | 12,047 | HEALTHY | yes | clean | HOLIDAY-THIN |
| RMBS | 2025-12-30 | 8,253 | 16,022 | HEALTHY | yes | clean | HOLIDAY-THIN |
| RMBS | 2026-01-12 | 10,416 | 18,386 | HEALTHY | yes | clean | |
| RMBS | 2026-01-20 | 23,068 | 47,245 | HEALTHY | yes | clean | |
| RMBS | 2026-01-22 | 25,812 | 63,576 | HEALTHY | yes | clean | |
| RMBS | 2026-04-02 | 36,642 | 35,259 | HEALTHY | yes | clean | |
| RMBS | 2026-04-07 | 28,094 | 31,404 | HEALTHY | yes | clean | |
| RMBS | 2026-04-16 | 19,189 | 23,791 | HEALTHY | yes | clean | |

Totals: 20/20 HEALTHY; 737,448 quotes; 1,538,490 trades (APP
556,869 / 1,251,892; RMBS 180,579 / 286,598).

Units-sanity detail (03b §6(b), per cell, both sides): APP `L = 40`
(median RTH bid $387.91–$718.26 across the 10 sessions — all in the
$250.01–1,000 MDI tier), per-side median sizes 40–80, min frac
divisible by L = 1.0, max frac < L = 0.0; RMBS `L = 100` (median RTH
bid $90.58–$124.58), medians 100–200, 1.0 / 0.0. Share-denominated
NBBO sizes throughout — consistent with the §6.1 grid baseline and the
§8 SHARES verdict.

**A1.4 HOLIDAY-THIN tags carried.** 2025-12-26 and 2025-12-30 sit in
the 2025-12-24 → 2026-01-02 holiday-thin belt (expansion artifact
§A.7/§C.5) and are tagged HOLIDAY-THIN in the inventory above. Tags
never exclude. Observed volumes are consistent with the tag (e.g. APP
26,525 quotes on 12-26 vs a 37k–102k range on untagged calm expansion
sessions). Combined-grid untagged-cell floor check (expansion artifact
§C.5): calm stratum 10 sessions / 2 tagged → 8 untagged per symbol;
elevated 10 / 0 tagged → 10; floor ≥ 4 PASSES for all symbols.

**A1.5 The 60 non-ingested expansion cells — DRAWN-NOT-INGESTED.**
The cells `{OLN, ENSG, DIOD, PCTY, MLI, CROX} × the 10 expansion dates`
(60 cells) are part of the ratified expansion draw but are NOT in
cache and are NOT evidence. Registered status: **DRAWN-NOT-INGESTED**
— dates ratified (no new draw needed), ingestion deferred; any future
ingestion of these cells goes through the identical bar (platform
path, policy 1(d) health, policy 1(e) guards, §3.2-style ex-date check
against the expansion dates — note ENSG/OLN/MLI ex-dates in span do
not coincide with any expansion date) and is recorded by a further
append-only amendment here. Until then the expanded evidence
inventory is 80 original cells + 20 expansion cells = **100 ingested
admissible cells**, with per-symbol session counts: APP 20, RMBS 20,
others 10.

**A1.6 Known-limitations update.**

- **L5 (new, L2-class): elevated-A single-week concentration.** The
  combined elevated-A stratum is `2025-11-25, 2025-12-01, 2025-12-02,
  2025-12-04` — three of four dates in one calendar week (Dec 1–5),
  and 12-01/12-02 adjacent (deterministic artifact of the half-day
  drop at shorter idx 5 walking +1 while the top-up sat at idx 7 —
  expansion artifact §C.6-1). Same class as L2: benign for intraday
  horizons, but elevated-A conclusions are evidence about
  early-December-2025-as-realized; per-window reporting under L4
  should treat elevated-A as effectively one episode-week.
- **L3 carries, reinforced:** RMBS dominated the expansion screen
  exclusions (3 of 6 new exclusions carry an RMBS trip — expansion
  artifact §C.2/§C.6-3). The combined 20-date grid remains conditioned
  on RMBS-quiet days; per-symbol diagnostics must continue to flag
  RMBS.
- L1, L2, L4 carry unchanged (expansion adds within-episode dispersion
  only; see the expansion artifact's limitation notes).

**A1.7 Census-instrument disposition — variant superseded.** For all
census work on the expanded grid, the **expanded census runs the
primary instrument only** (the Appendix-A read, primary run
parameters, `is_primary_run: true` — as in
`docs/research/artifacts/dislocation_lambda_census_2026-07-12.json`).
The s1.7 sensitivity variant
(`docs/research/artifacts/dislocation_lambda_census_variant_2026-07-12.json`,
`is_primary_run: false`) is **superseded** and is not re-run on
expansion cells; its original-grid results stand as recorded and its
trial remains counted in the multiple-testing ledger N. No new
hypothesis or parameter variant is evaluated by this amendment —
ingestion is data augmentation; **N is unchanged by this task**
(expansion artifact §A.8).

**A1.8 Provenance (FQ-3 template).**

```yaml
git_sha: "fb225ae219a1ef74f8a8dea173b83756cf7ced93"
worktree_clean: "yes at run START for all code paths — porcelain shows
  exactly one entry: the untracked expansion artifact
  docs/research/artifacts/universe_draw_expansion_evidence_2026-07-13.md
  (prior task's benign doc output, committed with this amendment per
  00d §3); src/, tests/, configs/, alphas/, platform.yaml clean"
host_fingerprint:
  os: "Windows-11-10.0.26200-SP0"
  cpu_arch: "AMD64"
  python_build: "3.14.2 (tags/v3.14.2:df79316, Dec 5 2025, 17:18:21) [MSC v.1944 64 bit (AMD64)]"
  libm: "Microsoft UCRT (linked by MSC v.1944)"
  config_checksum: "n/a — no PlatformConfig loaded (ingest + offline guard path only)"
  pythonhashseed: "0"
env_check: "MASSIVE_API_KEY absent from ambient shell, present in repo
  .env; loaded via feelies.cli.env.load_dotenv_optional in the one-off;
  key never echoed or persisted; shell + python preflight both reported
  set before the run"
expansion_artifact: "docs/research/artifacts/universe_draw_expansion_evidence_2026-07-13.md
  (draw pre-registration + execution + Lei ratification basis;
  committed with this amendment)"
ingest_command: "uv run python %TEMP%\\grid_expansion_ingest\\ingest_expansion.py
  %TEMP%\\grid_expansion_ingest\\ingest_summary.json   # driver verbatim
  in A1.9; per cell it calls
  feelies.harness.backtest_runner.ingest_data(api_key, [symbol], date,
  date) — the platform path"
ingest_window_utc: "2026-07-13T02:07Z .. 2026-07-13T02:13:43Z (single
  run, 394 s; Step-1 admissibility + dividends recheck ran first inside
  the same driver)"
cache_dir: "~/.feelies/cache (DiskEventCache default)"
event_schema_hash: "sha256:8ff53428a52107dcaa808fec2be1a4377df8562ec5f2c6d79052bdf1909909a7"
normalizer_version: "1"
multiple_testing_ledger: "N unchanged — data augmentation only (A1.7)"
```

**A1.9 Appendix — expansion ingest driver (verbatim, uncommitted
one-off per the governance carve-out).**

```python
"""Grid-expansion ingestion (+20 cells), 2026-07-13. Uncommitted one-off.

Executes Steps 1-2 of the grid-expansion ingestion task against the
Lei-ratified +10 dates recorded in
docs/research/artifacts/universe_draw_expansion_evidence_2026-07-13.md:

  Step 1: mechanical admissibility check (all 10 dates pre-2026-04-27,
          full weekday sessions) + APP/RMBS ex-dividend recheck via
          /v3/reference/dividends over [2025-11-01, 2026-05-01].
  Step 2: ingest {APP, RMBS} x 10 dates through the platform path
          (feelies.harness.backtest_runner.ingest_data ->
          MassiveHistoricalIngestor -> MassiveNormalizer ->
          DiskEventCache.save), health bar per 03c policy 1(d)
          (terminal DataHealth == HEALTHY and event_count > 0, one
          retry after cache eviction), then per-cell guards per 03c
          policy 1(e): 03b 6(b) units-sanity + 03b 6(a) unknown-id
          (per-field typing refinement of 03c 6).

No forward returns computed anywhere. Writes a JSON summary for the
03c AMENDMENTS inventory.
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

from feelies.cli.env import load_dotenv_optional, massive_api_key_from_env
from feelies.core.events import NBBOQuote, Trade
from feelies.harness.backtest_runner import ingest_data
from feelies.storage.disk_event_cache import DiskEventCache

SYMBOLS = ["APP", "RMBS"]
EXPANSION_DATES = [
    "2025-12-01", "2025-12-02",              # elevated A
    "2025-12-26", "2025-12-30", "2026-01-12",
    "2026-01-20", "2026-01-22",              # calm
    "2026-04-02", "2026-04-07", "2026-04-16",  # elevated B
]
ADMISSIBILITY_CUTOFF = "2026-04-27"
DIV_SPAN = ("2025-11-01", "2026-05-01")
CACHE_DIR = Path.home() / ".feelies" / "cache"
CONDITIONS_ARTIFACT = Path("docs/research/artifacts/massive_conditions_2026-07-09.json")
ET = ZoneInfo("America/New_York")

# Interpreted table (03b 6(a) as amended by 03c 6.2: indicator id 2 added).
KNOWN_INDICATORS = {1, 2, *range(501, 510), *range(601, 606), *range(901, 909)}
KNOWN_CORRECTIONS = {None, 0, 1, 7, 8, 10, 11, 12}

OUT = Path(sys.argv[1])

load_dotenv_optional()
api_key = massive_api_key_from_env()
assert api_key, "MASSIVE_API_KEY missing"

# ---- Step 1a: mechanical admissibility ----
admissibility = []
for d in EXPANSION_DATES:
    dt = date.fromisoformat(d)
    admissibility.append({
        "date": d,
        "pre_cutoff": d < ADMISSIBILITY_CUTOFF,
        "weekday": dt.weekday() < 5,
    })
adm_fail = [a for a in admissibility if not (a["pre_cutoff"] and a["weekday"])]
print(f"ADMISSIBILITY: {len(EXPANSION_DATES) - len(adm_fail)}/{len(EXPANSION_DATES)} "
      f"pre-{ADMISSIBILITY_CUTOFF} weekdays", flush=True)
if adm_fail:
    print(f"STOP: admissibility failures: {adm_fail}")
    sys.exit(2)

# ---- Step 1b: APP/RMBS dividends recheck ----
from massive import RESTClient  # noqa: E402

client = RESTClient(api_key=api_key)
div_report: dict[str, list[str]] = {}
for sym in SYMBOLS:
    ex_dates = []
    for div in client.list_dividends(
        ticker=sym,
        ex_dividend_date_gte=DIV_SPAN[0],
        ex_dividend_date_lte=DIV_SPAN[1],
        limit=1000,
    ):
        ex_dates.append(str(div.ex_dividend_date))
    div_report[sym] = sorted(ex_dates)
    hits = sorted(set(ex_dates) & set(EXPANSION_DATES))
    print(f"DIVIDENDS {sym}: {len(ex_dates)} ex-dates in span {DIV_SPAN}; "
          f"intersection with expansion dates: {hits or 'EMPTY'}", flush=True)
    if hits:
        print(f"STOP: ex-date collision for {sym}: {hits}")
        sys.exit(2)

# ---- interpreted table for the unknown-id guard (per-field typing) ----
cond_rows = json.loads(CONDITIONS_ARTIFACT.read_text(encoding="utf-8"))["results"]
TRADE_COND_IDS = {r["id"] for r in cond_rows if "trade" in r.get("data_types", [])}
QUOTE_COND_IDS = {
    r["id"] for r in cond_rows
    if {"bbo", "nbbo"} & set(r.get("data_types", []))
}


def evict(symbol: str, day: str) -> None:
    for suffix in (".jsonl.gz", ".manifest.json"):
        p = CACHE_DIR / symbol / f"{day}{suffix}"
        if p.exists():
            p.unlink()


def run_cell(symbol: str, day: str) -> dict[str, object]:
    attempts = 0
    last_error = ""
    while attempts < 2:
        attempts += 1
        try:
            _, _, day_sources = ingest_data(api_key, [symbol], day, day)
            ds = day_sources[0]
            health = ds.ingestion_health or "UNKNOWN"
            if health == "HEALTHY" and ds.event_count > 0:
                cache = DiskEventCache(CACHE_DIR)
                manifest = cache.read_manifest(symbol, day) or {}
                return {
                    "symbol": symbol,
                    "date": day,
                    "events": ds.event_count,
                    "quotes": manifest.get("quotes_count"),
                    "trades": manifest.get("trades_count"),
                    "health": health,
                    "source": ds.source,
                    "attempts": attempts,
                    "status": "OK",
                }
            last_error = f"health={health} events={ds.event_count}"
        except Exception:
            last_error = traceback.format_exc(limit=3)
        print(f"  RETRY {symbol} {day} after: {last_error}", flush=True)
        evict(symbol, day)
    return {
        "symbol": symbol, "date": day, "events": 0, "quotes": None,
        "trades": None, "health": "FAILED", "source": "api",
        "attempts": attempts, "status": f"FAILED: {last_error}",
    }


def et_time_of_day(ts_ns: int) -> tuple[int, int]:
    dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).astimezone(ET)
    return dt.hour, dt.minute


def guards(symbol: str, day: str) -> dict[str, object]:
    """03b 6(b) units-sanity + 6(a) unknown-id, direct cache read."""
    cache = DiskEventCache(CACHE_DIR)
    events = cache.load(symbol, day)
    assert events is not None, f"cache load failed {symbol}/{day}"
    quotes = [e for e in events if isinstance(e, NBBOQuote)]
    trades = [e for e in events if isinstance(e, Trade)]

    # RTH median bid -> MDI round lot tier
    rth_bids = []
    for q in quotes:
        h, m = et_time_of_day(q.exchange_timestamp_ns)
        if (h, m) >= (9, 30) and h < 16 and q.bid > 0:
            rth_bids.append(float(q.bid))
    med_bid = median(rth_bids)
    lot = 40 if 250.0 < med_bid <= 1000.0 else 100
    assert med_bid <= 1000.0, f"{symbol}/{day}: median bid {med_bid} above 1000-tier"

    sides: dict[str, list[int]] = {
        "bid": [q.bid_size for q in quotes if q.bid_size > 0],
        "ask": [q.ask_size for q in quotes if q.ask_size > 0],
    }
    units: dict[str, object] = {"L": lot, "median_rth_bid": round(med_bid, 2)}
    suspect = False
    for side, sizes in sides.items():
        med = median(sizes)
        frac_div = sum(1 for s in sizes if s % lot == 0) / len(sizes)
        frac_lt = sum(1 for s in sizes if s < lot) / len(sizes)
        units[side] = {
            "n": len(sizes),
            "median": med,
            "frac_div_L": round(frac_div, 6),
            "frac_lt_L": round(frac_lt, 6),
        }
        if med < lot or frac_div < 1.0:
            suspect = True
    units["verdict"] = "UNITS-SUSPECT" if suspect else "PASS"

    # unknown-id guard (per-field typing refinement)
    flags: list[str] = []
    tc = {c for t in trades for c in t.conditions}
    qc = {c for q in quotes for c in q.conditions}
    qi = {i for q in quotes for i in q.indicators}
    corr = {t.correction for t in trades}
    for i in sorted(tc - TRADE_COND_IDS):
        flags.append(f"UNKNOWN-ID(trade_condition, {i})")
    for i in sorted(qc - QUOTE_COND_IDS):
        flags.append(f"UNKNOWN-ID(quote_condition, {i})")
    for i in sorted(qi - KNOWN_INDICATORS):
        flags.append(f"UNKNOWN-ID(quote_indicator, {i})")
    for v in sorted((corr - KNOWN_CORRECTIONS), key=str):
        flags.append(f"UNKNOWN-ID(correction, {v})")

    return {"units_sanity": units, "unknown_id_flags": flags}


rows: list[dict[str, object]] = []
for sym in SYMBOLS:
    for d in EXPANSION_DATES:
        row = run_cell(sym, d)
        if row["status"] == "OK":
            row.update(guards(sym, d))
        rows.append(row)
        u = row.get("units_sanity", {})
        print(f"CELL {row['symbol']} {row['date']} -> {row['status']} "
              f"q={row['quotes']} t={row['trades']} "
              f"units={u.get('verdict', 'n/a')} L={u.get('L', '?')} "
              f"flags={row.get('unknown_id_flags', 'n/a')}", flush=True)
        OUT.write_text(json.dumps({
            "admissibility": admissibility,
            "dividends_recheck": div_report,
            "cells": rows,
        }, indent=1), encoding="utf-8")

n_ok = sum(1 for r in rows if r["status"] == "OK")
n_clean = sum(
    1 for r in rows
    if r["status"] == "OK"
    and r["units_sanity"]["verdict"] == "PASS"  # type: ignore[index]
    and not r["unknown_id_flags"]
)
print(f"DONE ok={n_ok}/{len(rows)} clean_guards={n_clean}/{len(rows)}", flush=True)
```

**AMENDMENT 1 complete. The closed list now comprises 100 ingested
admissible cells (§5.1 + A1.3) plus 60 DRAWN-NOT-INGESTED cells
(A1.5); limitations L1–L5 are in force (A1.6); expanded-census work
uses the primary instrument only (A1.7).**
