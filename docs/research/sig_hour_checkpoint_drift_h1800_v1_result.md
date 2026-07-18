<!--
  File:   docs/research/sig_hour_checkpoint_drift_h1800_v1_result.md
  Status: hypothesis — parked (power; final card) (H13 park close-out,
          2026-07-18; Lei ratifies the census verdict per frozen
          pool-collapse row / protocol C.8). Compact closure record
          instantiating the R10 proposal template
          (.cursor/skills/microstructure-alpha/proposal-template.md)
          with what exists. No outcome statistic (forward return, IC,
          Sharpe, CPCV, DSR, execution number) exists for this
          candidate; N unchanged at 12. PARK ≠ refutation. Program
          CLOSED on this universe/grid (pack-10 stop-rule executed).
  Owner:  microstructure-alpha (candidate) / research-workflow (ledger);
          prompt-pack H13 park close-out + program closure.

  Provenance (FQ-3 template):
    git_sha: "2455810c80e8b2cd86a7ad5c2fb1367b9b1c1dca" (HEAD at this
      task's start = latest H13 Phase-A / harness pin; this close-out
      is the first commit after it — no scripted analysis run in this
      task; every number below is quoted from the census record or the
      frozen spec/protocol)
    worktree_clean: "at task start: tracked tree clean at 2455810
      except uncommitted Task 8-C-H13 census outputs (modified
      validation_protocol.md C.0–C.7; untracked
      artifacts/hour_checkpoint_drift_census_2026-07-18.json) —
      committed by this close-out with C.8 adjudication + Status
      updates"
    pythonhashseed: "n/a — no scripted analysis run in this task
      (adjudication + close-out only). Artifact SHA-256 re-verified
      byte-identical this session before commit."
    normative_inputs:
      sig_hour_checkpoint_drift_h1800_v1_formal_spec.md (Task-7 frozen
        spec + Appendix P),
      sig_hour_checkpoint_drift_h1800_v1_validation_protocol.md (frozen
        protocol + CENSUS RESULTS C.0–C.7 + ADJUDICATION C.8),
      docs/research/artifacts/hour_checkpoint_drift_census_2026-07-18.json
        (sha256=2033cbd8b4268b1f1aefbdb8de95f3a57f843898b8bd22971c4028050c73834b),
      prompt_pack_11_hypothesis_slate_d.md (H13 card + DISPOSITIONS),
      prompt_pack_10_cycle2_retrospective.md (cycle-3 stop-rule),
      prompt_pack_backlog.md (entries 19–20).
-->

# `sig_hour_checkpoint_drift_h1800_v1` — closure record (hypothesis — parked (power; final card))

**Verdict first.** The pre-registered step-1 park-rule census (executed
2026-07-18 under the frozen protocol; artifact SHA-256
`2033cbd8…834b`) fired the §1.5 / §4.5 **power floor** before a
single IC number existed. Pooled viable-region in-hour episodes
across the eight-symbol evidence pool = **66 < 100** (D-only **60**;
ENSG/MLI **+6**). Edge axis non-empty on all six D symbols. The F2
:30 arm is independently **adjudicable** at viable-region n =
**175 ≥ 100** (frozen prior ≈96 / expected F2-INSUFFICIENT **not
realized** — recorded as a both-directions prior miss; counts only;
never scored). Infrastructure perfect (calendar-warm **1.000**,
`calendar_missing_rate` **0**, determinism green). The sequence
halted at protocol step 1; steps 2–8 never ran. Lei ratifies
**PARK (power)** per frozen pool-collapse row (protocol C.8).

**PARK ≠ refutation: F1–F5 never ran; zero outcome contact; N = 12.**
No claim is made that the hour scheduled-flow mechanism does not
exist — only that the pre-registered pooled in-hour episode count is
below the census floor as realized on the frozen evidence-pool grid.

**Program CLOSED.** H13 was the final card; this park exhausts the
contingency chain and executes the pack-10 stop-rule (cycle 3
complete without a step-2b PASS).

All twelve R10 sections follow; cost figures are one-way, per-fill,
bps of fill notional (00b convention).

## 1. SIGNAL

Larger institutional parents and desk-level participation caps are
often monitored on an **hourly** checkpoint grid (10:00, 11:00, … ET)
because schedule variance and VWAP benchmarks are reviewed on the
hour, which must leak into L1 as signed quote-flow pressure
concentrated on on-the-hour decision windows. Residual impact of
still-open parents continues over the next **H = 1800 s**. Clock
binding is load-bearing: matched flow extremes at **:30**
(half-hour-but-not-hour) must not produce the same continuation.
State: `ofi_integrated` quintile (`percentile ≥ 0.80` LONG / `≤ 0.20`
SHORT) ∧ `W_hr` (hour-only `ALGO_CLOCK` / `scheduled_flow_window_active`)
∧ `P(vol_breakout) < 0.7`. `horizon_seconds = 1800`. (Spec §0/§1,
unchanged from the pre-registered card.)

## 2. ARCHETYPE & COUNTERPARTY

Archetype **schedule-bound flow-following** (`SCHEDULED_FLOW`).
Actor: clock-sliced / hour-reviewed institutional parent.
Counterparty: LPs and discretionary flow that under-react between
hourly reviews. Conservation: edge ≤ residual impact of open
scheduled parents across the hourly grid.
`expected_half_life_seconds = 900` (envelope ✓; horizon ratio 2.0 ∈
[0.5, 4.0] ✓). Evidence / deployable set frozen six-symbol D
{APP, RMBS, OLN, DIOD, PCTY, CROX}; ENSG/MLI evidence-only
(never-promotable).

## 3. STATE VARIABLES

Entry-warm set: `scheduled_flow_window` (calendar-warm; hour-only
`ALGO_CLOCK` derived view — `:00` subset; `:30` excluded from
injection), `ofi_integrated` / `ofi_integrated_percentile` at h =
1800 (quote-fed), `realized_vol_30s` (gate). **No `spread_z_30d`.**
No NEW trade-fed sensor. Highest-mirage residual: OFI manufacture on
a known clock (MIXED, M = 1.5). (Spec §1/§3.)

## 4. PROCESS MODEL

Scheduled residual permanent-impact continuation — partial adjustment
with exponentially decaying remainder, hl = 900 s. Edge decomposition
`edge_ow = κ × σ₁₈₀₀`, κ = c_D × f_perm × r_rem × f_H × f_pass with
frozen central **κ = 0.172** and the one-way ratchet (spec §4). F2
required because unclocked / :30 OFI continuation can mimic the entry
arm without hour-checkpoint binding.

## 5. ENTRY-EXIT RULE

Gate ON: `P(vol_breakout) < 0.7` ∧ hour `W_hr` ∧ OFI quintile ∧
sign agreement ∧ vol-z backstop; OFF adds hysteresis. Entry: EV-gated
continuation WITH the OFI imbalance, LONG/SHORT side-symmetric,
passive/maker. Exits: hazard spike, gate-OFF FLAT close,
`HARD_EXIT_AGE` 1800 s (2 × hl). Session discipline: 09:35–15:50 ET.
Warm/stale: entries suppressed on cold/stale entry-warm ids
(including missing calendar → warm=False); exits never suppressed.
(Spec §5/§6 draft `evaluate` — Phase B never built.)

## 6. L2 LOSS ACCOUNTING

Spec ledger adopted; binding row is L2 queue composition — passive
entry into a continuation move is the structurally adverse fill
geometry. **Never exercised:** the sequence parked at step 1 before
any fill was simulated. Phase B YAML / router path was never
authorized.

## 7. STATISTICAL RESULT

**Not reached — parked at protocol step 1.** No forward return, IC,
RankIC, CPCV, or DSR number exists for this candidate. The deciding
evidence is the census (no outcome statistic; the only return-like
quantity was the unconditional session σ₁₈₀₀, authorized by frozen §1):

### Projection-vs-measured (uniform / rider / measured)

| arm | uniform (B) all-cell | κ-viable honesty rider | measured all-cell | measured viable-region | vs census floor ≥ 100 |
|---|---|---|---|---|---|
| in-hour (primary) | **120.9** | **≈96** | **82** | **66** | **FAIL** (66) |
| :30 (F2 counts) | **120.9** | **≈96** | **220** | **175** | **adjudicable** (175; prior miss) |

**Per-symbol viable-region roll-up** (census C.4):

| symbol | role | viable-region in-hour | viable-region :30 |
|---|---|---|---|
| APP | D | **22** | **21** |
| RMBS | D | **12** | **36** |
| OLN | D | **10** | **28** |
| DIOD | D | **2** | **23** |
| PCTY | D | **8** | **27** |
| CROX | D | **6** | **30** |
| ENSG | evidence-only | **3** | **4** |
| MLI | evidence-only | **3** | **6** |
| **pooled** | evidence pool | **66** | **175** |
| D-only (extractable) | — | **60** | — |

Edge axis non-empty on all six D symbols; warm-drop did not fire;
infrastructure PASS. Deployable set before power park would have been
D = {APP, RMBS, OLN, DIOD, PCTY, CROX}. Power park governs — card
does not PROCEED.

### :00-vs-:30 occupancy asymmetry (census-legal characterization)

Viable-region :30 / in-hour = 175/66 ≈ **2.6×** on this
hour-only × H=1800 grid. Realized/rider ratios: in-hour 66/96 ≈
**0.69×**; :30 arm 175/96 ≈ **1.8×**. Recorded as a
characterization finding of this grid/geometry — not an outcome
statistic, not a κ edit, not a RankIC prior. Contrast with
cross-card `f_resid` transfer (H12's 0.3935 was a characterization
input to the rebuild, not a measured H13 fact):

| card | conditioning / geometry class | realized / design-central | source |
|---|---|---|---|
| H8 | non-percentile joint occupancy prior | ≈ **0.55×** | pack-10 §1.2 |
| H12 | window × quintile × gate (quintile exempt; window/gate not) | ≈ **0.46×** (68 / 147.7) | H12 census / C.4 |
| **H13** | hour-only × quintile × gate post-rebuild (κ-viable rider) | ≈ **0.69×** (66 / 96); :30 arm ≈ **1.8×** | census C.4 / C.8 |
| H10 | **percentile-exempt** decile × ISO-warm | ≈ **1.04×** (152 / 146.2) | pack-10 §1.2 |

**Arm-specific occupancy must be MEASURED on the target window
geometry; cross-card `f_resid` transfer is itself an unvalidated
prior.** Registered as backlog **20** (extends backlog 19; cites
8-C-H13).

Full record: protocol CENSUS RESULTS C.0–C.7 + ADJUDICATION C.8;
artifact `docs/research/artifacts/hour_checkpoint_drift_census_2026-07-18.json`
(sha256 `2033cbd8b4268b1f1aefbdb8de95f3a57f843898b8bd22971c4028050c73834b`).

## 8. EXECUTION RESULT

**Not reached — parked at protocol step 1.** No backtest, fill, cost,
or latency number exists; nothing was produced before (or after) the
Task-12 router timing-parity check. No Tier-1 number exists either.
Phase B was never authorized.

## 9. CAPACITY & CROWDING

Declared at spec time, never exercised: top-of-book scale,
Sharpe-max target; sizing beyond displayed-depth scale forfeits the
passive economics. Caveat (OQ-3): runtime mechanism-share enforcement
is not active; no deployment claim may rely on it.

## 10. FALSIFICATION CONDITION

Pre-registered F1–F5 (spec): F1 RankIC on pooled in-hour quintile
boundaries; **F2 window-binding** (matched ofi-quintile at :30
refutes hour-checkpoint binding); F3 regime/stratum sign flip; F4
passive realism / `--inv12-stress`; F5 structural boundaries.
**None was evaluated** — the park is a precondition failure, not a
falsification outcome. The criteria stand as written; F2 was
independently adjudicable on power (n = 175) even though step 1
did not clear — never scored under the stop-rule halt.

## 11. STATUS

**hypothesis — parked (power; final card)** (park-rule census: pooled
viable-region in-hour episodes **66 < 100** across evidence pool;
D-only 60; ENSG/MLI +6; F2 arm adjudicable at **175 ≥ 100**; edge
non-empty all six D symbols; infrastructure perfect; Lei
adjudication C.8, 2026-07-18 — **PARK (power) ratified**). Slate
DISPOSITIONS (`docs/research/prompt_pack_11_hypothesis_slate_d.md`).
Trial ledger: **N = 12, unchanged** — census N-neutral; zero outcome
contact; all REGISTERED-UNEVALUATED variants remain unevaluated
(N-impact 0 each).

## 12. NEXT ACTION

**none** for this candidate (final card parked). **Program CLOSED**
on this universe/grid per pack-10 DISPOSITION 2 / pack-11
DISPOSITIONS (stop-rule executed — cycle 3 complete without a
step-2b PASS). The residual fork named in pack-10 / pack-07
(universe **tranche 2** vs stop) is a **fresh capital decision**
requiring its own Lei authorization; nothing in this closure
pre-commits it. Occupancy pre-read discipline for arm-specific
geometry (no cross-card `f_resid` transfer) is registered as
backlog **20**.

## Artifact disposition (hygiene)

Phase-A deliverables (hour-only `ALGO_CLOCK` derivation,
`ofi_integrated_percentile` at h=1800, census instrument, harness IC
row) **remain in place as platform capability**: tested, card-
independent where additive, and no locked parity baseline moved. The
census script `scripts/research/hour_checkpoint_drift_census.py`
remains committed with its owning audit recorded in the
`docs/prompts/README.md` coverage map (research_validation).
