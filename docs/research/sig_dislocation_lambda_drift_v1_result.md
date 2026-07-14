<!--
  File:   docs/research/sig_dislocation_lambda_drift_v1_result.md
  Status: rejected (H8 rejection close-out, 2026-07-14; Lei
          adjudication S.8 — REJECTED governs, §9 row "2b IC gate";
          the A-2.1 safeguard park fired but is subordinate).
          Compact closure record instantiating the R10 proposal
          template
          (.cursor/skills/microstructure-alpha/proposal-template.md)
          with what exists. First outcome contact for this candidate
          was the step-2 execution (Task 11); N = 11.
  Owner:  microstructure-alpha (candidate) / research-workflow
          (ledger); prompt-pack H8 rejection close-out, Phase B.

  Provenance (FQ-3 template):
    git_sha: "8e6f94dd5d97018a04bfec587c382a2e673cc06a" (HEAD at this
      task's start = the CPCV-fixture commit that preceded every
      Task-11 evidence run; this close-out commit is the first after
      it and carries the Task-11 STATISTICAL RESULTS + S.8
      ADJUDICATION protocol sections, the two instrument scripts,
      and the artifact directory — all uncommitted at Task-11 report
      time, disclosed there)
    worktree_clean: "at task start: the Task-11 outputs pending
      commit (modified validation protocol; untracked
      dislocation_lambda_validation_extract.py / _stats.py;
      untracked artifacts/sig_dislocation_lambda_drift_v1/) — all
      committed by this close-out"
    pythonhashseed: "n/a — no scripted analysis run in this task
      (adjudication + close-out only; every number below is quoted
      from the committed protocol record). The five S.7 artifact
      SHA-256s were re-verified byte-identical this session before
      commit."
    normative_inputs:
      sig_dislocation_lambda_drift_v1_formal_spec.md (frozen spec
        §1–§16 incl. deviation rows 1–8),
      sig_dislocation_lambda_drift_v1_validation_protocol.md (frozen
        protocol + CENSUS RESULTS + EXPANDED CENSUS + AMENDMENTS
        A-1/A-2 + STATISTICAL RESULTS S.1–S.7 + ADJUDICATION S.8),
      docs/research/artifacts/sig_dislocation_lambda_drift_v1/
        (boundaries_extract_2026-07-14.json sha256=80fdc56c…bf25,
        validation_stats_2026-07-14.json sha256=21014b34…c418,
        sensor_feature_ic_h8_2026-07-14.csv sha256=52fae36f…0130,
        + stdout/stderr captures per S.7),
      prompt_pack_06_hypothesis_slate_b.md (H8 card, trial ledger,
        DISPOSITIONS 1–7).
-->

# `sig_dislocation_lambda_drift_v1` — closure record (rejected)

**Verdict first.** The pre-registered step-2b RankIC gate (executed
2026-07-14 under the frozen protocol and the A-2.1 ruled evidence
set, from commit `8e6f94d`) **FAILED**, basis-independently, at the
frozen conjunctive bars. Lei adjudicates the S.5 two-row conflict to
**REJECTED** (§9 row "2b IC gate" governs; the A-2.1 safeguard park
fired but is subordinate — protocol S.8). The sequence halted inside
step 2b; steps 2.3, 2.4, 3, 4, 4.4, 5, 6, 7, and 8 **never executed
and no statistic exists for them**.

**Scope of the rejection, stated precisely (S.8 correction):** what
is rejected is the **elevated-λ continuation claim at H = 300,
passive, on this universe** (F1 fired at every frozen bar). The
λ-contrast mechanism tie **passed** — the baseline-λ stratum reverts
significantly (−5.4 bps, t −2.5) while the elevated stratum does
not — so the λ-separation phenomenon is *not* refuted by this
record, and no claim of F2 death may cite it.

All twelve R10 sections follow; cost figures are one-way, per-fill,
bps of fill notional (00b convention).

## 1. SIGNAL

When a 300-s price dislocation is produced by trading with elevated
price impact — flow moving price more per unit size than the recent
baseline — the dislocation is information being incorporated (Kyle:
the MM's pricing rule steepens when informed intensity rises) rather
than a liquidity shock (which reverts); incomplete incorporation at
the boundary must leak into L1 as continuation over the next 300 s,
*only* in the impact-elevated stratum. State variables:
`|micro_price_drift| / micro_price ≥ 0.75 × σ₃₀₀,med` (per-symbol
constants APP 25.36 bps, RMBS 23.72 bps) ∧
`kyle_lambda_60s_percentile ≥ 0.5` (trailing-300 s Hazen percentile).
`horizon_seconds = 300`. (Spec §0/§1, unchanged from the
pre-registered card; deviations logged in spec §16.)

## 2. ARCHETYPE & COUNTERPARTY

Archetype **informed-flow-following via the impact fingerprint**;
structural counterparty: liquidity providers and mean-reversion
traders who fade information-driven moves as if they were liquidity
shocks — their fading losses fund the continuation. `TrendMechanism`
family `KYLE_INFO`; `expected_half_life_seconds = 150` (envelope
60–1800 ✓; horizon ratio 2.0 ∈ [0.5, 4.0] ✓). Symbol set {APP
primary, RMBS evidence-only per the expanded census E.4/A-2.1}.

## 3. STATE VARIABLES

Entry-warm set (all existing, registered, DI-09-ingesting; YAML-only
card, no new sensor or wiring): `kyle_lambda_60s` 2.0.0 (Trade,
causal alignment, ≥ 30 (Δp, Δq) pairs / 60 s), `micro_price` 1.1.0
(NBBOQuote, depth-weighted), `realized_vol_30s` 1.3.0 (NBBOQuote,
gate backstop only). Consumed h=300 features: `micro_price_drift`,
`micro_price`, `kyle_lambda_60s_percentile`,
`realized_vol_30s_zscore`. Highest-mirage inputs: L6 tick-rule
signing inside λ and L5 displayed-size weighting inside micro-price
(spec §3/§9).

## 4. PROCESS MODEL

Kyle (1985) dynamic informed-trader incorporation —
partial-adjustment drift with exponentially decaying remainder,
hl = 150 s, τ ≈ 216 s, `f_H = 1 − e^(−300/216) ≈ 0.75`. Edge
decomposition `edge_ow = κ × σ₃₀₀`,
κ = c_D × f_perm × r_rem × f_H × f_pass = 1.3 × 0.6 × 0.5 × 0.75 ×
0.65 = **0.190, frozen** with the one-way ratchet (spec §5). The OU
inventory-reversion model (H2) was the pre-registered null for the
baseline-λ stratum — which is exactly what the data showed (§7,
POST-HOC).

## 5. ENTRY-EXIT RULE

Gate ON: `P(vol_breakout) < 0.7 ∧ |micro_price_drift| ≥ disloc_min ×
micro_price ∧ kyle_lambda_60s_percentile ≥ 0.5 ∧
realized_vol_30s_zscore ≤ 3.0`; OFF adds hysteresis margins 0.15 on
the posterior and λ axes (the λ release doubles as the
mechanism-lapse exit). Entry: EV-gated continuation (WITH the
dislocation), LONG/SHORT side-symmetric, passive/maker. Exits:
hazard spike, gate-OFF FLAT close, `HARD_EXIT_AGE` 300 s (2 × hl).
Session discipline: no entry in the first 300 s; flatten from 15:50
ET. Warm/stale: entries suppressed on any cold/stale entry-warm id;
exits never suppressed; D-1 NaN guard (spec §16 row 8). (Spec §6.)

## 6. L2 LOSS ACCOUNTING

Spec §9 ledger adopted in full; the binding row is L2 queue
composition — passive entry into a continuation move is the
structurally adverse fill geometry (the resting order fills when the
move retraces or stalls), adopted first-class via spec §12
(fill-hazard model + 3×3×3 sensitivity grid + filled-vs-unfilled
markout diagnostics). **Never exercised:** the sequence rejected at
step 2b before any fill was simulated.

## 7. STATISTICAL RESULT

**FAIL at protocol step 2b** (first-FAIL stop rule; steps 2.3–8 not
computed). Step 2a (sign-golden through the real pipeline) passed
7/7 first. The step-2b table, verbatim from the protocol S.4 record
(pooled {APP ∪ RMBS-evidence-only}, viable-region sessions, h = 300;
RankIC = Spearman ρ, p = Fisher-z two-sided):

| basis | λ-elevated n | RankIC | p | λ-baseline n | RankIC | p | contrast |
|---|---|---|---|---|---|---|---|
| including-flagged | 1,231 | +0.0164 | 0.567 | 1,173 | −0.0645 | 0.027 | +0.0808 |
| **primary (binding)** | **1,042** | **+0.0186** | **0.548** | **975** | **−0.0871** | **0.0065** | **+0.1057** |
| binary (H2, saturates) | 193 | −0.0340 | 0.640 | 171 | −0.1144 | 0.137 | +0.0804 |

APP-only (per-symbol + A-2.1 safeguard): including-flagged n = 657,
RankIC +0.0464, p 0.235; **primary n = 579, RankIC +0.0327,
p 0.433**. Supporting rows (primary basis): baseline
matched-dislocation continuation-signed mean **−5.43 bps** (n = 373,
SE 2.17, t = −2.50 — the baseline-λ stratum reverts, significantly);
elevated-stratum bucket top-minus-bottom spread +6.89 bps;
conditional tail on the 135 APP viable-region primary episodes
+5.38 bps, t = 1.41.

Scored against the frozen conjunctive gate: sign, n ≥ 1,000 (1,231),
λ-contrast, per-symbol APP sign/n, and bucket spread **PASS**;
|RankIC| ≥ 0.03 (0.0186), Fisher-z p ≤ 0.01 (0.548), conditional
tail t ≥ 2 (1.41), and the A-2.1 APP safeguard p ≤ 0.05 (0.433)
**FAIL**. The failure is **basis-independent** (every contamination
basis fails the same bars). Full record: protocol S.1–S.7; artifacts
under `docs/research/artifacts/sig_dislocation_lambda_drift_v1/`
(extraction and statistics each run twice, bit-identical).

## 8. EXECUTION RESULT

**Not reached — rejected at protocol step 2b.** No backtest, fill,
cost, latency, CPCV, DSR, or sensitivity number exists for this
candidate; nothing was produced at any execution tier. The Task-12
router timing-parity precondition (P0-6) was verified 2026-07-12 but
steps 7–8 were never unlocked by the statistics.

## 9. CAPACITY & CROWDING

Declared at spec time, never exercised: top-of-book scale (≈ 80-share
reference fill APP, 100-share lots RMBS,
`platform_min_order_shares = 50` respected), Sharpe-max target;
sizing beyond displayed-depth scale forfeits the passive economics.
Taker was closed at design universe-wide (κT_req 0.449) — no taker
variant exists.

## 10. FALSIFICATION CONDITION

**F1 fired at the frozen bar** — the pre-registered forward test
(continuation-signed conditional 300 s forward return at the joint
condition) is indistinguishable from zero at every frozen criterion:
|RankIC| 0.0186 < 0.03, Fisher-z p 0.548 > 0.01, conditional tail
t 1.41 < 2, APP safeguard p 0.433 > 0.05. The 8-F conjunctive design
rejects exactly this configuration by construction; the magnitude
bar is n-invariant, so this is not a power shortfall (S.8 item 3).
**F2 (the λ-contrast mechanism tie) PASSED** — baseline reverts
(−5.4 bps, t −2.5; stratum RankIC −0.0871, p 0.0065), elevated does
not; the λ arm does work. F3–F5 were never evaluated (steps 4/7/8
not reached). The rejection is of the elevated-λ continuation claim
at H = 300 passive on this universe — not of the λ-separation
phenomenon.

## 11. STATUS

**rejected** (step-2b IC gate, §9 row "2b IC gate"; Lei adjudication
S.8, 2026-07-14 — REJECTED governs; the A-2.1 safeguard park fired
but is subordinate: a safeguard tightens a pass and cannot loosen a
primary fail; §9 freeze seniority; the magnitude bar is n-invariant
at pooled 0.0186; the APP p-path needs ≈ 3,600 boundaries ≈ 110
sessions, beyond authorized programs). Slate DISPOSITIONS 5–7
(`docs/research/prompt_pack_06_hypothesis_slate_b.md`). Trial
ledger: **N = 11** — the step-2 execution was the H8 primary row's
first outcome contact (FQ-6B-R); zero exploratory variants were
evaluated; the spec §14 drafted-not-evaluated rows remain N-impact 0
and are NOT authorized by this close-out (any future evaluation is a
new trial, +1 N, own protocol from step 1). **Steps 3–8 never
executed — no statistics exist for them**, and none may be quoted.

## 12. NEXT ACTION

**Slate-B program retrospective** (the mandated next task, before
any slate C): slate B is now fully adjudicated with zero survivors —
H6/H7 not-selected at review, H8 rejected at step 2b — and the
program has consumed two full validation sequences (H2 parked at
step 1, H8 rejected at step 2b) at N = 11 with no candidate
reaching step 3. The retrospective must examine, against the
committed records only: (a) whether the feasibility-map pre-filter
plus census plus conjunctive IC gate is correctly calibrated to the
realized effect-size regime of this universe at these horizons
(H8's binding failure was magnitude, 0.0186 vs 0.03 — n-invariant);
(b) whether the midcap L1 grid can power per-symbol significance
bars at all (the ≈ 110-session arithmetic of S.8); and (c) what the
POST-HOC baseline-reversion observation implies for where mechanism
evidence actually concentrates. Output: a program-level
recommendation (universe tranche 2 per backlog entry 11, horizon
re-scoping, or bar re-derivation as a documented architectural
review — never a per-card threshold edit).

## POST-HOC OBSERVATIONS (in-sample, outcome-contaminated — hypothesis seed ONLY)

**Labeling first: everything in this section was observed in the H8
evidence sample AFTER outcome contact. It is in-sample,
outcome-contaminated, carries zero evidential weight, and is
recorded solely as a hypothesis seed.** Any future card built on it
requires **fresh sessions** (no reuse of the 20-session H8 evidence
grid for confirmation) and **honest-N accounting** (its first
outcome contact is +1 N on the living ledger; N ≥ 11 at that point).

The observation: the **baseline-λ stratum reverts** — matched
dislocations (≥ 0.75σ) with `kyle_lambda_60s_percentile < 0.5`
showed continuation-signed mean **−5.43 bps** (n = 373, SE 2.17,
t = −2.50; stratum RankIC −0.0871, Fisher-z p 0.0065, primary
basis), consistent across contamination bases (including-flagged
−0.0645, p 0.027). In H8's own process-model terms this is the OU
liquidity-shock null behaving as predicted: dislocations *without*
the impact fingerprint revert at H = 300. A dislocation-reversion
card conditioned on *baseline* λ (fade, not follow) is the natural
seed — but note it was H8's contrast arm, selected into view by this
sample; the reversion magnitude sits near the single-stress floor
(≈ 4.7–5.5 bps) and passive-fade economics on a reverting leg carry
the H2-class L2 adverse-fill geometry. Seed only; no card is drafted
here.
