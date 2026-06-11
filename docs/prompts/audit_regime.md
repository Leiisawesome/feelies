# Services regime & regime-gate audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies
platform-level regime detection (`services/`), the **RegimeGate DSL** (the primary
gate for signal emission), hazard detection, and all downstream consumers that
turn regime state into sizing, risk limits, and orders.

---

## Mission

You are a senior quantitative microstructure researcher, Bayesian filtering specialist,
and systems auditor. Perform a **read-only, evidence-based audit** of the feelies
regime stack end-to-end — from NBBOQuote → `RegimeState` → `RegimeGate` → `Signal`
→ risk/sizer → `OrderRequest`.

**Primary focus:** The **regime gate** is the most consequential control surface in
the trading path. A wrong gate fires alpha in the wrong microstructure regime
(adverse selection, cost blowout); a too-loose gate fails Inv-11; a too-tight gate
starves valid edge. Audit it with the same rigor as a production risk model.

**Goal:** Identify where regime math is rigorous vs. heuristic, where gate logic is
sound vs. fragile, where consumer contracts disagree, and what changes would yield
**safer, more economically meaningful** regime conditioning — without breaking
platform invariants.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Platform context (read first)

1. Read `.cursor/skills/regime-detection/SKILL.md` end-to-end.
2. Read `.cursor/skills/microstructure-alpha/SKILL.md` § on `regime_gate:` and
   hysteresis.
3. Read `.cursor/skills/risk-engine/SKILL.md` § on regime scaling and hazard exits.
4. Read `docs/three_layer_architecture.md` §8.4 (regime gate), §12 (determinism &
   parity — the L6 regime-state hash), §20.3–20.7 (hazard detection / exits). The
   regime engine's writer/reader contract is documented in the regime-detection skill,
   not the architecture doc.
5. Skim `platform.yaml` `regime_engine:` and example alpha `regime_gate:` blocks in
   `alphas/` (especially `sig_benign_midcap_v1`, `sig_inventory_revert_v1`,
   `sig_moc_imbalance_v1`).

**Architecture (contractual):**

```
M1  NBBOQuote logged + bus published
M2  orchestrator → regime_engine.posterior(quote)  [SOLE WRITER]
    → RegimeState on bus → RegimeHazardDetector → RegimeHazardSpike?
SENSOR_UPDATE / HORIZON_AGGREGATE
SIGNAL_GATE   HorizonSignal.evaluate(snapshot, regime)
                regime_gate DSL: on_condition / off_condition + hysteresis
M5  risk: check_signal / check_sized_intent + position_sizer (current_state)
M6  risk: check_order + HazardExitController (hazard spikes)
```

- **Layer 2 gate:** `RegimeGate` evaluates boolean DSL against `RegimeState`
  posteriors + live sensor cache — purity boundary; no raw quotes.
- **Risk/sizer:** read-only `current_state(symbol)` — never call `posterior()`.
- **Hazard:** pure function over consecutive `RegimeState` pairs; exit-only.

**Hard invariants (non-negotiable):**

- Inv-5: deterministic replay (same log + params → bit-identical outputs).
- Inv-6: causality — gate bindings at boundary T use only data ≤ T.
- Inv-7: typed events; no untyped cross-layer leakage.
- Inv-11: fail-safe — missing/unknown regime → reduced exposure, never amplified.
- Single-writer: only orchestrator M2 calls `posterior()`.
- Idempotency: `posterior()` cached per `(symbol, sequence)`.

---

## Scope — files to audit

### Core regime services

- `src/feelies/services/regime_engine.py`
  (`RegimeEngine` protocol, `HMM3StateFractional`, registry, entropy helper)
- `src/feelies/services/regime_hazard_detector.py`
  (`detect`, suppression, `RegimeHazardDetector`)

### Regime gate (highest priority)

- `src/feelies/signals/regime_gate.py` — AST whitelist, bindings, hysteresis SM
- `src/feelies/signals/horizon_engine.py` — how gate integrates with signal eval
- `src/feelies/alpha/loader.py` — YAML parse / gate construction at load time

### Event schema & wiring

- `src/feelies/core/events.py` — `RegimeState`, `RegimeHazardSpike` fields
- `src/feelies/kernel/orchestrator.py` — M2 writer, calibration, hazard wiring,
  session reset, tie-breaking for `dominant_state`
- `src/feelies/bootstrap.py` — engine selection, registry name, calibration quotes

### Downstream consumers (signal → risk → order path)

- `src/feelies/risk/basic_risk.py` — `_regime_scaling()` (EV over posteriors)
- `src/feelies/risk/position_sizer.py` — `_get_regime_factor()`
- `src/feelies/risk/hazard_exit.py` — `HazardExitController`
- `src/feelies/composition/` — any regime-aware portfolio paths

### Alpha contracts (ground truth for intended semantics)

- `alphas/*/*.alpha.yaml` — every `regime_gate:` block
- `tests/alpha/test_gate_g16*.py` — gate validation at load time

### Tests (spec + gap analysis)

- `tests/services/test_regime_engine.py`
- `tests/services/test_regime_engine_improvements.py`
- `tests/services/test_regime_hazard_detector.py`
- `tests/services/test_regime_hazard_engine_wiring.py`
- `tests/signals/test_regime_gate_dsl.py`
- `tests/signals/test_regime_gate_dsl_props.py`
- Determinism: `tests/determinism/test_regime_hazard_replay.py` (L5 hazard hash),
  `tests/determinism/test_hazard_exit_replay.py`
- Kernel: `tests/kernel/test_orchestrator.py` (M2 regime paths)

---

## Audit dimensions (answer each with evidence)

### A. RegimeEngine mathematical rigor (`HMM3StateFractional`)

The class docstring states this is a **fixed-structure forward filter**, not a
full Baum–Welch HMM. Audit accordingly — do not grade it as an EM-fit HMM.

1. **Model specification**
   - Write the state-space model explicitly: hidden Markov chain over K states,
     observation = log-relative spread, emission = diagonal Gaussian.
   - Cite literature: Hamilton (1989) regime switching, Kim (1994) Markov-switching,
     vs. online forward-only filters (fixed parameters).
   - Is log-relative spread a **sufficient statistic** for the claimed states
     (`compression_clustering`, `normal`, `vol_breakout`)? What microstructure
     forces does it capture vs. miss (vol without spread widening, inventory
     pressure, information asymmetry)?

2. **Emission calibration**
   - Quantile-bucket Gaussian fit: sample size (`_MIN_CALIBRATION_SAMPLES=30`),
     bucket boundaries, per-symbol vs pooled.
   - `order_emissions_by_increasing_mean=True`: index–name semantic mismatch
     (state 0 = tightest spread, but name may say `compression_clustering`).
   - Pairwise separation gate: is `d = |μ_i−μ_j| / sqrt(σ_i²+σ_j²) ≥ 0.5`
     adequate for 3-way classification at L1?
   - Uncalibrated defaults: quantify posterior discrimination with placeholder
     emissions on typical US midcap spreads.

3. **Transition dynamics**
   - Default matrix dwell times in **ticks** vs **seconds** — quantify mean
     dwell at 10 / 50 / 100 quotes/sec.
   - `transition_time_scaling_enabled`: verify `p_stay_new = p_stay^scale` math,
     row renormalization, cache correctness, edge cases (first quote, gaps, halts).
   - Is tick-indexed transition appropriate when quote rate varies 10× intraday?

4. **Bayesian update correctness**
   - Predict step: `π_pred = π_prior @ T` — verify index convention (row vs col).
   - Update step: unnormalized product + renorm; degenerate likelihood fallback.
   - Invalid spread (`spread ≤ 0`): prediction-only path — economically justified?
   - NaN/inf handling: reset to uniform — fail-safe or information destruction?

5. **Identifiability & label stability**
   - Can two calibration runs on adjacent days permute state indices?
   - Impact on `P(normal)` in alpha YAML when emissions reorder but names don't.
   - Checkpoint/restore: determinism under flag mismatch.

6. **Idempotency & single-writer**
   - Sequence watermark vs timestamp — replay parity when duplicate sequences?
   - Any code path besides orchestrator M2 that calls `posterior()`?

### B. RegimeGate DSL — **critical path for signals** (deep dive)

This section gets the most audit depth. The gate controls **whether alpha logic runs
at all** at each horizon boundary.

1. **Parse-time safety (G2 purity)**
   - Whitelist completeness: every allowed AST node type documented and enforced.
   - Forbidden nodes: Attribute, Subscript, Call (non-whitelist), Lambda, etc.
   - Can any whitelisted construct leak scope or enable side effects?
   - `P(<state_name>)` resolution: typo → `UnknownRegimeStateError` at eval or load?

2. **Runtime bindings — causality (Inv-6)**
   - `P(state)`: sourced from which `RegimeState` — same-tick M2 or stale?
   - `dominant`, `entropy`: consistent with posteriors passed in?
   - Sensor bindings (`<id>`, `_zscore`, `_percentile`): snapshot time vs gate eval
     time — any lookahead via aggregator last-value hold?
   - Missing binding behavior: suppress vs crash — aligned with warm/stale policy?

3. **Hysteresis state machine**
   - ON/OFF transitions: `on_condition` / `off_condition` both false → hold state.
   - `posterior_margin` / `percentile_margin` YAML block: wired or dead config?
   - Overlap band: can gate be ON while `P(normal)` is below alpha author's intent?
   - Per `(alpha_id, symbol)` isolation — cross-symbol leakage impossible?
   - Cold start: initial OFF — correct for entry suppression (Inv-11)?

4. **Economic semantics of example gates**
   - For each production alpha YAML, translate gate to plain English microstructure
     hypothesis ("trade only when spread is tight AND OFI elevated AND regime normal").
   - Falsifiability: what market conditions should **disprove** the gate design?
   - Gate vs mechanism: does `on_condition` align with declared `trend_mechanism`
     and `expected_half_life_seconds` (G16)?

5. **Interaction with HorizonSignalEngine**
   - Gate evaluated before or after `evaluate()`? (Must be before — verify.)
   - Regime OFF: entries suppressed, exits permitted? (Fail-safe path.)
   - Warm/stale snapshot + gate ON: can stale features fire entries?

6. **Operator precedence & DSL edge cases**
   - `and`/`or`/`not` precedence matches author intent?
   - Division by zero, comparison with None/missing bindings.
   - String equality on `dominant` — case sensitivity, unknown state names.

### C. RegimeHazardDetector — math & suppression logic

1. **Detection criterion**
   - Formalize: fire iff `p_now < p_prev` AND (`dominant flipped` OR
     `p_now < 1 − hysteresis_threshold`).
   - "Sliding peak" case: dominant unchanged but below floor — quant justification.
   - `hazard_score = clip01((p_prev − p_now) / max(p_prev, ε))` — calibration to
     exit urgency; relationship to hazard-rate literature (survival analysis).

2. **Suppression / re-arm**
   - Episode definition: one spike per `(symbol, engine_name, departing_state)`.
   - Re-arm on re-dominance vs posterior recovery above floor — logic sound?
   - Session boundary reset in orchestrator — prevents cross-session false spikes?

3. **Pure-function contract**
   - `detect()` with `suppressed=None` vs stateful wrapper — replay equivalence.
   - `_validate_dominant_consistency`: orchestrator tie-break (lowest index) vs
     hazard incoming-state tie (`None`) — downstream handling in hazard exit.

4. **Consumer: HazardExitController**
   - Threshold mapping: `hazard_score` vs `hazard_score_threshold` in alpha YAML.
   - Exit-only invariant (Inv-11): entries never triggered by hazard path.
   - Interaction with regime gate OFF — double exit or conflicting signals?

### D. Consumer contract coherence (signal → risk → order)

Build a **single table** tracing one tick/boundary through all regime touchpoints:

| Stage | Component | Regime input | Aggregation | Fail-safe default |
|-------|-----------|--------------|-------------|-------------------|
| M2 | RegimeEngine | NBBOQuote | posterior vector | uniform / skip |
| Gate | RegimeGate | posteriors + sensors | boolean ON/OFF | OFF (no entry) |
| Signal | HorizonSignalEngine | gate + snapshot | Signal or None | suppress |
| M5 | Position sizer | current_state EV | scale factor | 1.0× |
| M5 | Risk check_signal | current_state EV | limit multiplier | 1.0× |
| M6 | Risk check_order | current_state EV | limit multiplier | 1.0× |
| Hazard | HazardExitController | RegimeHazardSpike | flatten order | no action |

Audit for:

1. **Semantic inconsistency** — gate uses `P(normal) > 0.7` (hard threshold) while
   risk uses EV smoothing — can signal fire in a regime risk considers stressed?
2. **Double scaling** — sizer EV × risk EV: intentional series or accidental compounding?
3. **Dominant vs posterior** — gate can use `dominant`; risk uses EV; hazard uses
   dominant index — document when these disagree and capital impact.
4. **Timing** — `current_state()` at M5/M6: same M2 posterior as gate saw at last
   boundary, or updated per-tick? Horizon signals vs tick-level risk: lag model.
5. **Unknown state names** — risk defaults to `min(scales)`; sizer defaults to
   configured default — aligned fail-safe?

### E. Quantitative trading grounding

1. **Regime taxonomy vs microstructure reality**
   - Map each state name → observable proxy (spread) → latent force (liquidity,
     volatility, information) → expected alpha behavior (edge sign, half-life,
     cost sensitivity).
   - Is 3-state spread-only taxonomy adequate for intraday equity microstructure?
   - What regimes **cannot** be detected with this engine (flash events, MOC,
     halts, quote stuffing)?

2. **Gate design patterns**
   - Good vs bad gate templates for each `TrendMechanism` family
     (KYLE_INFO, INVENTORY, HAWKES_SELF_EXCITE, LIQUIDITY_STRESS, SCHEDULED_FLOW).
   - Should LIQUIDITY_STRESS alphas gate **on** stress or **off** stress given
     G16 exit-only invariant?
   - Cost realism (Inv-12): gates that fire in wide-spread regimes — survivable?

3. **Regime conditioning and alpha decay**
   - When spread regime flips faster than horizon boundary (30–1800s), gate lag
     and stale ON state — quantify holding-period risk.
   - Hazard spike as **leading indicator** vs gate hysteresis — which should
     dominate exits?

4. **Calibration & deployment**
   - Required calibration protocol before live: sample size, symbol cohort, refit
     frequency, drift detection.
   - Per-symbol emissions vs global: when does cross-sectional gate comparability break?

### F. Test & validation gaps

1. Map each invariant (single-writer, idempotency, hysteresis band, suppression,
   fail-safe defaults, DSL safety) to existing tests — mark **covered / partial / missing**.
2. Property tests in `test_regime_gate_dsl_props.py` — do they encode economic
   invariants or only syntactic ones?
3. Propose **minimal** new tests (golden replay, property-based, counterexample)
   — specs only, no implementation.
4. Propose offline validation methodology:
   - Regime occupancy rates, transition matrix EM vs assumed T, spread-conditional
     forward returns by posterior bucket (APP/AAPL cached NBBO).
   - Gate ON/OFF vs conditional Sharpe / hit-rate / cost — methodology only.

### G. Prioritized recommendations

Three tiers:

- **P0 (correctness / safety):** math bugs, causality/lookahead, non-determinism,
  gate logic errors, fail-safe violations, dominant/posterior inconsistency,
  cross-session hazard false positives.
- **P1 (economic soundness):** miscalibrated emissions, tick-time transition mismatch,
  gate–risk semantic divergence, hysteresis dead config, insufficient separation gate.
- **P2 (research / product):** richer regime features (vol, trade intensity),
  alternative engines, gate DSL extensions, calibration automation.

Each item: component, `file:line`, one-sentence fix, expected impact on signal
quality / risk / order safety.

---

## Working method

1. Build a **regime stack inventory**: engine config, state names, transition flags,
   every alpha `regime_gate:` block (engine name, on/off strings, hysteresis).
2. Audit `regime_engine.py` math first (foundation).
3. Audit `regime_gate.py` second (critical path) — trace one alpha end-to-end.
4. Audit hazard detector + orchestrator wiring third.
5. Audit consumers last — verify contract table against code.
6. Cross-check tests and L5 hazard parity hash.
7. Run **read-only** checks only:
   - `uv run pytest tests/services/test_regime_engine.py tests/services/test_regime_hazard_detector.py -q`
   - `uv run pytest tests/signals/test_regime_gate_dsl.py tests/signals/test_regime_gate_dsl_props.py -q`
   - `uv run pytest tests/determinism/test_regime_hazard_replay.py tests/determinism/test_hazard_exit_replay.py -q`
   Do not modify production code.

---

## Output format (strict)

Write the audit report to `docs/audits/regime_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top risks to signal/risk/order path; top
   opportunities for economically meaningful regime conditioning.
2. **Regime stack inventory** (markdown table: engine, states, consumers, alphas).
3. **RegimeEngine audit** (model spec, calibration, transitions, update math).
4. **RegimeGate audit** (deep dive — largest section): per-alpha gate semantics,
   hysteresis, causality, DSL safety.
5. **Hazard detector audit** (detection math, suppression, session boundaries).
6. **Consumer coherence audit** (signal → risk → order trace table + disagreements).
7. **Microstructure grounding** (state taxonomy vs reality; mechanism × gate matrix).
8. **Test gap matrix**.
9. **Prioritized backlog** (P0/P1/P2, effort S/M/L).
10. **Appendix:** open questions needing data runs (symbol, date, metric).

Use code citations as `path:line` for every non-trivial claim.
When citing literature, give author–year–title, not vague "standard practice."
Distinguish **implementation bug** vs **modeling choice** vs **L1 identifiability limit**.

---

## Quality bar

- Prefer **falsifiable** statements ("if gate ON while `P(vol_breakout) > 0.4`,
  alpha X fires into wide-spread adverse selection") over adjectives.
- Treat **RegimeGate** as a production risk control — not syntactic sugar around alpha.
- Flag any path where regime state **increases** exposure vs baseline (Inv-11 violation).
- Do not recommend L2 order book features — platform is L1 NBBO only.
- Respect deterministic replay: no fixes that introduce randomness or wall-clock.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for RegimeGate hysteresis wiring and
  orchestrator dominant-state consistency as a follow-up PR plan."*
- *"Propose a calibration script spec for `HMM3StateFractional.calibrate()` using
  disk cache APP/2026-03-26 — still no code changes."*
- *"For `sig_benign_midcap_v1`, rewrite the regime_gate block in plain English and
  suggest a falsifiable alternative gate — audit commentary only."*
