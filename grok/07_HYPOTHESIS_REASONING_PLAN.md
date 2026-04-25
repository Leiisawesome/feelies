<!--
  File:    grok/07_HYPOTHESIS_REASONING_PLAN.md
  Status:  SUPERSEDED (Phase 5).  Retained for historical context only.
  Purpose: Design notes for the 7th Grok prompt (Hypothesis Reasoning Protocol)
           and the coherence patches required across Prompts 1–6.
           Saved for offline review; supersedes nothing until accepted.
  Owner:   PI
-->

> **SUPERSEDED — Phase 5.**
>
> The Hypothesis Reasoning Protocol has shipped under
> `grok/prompts/`. The canonical sources of truth are now:
>
> - `grok/prompts/hypothesis_reasoning.md` — the full reasoning
>   protocol (generation, mutation gates, hard refusal conditions,
>   output contract, sensor catalog cross-reference).
> - `grok/prompts/sensor_catalog.md` — Layer-1 sensor vocabulary +
>   per-mechanism fingerprint matrix (G16 rule 5).
> - `grok/prompts/mutation_protocol.md` — five-axis mutation
>   discipline + parity-preservation rules.
>
> The schema-version blocker (collision **C1** below) was resolved
> by landing schema 1.1 in `feelies.alpha.loader.AlphaLoader` (Phase
> 1.1 / Phase 3) — there is no sidecar; the new fields are first-
> class on the alpha YAML. The historical `LEGACY_SIGNAL` layer was
> retired in Workstream D.2; the loader now rejects it outright (see
> `docs/migration/schema_1_0_to_1_1.md`).
>
> The collision analysis below remains a useful audit of the gaps
> the protocol filled, but **the resolutions documented here are
> no longer authoritative.** Read the live prompts for the
> shipped contracts.


# Plan — Add Prompt 7 (Hypothesis Reasoning Protocol) and reconcile Prompts 1–6

> Draft. Open questions at the bottom. Revisit before authoring `grok/07_HYPOTHESIS_REASONING.md`
> or editing any of `grok/00`–`grok/06`.

## Verdict on the original observation

Yes, agreed. Prompts 1–6 give Grok a complete **mechanical** loop (data -> spec -> backtest
-> mutate -> adopt -> export -> audit) but no **reasoning protocol**. The closest thing today is
`formalize_hypothesis(...)` in `grok/03_ALPHA_DEVELOPMENT.md` (CELL 3 / Step 3) — a free-form
dict constructor with no causal-grounding enforcement, no layer classification, no
cost-survivability gate, no anti-pattern refusal, and no required REPL output structure.
`MECHANISM_CATALOG` constrains *what* mechanism is named but not *how* a hypothesis is built
around it. The mutation layer (Prompt 6) operates on parameters and feature swaps without
ever requiring a per-mutation hypothesis, which is exactly the failure mode the new doc
names as forbidden in Section 5.

So the new doc fills a real gap. The task is to land it without breaking what already works.

---

## The 8 collisions between the new doc and the existing 6 prompts

These have to be resolved before Prompt 7 can be authored, because each one will silently
break either Grok's REPL flow or the parity contract.

### C1. Schema version — blocker

- New doc emits `schema_version: "1.1"` with mandatory new fields (`layer`,
  `horizon_seconds`, `structural_actor`, `mechanism`, `cost_arithmetic`, `regime_gate`,
  `depends_on_sensors`, `depends_on_signals`, structured `falsification_criteria`).
- `feelies.alpha.loader.AlphaLoader` (Prompt 3 §1) only accepts `schema_version: "1.0"`.
  Any 1.1 spec -> `validate_alpha()` fails -> MUTATE/ADOPT/EXPORT all reject. Protocol is
  dead on arrival.
- **Recommended resolution (option A, no repo change):** keep `.alpha.yaml` at
  `schema_version: "1.0"`. Persist all new fields to a **sidecar**
  `<alpha_id>.hypothesis.yaml` (and human-readable `rationale.md`) in the same directory.
  AlphaLoader ignores them; Grok reads them; the registry indexes the sidecar.
- **Option B (repo change, deferred):** PR `feelies/alpha/loader.py` to accept `"1.1"` with
  the new fields validated as a new `meta:` block. Bump the `_COMMIT_SHA` in
  `grok/01_BOOTSTRAP.md`. Out of scope for this PR.
- **Decision needed:** confirm A. If confirmed, Prompt 7 ships sidecar I/O; the doc's
  Section 7.1 YAML gets re-rooted under a `meta:` key in the sidecar rather than appended
  to the .alpha.yaml.

### C2. Layer model — only SIGNAL is wireable today

- The doc defines SENSOR (state estimator, no trades), SIGNAL (current behavior), PORTFOLIO
  (cross-sectional construction). The platform pipeline only consumes specs that emit
  `Signal` events through `evaluate(features, params)`.
- SENSOR specs replace `signal:` with `state_estimator:` — AlphaLoader has no such hook.
  PORTFOLIO `construction:` block has no consumer.
- **Resolution:** Prompt 7 declares scope explicitly:
  - `layer: SIGNAL` -> fully operational; passes through MUTATE/ADOPT/EXPORT.
  - `layer: SENSOR` -> produces sidecar + rationale only; `ADOPT` refuses with
    `"SENSOR layer not yet executable"`.
  - `layer: PORTFOLIO` -> same as SENSOR; refuses with explicit message naming what's
    missing (cross-sectional aggregator, factor-neutralization service).
- This keeps the doc honest without pretending platform support exists.

### C3. Sensor catalog vs FEATURE_LIBRARY

- Doc Section 8 lists 10 `sensor_id`s (`ofi_ewma`, `vpin_50bucket`, `kyle_lambda_60s`, ...).
  None of these are implemented in Prompt 3's `FEATURE_LIBRARY` (which has 6:
  `spread_bps`, `microprice`, `order_imbalance`, `imbalance_ema`, `mid_zscore`, `mu_ema`).
- Doc rule: "Reference sensors by `sensor_id`. Do not invent."
- Without a mapping, every doc-conformant hypothesis fails G4 (sensor in catalog).
- **Resolution:** Prompt 7 ships a `SENSOR_CATALOG` dict that does three things:
  1. **Aliases** existing FEATURE_LIBRARY entries to canonical sensor_ids where the math
     matches:
     - `ofi_ewma` <- `imbalance_ema` (size-imbalance EWMA; close enough as a
       Cont-Kukanov-Stoikov OFI proxy on L1)
     - `micro_price` <- `microprice`
     - `micro_price_drift` <- derive `micro_price - mid` as a one-line wrapper feature
     - `realized_vol_30s` <- new feature (small, deterministic; ship the Python)
     - `spread_z_30d` <- new feature requiring 30-day rolling state; needs explicit
       storage; ship a stub feature with caveat
  2. **Marks gaps** as `status: REQUIRES_NEW_FEATURE` for `vpin_50bucket`, `kyle_lambda_60s`,
     `quote_hazard_rate`, `trade_through_rate`, `quote_replenish_asymmetry`. Hypotheses
     depending on these MUST first ship a SENSOR companion (which today writes a sidecar
     only — see C2).
  3. **Refuses** hypotheses that reference any sensor not in the catalog.
- Net effect: ~5 sensors usable on day 1, ~5 deferred behind a clearly-named gate.

### C4. Mechanism catalog — two vocabularies, must align

- Prompt 3 has `MECHANISM_CATALOG = {M001..M010}` keyed by id, with `name`, `mechanism`,
  `observable`, `holding_s`, `features`.
- Doc Section 4 Step 1–2 introduces `structural_actor` + `mechanism` as free-text. The
  canonical example doesn't cite an M-id.
- **Resolution:** unify, do not fork. Prompt 7:
  1. Extends `MECHANISM_CATALOG` entries (in a Prompt-7 monkey-patch cell) with
     `structural_actor` and `incentive` keys derived from existing prose.
  2. Requires every Prompt-7 proposal to cite `mechanism_id ∈ MECHANISM_CATALOG` AND fill
     `structural_actor` + `mechanism` in template form. The free-text fields complement,
     never replace, the discrete id.
  3. Adds `extend_mechanism_catalog(M_id, name, structural_actor, mechanism, observable,
     holding_s, features)` so new mechanisms are added in-session, traceably.

### C5. Regime engine state names — three competing vocabularies

- `feelies.services.regime_engine.HMM3StateFractional` (per Prompt 4 CELL 4) uses
  `("compression_clustering", "normal", "vol_breakout")`.
- Prompt 6 `op_regime_filter` defaults use `("trending", "compression_clustering",
  "vol_breakout")` — `"trending"` is a **pre-existing typo** (the engine has no `trending`
  state); flag for fix.
- New doc Appendix B uses `Benign | Stressed | Toxic` and writes `P(benign | obs_t)` in the
  regime gate.
- **Resolution:**
  1. Fix Prompt 6 typo: `"trending"` -> `"normal"` in `op_regime_filter`.
  2. Prompt 7 ships `REGIME_ALIASES = {"benign": "compression_clustering", "stressed":
     "normal", "toxic": "vol_breakout"}` and a translator that rewrites doc-vocabulary
     `on_condition`/`off_condition` into canonical state names before they're embedded in
     the spec's `signal:` evaluate body or registry.
  3. Operator-facing docs and the Prompt 7 protocol text use the doc vocabulary (matches
     the new system context); the wire format always uses canonical names.

### C6. Cost arithmetic — analytical (Prompt 7) vs empirical (Prompt 4)

- Doc G7: analytical `margin_ratio = expected_edge / (1.5 × round_trip_cost) ≥ 1.5`,
  computed pre-trade.
- Prompt 4 `tc_sensitivity()`: empirical breakeven multiplier on actual `DefaultCostModel`
  runs, threshold > 1.5×.
- These are complementary (pre/post). They become contradictory only if the analytical
  estimate is far off the realized cost.
- **Resolution:** Prompt 7 enforces G7 BEFORE backtest (refuse to emit if margin_ratio <
  1.5). Prompt 4 `TEST` is monkey-patched to also compute `cost_arithmetic_drift_pct =
  |empirical_breakeven − analytical_hurdle| / analytical_hurdle` and stamp it on the
  report. Drift > 50% -> Grok's next mutation cycle is required to re-derive
  `cost_arithmetic` (regenerates the sidecar).

### C7. Lifecycle vocabulary

- Prompt 5 `LIFECYCLE_STATES = ["RESEARCH", "PAPER", "LIVE", "QUARANTINED",
  "DECOMMISSIONED"]`; registry `status` accepts strings like `"candidate"`,
  `"parity_verified"`, `"retired"`.
- Doc Appendix C: `DRAFT -> PROPOSED -> VALIDATING -> PAPER -> LIVE -> DECAYING ->
  RETIRED -> MUTATED`.
- **Resolution:** introduce a NEW additive registry column `hypothesis_status` (Prompt 7
  owns it; appended via the C9 monkey-patch on `REGISTRY_COLS`). Mapping table:

  | Doc state | Existing platform `status` | New `hypothesis_status` |
  |---|---|---|
  | DRAFT | (not in registry; lives in `_drafts/`) | `draft` |
  | PROPOSED | `candidate` | `proposed` |
  | VALIDATING | `candidate` (selfcheck pending) | `validating` |
  | PAPER | `parity_verified` | `paper` |
  | LIVE | `parity_verified` + LIFECYCLE=LIVE | `live` |
  | DECAYING | `parity_verified` + AUDIT=DEGRADED | `decaying` |
  | RETIRED | `retired` | `retired` |
  | MUTATED | (carried via `parent_id`) | `mutated` |

  Existing semantics untouched; new column is informational.

### C8. Output locations — Grok session vs repo tree

- Doc writes to `alphas/<alpha_id>/<alpha_id>.alpha.yaml`, `alphas/_drafts/`,
  `alphas/_deprecated/`.
- Grok session: `ALPHA_DEV_DIR=/home/user/alphas` (research),
  `ALPHA_ACTIVE_DIR=/home/user/alphas_active` (live), repo `alphas/` is in `FEELIES_REPO`.
- **Resolution:** Prompt 7 uses `ALPHA_DEV_DIR/<alpha_id>/`, `ALPHA_DEV_DIR/_drafts/`,
  `ALPHA_DEV_DIR/_deprecated/` for in-session artifacts. Promotion to repo `alphas/`
  continues to flow through `EXPORT()` — unchanged.

---

## File-by-file change plan

### NEW: `grok/07_HYPOTHESIS_REASONING.md`

Cell-by-cell structure (mirroring the activation pattern of Prompts 2–6):

| # | Cell | Purpose |
|---|---|---|
| 1 | `SENSOR_CATALOG` + `LIST_SENSORS()` | Maps doc's 10 `sensor_id`s to existing FEATURE_LIBRARY (5 ALIASED + 0 EXTENDED) and gaps (5 marked REQUIRES_NEW_FEATURE). Provides `feature_entry_for_sensor(sensor_id)`. |
| 2 | Cost arithmetic helper | `cost_arithmetic_block(universe_tier, expected_edge_bps, edge_source, **overrides) -> dict` returning the doc's exact `cost_arithmetic` block; raises if `margin_ratio < 1.5` (G7). |
| 3 | Hard gates | `HARD_GATES = [G1..G15]` with predicates; `audit_gates(proposal_dict) -> {gate_id: bool, message}`; `print_gate_audit(audit)`. Each gate maps to a callable that inspects either the proposal dict (G1–G11) or the spec dict / sensor catalog (G12–G15). |
| 4 | Sidecar I/O | `write_proposal(alpha_id, blocks)` writes `<alpha_id>.hypothesis.yaml` + `rationale.md` next to the .alpha.yaml; `write_draft(alpha_id, spec, failed_gates)` lands in `_drafts/`; `move_deprecated(alpha_id)` for mutation predecessors. |
| 5 | REPL output protocol | `emit_proposal(mode, reasoning, audit, decision, yaml_text) -> str` formats the canonical 5-block REPL turn (Section 13); `parse_proposal(text) -> dict` re-parses it for downstream consumers. `PROPOSE(operator_request: str)` is a thin wrapper that prints the operator instructions (it cannot literally generate the LLM's reasoning — it sets up state and prompts Grok to follow Section 4 or Section 5). |
| 6 | Anti-pattern guardrail | `pre_propose_audit(request: str) -> list[str]` scans for forbidden patterns (MA crossover, bare momentum, Sharpe-driven, NN find-the-signal, etc. — Section 11). Returns refusal reasons. Called inside `PROPOSE`. |
| 7 | New mutation operators | `op_tighten_regime_gate` (doc Axis 1), `op_restrict_universe` (Axis 4), `op_promote_to_portfolio` (Axis 5; raises `NotImplementedError("PORTFOLIO layer not yet wired")`). Sensor substitution (Axis 2) maps to existing `op_swap_feature` with a Prompt-7 wrapper that requires the substitute sensor to measure the same `latent_variable` (per Section 5 forbidden mutations). Horizon adjustment (Axis 3) maps to `op_perturb_parameter` on `horizon_seconds_param` with a per-parameter rationale gate. All registered into `MUTATION_OPERATORS` with `axis` metadata. |
| 8 | Lifecycle bridge | `set_hypothesis_status(signal_id, status)`, `HYPOTHESIS_STATUS_TO_PLATFORM = {...}`, optional reconciliation that nudges the existing `status` column when the hypothesis_status transition implies it. |
| 9 | Coherence patches (defensive monkey-patches) | (a) Extend `REGISTRY_COLS` in place with `hypothesis_status`, `layer`, `horizon_seconds`, `margin_ratio`, `structural_actor`. (b) Fix `op_regime_filter` typo (`"trending"` -> `"normal"`). (c) Install a pre-mutation hook on `MUTATE` that calls `pre_propose_audit` on the operator's stated rationale (passed via `**operator_kwargs.get("rationale")`); refuses if missing for `perturb_param` / `swap_feature`. (d) Wrap `TEST` to compute and stamp `cost_arithmetic_drift_pct`. |
| 10 | Protocol body (system context) | The full doc text, edited for Grok-environment fit: `alphas/` -> `ALPHA_DEV_DIR`, schema_version note (sidecar pattern), regime-name aliasing call-out, scope note that SENSOR/PORTFOLIO are documentation-only today. Sentinel: `"Hypothesis Reasoning module: ACTIVE"`. |

### EDITS to existing prompts

Minimal-surface edits, all backwards-compatible. Each is justified by a specific collision
above.

- **`grok/00_ARCHITECTURE.md`**
  - Add row `Prompt 7: Paste once to activate hypothesis reasoning protocol (PROPOSE,
    gates, sensor catalog, anti-patterns)` to "Session Flow" and to the file map.
  - Add `Prompt 7` to the PI Workflow sentinel table:
    `"Hypothesis Reasoning module: ACTIVE"`.
  - Add `PROPOSE`, `LIST_SENSORS`, `MUTATE_BY_AXIS` rows to the command list.
- **`grok/01_BOOTSTRAP.md`**
  - CELL 4: extend `WORKSPACE` with `"alpha_drafts": "/home/user/alphas/_drafts"`,
    `"alpha_deprecated": "/home/user/alphas/_deprecated"`. Extend `REGISTRY_COLS` with the
    5 new columns (or leave to Prompt 7's monkey-patch — pick one). Add
    `SESSION["last_proposal"] = None`, `SESSION["proposal_history"] = []`.
  - CELL 5 (`INITIALIZE`): add
    `_m7 = "PROPOSE" in dir() or "PROPOSE" in globals()`; print Module 7 status; require it
    in the "all active" check.
  - §3 USER COMMANDS: add `PROPOSE`, `LIST_SENSORS`, `MUTATE_BY_AXIS`.
- **`grok/03_ALPHA_DEVELOPMENT.md`**
  - No code changes (keep first-paste lean). Add a short "See Prompt 7" pointer in §3
    (`HYPOTHESIS FORMALIZATION TEMPLATE`) noting that `formalize_hypothesis()` is now
    wrapped by Prompt 7's `PROPOSE` for the structured 5-block REPL flow and gate audit.
- **`grok/04_BACKTEST_EXECUTION.md`**
  - No mandatory changes; Prompt 7 monkey-patches `TEST` from CELL 9 to add
    `cost_arithmetic_drift_pct`.
  - Optionally (recommended): in CELL 5 `TEST()`, add a single line that calls a
    Prompt-7-defined hook if present
    (`_post_test_hook = globals().get("post_test_hypothesis_audit"); _post_test_hook and _post_test_hook(report, spec)`).
    This avoids relying on monkey-patching and keeps the hook explicit.
- **`grok/05_EXPORT_LIFECYCLE.md`**
  - `_registry_upsert`: include the 5 new fields in the `row` dict (with `""` defaults so
    legacy rows don't break).
  - `EXPORT`: when a `<alpha_id>.hypothesis.yaml` sidecar exists in
    `ALPHA_DEV_DIR/<alpha_id>/`, copy it into the export package alongside `.alpha.yaml`
    and `parity_fingerprint.json`. Add a sidecar-presence note to `README_deploy.txt`.
  - `PROMOTION_GATES["RESEARCH -> PAPER"]`: append "All Prompt 7 hard gates G1–G15 pass on
    the live spec".
- **`grok/06_EVOLUTION.md`**
  - `op_regime_filter`: fix `"trending"` -> `"normal"` in the default `regimes` tuple.
    (Standalone bug fix, would also be worth doing without Prompt 7.)
  - `MUTATE`: add a docstring note that Prompt 7 installs a pre-mutation rationale guard.
  - `MUTATION_OPERATORS`: leave Prompt 6 untouched — Prompt 7 registers the 3 new
    operators by importing and `MUTATION_OPERATORS.update(...)` in CELL 7.

---

## What this delivers, end to end

After paste:

1. PI runs `PROPOSE("propose an alpha exploiting institutional parent-order flow in
   mid-cap equities")`. Prompt 7 prints the operator-side scaffold and the doc Section 4
   step list.
2. Grok responds in the Section-13 5-block format. Prompt 7's `parse_proposal()` validates
   structure; `audit_gates()` runs G1–G15.
3. If all gates pass: `assemble_alpha()` builds the .alpha.yaml; `write_proposal()` writes
   the sidecar + `rationale.md`; `validate_alpha()` confirms loader compatibility;
   `ADOPT()` flips the live spec; `RUN_ACTIVE()` backtests through the production
   discovery path; `TEST()`'s extended hook stamps cost-arithmetic drift.
4. If any of G1–G11 fails: `write_draft()` lands the spec in `_drafts/` with a
   `# FAILED_GATES: [..]` header; ADOPT is refused.
5. If G12–G15 fails: hard refuse, print clarifying question per Section 12.
6. For mutation: `MUTATE_BY_AXIS(parent, axis="regime_refinement", rationale=...)`
   dispatches to the right operator, gate-checks the child against G1–G15 (re-runs cost
   arithmetic per Axis 1's "tighter regime -> fewer trades" rule), sidecar-writes, and
   auto-ADOPTs.

Status: `Hypothesis Reasoning module: ACTIVE` — a single sentinel, consistent with the
other six modules.

---

## Decisions still open

1. **Schema policy (C1):** confirm sidecar pattern (`<alpha_id>.hypothesis.yaml`) instead
   of bumping `schema_version: "1.1"` for now. If you'd rather bump the loader, the work
   moves to a separate repo PR + new `_COMMIT_SHA` in `grok/01_BOOTSTRAP.md` and Prompt 7
   becomes much smaller.
2. **Registry columns (C7):** add the 5 new columns by editing `REGISTRY_COLS` in
   `grok/01_BOOTSTRAP.md` directly (clean, but bumps the schema implicitly), or via Prompt
   7 monkey-patch (keeps Prompt 1 untouched, but requires Prompt 7 before any registry
   write). Recommend editing Prompt 1.
3. **Sensor gaps (C3):** ship the 5 missing sensors as new feature implementations now
   (more work, fully usable doc on day 1), or mark them `REQUIRES_NEW_FEATURE` and refuse
   hypotheses that reference them (less work, partially usable). Recommend the latter for
   first cut.
4. **TEST hook (C6):** add the explicit hook line in `grok/04_BACKTEST_EXECUTION.md`
   (clean), or rely on Prompt 7 wrapping `TEST` post-paste (zero change to Prompt 4).
   Recommend explicit hook.
5. **Prompt 6 typo fix:** ship `"trending"` -> `"normal"` as part of this PR even though
   it's an independent bug? Recommend yes — the new regime-aliasing layer assumes
   canonical state names.

---

## Resume checklist (when you come back to this)

- [ ] Decide C1–C5 above; record decisions inline.
- [ ] Re-confirm `_COMMIT_SHA` pinned in `grok/01_BOOTSTRAP.md` still matches the
      `feelies.alpha.loader` semantics this plan assumes (schema 1.0 only, ignores
      unknown top-level keys vs rejects them — verify by reading the loader).
- [ ] Re-check `op_regime_filter` source in `grok/06_EVOLUTION.md` to confirm the
      `"trending"` typo is still present (low-risk bug; may have been fixed elsewhere).
- [ ] Decide whether Prompt 7's protocol body (CELL 10) reproduces the user's doc verbatim
      or links to it from a canonical location (e.g. `docs/hypothesis_reasoning.md` in
      the repo) and Grok pulls it. The latter avoids drift between two copies.
- [ ] Once decisions are locked, switch to agent mode and produce the file changes in one
      pass: new `grok/07_HYPOTHESIS_REASONING.md` plus the minimal-surface edits to
      Prompts 0/1/3/4/5/6 listed above.
