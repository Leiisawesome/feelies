# Layer-3 PORTFOLIO / composition audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies
Layer-3 cross-sectional construction — `UniverseSynchronizer` fan-in,
`CrossSectionalRanker`, `FactorNeutralizer`, `SectorMatcher`, `TurnoverOptimizer`,
`CompositionEngine`, and the position stores — from `Signal` events →
`CrossSectionalContext` → `SizedPositionIntent`.

---

## Mission

You are a senior quantitative portfolio-construction researcher and systems auditor.
Perform a **read-only, evidence-based audit** of the feelies PORTFOLIO layer.

**Primary focus:** This layer is where per-symbol signals become a *desired book*. It
is the only cross-sectional component, and it carries a `decision_basis_hash` that must
be bit-identical across replays (Inv-5). A non-deterministic optimizer, a mis-applied
factor neutralization, or a leaked mechanism cap silently distorts every downstream
order and PnL attribution.

**Goal:** Identify where construction is mathematically sound vs. ad hoc, where
determinism is at risk (cvxpy is a classic offender), where mechanism caps and
completeness thresholds are enforced vs. cosmetic, and what changes would yield
**deterministic, economically coherent** intents — without breaking invariants.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Agent context (mandatory)

| Step | Resource |
|------|----------|
| 1 | `.cursor/rules/platform-invariants.mdc` — **Inv-5, 6, 11**; glossary: portfolio alpha, sized position intent, mechanism concentration, decay weighting |
| 2 | `.cursor/rules/karpathy-guidelines.mdc` |
| 3 | `.cursor/skills/README.md` — L3 parity hashes → testing-validation |
| 4 | `.cursor/skills/composition-layer/SKILL.md` (**owner**) |
| 5 | `.cursor/skills/microstructure-alpha/SKILL.md` — `TrendMechanism` caps |
| 6 | `.cursor/skills/risk-engine/SKILL.md` — `check_sized_intent` per-leg veto |

Default `composition_completeness_threshold`: **0.80** (platform invariants glossary).


**Shipped vs Not shipped:** Treat skill sections marked **Not shipped** as design
targets — P0 only if code/tests claim they are live.

**Finding bar:** P0/P1 items must cite `Inv-N` + `path:line`. Read-only pass per
`.cursor/rules/karpathy-guidelines.mdc`.

---

## Platform context (read first)

**Docs and config** (after Agent context):

1. Read `docs/three_layer_architecture.md` §5.6 (`CrossSectionalContext`), §5.7
   (`SizedPositionIntent`), §6.5 (composition module), §7.5 (UniverseSynchronizer
   barrier semantics).
2. Skim `platform.yaml` composition keys (`composition_completeness_threshold`,
   factor model, `λ_TC`, `λ_risk`) and any `layer: PORTFOLIO` alpha YAML.


**Architecture (contractual):**

```
Signal (per symbol, per alpha)
  → UniverseSynchronizer: fan-in to CrossSectionalContext per (alpha_id, horizon, boundary)
  → CompositionEngine → CrossSectionalRanker (+ optional decay weighting)
       → FactorNeutralizer → SectorMatcher → TurnoverOptimizer (cvxpy)
  → SizedPositionIntent (target_positions, mechanism_breakdown, decision_basis_hash)
  → RiskEngine.check_sized_intent → per-leg OrderRequest   [out of scope here]
```

**Hard invariants (non-negotiable):**

- Inv-5: deterministic replay — `decision_basis_hash` and emission order bit-identical
  (Level-3 sized-intent + Level-4 portfolio-order parity hashes).
- Inv-6: causality — construction at boundary T uses only Signals with ts ≤ T.
- Inv-7: typed `CrossSectionalContext` / `SizedPositionIntent`.
- Inv-11: fail-safe — low completeness / missing data → reduce or skip, never inflate.
- G16 PORTFOLIO rule 8: per-family `mechanism_max_share_of_gross` cap enforced at emit.

---

## Scope — files to audit

### Composition pipeline

- `src/feelies/composition/synchronizer.py` — `UniverseSynchronizer` fan-in / barrier
- `src/feelies/composition/cross_sectional.py` — `CrossSectionalRanker`, decay weighting
- `src/feelies/composition/factor_neutralizer.py` — factor-loading neutralization
- `src/feelies/composition/sector_matcher.py` — sector matching
- `src/feelies/composition/turnover_optimizer.py` — cvxpy turnover/risk optimization
- `src/feelies/composition/engine.py` — `CompositionEngine` orchestration
- `src/feelies/composition/protocol.py` — `PortfolioAlpha` protocol

### Position state

- `src/feelies/portfolio/cross_sectional_tracker.py`
- `src/feelies/portfolio/position_store.py`, `memory_position_store.py`,
  `strategy_position_store.py` (*touchpoints* — position-state reads only; PnL math is
  owned by `audit_position_management.md`)
- `src/feelies/alpha/portfolio_layer_module.py`, `intent_set.py`
- `src/feelies/core/events.py` — `CrossSectionalContext`, `SizedPositionIntent` fields

### Reference-data inputs

- `scripts/build_reference_factor_loadings.py` — factor-loading artifact builder
- `src/feelies/storage/reference/factor_loadings/`, `sector_map/` (*touchpoints* —
  store machinery owned by `audit_data_ingestion.md`; here only causality/staleness of
  the loadings consumed)

### Tests (spec + gap analysis)

- `tests/composition/test_synchronizer.py`, `test_cross_sectional.py`, `test_engine.py`,
  `test_ranker_multi_feeder.py`, `test_portfolio_loader.py`
- `tests/portfolio/test_*.py`
- Determinism: `tests/determinism/test_sized_intent_replay.py`,
  `test_sized_intent_with_decay_replay.py`, `test_portfolio_order_replay.py`
- Integration: `tests/integration/test_xsect_v1_e2e.py`,
  `test_mixed_mechanism_e2e.py`, `test_mixed_mechanism_universe.py`,
  `test_dual_scale_down_e2e.py`, `test_phase4_e2e.py`
- Acceptance: `tests/acceptance/test_bt13_portfolio_research_only.py` (PORTFOLIO
  research-only gating — *cross-ref*; cited by `audit_harness_cli.md` for the CLI side)

**Out of scope:** SIGNAL alpha internals, risk per-leg veto (see `audit_risk_engine.md`),
fills.

---

## Audit dimensions (answer each with evidence)

### A. UniverseSynchronizer fan-in & barrier

1. Emission order: sorted by `(boundary_ts_ns, alpha_id, horizon_seconds)` —
   deterministic and stable under symbol-set permutation?
2. `completeness` computation: numerator/denominator correct? Stale-signal exclusion?
3. Barrier timeout / `composition_completeness_threshold`: below threshold → skip with
   warning (fail-safe)? Any path that proceeds on partial universe and inflates weights?
4. Causality: does the fan-in ever capture a Signal with ts > boundary_ts_ns?

### B. CrossSectionalRanker & decay weighting

1. Ranking/standardization math: stated in plain math; numerically stable (zero-variance
   universe, single-symbol)?
2. Decay weighting: `exp(-Δt/hl)` with `hl = expected_half_life_seconds`; `decay_floor`
   clamp present? Produces a *different* `decision_basis_hash` than decay-OFF (verified)?
3. Mechanism breakdown: `dict[TrendMechanism, float]` sums to gross? Cap scaling applied
   *before* renormalization (G16 rule 8)?

### C. Determinism of the optimizer (highest risk)

1. `turnover_optimizer.py` (cvxpy): is the solver, solver options, and tolerances pinned
   so the solution is bit-identical across platforms/BLAS? Any reliance on solver default
   that could drift?
2. Tie-breaking and ordering of decision variables — deterministic?
3. Infeasibility / solver failure: fail-safe (flat / reduce) or undefined?
4. Float→quantity rounding: where, and is it deterministic?

### D. Factor neutralization & sector matching

1. Factor-loading ingestion: source, refresh cadence (`0 = static at bootstrap`),
   staleness handling. Causality of loadings (no future loadings).
2. Neutralization math: regression/projection correct? Degenerate factor matrix?
3. Sector matching: does it preserve mechanism caps and neutralization?

### E. decision_basis_hash & provenance

1. What exactly is hashed? Does it cover all inputs that affect `target_positions`?
2. Could two materially different inputs collide, or identical inputs differ?
3. Correlation IDs `intent:<alpha_id>:<boundary_index>` — unique and sequence-stamped?

### F. Test & validation gaps

1. Map invariants (determinism, completeness fail-safe, mechanism cap, causality) to
   tests — **covered / partial / missing**.
2. Is optimizer determinism asserted under a perturbed environment (different BLAS / OS)?
3. Propose **minimal** new tests (golden intent replay, property-based cap) — specs only.

### G. Prioritized recommendations (P0/P1/P2)

- **P0:** optimizer non-determinism, completeness fail-safe bypass, causality leak,
  mechanism-cap miscount, decision_basis_hash under-coverage.
- **P1:** neutralization math weaknesses, stale factor loadings, decay-weighting edge
  cases, rounding drift.
- **P2:** richer construction (risk model, sector taxonomy), turnover-cost calibration.

Each item: component, `file:line`, one-sentence fix, expected impact.

---

## Working method

1. Build a **PORTFOLIO alpha inventory** (alpha_id, universe size, depends_on_signals,
   mechanism caps, factor model, completeness threshold).
2. Audit `synchronizer.py` (fan-in/barrier) first.
3. Audit `cross_sectional.py` + `turnover_optimizer.py` (determinism) — the crux.
4. Trace one boundary: Signals → context → intent, and recompute the hash inputs.
5. Cross-check Level-3 + Level-4 parity hashes.
6. Cross-check findings against the owning skill's **Not shipped** sections before filing P0 on absent features.
7. Run **read-only** checks only:
   - `uv run pytest tests/composition/ tests/portfolio/ -q`
   - `uv run pytest tests/determinism/test_sized_intent_replay.py tests/determinism/test_sized_intent_with_decay_replay.py tests/determinism/test_portfolio_order_replay.py -q`
   - `uv run pytest tests/integration/test_xsect_v1_e2e.py -q`
   Do not modify production code.

---

## Output format (strict)

Write the audit report to `docs/audits/composition_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top determinism/safety risks; top opportunities.
2. **PORTFOLIO alpha inventory** (markdown table).
3. **Synchronizer/barrier audit** (fan-in, completeness, causality).
4. **Ranker & decay audit** (math, mechanism breakdown).
5. **Optimizer determinism audit** (deep dive — largest section).
6. **Neutralization / sector audit**.
7. **decision_basis_hash & provenance audit**.
8. **Test gap matrix**.
9. **Prioritized backlog** (P0/P1/P2, effort S/M/L).
10. **Appendix:** open questions needing data runs.

Use code citations as `path:line` for every non-trivial claim.
Distinguish **implementation bug** vs **modeling choice** vs **library nondeterminism**.

---

## Quality bar

- Prefer **falsifiable** statements ("cvxpy ECOS default tolerance lets the solution
  drift in the 8th digit → decision_basis_hash differs across BLAS") over adjectives.
- Treat any optimizer nondeterminism as a P0 — it breaks Inv-5 platform-wide.
- Flag any path where low completeness or missing factor data *increases* gross.
- Respect deterministic replay: no fixes that introduce randomness or wall-clock.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for `TurnoverOptimizer` solver pinning and
  the completeness fail-safe as a follow-up PR plan."*
- *"Verify decision_basis_hash coverage by enumerating every input to `target_positions`
  and checking each is hashed — audit commentary only."*
- *"Propose a cross-platform determinism harness for the optimizer (different BLAS) —
  spec only, no code."*
