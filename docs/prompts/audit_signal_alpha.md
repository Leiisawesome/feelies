# Layer-2 SIGNAL alpha & horizon engine audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies
Layer-2 `HorizonSignal` alphas, the `HorizonSignalEngine`, the `cost_arithmetic`
disclosure, the `trend_mechanism` taxonomy (G16), and the `Signal` event contract —
from `HorizonFeatureSnapshot` + `RegimeState` → `Signal`.

---

## Mission

You are a senior quantitative microstructure researcher and systems auditor. Perform a
**read-only, evidence-based audit** of the feelies SIGNAL layer — the code that turns
features into edge claims.

**Primary focus:** This layer is where the platform asserts an *economic hypothesis*.
Inv-1 (structural mechanism required) and Inv-12 (cost realism) live or die here. A
signal that fires without a real mechanism, or whose disclosed `cost_arithmetic`
doesn't reconcile with its actual edge, leaks capital with full provenance.

**Goal:** Identify where signal logic is mechanistically sound vs. curve-fit, where the
cost disclosure is honest vs. aspirational, where G16 mechanism↔horizon binding is
enforced vs. cosmetic, and what changes would yield **falsifiable, cost-survivable**
signals — without breaking platform invariants.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Platform context (read first)

1. Read `.cursor/skills/microstructure-alpha/SKILL.md` end-to-end (the `HorizonSignal`
   protocol, `Signal` semantics, `cost_arithmetic`, `TrendMechanism`).
2. Read `.cursor/skills/feature-engine/SKILL.md` § on `HorizonFeatureSnapshot` (the
   sole Layer-2 input post-D.2).
3. Read `docs/three_layer_architecture.md` §5.5 (`Signal` event), §8.4 (regime gate
   DSL), §20 (Trend-Physics Enforcement Layer / G16), §6.4 (signals module).
4. Skim every `alphas/*/*.alpha.yaml` — `consumed_features`, `horizon_seconds`,
   `trend_mechanism:`, `cost_arithmetic:`, `regime_gate:`.

**Architecture (contractual):**

```
HorizonFeatureSnapshot + RegimeState
  → RegimeGate (on/off; see audit_regime.md — out of scope here)
  → HorizonSignal.evaluate(snapshot, regime, params) → Signal | None   [STATELESS]
  → HorizonSignalEngine: one Signal per (alpha_id, symbol, boundary_index)
  → bus → orchestrator M4 SIGNAL_EVALUATE
```

- **Stateless purity:** `evaluate` is a pure function of (snapshot, regime, params).
  No per-symbol state, no clock reads, no raw quotes.
- **Single-horizon binding (v0.2 §10):** each alpha anchors to one `horizon_seconds`.
- **Mechanism propagation:** engine stamps `Signal.trend_mechanism` and
  `Signal.expected_half_life_seconds` from the alpha's G16 block.

**Hard invariants (non-negotiable):**

- Inv-1: every signal names the causal mechanism it exploits.
- Inv-2: falsifiability defined before testing — no retrospective narratives.
- Inv-5: deterministic replay (Level-2 SIGNAL parity hash locks scope/ordering/sequence).
- Inv-6: causality — `evaluate` at boundary T uses only data ≤ T.
- Inv-7: typed `Signal` events; no untyped leakage.
- Inv-12: `expected_edge > 1.5× round_trip_cost`; survive 1.5× cost and 2× latency.

---

## Scope — files to audit

### Signal engine & protocol

- `src/feelies/signals/horizon_engine.py` — `HorizonSignalEngine` (gate→evaluate→emit)
- `src/feelies/signals/horizon_protocol.py` — `HorizonSignal` protocol contract
- `src/feelies/core/events.py` — `Signal` fields (direction, strength, edge,
  `trend_mechanism`, `expected_half_life_seconds`)

### Alpha disclosure & gates (load-time correctness)

- `src/feelies/alpha/cost_arithmetic.py` — `CostArithmetic` reconciliation (±5%, ≥1.5×)
- `src/feelies/alpha/layer_validator.py` — G2–G16 structural gates (*touchpoint* — owned
  by `audit_alpha_lifecycle.md`; here only G12/G16 as they bear on signal semantics)
- `src/feelies/alpha/loader.py` — YAML → alpha construction (*touchpoint* — owned by
  `audit_alpha_lifecycle.md`)
- `src/feelies/alpha/arbitration.py`, `aggregation.py` — multi-alpha conflict / combine
- `src/feelies/alpha/signal_layer_module.py`, `module.py` — loaded alpha surface
  (*touchpoints* — owned by `audit_alpha_lifecycle.md`; read for how `evaluate` and
  params reach the engine, defer structural critique)

### Alpha contracts (ground truth for intended semantics)

- `alphas/*/*.alpha.yaml` — every SIGNAL alpha

### Tests (spec + gap analysis)

- `tests/signals/test_horizon_signal_engine.py`
- `tests/alpha/test_cost_arithmetic_gate.py`, `test_gate_g16.py`, `test_gate_g16_props.py`
- `tests/alpha/test_layer_validator_g2_g13.py`, `test_arbitration.py`, `test_aggregation.py`
- `tests/alpha/test_sig_*.py` (per-alpha behavioral tests)
- Determinism: `tests/determinism/test_signal_replay.py`,
  `tests/determinism/test_emit_signals_jsonl.py`
- Acceptance: `tests/acceptance/test_g16_rule_completeness.py`,
  `tests/acceptance/test_inv12_stress_gate.py`

**Out of scope:** regime gate internals (see `audit_regime.md`), sensor math (see
`audit_sensor.md`), risk sizing, fills.

---

## Audit dimensions (answer each with evidence)

### A. HorizonSignal purity & causality

1. Is `evaluate` genuinely stateless? Any hidden per-symbol accumulation, module-level
   mutable state, or `datetime`/clock read?
2. Causality: does `evaluate` only read `snapshot.values` at boundary T and the
   contemporaneous `RegimeState`? Any access to live sensor cache or raw quotes?
3. Warm/stale handling: does the engine suppress entries on `warm=False` / `stale=True`
   features while permitting exits (fail-safe)?
4. One-`Signal`-per-`(alpha_id, symbol, boundary_index)`: enforced? Idempotent on replay?

### B. Mechanism honesty (Inv-1, G16)

For **each** SIGNAL alpha:
1. State the declared `trend_mechanism` family and translate the `evaluate` body into
   the plain-English causal claim. Do they match?
2. `expected_half_life_seconds` vs `horizon_seconds`: ratio in `[0.5, 4.0]`? Does the
   actual decay implied by the logic match the declared half-life?
3. `l1_signature_sensors`: are the consumed features actually the fingerprint of the
   claimed mechanism, or convenient proxies?
4. `LIQUIDITY_STRESS` family: exit-only invariant — can any entry-direction `Signal`
   originate from a stress alpha?

### C. Cost arithmetic honesty (Inv-12)

1. For each alpha, recompute `margin_ratio = edge / (half_spread + impact + fee)` from
   the disclosed components. Does it reconcile within ±5%? Is it ≥ 1.5×?
2. Are the disclosed `half_spread_bps` / `impact_bps` / `fee_bps` plausible for the
   symbol cohort and horizon, or optimistic?
3. Stress: would the alpha still clear 1.5× under 1.5× cost and 2× latency
   (`tests/acceptance/test_inv12_stress_gate.py`)?

### D. Falsifiability & edge vs alpha (Inv-2)

1. For each alpha, what market condition should **disprove** the hypothesis? Is it
   stated anywhere (YAML, test, docstring) or only implied?
2. Distinguish *edge* (structural mechanism) from *measured alpha* — is any alpha's
   evidence consistent with overfitting (many free parameters, no OOS claim)?
3. Parameter surface: does the alpha respect the §8.5 parameter cap? Count free knobs.

### E. Multi-alpha interaction

1. `arbitration.py` / `aggregation.py`: how are conflicting signals on the same symbol
   resolved? Deterministic? Economically coherent?
2. Can two alphas double-count the same mechanism (crowding into one L1 observable)?

### F. Test & validation gaps

1. Map each invariant (purity, causality, one-per-boundary, mechanism binding, cost
   reconciliation) to existing tests — mark **covered / partial / missing**.
2. Do per-alpha tests assert *economic* behavior or only that code runs?
3. Propose **minimal** new tests (golden replay, property-based) — specs only.
4. Propose offline validation: conditional forward-return / IC by signal bucket on
   cached NBBO (APP/AAPL) — methodology only, no code.

### G. Prioritized recommendations (P0/P1/P2)

- **P0 (correctness/safety):** purity violations, lookahead, non-determinism,
  stress-family entries, cost-arithmetic that fails to reconcile.
- **P1 (economic soundness):** mechanism↔logic mismatch, optimistic cost components,
  half-life/horizon ratio drift, overfit parameter surfaces.
- **P2 (research/product):** new mechanism families, arbitration improvements,
  falsifiability documentation.

Each item: alpha_id or module, `file:line`, one-sentence fix, expected impact.

---

## Working method

1. Build a **SIGNAL alpha inventory** (alpha_id, mechanism, horizon, half-life,
   margin_ratio, consumed_features, regime_gate summary) from YAML + code.
2. Audit `cost_arithmetic.py` + `layer_validator.py` (load-time contract) first.
3. Audit `horizon_engine.py` (purity/causality/ordering) second.
4. Trace one alpha end-to-end: YAML → loader → evaluate → emitted `Signal`.
5. Cross-check the Level-2 SIGNAL parity hash.
6. Run **read-only** checks only:
   - `uv run pytest tests/signals/test_horizon_signal_engine.py tests/alpha/test_gate_g16.py tests/alpha/test_cost_arithmetic_gate.py -q`
   - `uv run pytest tests/determinism/test_signal_replay.py tests/acceptance/test_inv12_stress_gate.py -q`
   Do not modify production code.

---

## Output format (strict)

Write the audit report to `docs/audits/signal_alpha_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top capital risks; top opportunities.
2. **SIGNAL alpha inventory** (markdown table).
3. **Engine audit** (purity, causality, ordering, warm/stale).
4. **Per-alpha audit** (one subsection each, ≤1 page): mechanism honesty, cost
   reconciliation, falsifiability.
5. **Multi-alpha interaction** (arbitration / aggregation / crowding).
6. **Cost & stress matrix** (alpha × margin_ratio × stress survival).
7. **Test gap matrix**.
8. **Prioritized backlog** (P0/P1/P2, effort S/M/L).
9. **Appendix:** open questions needing data runs (symbol, date, metric).

Use code citations as `path:line` for every non-trivial claim.
When citing literature, give author-year-title, not vague "standard practice."
Distinguish **implementation bug** vs **modeling choice** vs **L1 identifiability limit**.

---

## Quality bar

- Prefer **falsifiable** statements ("alpha X discloses 9 bps edge but its OFI proxy
  decays in <5s, so half-life=120s is unsupported") over adjectives.
- Treat `cost_arithmetic` as an economic contract, not metadata — recompute it.
- Flag any signal path that could fire entries in adverse regimes or stress families.
- Do not recommend L2 order-book features — platform is L1 NBBO only.
- Respect deterministic replay: no fixes that introduce randomness or wall-clock.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft P0 fixes only for the cost-arithmetic reconciliation and
  any stress-family entry path as a follow-up PR plan."*
- *"For `sig_kyle_drift_v1`, rewrite the mechanism claim and falsification rule in
  plain English and propose a tighter cost disclosure — audit commentary only."*
- *"Propose an offline IC/forward-return methodology for each alpha using disk cache
  APP/2026-03-26 — still no code changes."*
