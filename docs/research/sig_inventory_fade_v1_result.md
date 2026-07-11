<!--
  File:   docs/research/sig_inventory_fade_v1_result.md
  Status: hypothesis — parked (park close-out, 2026-07-11; Lei upholds
          the census verdict). Compact closure record instantiating the
          R10 proposal template
          (.cursor/skills/microstructure-alpha/proposal-template.md)
          with what exists. No outcome statistic (forward return, IC,
          Sharpe, CPCV, DSR, execution number) exists for this
          candidate; N unchanged at 10.
  Owner:  microstructure-alpha (candidate) / research-workflow (ledger);
          prompt-pack park close-out, Phase B.

  Provenance (FQ-3 template):
    git_sha: "642d12d0bf705b93c61cfbecab3825cf8b9cee7a" (census
      execution commit = HEAD at this task's start; this close-out is
      the first commit after it — no scripted analysis run in this
      task; every number below is quoted from the committed census
      record or the frozen spec/protocol)
    worktree_clean: "yes at task start (git status --porcelain empty)"
    pythonhashseed: "n/a — no scripted run in this task"
    normative_inputs:
      sig_inventory_fade_v1_formal_spec.md (frozen spec incl. §15
        ruling and §16 deviations),
      sig_inventory_fade_v1_validation_protocol.md (frozen protocol +
        appended CENSUS RESULTS C.1–C.7),
      docs/research/artifacts/inventory_fade_census_2026-07-11.json
        (sha256=3ab881f5974b20554558f3d097c6d4e92486df7cf726ecd547
        ae8ce95a4c2cb0),
      prompt_pack_04_hypothesis_slate.md (DISPOSITIONS 4–6, ledger).
-->

# `sig_inventory_fade_v1` — closure record (hypothesis — parked)

**Verdict first.** The pre-registered step-1 park-rule census (commit
`642d12d`, executed 2026-07-11 under the frozen protocol) fired **both**
§1.4 park conditions before a single IC number existed. The sequence
halted at protocol step 1; steps 2–8 (F1–F5, CPCV, DSR, execution
overlay, sensitivity grid) never ran. Lei upholds the verdict.

**PARK ≠ refutation: F1–F5 never ran; the economic-viability
precondition failed on this universe/grid/cost structure.** No claim is
made that the inventory-fade mechanism does not exist — only that the
pre-registered deployable region is empty as realized on the frozen
80-cell grid at the frozen cost floors.

All twelve R10 sections follow; cost figures are one-way, per-fill, bps
of fill notional (00b convention).

## 1. SIGNAL

An impatient uninformed seller (or their broker schedule — redemption,
hedge, deadline) demands immediacy in size, forcing market makers to
warehouse unwanted inventory; capital- and variance-constrained MMs
concede price temporarily to shed it, which leaks into L1 as one-sided
inferred aggressor flow with *unstressed* spreads, followed by reversion
of the temporary concession. State variable: `inventory_pressure`
(dimensionless ∈ [−1, 1], `Σ(−aggressor·size)/Σsize` over trailing
60 s). Claim: conditional on `|inventory_pressure| ≥ 0.5` in the benign
stratum, the 120 s forward return is positive in the fade direction.
`horizon_seconds = 120`. (Spec §0/§1, unchanged from the pre-registered
card.)

## 2. ARCHETYPE & COUNTERPARTY

Archetype **liquidity provision**; structural counterparty: the
urgency-constrained uninformed trader, whose binding mandate funds the
immediacy premium. `TrendMechanism` family `INVENTORY`;
`expected_half_life_seconds = 40` (envelope 5–60 ✓; horizon ratio
3.0 ∈ [0.5, 4.0] ✓).

## 3. STATE VARIABLES

Entry-warm set: `inventory_pressure` (Trade feed, 60 s / ≥ 20 trades),
`spread_z_30d` (NBBOQuote, 6000-quote window), `realized_vol_30s`
(NBBOQuote, 30 s / ≥ 16 returns). Confirmation-only (off the entry
path): `quote_replenish_asymmetry` (L5 mirage risk — distributional use
only). Highest-mirage input is the L6 tick-rule aggressor inference
inside `inventory_pressure` (spec §1.1/§8). All sensors existing,
registered, DI-09-ingesting; no condition filter at runtime.

## 4. PROCESS MODEL

Inventory-control mean reversion (Ho–Stoll 1981 / Madhavan–Smidt 1991):
OU-type exponential decay of the temporary concession, τ = 40/ln 2 ≈
57.7 s. Zero-integrated-edge conservation: the counterparty's mandate
(completion priced above price improvement) funds the concession; the
MM recovers it as the fade pays. Edge decomposition
`edge_ow = κ × σ₁₂₀`, κ ∈ [0.06, 0.30] central 0.16 (spec §3/§4.1).

## 5. ENTRY-EXIT RULE

Gate ON: `P(normal) > 0.6 ∧ |inventory_pressure| > 0.5 ∧
spread_z_30d ≤ 1.0`; OFF: `P(vol_breakout) > 0.3 ∨ spread_z_30d > 2.0
∨ realized_vol_30s_zscore > 3.0` (hysteresis `posterior_margin = 0.20`).
Entry: EV-gated fade (`edge_bps ≥ 5.0` stressed anchor encoded in the
pure logic), LONG on p > 0, SHORT on p < 0, passive/maker. Exits:
hazard spike, gate-OFF FLAT close, `HARD_EXIT_AGE` 80 s (2 × hl).
Session discipline: no entry before 09:35 or after 15:50 ET. Warm/stale:
entries suppressed when any entry-warm id is cold or stale; exits never
suppressed. (Spec §5.2–§5.4.)

## 6. L2 LOSS ACCOUNTING

Spec §8 ledger adopted in full; the binding row is L2 queue
composition — passive fills are conditionally adverse (filled exactly
when reversion fails), adopted first-class via Amendment F (fill-hazard
model + sensitivity grid + fill-mix diagnostics). Never exercised: the
sequence parked before any fill was simulated.

## 7. STATISTICAL RESULT

**Not reached — parked at protocol step 1.** No forward return, IC,
RankIC, CPCV, or DSR number exists for this candidate. The deciding
evidence is the census (no outcome statistic; the only return-like
quantity was the unconditional session σ₁₂₀, authorized by frozen §1):

- **Park condition 1 — viable σ-region empty as realized:** realized
  σ₁₂₀ spans 7.7–32.3 bps across the 80 cells vs per-symbol thresholds
  of 29.1–38.8 bps. Exactly **1/70** floored cells is viable
  (APP/2026-04-10, σ₁₂₀ = 32.3), and its single eligible boundary is
  **contamination-flagged** → viable-region contamination-excluded
  eligible episodes = 0 for every grid symbol.
- **Park condition 2 — power floor ≥ 100 unreachable:** maximum
  viable-region count = 0; even ungated by σ-viability the per-symbol
  maximum is **35** (RMBS). Deployable candidate set D = ∅.
- **Robust to the §11.1 correction:** the verdict does not hinge on the
  2.0 vs 4.0 bps adverse-selection choice — thresholds at the rejected
  §15(ii) vertex (≈ 57–67 bps) only empty the region further, and
  dropping the σ floor entirely still fails on power.

Full record: protocol CENSUS RESULTS C.1–C.7; artifact
`docs/research/artifacts/inventory_fade_census_2026-07-11.json`
(bit-identical on full-grid re-run).

## 8. EXECUTION RESULT

**Not reached — parked at protocol step 1.** No backtest, fill, cost,
or latency number exists; nothing was produced before (or after) the
Task-12 router timing-parity check. No Tier-1 number exists either.

## 9. CAPACITY & CROWDING

Declared at spec time, never exercised: top-of-book scale (≈ 80-share
reference fill, `platform_min_order_shares = 50` respected), Sharpe-max
target; sizing beyond displayed-depth scale forfeits the passive
economics. Caveat (OQ-3): runtime mechanism-share enforcement is not
active (`mechanism_max_share_of_gross = 1.0` at bootstrap); no
deployment claim may rely on it.

## 10. FALSIFICATION CONDITION

Pre-registered F1–F5 (spec §12): F1 forward test (honest-N), F2 MM
re-quoting footprint, F3 spread-tercile sign stability, F4 execution
validity vs per-symbol stressed floors, F5 structural boundaries.
**None was evaluated** — the park is a precondition failure, not a
falsification outcome. The criteria stand as written for any revival.

## 11. STATUS

**hypothesis — parked** (park-rule census `642d12d`: viable σ-region
empty as realized — 1/70 floored cells, contamination-flagged; power
floor ≥ 100 unreachable, max 35; verdict robust to the §11.1
correction). Slate DISPOSITIONS entry 6
(`docs/research/prompt_pack_04_hypothesis_slate.md`). Trial ledger:
**N = 10, unchanged** — the census executed the pre-registered primary
trial (N-row 3) under its own frozen protocol; all
REGISTERED-UNEVALUATED variants remain unevaluated (N-impact 0 each).
Per spec §15(i) the κ-arithmetic one-way ratchet stands; any future
variant supersedes it only with measured evidence.

## 12. NEXT ACTION

**The measured horizon-feasibility map** (backlog entry 7, as
extended): a successor task must turn the census's measured
σ₁₂₀-vs-floor and episode-density surfaces into the mandatory
hypothesis-slate pre-filter, so that slates are screened against
measured feasibility on the frozen grid — not just per-card cost
floors — before any candidate is ranked. Registered in
`docs/research/prompt_pack_backlog.md` (entry 7 extension; see also
entries 9–10 for the `spread_z_30d` warm-starvation thread and the
DI-09 contamination-at-extremes lesson).

## Artifact disposition (hygiene)

The commit-`6a3ac12` bootstrap wiring (`inventory_pressure` passthrough
at h=120) **remains in place as platform capability**: tested
(`tests/bootstrap/test_horizon_feature_factories.py`), harmless (no
shipped alpha consumes the key; consume-driven required-warm sets
unchanged; no baseline moved), and card-independent. The census script
`scripts/research/inventory_fade_census.py` remains committed with its
owning audit recorded in the `docs/prompts/README.md` coverage map
(research_validation).
