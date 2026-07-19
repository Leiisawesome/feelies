<!--
  File:   docs/research/prompt_pack_06a_slate_b_review.md
  Status: DECIDED (2026-07-12) — see DECISION RECORD at end of file.
          Cold-read review dossier on
          hypothesis slate B (Task FQ-6B-2, 2026-07-11). Independent
          grading of prompt_pack_06_hypothesis_slate_b.md; no candidate
          selected or endorsed. No forward returns, IC, or signal
          evaluation — artifact reads and arithmetic only.
  Owner:  independent slate reviewer (Task FQ-6B-2); decision is Lei's.

  Provenance (FQ-3 template):
    git_sha: "a0881cfd9d7156959840c3001d6aa8bbaeb1ff0f" (HEAD at task
      start = the Task 6-B commit under review; this file is the only
      output)
    worktree_clean: "yes at task start (git status --porcelain empty)"
    pythonhashseed: "0 (set in session for the recompute run)"
    recompute: "throwaway stdlib script (json/math only) against
      docs/research/artifacts/horizon_feasibility_map_2026-07-11.json;
      artifact SHA-256 recomputed =
      362c42cafd07659a9d0bdf51e1c72f8495ccfa78502b349f12a17ca52a51f3fd
      (matches the slate §0.1 citation); script deleted after the run
      per the task's read-only rule — every number it produced is
      reproduced inline below as plain arithmetic. No src/, tests/, or
      committed-artifact file touched."
    bias_control: "cards graded and an independent order recorded from
      the per-card economics BEFORE reading slate §(1)–(3); the
      numeric recompute was executed after that read and did not
      change the order. Sequencing stated honestly here."
    normative_inputs: prompt_pack_05_horizon_feasibility_map.md (+ JSON
      artifact), sig_inventory_fade_v1_validation_protocol.md §11.1 +
      CENSUS RESULTS C.3–C.5, prompt_pack_03b_print_eligibility.md
      (§2, §3.3, §4.3–4.4, §6), prompt_pack_03c_universe_and_cache.md
      (§2 L1–L4, §5.1, §3.1), prompt_pack_00b_edge_units_convention.md,
      prompt_pack_04_hypothesis_slate.md DISPOSITIONS 1–7 +
      prompt_pack_04a_slate_review.md (H1/H2 park record),
      src/feelies/alpha/layer_validator.py (G16 tables),
      src/feelies/sensors/impl/kyle_lambda_60s.py (min_samples=30),
      src/feelies/bootstrap.py (_HORIZON_FEATURE_FACTORIES wiring).
-->

# Task FQ-6B-2 — Cold-read review dossier: hypothesis slate B

Independent review of `prompt_pack_06_hypothesis_slate_b.md`
(commit `a0881cf`). I grade; Lei decides. Trial ledger: **N = 10,
unchanged by this review** — nothing here evaluated any hypothesis;
the only computations are artifact reads and design arithmetic.

---

## 1. SLATE-SHAPE AUDIT — exclusions verified against artifacts, not prose

**(i) INVENTORY / HAWKES_SELF_EXCITE closure at honest κ — CONFIRMED.**
From the map artifact (not the slate's text): G16 confines both
families to H ∈ {30, 120} (`_FAMILY_HALF_LIFE_RANGES_SECONDS`: 5–60 s,
ratio bounds [0.5, 4.0] — verified in `layer_validator.py`). H = 30
passive κ_req at p90, best cell: APP 0.379 — closed universe-wide,
both variants. H = 120 passive κ_req from the artifact: APP
0.2224/0.2080/0.1747 (med/p75/p90), RMBS 0.2400/0.2170/0.2039. Every
quantile exceeds the honest central κ ≈ 0.16 (map §4 shrinkage note,
sourced from the H2-spec derivation). The slate's quoted "0.175/0.204
at p90" matches the artifact to rounding. Closure claim stands.

**(ii) SCHEDULED_FLOW power-floor count basis — CONFIRMED.**
Recomputed from boundary construction: any single-window-per-session
mechanism yields exactly 10 episodes/symbol on the 10-session grid
(the H4 density failure: census-confirmed ~10 close windows/symbol).
The densest non-close construction offered (30-minute algo-clock
boundaries 10:00–15:30) is 12/session — recount: 10:00, 10:30, …,
15:30 = 12 ✓ — giving 120/symbol unconditioned, so ≥ 100 requires a
conditioning fraction ≥ 100/120 = 0.833 ✓. A directional conditioning
retaining 83 % of boundaries is indeed no conditioning; exclusion is
sound. (The close-window revival stays parked in backlog 8, now
correctly annotated with the map's taker-closure at H = 900.)

**(iii) H = 900 density death — ARITHMETIC CONFIRMED, floor applied
correctly.** Boundaries at 900·k anchored at 09:30 with entries in
[09:35, 15:50]: k = 1 (09:45) … k = 25 (15:45) → 25/session →
250/symbol ✓. The ≥ 100 floor then needs conditioning fraction
≥ 100/250 = 0.40 ✓. The joint-unsatisfiability argument (a 0.40
fraction forces near-median conditioning, collapsing c_D to ≈ 0.4–0.5
and κ to ≈ 0.05–0.07 vs artifact κ_req,med 0.110 APP / 0.112 RMBS at
H = 900) is design judgment, but the arithmetic in it is correct and
the direction is right: weak conditioning and tail κ cannot both
hold. The H = 300 basis (76 in-window boundaries/session → 760/symbol)
also recomputes exactly (78 emitted; k = 1…76 inside [09:35, 15:50]).

**Housekeeping ride-alongs — LANDED AS SPECIFIED.** Commit `a0881cf`
touched exactly three things beside the slate: backlog entry 8's
feasibility-map update (H4 program deprioritized, taker closed at
H = 900 median), backlog entry 7's operative-gate line
("prompt_pack_05 §6 … first applied: Task 6-B"), and pack-04
DISPOSITIONS 7 (H4 pointer, append-only; the H4 card untouched). One
cosmetic inconsistency: the slate's provenance header says "the two
approved ride-along backlog/DISPOSITIONS amendments" while its
closing note and the commit list three items across two files.
Trivial, but a header correction at confirmation would keep the
provenance literal.

**Structural consequence of a one-family slate (dossier note, not a
verdict).** All three cards share one causal premise: *institutional
informed/committed flow leaves a permanent-impact remainder that is
harvestable passively over 300 s on this universe.* If that premise
is refuted — impact fully incorporated by detection time, or the
passive fill mix eats the remainder (F4) — all three die together;
the slate buys three tickets to one lottery. Concentration is worse
than family-level: all three anchor on **APP** (H8 adds RMBS only as
a park-armed secondary that its own arithmetic expects to drop —
§2 H8), gate on the same regime posterior, share `kyle_lambda_60s`
as fingerprint, and pre-declare the same F4 trap-quadrant exit. And
if more than one card ever ships, three same-family SIGNAL alphas
imply maximal KYLE_INFO mechanism-share concentration at the
composition layer while runtime mechanism-cap enforcement is
inactive (OQ-3 caveat — correctly carried by every card, but the
slate-level implication deserves stating: portfolio-level mechanism
diversification from this slate is zero). The slate's §0 records the
reduction as forced by the map; the audit above confirms the forcing.
The consequence remains Lei's to weigh.

---

## 2. PER-CARD VERDICT MATRICES

Verdicts: **PASS / CONCERN / FAIL**, one-line evidence. All map
numbers below re-read from the JSON artifact; census numbers from the
committed CENSUS RESULTS tables.

### H6 — `sig_ofi_kyle_drift_v1`

| Check | Verdict | Evidence |
|---|---|---|
| a. Family & form | PASS | KYLE_INFO; hl 150 ∈ [60, 1800]; H = 300; ratio 2.0 ∈ [0.5, 4]; `kyle_lambda_60s` is a validator rule-5 KYLE primary; conditional statement carries units (shares; bps; percentile ≥ 0.90); no narrative residue. |
| b. Archetype & counterparty | PASS | Losing side named twice — latency-lagged LPs whose stale quotes fund the drift, and the schedule-bound parent's own implementation shortfall; pool persists because completion mandates force the impact payment regardless. |
| c. Feasibility citation | PASS | Recomputed: κ_req,med APP 0.1385 ✓; product 1.2 × 0.55 × 0.5 × 0.75 × 0.65 = 0.1609 ≈ 0.16 ✓ (band [0.029, 0.533] → stated [0.03, 0.30 capped] ✓); park arithmetic 0.16 × 33.81 = 5.41 vs floor 2.25 × (2.0 + 0.080) = 4.68 ✓ single-stress anchor, no §11.1 stacking; fee from grid-median bid 544.08 ✓; f_pass explicitly disclaims double-count with the 2.0 bps AS charge; RMBS exclusion (κ-open at p75 0.1427 but power-dead) applies the H2 lesson correctly; deployable set {APP} matches the arithmetic. |
| d. Episode density | **CONCERN** | Recomputed 760 × 0.8 × 0.90 × 0.95 × 0.20 = 104 ✓ and viable-session 8/10 APP cells ≥ σ₁₂₀ 18.5 ✓ — but see (e): the 104 includes short-side episodes the card's own rider arithmetic closes at central κ, so the design-consistent central expectation is ≈ 52 < 100; the card states the park chain but headlines the 104. No warm-starved sensor in the case (no `spread_z_30d`; APP quote/trade rates ample). |
| e. Short-side rider | **CONCERN** | Recomputed: SELL floor 2.25 × (2.0 + 0.080 + 0.503) = 5.81 ✓, κ_req 0.172 > κ central 0.16 — short side fails at the median *at the card's own frozen central*; clears only in p90-tail sessions (0.16 × 36.82 = 5.89 ≥ 5.81, marginal). The consequence chain (short drops → 52 → PARK, no tuning) is pre-registered and honest, but this means the card's central-prior expectation is a power park; it survives only if measured edge beats frozen central — and κ is a one-way ratchet, revisable down only. |
| f. Warm reality | PASS | `realized_vol_30s_zscore` 0.94–0.995 ✓ census C.5; `inventory_pressure` ≥ 0.985 proxy ✓; APP quote counts 37,666–70,353 ✓ 03c §5.1; APP trades 3.59–6.30/s → 216–378/60 s vs λ's `min_samples=30` ✓ (verified in sensor source); `spread_z_30d` not used anywhere ✓; unmeasured warmths flagged with pre-registered census verification + coverage rule. |
| g. Contamination posture | PASS | Entry conditioning quote-fed (Class-B structurally absent); the analogous quote-side hazard (L5 cancel conflation) named and carried as the defining failure mode; inherited unfiltered `kyle_lambda_60s` confined to the F2 diagnostic at aggregated percentile, never entry extremes, with the Class-A-filtered NEW λ fallback pre-registered in the ledger. |
| h. Falsification & regime | PASS | F1/F2 dual-form with clauses; F3 (regime-stratum + tick-stratum) and F4/F5 testable prose — ≥ 3 mechanism-specific; L1–L4 attach via §0.1 (Q3-disposition routing pattern); NEW-SENSOR count 0, YAML + one factory line — recorded. |
| i. Distinctness | see §4 | Shares dominant failure mode (adversarial manufacture → negative tail) and fingerprint with H7. |
| j. No anchoring / no peeking | PASS | No outcome statistic anywhere; CKS/Kyle-GM citations are literature grounding, not shipped-alpha economics; census/map reads are characterization only. |

### H7 — `sig_sweep_kyle_drift_v2`

| Check | Verdict | Evidence |
|---|---|---|
| a. Family & form | PASS | KYLE_INFO; hl 150; H = 300; ratio 2.0; `kyle_lambda_60s` rule-5 primary present (listing the NEW sensor alongside is legal — rule 5 needs ≥ 1 primary); SFI conditional statement with units (shares, quote-rule signed, eligible prints); no residue. |
| b. Archetype & counterparty | PASS | Losing side: resting LPs whose displayed standing commitments are lifted cross-venue before repricing — under-collected adverse-selection premium funds the drift; persistence argued from the obligation to display; secondary stale uninformed flow named. |
| c. Feasibility citation | PASS | Recomputed: product 1.2 × 0.65 × 0.45 × 0.75 × 0.6 = 0.158 ✓ (band [0.032, 0.490] → [0.03, 0.30 capped] ✓); factor deltas vs H6 (f_perm ↑, r_rem ↓, f_pass ↓) are named, offsetting, and not double-counted; park arithmetic and floors identical to H6 and verified (5.41 vs 4.68, single stress); κ_req APP 0.1385 < 0.158 — median-open at the *derived* κ, not only the rounded one. Hygiene note: the park table uses 0.16 where the derivation gives 0.158 (≈ 1.3 % flattery); immaterial to any verdict but the frozen value should be recorded as 0.158 for ratchet purposes. |
| d. Episode density | **CONCERN** | Same 104-straddle as H6 with the same short-side inconsistency (→ ≈ 52 design-central, park chain pre-stated); *plus* the sensor's conditioning set rests on the id-14 share (28.5 % prints / 17.6 % vol) measured on the 03b **legacy 7-session APP-only scan, not the frozen grid** — the card flags this and pre-registers grid verification, but warm coverage and episode count shrink together if the grid-wide ISO rate is lower; this is the slate's most stacked density case. |
| e. Short-side rider | **CONCERN** | Identical arithmetic to H6 (5.82 floor, κ_req 0.172 > 0.158 central — the derived κ makes it slightly worse than the rounded 0.16); consequence chain pre-registered; same design-central power-park implication. |
| f. Warm reality | PASS | Design warm ≥ 20 eligible prints/300 s vs recomputed ~308–539 ISO prints/window on APP ✓; λ and vol gates as H6 ✓; no `spread_z_30d` ✓; the ISO-rate provenance caveat is disclosed in the card itself. |
| g. Contamination posture | PASS | Exemplary and exactly what backlog 10 demands: NEW trade-fed extreme-conditioned sensor with 03b §3.3 Class A (∩ id 14, id-41 overlay pass-through), Class-B exclusion verbatim, `drop_correction_records = {10, 11, 12}`, retroactive-correction conditioning banned (Inv-6/§4.3) — all as explicit constructor/YAML parameters. |
| h. Falsification & regime | PASS | F1/F2 clauses + F3/F4/F5; ignition failure mode carries the pre-registered (REGISTERED-UNEVALUATED) volume-floor mitigation without double-adding a ledger row; NEW-SENSOR count 1 with O(1) incremental pattern and full guard obligations — recorded (this is the Task 9 sizing driver). |
| i. Distinctness | see §4 | Same dominant failure mode as H6; distinct in observable class (certified irrevocable prints vs revocable quote deltas). |
| j. No anchoring / no peeking | PASS | The H1 park is used strictly as a pointer (execution mode + horizon changed); κ factors are fresh priors; 03b prevalence is data-contract characterization; v1 ledger rows stand unduplicated. |

### H8 — `sig_dislocation_lambda_drift_v1`

| Check | Verdict | Evidence |
|---|---|---|
| a. Family & form | PASS | KYLE_INFO; hl 150; H = 300; ratio 2.0; **both** listed fingerprints (`kyle_lambda_60s`, `micro_price`) are validator rule-5 KYLE primaries ✓; conditional statement fully specified (0.75 σ₃₀₀-scale, sign-matched, λ ≥ p50) with the frozen multiple recorded. |
| b. Archetype & counterparty | PASS | Losing side: LPs and mean-reversion faders treating information-driven dislocations as liquidity shocks — the classic Kyle transfer; persistence from the structural inability to distinguish at trade time; the selection danger (herding with elevated λ, no information) is named as the dominant failure mode rather than hidden. |
| c. Feasibility citation | PASS | Recomputed: product 1.3 × 0.6 × 0.5 × 0.75 × 0.65 = 0.190 ✓ (band [0.041, 0.571] → [0.04, 0.30 capped] ✓); c_D 1.3 grounding verified — E[\|z\| given \|z\| ≥ 0.75] = 1.329 under Gaussian ✓, and it is fixed by construction, the least speculative c_D on the slate; APP 6.42 vs 4.68 (headroom 1.37×) ✓; RMBS 6.01 vs 5.46 open at median ✓ (artifact κ_req 0.1728 < 0.19, 10 % margin, park-armed, artifact-flag authority correctly invoked); CROX correctly excluded rather than riding its open p90 (0.1852 < 0.19) — the no-p90 rule applied against the card's own interest ✓; single-stress anchor throughout; fees at grid-median prices ✓. |
| d. Episode density | PASS | Recomputed: P(\|z\| ≥ 0.75) = 0.453, joint with the λ median split = 0.227 ✓ (product is the conservative floor under positive arm correlation — direction correct); APP 760 × 1.0 × 0.90 × 0.95 × 0.226 ≈ 147 ✓ (10/10 cells ≥ σ₁₂₀ 15.6, census min 16.8 ✓); RMBS ≈ 111 ✓ (8/10 cells ≥ 18.2 ✓, warm multiplier honestly reduced to 0.90); keeping the OFI-agreement arm OUT of entry to protect power is recorded as a drafted variant, not silently absorbed ✓; no warm-starved sensor in the case. |
| e. Short-side rider | PASS | Recomputed: APP SELL floor 5.81 → κ_req 0.172 ≤ 0.19 — **the only card whose short side clears rider-inclusive at the median**, so its headline 147 is internally consistent; RMBS SELL floor ≈ 6.61–6.63 → κ_req 0.209 > 0.19, closed, with the long-only recheck (≈ 55 → RMBS drops, APP stands) pre-stated. Design-central read: H8 is an APP-only card at 147 episodes. |
| f. Warm reality | PASS | Census citations exact; quote-fed `micro_price` warm on APP/RMBS quote rates (0.39–3.0/s recomputed from 03c §5.1); RMBS λ marginality quantified (47–110 trades/60 s vs the 30 floor) with a numeric coverage-drop rule, not tuning; no `spread_z_30d`. |
| g. Contamination posture | **CONCERN** | Only card with an inherited unfiltered trade-fed sensor **inside the entry rule** (`kyle_lambda_60s_percentile ≥ 0.5`). The justification is real — DI-09 flags concentrate at trade-flow extremes and a median split dilutes single-print OLS distortion; the filtered NEW λ fallback is pre-registered and the census both-ways co-occurrence report is committed to. Residual that keeps this at CONCERN: H8's quote-side extreme (0.75 σ dislocations) is *driven by* heavy one-sided trading, exactly the windows where census flags cluster — so entry windows may resemble census extremes even though the λ arm itself is a median split. Bounded and disclosed, not resolved. |
| h. Falsification & regime | PASS | F2's reversion-contrast is the strongest falsifier on the slate — a genuine two-sided mechanism prediction (baseline-λ dislocations must revert; undiscriminating λ kills the card as "an unpre-registered momentum hypothesis — dead by its own terms"); F1 clause, F3–F5 present; L3/RMBS flagged specifically; NEW-SENSOR count 0, YAML-only. |
| i. Distinctness | see §4 | The most separable card: makes a contrast prediction the others do not. |
| j. No anchoring / no peeking | PASS | No outcome statistics; conditional-expectation arithmetic is analytic, not measured; no shipped-alpha economics. |

---

## 3. RANKING — independent order, recompute, reconciliation

**Independent order (recorded from the per-card grades before reading
slate §(1)–(3)): H8 > H7 > H6.** Basis: H8 is the only card whose
central-prior arithmetic is internally consistent end-to-end — floor
headroom 1.37× (vs 1.15–1.16×), the only rider-clean short side at
the median (hence the only headline episode count, 147, not
undermined by its own rider table), the strongest falsifier (F2
contrast), zero implementation cost, and the least speculative c_D.
H7 second on the certified observable and exemplary contamination
posture, dragged by the 104-straddle-plus-52-central power case, the
non-grid ISO-rate basis, and the new-sensor cost. H6 third: same
power case as H7 with a free-to-manufacture observable and no
certification.

**Pre-filter recompute (map §6, applied first) — agrees with the
slate:** H6 PASS (0.16 > κ_req,med 0.1385 on {APP}), H7 PASS (0.158 >
0.1385), H8 PASS (0.19 > 0.1385 APP, > 0.1728 RMBS). No card needs
the p90 tail for its primary region; no stacked stress found anywhere
(all floors = 2.25 × (2.0 + fee_s), §11.1 anchor).

**Formula recompute — arithmetic correct:** H7 = 5 × 3 ÷ 1.0 = 15.0;
H8 = 4 × 5 ÷ 1.5 = 13.3; H6 = 4 × 4 ÷ 1.5 = 10.7. Slate ranking
H7 > H8 > H6 follows from its stated S/F/M.

**Reconciliation.** The divergence (slate H7-first, this review
H8-first) is not arithmetic: it sits entirely in S and in what the
formula cannot see. (1) S = 5 for H7 rewards certification of the
*conditioning observable* — but certification proves the sweep, not
the information (the card itself says so); H8's F2 contrast tests the
KYLE attribution more directly than H7's flag does. (2) The formula
does not encode the short-side/power interaction: H7's F = 3 already
prices the straddle, but H6's F = 4 arguably does not (identical
104/52 case, only cheaper to build). (3) The pack-04 cycle
demonstrated exactly this failure shape — formula-first (H1) over
economics-first (H2 elevation by the reviewer, Lei's override). The
slate has internalized half the lesson: it applied the hard
pre-filter first (all three pass), and its own recommendation section
names H8 as a defensible override. So unlike pack-04, this is a
genuine judgment call between a certified-mechanism card with a
fragile power case and a robust-economics card with a residual
contamination concern — not an arithmetic error to correct. This
dossier does not select.

**Ledger appendix — VERIFIED.** N = 10, unchanged and consistent with
the pack-04 ledger (10 numbered rows there; census C.6 confirmed no
increment). The appendix carries the three card primaries as
drafted-not-evaluated (N-impact 0) — plus five more drafted rows
(two H6/H8 alts each…, the shared filtered-λ fallback, and the
design-killed micro-price-divergence mechanism), eight in total, all
N-impact 0. That exceeds the expected "three drafted rows" in the
benign direction (more disclosure, not less) and complies with the
FQ-6B-R rule (drafting ≠ data contact). Carried-over pack-04
conditionals are pointed to, not duplicated — no silent-reset vector
found. One consistency note: the design-killed row is correctly
0-count under the rule, but its κ ≈ 0.11 derivation should be treated
as frozen-down if the mechanism is ever revived.

---

## 4. DISTINCTNESS — three hypotheses or one?

Honest answer: **approximately one and a half.** All three cards
share the causal premise (incomplete permanent-impact incorporation
of institutional flow, harvestable passively over 300 s on APP), the
family, horizon, half-life, gate structure, κ band, fingerprint
sensor, expected F4 exit, and the adversarial-manufacture failure
mode. The distinct falsifiable claim each makes: **H6** — persistent
*quote-side* order-flow imbalance (revocable, costless to
manufacture) carries a 300-s permanent remainder; refuted by F2's
no-prints/no-λ clause without touching H7 or H8. **H7** — the
exchange-certified urgency flag adds permanent-impact share *beyond
generic flow* (f_perm 0.65 vs 0.55); refutable by sweeps that move
price no more than baseline. **H8** — impact elevation *discriminates*
continuation from reversion at matched dislocation size; uniquely
two-sided (it predicts baseline-λ dislocations revert — neither H6
nor H7 makes any reversion claim). H6 and H7 share their dominant
failure mode and fingerprint and differ mainly in which tape the same
conditioning idea reads (quotes vs certified prints) — they are
closer to conditioning variants of one hypothesis than independent
hypotheses, and a single refutation of the flow-continuation premise
in the non-breakout stratum (F3) kills both simultaneously. H8 is
structurally separable via its contrast clause. Consequence for
Task 7 sizing: selecting two cards from {H6, H7} buys little
independent information; {H8} + one of {H6, H7} is the maximally
distinct pair if two are ever advanced.

---

## 5. RISKS — H7 specifically (the weakest check, and what Task 7 must resolve)

H7's weakest check is **episode density (d)** — not because the
arithmetic is wrong (it recomputes exactly) but because it is the
most stacked case on the slate: the 104 headline sits on four
multiplied assumptions (gate 0.90 and warm 0.95 unmeasured; viable
0.8 from census σ; tail 0.20 by construction), *and* its own
short-side rider table closes the SELL leg at the derived central
κ = 0.158 at the median session, making the design-consistent
central expectation ≈ 52 episodes — below the ≥ 100 floor. Under the
one-way κ ratchet the card reaches census power only if the measured
edge beats its own frozen central. On top of that, the conditioning
set's existence rests on the id-14 share measured on the 03b legacy
7-session APP-only scan, not the frozen grid; a materially lower
grid-wide ISO rate shrinks warm coverage and episode count together.
Task 7 must resolve, before spec freeze: (1) the passive entry
protocol pinned exactly (rest duration, cancel-on-runaway, re-quote
rules) since f_pass = 0.6 is the least-grounded factor and F4 is the
pre-declared likely exit; (2) a grid-wide ISO-prevalence and
SFI-warm census plan pre-registered with the park rule armed (and
whether that characterization precedes or accompanies the census
stage — Q3 below); (3) the short-side pre-registration made explicit
in the spec (long-only from the start vs measured-edge test), because
the power verdict hinges on it; (4) the ignition volume-floor
mitigation either specced (still N-impact 0 as drafted) or explicitly
deferred; (5) the L6 quote-rule signing convention at burst moments
pinned, since systematic mis-signing attenuates SFI exactly in
signal-active windows; (6) Task 9 sizing: H7 is the only card
requiring a new sensor module with full guard obligations.

---

## 6. QUESTIONS FOR LEI

1. **Certification vs robustness (the selection axis).** The slate
   recommends H7 on S = 5 (certified conditioning); H8 dominates on
   every recomputed economics axis — stressed-floor headroom 1.37×
   vs 1.15×, the only internally consistent power case (147 episodes
   with a rider-clean short side, vs H7/H6's 104 headline that
   degrades to ≈ 52 at the cards' own central κ), YAML-only vs a new
   sensor module, and the strongest mechanism falsifier (F2
   reversion contrast). Do you confirm H7, override to H8, or
   advance the maximally distinct pair {H8 + H7} through Task 7 spec
   (accepting the Task 9 sensor cost and per-card ledger discipline)?

2. **The one-family, one-symbol concentration.** The slate-shape
   audit confirms the map forces a KYLE-only slate, and the design
   arithmetic makes every card APP-primary. Do you accept the
   correlated-failure structure (one refuted premise, or one APP
   idiosyncrasy, kills the whole slate) for this cycle, or should a
   diversification thread (backlog-8 calendar-event grid, or a
   universe/grid extension) be scheduled in parallel *before* Task 7
   effort is committed to a single premise?

3. **H6/H7 short-side power inconsistency — handle at design or at
   census?** Both cards headline 104 episodes while their own rider
   arithmetic closes the short side at central κ (design-central
   ≈ 52 < 100). Options: (a) leave as-is — census measures both
   sides, park rule armed (the slate's current posture); (b) require
   the selected card to re-state its density case at the
   design-central long-only number before Task 7 freeze (which would
   park H6/H7 at design unless the short side is defended); or
   (c) treat short-side viability as a pre-registered census
   sub-hypothesis with its own pass bar. Which posture governs the
   Task 7 spec?

---

*Reviewer stops here — no candidate selected or advanced. Status
remains AWAITING-LEI-DECISION.*

---

## DECISION RECORD (Lei, 2026-07-12 — append-only)

Rulings on §6: (1) OVERRIDE to H8 — confirmed for Task 7 on the
short-side/power finding; (2) concentration ACCEPTED this cycle,
diversification registered as backlog entry 11 (universe tranche 2);
(3) H6/H7 NOT SELECTED at design (not parked — no census ran);
revival requires re-derivation with an explicit short-side posture as
a new drafted variant. Full record:
`prompt_pack_06_hypothesis_slate_b.md` DISPOSITIONS. N unchanged
at 10.
