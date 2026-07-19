<!--
  File:   docs/research/sig_sweep_kyle_drift_h900_v1_result.md
  Status: rejected (H10 rejection close-out, 2026-07-16; Lei
          adjudication S.8 — REJECTED per frozen §9 row "2b IC gate",
          ratified). Compact closure record instantiating the R10
          proposal template
          (.cursor/skills/microstructure-alpha/proposal-template.md)
          with what exists. First outcome contact for this candidate
          was the step-2 execution (Task 11-A-H10); N = 12.
  Owner:  microstructure-alpha (candidate) / research-workflow
          (ledger); prompt-pack H10 rejection close-out.

  Provenance (FQ-3 template):
    git_sha: "0ce3d9ece62c33886dbf6707fa4762c277eb4b15" (HEAD at this
      task's start = Task 11-A-H10 step-2 evidence commit; this
      close-out commit is the first after it and carries S.8
      ADJUDICATION, this result doc, slate-C disposition close-out,
      and the previously untracked formal_spec.md)
    worktree_clean: "at task start: tracked tree clean after
      0ce3d9e; formal_spec.md untracked sibling (freeze-allowed) —
      committed by this close-out"
    pythonhashseed: "n/a — no scripted analysis run in this task
      (adjudication + close-out only; every number below is quoted
      from the committed protocol record / artifacts). Artifact
      SHA-256s re-verified byte-identical this session before
      commit."
    normative_inputs:
      sig_sweep_kyle_drift_h900_v1_formal_spec.md (Task-7 frozen
        spec),
      sig_sweep_kyle_drift_h900_v1_validation_protocol.md (frozen
        protocol + CENSUS RESULTS + AMENDMENTS A-1/A-2 + STATISTICAL
        RESULTS S.1–S.7 + ADJUDICATION S.8),
      docs/research/artifacts/sig_sweep_kyle_drift_h900_v1/
        (boundaries_extract_2026-07-16.json
        sha256=522e0ff14c1986a6099ba7a9523f9a4b488b9730ab3d1ba09d4458da6d8f0c25,
        validation_stats_2026-07-16.json
        sha256=4735b20a937ba7382f4108b29138d365892616f10824ce856bce18e7ff9cd9ea),
      docs/research/artifacts/sweep_kyle_drift_census_2026-07-16.json
        (sha256=a2f49e6bb7e32e68c5b776a106b4b27d9aa1218a9e1ed5af5f8a3dffe5eb7829),
      prompt_pack_09_hypothesis_slate_c.md (H10 card, trial ledger,
        DISPOSITIONS).
-->

# `sig_sweep_kyle_drift_h900_v1` — closure record (rejected)

**Verdict first.** The pre-registered step-2b RankIC gate (executed
2026-07-16 under the frozen protocol, Ordering B harness path, from
commit `0ce3d9e`) **FAILED** at the frozen conjunctive bars. Lei
adjudicates **REJECTED** per frozen §9 row **"2b IC gate"**, ratified
(protocol S.8). Failure decomposition: **magnitude PASSED**
(+0.089 ≥ 0.03); **significance FAILED** n-variantly (p 0.288; no
legal rescue inside the frozen pool); **F2 mechanism tie FAILED**
(no λ elevation, no same-direction volume co-travel) — the KYLE
attribution is refuted in-sample and is the governing substance of
the rejection. The sequence halted inside step 2b; steps 2.3, JC-5,
2.4, 3, 4, 4.4, 5, 6, 7, and 8 **never executed and no statistic
exists for them**.

All twelve R10 sections follow; cost figures are one-way, per-fill,
bps of fill notional (00b convention).

## 1. SIGNAL

When institutional traders with short-half-life information execute
with intermarket sweep orders, paying take fees and through-prices is
rational only when immediacy value exceeds patience — urgency reveals
information — which must leak into L1 as clusters of condition-14
(ISO) prints. Permanent impact (Kyle) continues over **H = 900 s**; a
**passive same-side entry** harvests the remainder at maker cost.
State variables: `sweep_flow_imbalance` (signed, Class-A ∩ id-14
filtered) at extreme decile (`percentile ≥ 0.90` LONG / `≤ 0.10`
SHORT) ∧ `P(vol_breakout) < 0.7` ∧ `realized_vol_30s_zscore ≤ 3.0`
∧ SFI sign agreement. `horizon_seconds = 900`. (Spec §0/§1,
unchanged from the pre-registered card.)

## 2. ARCHETYPE & COUNTERPARTY

Archetype **informed-flow-following via certified ISO sweeps**;
structural counterparty: resting LPs lifted across venues before
repricing — their adverse-selection losses fund the continuation.
`TrendMechanism` family `KYLE_INFO`; `expected_half_life_seconds =
450` (envelope 60–1800 ✓; horizon ratio 2.0 ∈ [0.5, 4.0] ✓). Evidence
/ deployable set frozen **{APP, RMBS}** (DISPOSITIONS 4; Tranche-1B
out of scope).

## 3. STATE VARIABLES

Entry-warm set: **`sweep_flow_imbalance` 1.0.0** (NEW; Trade + NBBO
mid/tick-rule prior; Class-A ∩ id-14 + correction drop; warm ≥ 20
eligible prints / 900 s), `realized_vol_30s` 1.3.0 (gate backstop),
`kyle_lambda_60s` 2.0.0 causal (**F2 diagnostic only** — not on the
entry path). Consumed h=900 features:
`sweep_flow_imbalance`, `sweep_flow_imbalance_percentile`,
`realized_vol_30s_zscore`; λ percentile reported for F2.
Highest-mirage residual: L6 tick-rule signing inside the ISO window
(certified-print mirage otherwise LOW, M = 1.0). (Spec §1/§3.)

## 4. PROCESS MODEL

Kyle (1985) dynamic informed-trader incorporation via paid-for
urgency (ISO) — partial-adjustment drift with exponentially decaying
remainder, hl = 450 s. Edge decomposition `edge_ow = κ × σ₉₀₀`,
κ = c_D × f_perm × r_rem × f_H × f_pass with frozen central
**κ = 0.158** and the one-way ratchet (spec §4). F2 required because
delta-hedger sweeps can mimic the print cluster without permanent
impact — λ / volume co-travel is the attribution lock.

## 5. ENTRY-EXIT RULE

Gate ON: `P(vol_breakout) < 0.7` ∧ extreme-SFI decile arm ∧
`realized_vol_30s_zscore ≤ 3.0` ∧ SFI sign agreement; OFF adds
hysteresis on the posterior. Entry: EV-gated continuation (WITH the
sweep imbalance), LONG/SHORT side-symmetric, passive/maker. Exits:
hazard spike, gate-OFF FLAT close, `HARD_EXIT_AGE` 900 s (2 × hl).
Session discipline: no entry in the first 300 s; flatten from 15:50
ET. Warm/stale: entries suppressed on any cold/stale entry-warm id;
exits never suppressed. (Spec §5/§6 draft `evaluate` — Phase B never
built.)

## 6. L2 LOSS ACCOUNTING

Spec §9 ledger adopted; binding row is L2 queue composition —
passive entry into a continuation move is the structurally adverse
fill geometry. Adopted first-class via the fill-hazard model +
sensitivity grid + filled-vs-unfilled markout diagnostics (spec §11).
**Never exercised:** the sequence rejected at step 2b before any fill
was simulated. Phase B YAML / router path was never authorized.

## 7. STATISTICAL RESULT

**FAIL at protocol step 2b** (first-FAIL stop rule; steps 2.3–8 not
computed). Step 2a (harness sign-golden through the real pipeline)
passed 7/7 first. The step-2b table, verbatim from the protocol S.4
record (pooled {APP ∪ RMBS}, viable-region primary eligible episodes,
h = 900; RankIC = Spearman ρ, p = Fisher-z two-sided):

| criterion | bar | observed | n-class | verdict |
|---|---|---|---|---|
| extreme-SFI pooled RankIC sign | > 0 | +0.0893 | n-invariant | **PASS** |
| extreme-SFI pooled \|RankIC\| | ≥ 0.03 | 0.0893 | n-invariant | **PASS** |
| extreme-SFI pooled Fisher-z p | ≤ 0.01 | 0.288 | n-variant | **FAIL** |
| pooled sample minimum | n ≥ 100 | 152 (IC-pair 144) | n-variant | **PASS** |
| interior contrast | contrast > 0 AND interior not sig-positive | +0.0586; interior t 0.22 | n-invariant | **PASS** |
| F2 λ / volume co-travel | ≥ 1 material positive contrast | both absent / negative | mechanism | **FAIL** |
| per-symbol diagnostics | reported (non-governing) | APP +0.083 (n=89, p=0.44); RMBS +0.226 (n=55, p=0.097) | diagnostic | **PASS** (reported) |
| bucket monotonicity | top−bottom > 0 | +10.52 bps | n-invariant | **PASS** |
| conditional tail | mean > 0 with t ≥ 2 | +2.86 bps, **t 0.82** | sign n-inv; t n-var | **FAIL** |

Supporting quantities (S.4): episode n = 152 (APP 94 / RMBS 58);
IC-pair n = 144 (8 end-session drops); F2 λ pctl contrast −0.014;
F2 print-volume contrast −19,407; interior RankIC +0.0306 (n=517,
p 0.487). Full record: protocol S.1–S.8; artifacts under
`docs/research/artifacts/sig_sweep_kyle_drift_h900_v1/` (extraction
and statistics each run twice, bit-identical).

## 8. EXECUTION RESULT

**Not reached — rejected at step 2b (Phase B never built).** No
backtest, fill, cost, latency, CPCV, DSR, or sensitivity number
exists for this candidate; nothing was produced at any execution
tier. The Task-12 router timing-parity precondition (P0-6) was
verified 2026-07-12 but steps 7–8 were never unlocked by the
statistics. Phase B (YAML, loader-compiled `evaluate`, config) was
gated on step-2 PASS and was never authorized.

## 9. CAPACITY & CROWDING

Declared at spec time, never exercised: top-of-book scale,
Sharpe-max target; sizing beyond displayed-depth scale forfeits the
passive economics. Taker was closed at design for this κ band — no
taker variant exists.

## 10. FALSIFICATION CONDITION

**F2 fired at the frozen bar** — among primary eligible episodes,
neither `kyle_lambda_60s_percentile` elevation nor same-direction
print-volume elevation versus baseline was present (contrasts
negative). The KYLE attribution is refuted in-sample; this is the
governing substance of the rejection (S.8). **Significance also
failed** (Fisher-z p 0.288 > 0.01) — n-variant, with no legal rescue
inside the frozen pool (n ≈ 680 required at this RankIC vs 144
realized). **Magnitude did not fire** — pooled \|RankIC\| +0.089 ≥
0.03 (~5× H8's H=300 realization). Conditional-tail t 0.82 < 2
reinforces the same §9 row. F1's forward-test form is therefore
split: magnitude cleared; indistinguishability-from-zero at p ≤ 0.01
and the mechanism tie did not. F3–F5 were never evaluated (steps
4/7/8 not reached).

## 11. STATUS

**rejected** (step-2b IC gate, §9 row "2b IC gate"; Lei adjudication
S.8, 2026-07-16 — REJECTED ratified; magnitude PASSED; significance
FAILED n-variantly with no legal pool rescue; F2 FAILED and governs
substance). Slate DISPOSITIONS
(`docs/research/prompt_pack_09_hypothesis_slate_c.md`). Trial
ledger: **N = 12** — the step-2 execution was the H10 primary row's
first outcome contact (FQ-6B-R); zero exploratory variants were
evaluated; the spec §13 drafted-not-evaluated rows remain N-impact 0
and are NOT authorized by this close-out (any future evaluation is a
new trial, +1 N, own protocol from step 1). **Steps 2.3–8 never
executed — no statistics exist for them**, and none may be quoted.

## 12. NEXT ACTION

**none** (rejected). Slate C is fully adjudicated (DISPOSITIONS
close-out): H10 rejected; H9 contingent card ADJUDICATED to
presumptive death despite the magnitude-trigger gap; H11 remains NOT
SELECTED. Living ledger **N = 12**. No slate-C candidate proceeds to
Phase B or step 3.

## POST-HOC OBSERVATIONS (in-sample, outcome-contaminated — hypothesis seed ONLY)

**Labeling first: everything in this section was observed in the H10
evidence sample AFTER outcome contact. It is in-sample,
outcome-contaminated, carries zero evidential weight, and is
recorded solely as a hypothesis seed.** Any future card built on
either observation requires **fresh sessions** (no reuse of the
20-session H10 evidence grid for confirmation) and **honest-N
accounting** (its first outcome contact is +1 N on the living
ledger; **N ≥ 13** at that first contact).

1. **RMBS per-symbol diagnostic RankIC +0.226** (n = 55, p = 0.097)
   — larger point estimate than the pooled +0.089 / APP +0.083, but
   non-governing by JC-5 / §2.2.1 (diagnostics only; JC-5 acts only
   on a primary 2b PASS, which did not occur). Contaminated seed;
   fresh-evidence + honest-N required; **N ≥ 13 at first contact**.

2. **H = 300 → H = 900 magnitude improvement** — H8's primary
   λ-elevated RankIC was **+0.0186** (failed the 0.03 floor); H10's
   extreme-SFI RankIC is **+0.089** (cleared the floor, ~5×). Both
   figures are **sub-proof**: H8 failed magnitude; H10 failed
   significance and F2. Neither number is an economic result, a
   horizon-calibration finding, or a prior for any future card.
   Seed only; no card is drafted here.
