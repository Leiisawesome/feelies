<!--
  File:   docs/research/sig_halfhour_clock_drift_h900_v1_result.md
  Status: hypothesis — parked (power) (H12 park close-out, 2026-07-17;
          Lei ratifies the census verdict per frozen §1.5). Compact
          closure record instantiating the R10 proposal template
          (.cursor/skills/microstructure-alpha/proposal-template.md)
          with what exists. No outcome statistic (forward return, IC,
          Sharpe, CPCV, DSR, execution number) exists for this
          candidate; N unchanged at 12. PARK ≠ refutation.
  Owner:  microstructure-alpha (candidate) / research-workflow (ledger);
          prompt-pack H12 park close-out + H13 activation.

  Provenance (FQ-3 template):
    git_sha: "516b233c05ea1007a3f762bc5e8639af9476a787" (HEAD at this
      task's start = latest H12 census SHA-align commit; this close-out
      is the first commit after it — no scripted analysis run in this
      task; every number below is quoted from the committed census
      record or the frozen spec/protocol)
    worktree_clean: "at task start: tracked tree clean after 516b233;
      formal_spec.md untracked sibling (freeze-allowed) — committed
      by this close-out with Status updated to parked"
    pythonhashseed: "n/a — no scripted analysis run in this task
      (adjudication + close-out only). Artifact SHA-256 re-verified
      byte-identical this session before commit."
    normative_inputs:
      sig_halfhour_clock_drift_h900_v1_formal_spec.md (Task-7 frozen
        spec),
      sig_halfhour_clock_drift_h900_v1_validation_protocol.md (frozen
        protocol + CENSUS RESULTS C.0–C.7 + ADJUDICATION C.8),
      docs/research/artifacts/halfhour_clock_drift_census_2026-07-17.json
        (sha256=3d0783bf60afb4ca94c857690c0237dc7c742daba8494af89938714722bbf5a3;
         census commit 3ed79a6),
      prompt_pack_11_hypothesis_slate_d.md (H12 card + DISPOSITIONS;
        H13 contingent triggers),
      prompt_pack_11a_slate_d_review.md (κ 0.172 minimum-rule /
        0.189 factor-product bug logged).
-->

# `sig_halfhour_clock_drift_h900_v1` — closure record (hypothesis — parked (power))

**Verdict first.** The pre-registered step-1 park-rule census (commit
`3ed79a6`, executed 2026-07-17 under the frozen protocol) fired the
§1.5 **power floor** before a single IC number existed. Pooled
viable-region in-window episodes = **59 < 100**. The F2 arm is
independently **F2-INSUFFICIENT** (out-window viable-region n =
**89 < 100**, JC-9). Edge axis non-empty on both symbols (APP 40 /
RMBS 19). Infrastructure perfect (calendar-warm **1.000**,
`calendar_missing_rate` **0**, determinism green). The sequence
halted at protocol step 1; steps 2–8 never ran. Lei ratifies
**PARK (power)** per frozen §1.5 (protocol C.8).

**PARK ≠ refutation: F1–F5 never ran; zero outcome contact; N = 12.**
No claim is made that the half-hour scheduled-flow mechanism does
not exist — only that the pre-registered pooled in-window episode
count is below the census floor as realized on the frozen
{APP, RMBS} × 20-session grid.

All twelve R10 sections follow; cost figures are one-way, per-fill,
bps of fill notional (00b convention).

## 1. SIGNAL

Institutional execution algos slice parent orders on a **30-minute
wall-clock grid** (10:00, 10:30, … ET) because schedule adherence and
participation-rate caps are specified in clock time, which must leak
into L1 as elevated signed quote-flow imbalance in half-hour-aligned
decision windows. Residual permanent impact of the still-open parent
continues over the next **H = 900 s**. Clock binding is load-bearing:
the same flow extreme **off** the half-hour grid must not produce the
same continuation. State: `ofi_integrated` quintile
(`percentile ≥ 0.80` LONG / `≤ 0.20` SHORT) ∧ `W_hh` (half-hour
`ALGO_CLOCK` / `scheduled_flow_window_active`) ∧
`P(vol_breakout) < 0.7`. `horizon_seconds = 900`. (Spec §0/§1,
unchanged from the pre-registered card.)

## 2. ARCHETYPE & COUNTERPARTY

Archetype **schedule-bound flow-following** (`SCHEDULED_FLOW`).
Actor: clock-sliced institutional parent. Counterparty: LPs and
discretionary flow that under-react to predictable clock pressure.
Conservation: edge ≤ residual impact of open scheduled parents across
the half-hour grid. `expected_half_life_seconds = 450` (envelope ✓;
horizon ratio 2.0 ∈ [0.5, 4.0] ✓). Evidence / deployable set frozen
**{APP, RMBS}** pooled.

## 3. STATE VARIABLES

Entry-warm set: `scheduled_flow_window` (calendar-warm; `ALGO_CLOCK`
half-hour YAML per operative date), `ofi_integrated` /
`ofi_integrated_percentile` at h = 900 (quote-fed),
`realized_vol_30s` (gate). **No `spread_z_30d`.** No NEW trade-fed
sensor. Highest-mirage residual: OFI manufacture on a known clock
(MIXED, M = 1.5). (Spec §1/§3.)

## 4. PROCESS MODEL

Scheduled residual permanent-impact continuation — partial adjustment
with exponentially decaying remainder, hl = 450 s. Edge decomposition
`edge_ow = κ × σ₉₀₀`, κ = c_D × f_perm × r_rem × f_H × f_pass with
frozen central **κ = 0.146** and the one-way ratchet (spec §4). F2
required because unclocked OFI continuation can mimic the entry arm
without schedule binding.

## 5. ENTRY-EXIT RULE

Gate ON: `P(vol_breakout) < 0.7` ∧ half-hour `W_hh` ∧ OFI quintile ∧
sign agreement ∧ vol-z backstop; OFF adds hysteresis. Entry: EV-gated
continuation WITH the OFI imbalance, LONG/SHORT side-symmetric,
passive/maker. Exits: hazard spike, gate-OFF FLAT close,
`HARD_EXIT_AGE` 900 s (2 × hl). Session discipline: 09:35–15:50 ET.
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
quantity was the unconditional session σ₉₀₀, authorized by frozen §1):

### Shortfall attribution (design → all-cell → viable)

| arm | design-central | measured all-cell | measured viable-region | vs census floor ≥ 100 |
|---|---|---|---|---|
| in-window (primary) | **147.7** | **68** | **59** | **FAIL** (59) |
| out-window (F2 counts) | **160.1** | **105** | **89** | **F2-INSUFFICIENT** (89) |

**Per-arm attrition** (census C.4, as reported):

| symbol | in-window all → viable | out-window all → viable |
|---|---|---|
| APP | 43 → **40** | 38 → **36** |
| RMBS | 25 → **19** | 67 → **53** |
| **pooled** | 68 → **59** | 105 → **89** |

Edge axis non-empty on both symbols; warm-drop did not fire;
infrastructure PASS. Deployable set before power park would have been
D = {APP, RMBS}. Power park governs — card does not PROCEED.

### Percentile-exemption lesson

Non-percentile arms (window × sign-agreement × gate) are **design
priors that required measured pre-reads**. Realized/design all-cell
in-window ratio on this card: 68/147.7 ≈ **0.46×**. Contrast:

| card | conditioning class | realized / design-central | source |
|---|---|---|---|
| H8 | non-percentile joint occupancy prior | ≈ **0.55×** (81 ≪ 147) | pack-10 §1.2 |
| **H12** | window × quintile × gate (quintile exempt; window/gate not) | ≈ **0.46×** (68 / 147.7) | census `3ed79a6` / C.4 |
| H10 | **percentile-exempt** decile × ISO-warm | ≈ **1.04×** (152 / 146.2) | pack-10 §1.2 |

**Percentile-exemption is arm-scoped, not card-scoped.** Exempting
the quintile tail does not exempt the clock-window, gate, or
sign-agreement arms from occupancy pre-reads. Registered as backlog
**19**.

Full record: protocol CENSUS RESULTS C.0–C.7 + ADJUDICATION C.8;
artifact `docs/research/artifacts/halfhour_clock_drift_census_2026-07-17.json`
(sha256 `3d0783bf60afb4ca94c857690c0237dc7c742daba8494af89938714722bbf5a3`).

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

Pre-registered F1–F5 (spec): F1 RankIC on pooled in-window quintile
boundaries; **F2 window-binding** (matched ofi-quintile off-clock
refutes); F3 regime/stratum sign flip; F4 passive realism /
`--inv12-stress`; F5 structural boundaries. **None was evaluated** —
the park is a precondition failure, not a falsification outcome. The
criteria stand as written; F2 was independently unadjudicable on
power (n = 89) even had step 1 cleared.

## 11. STATUS

**hypothesis — parked (power)** (park-rule census `3ed79a6`: pooled
viable-region in-window episodes **59 < 100**; F2 arm
F2-INSUFFICIENT at **89 < 100**; edge non-empty both symbols;
infrastructure perfect; Lei adjudication C.8, 2026-07-17 —
**PARK (power) ratified**). Slate DISPOSITIONS
(`docs/research/prompt_pack_11_hypothesis_slate_d.md`). Trial ledger:
**N = 12, unchanged** — census N-neutral; zero outcome contact; all
REGISTERED-UNEVALUATED variants remain unevaluated (N-impact 0 each).

## 12. NEXT ACTION

**H13 activated** under pack-11 DISPOSITIONS 2 trigger **(a)** (H12
design/census death). Next falsifying step is the H13 Task-7/8 path
for `sig_hour_checkpoint_drift_h1800_v1` under its pre-registered
conditions: **κ frozen 0.172** (minimum rule; the 0.189
factor-product bug remains a logged card deviation — factors are not
restated to erase the freeze); **pool-collapse floor behavior must
be frozen into the H13 protocol before any H13 census** (11a §2e
axis-split: 6→221.6 … 3→110.8 clears census ≥100 / fails design ≥130;
2→73.9 fails both). Stop-rule: H12 park counts toward closure; H13
is the **final card** — death at any gate closes the program.
Occupancy pre-read discipline for every non-percentile conditioning
arm is registered as backlog **19**.

## Artifact disposition (hygiene)

Phase-A deliverables (`WindowKind.ALGO_CLOCK`, half-hour calendars,
`ofi_integrated_percentile` factory, census instrument, harness IC
row) **remain in place as platform capability**: tested, card-
independent where additive, and no locked parity baseline moved. The
census script `scripts/research/halfhour_clock_drift_census.py`
remains committed with its owning audit recorded in the
`docs/prompts/README.md` coverage map (research_validation).
