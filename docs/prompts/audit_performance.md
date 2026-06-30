# Performance & latency-budget audit (Claude Code)

Use this prompt in a **Claude Code** session with full repo access. Scope: feelies
tick-to-trade hot path — critical-path latency, allocation/GC behavior, data-structure
choices, and the pinned perf baselines — **without sacrificing determinism**.

---

## Mission

You are a senior performance engineer for latency-critical trading infrastructure.
Perform a **read-only, evidence-based audit** of the feelies hot path and its perf
guardrails.

**Primary focus:** Performance here is constrained by a hard rule the rest of the industry
doesn't have — **determinism is non-negotiable** (Inv-5). Any optimization that introduces
parallelism, nondeterministic ordering, or wall-clock timing into the decision path is
forbidden, no matter how fast. The job is to find latency wins that are *determinism-safe*,
and to verify the perf baselines actually guard against regression.

**Goal:** Identify the real critical path (tick → sensor → snapshot → signal → risk →
order), where time/allocations are spent, which optimizations are safe vs. determinism-
breaking, and whether the pinned baselines are meaningful — without changing behavior.

**Do not implement fixes in this pass.** Deliver a structured audit report with
file/line citations, severity, and prioritized recommendations.

---

## Agent context (mandatory)

| Step | Resource |
|------|----------|
| 1 | `.cursor/rules/platform-invariants.mdc` — **Inv-5** (determinism is the binding constraint on optimizations) |
| 2 | `.cursor/rules/karpathy-guidelines.mdc` |
| 3 | `.cursor/skills/README.md` |
| 4 | `.cursor/skills/performance-engineering/SKILL.md` (**owner**) |
| 5 | `.cursor/skills/system-architect/SKILL.md` — M1–M6 hot path |

Perf wins that break parity hashes are P0 regressions, not P2 optimizations.


**Shipped vs Not shipped:** Treat skill sections marked **Not shipped** as design
targets — P0 only if code/tests claim they are live.

**Finding bar:** P0/P1 items must cite `Inv-N` + `path:line`. Read-only pass per
`.cursor/rules/karpathy-guidelines.mdc`.

---

## Platform context (read first)

**Docs and config** (after Agent context):

*(Skills and invariants loaded in Agent context above.)*


**Architecture (contractual):**

```
hot path per market event: M1 log/publish → M2 regime → SENSOR_UPDATE → HORIZON_AGGREGATE
                            → M4 SIGNAL_EVALUATE → M5/M6 risk → OrderRequest
perf budgets: per-stage latency targets; pinned baselines per host
known budget: decay-weighting end-to-end ≤ 5% wall-clock regression vs decay-OFF
```

**Hard invariants (binding constraints on any optimization):**

- Inv-5: no parallelism / ordering change / nondeterminism on the decision path.
- Inv-10: no wall-clock on the decision path (timing harness only, off-path).
- Optimizations must be behavior-preserving and replay-bit-identical.

---

## Scope — files to audit

### Hot path (profile, don't rewrite)

- `src/feelies/kernel/orchestrator.py`, `kernel/micro.py` — per-event driver
- `src/feelies/sensors/impl/*.py` — per-event incremental sensors
- `src/feelies/features/aggregator.py` — horizon aggregation
- `src/feelies/signals/horizon_engine.py` — signal evaluation
- `src/feelies/composition/*.py` — cross-sectional construction (cvxpy is heavy)
- `src/feelies/risk/*.py` — per-event risk checks
- `src/feelies/bus/event_bus.py` — dispatch overhead

### Perf guardrails

- `tests/perf/_pinned_baseline.py`, `tests/perf/baselines/v02_baseline.json`
- `tests/perf/test_paper_rth_no_regression.py`
- `tests/acceptance/test_perf_baseline_plumbing.py`
- `scripts/record_perf_baseline.py`, `record_paper_perf_baseline.py` (*touchpoints* —
  owned by `audit_harness_cli.md`; here only whether what they pin is meaningful)

**Out of scope:** correctness of the math (audited per layer); here the lens is
**latency, allocation, and regression guarding — subject to determinism**.

---

## Audit dimensions (answer each with evidence)

### A. Critical-path identification

1. Map the tick-to-trade path and estimate per-stage cost (from code structure; run the
   perf tests for measured numbers). Where is the time actually spent?
2. Which stages are O(symbols) vs O(1) per event? Any accidental O(n²) in fan-in /
   ranking / aggregation?
3. cvxpy in the composition layer: how heavy per boundary, and is it on the critical path
   or amortized at horizon boundaries only?

### B. Allocation & GC

1. Hot loops (per-quote sensors, aggregator): per-event allocations (new dataclasses,
   dict/list churn)? Could pre-allocation / reuse help **without** shared mutable state
   that breaks determinism?
2. Any large transient structures rebuilt every tick?
3. GC pause risk: long-lived large containers, reference cycles.

### C. Data-structure choices

1. Are hot-path lookups using the right structures (dict vs scan)? Any linear search where
   a map would do?
2. Decimal vs float on the hot path: where is Decimal required (PnL fidelity) vs where it
   costs unnecessarily?
3. Determinism constraint: any "faster" structure (set, unordered) that would break
   ordering — explicitly rule these out.

### D. Determinism-safety of optimizations (the binding lens)

1. For every optimization you propose, classify it: **determinism-safe** (pure speedup,
   identical outputs/ordering) vs **forbidden** (introduces parallelism/ordering/clock).
2. Confirm there is no existing parallelism on the decision path; if any exists, is it
   provably deterministic or a latent Inv-5 risk?

### E. Perf baselines & regression guarding

1. `_pinned_baseline.py` / `v02_baseline.json`: what is pinned, per which host, and how is
   drift detected? Is the ≤5% decay-weighting budget actually enforced?
2. Are baselines host-specific (so CI on a different machine is meaningful), or brittle?
3. Does `test_perf_baseline_plumbing.py` verify the harness wiring, not just a number?

### F. Test & validation gaps + prioritized recommendations

1. Which hot-path stages have **no** perf coverage? Note them.
2. Propose **minimal** perf tests / micro-benchmarks for uncovered stages — specs only.
3. Tiers:
   - **P0:** any existing nondeterminism/parallelism on the decision path; a perf baseline
     that guards nothing.
   - **P1:** hot-path allocations, O(n²) fan-in, Decimal misuse, brittle baselines.
   - **P2:** micro-optimizations, caching (determinism-safe only), observability.

Each item: component, `file:line`, optimization, **determinism classification**, expected
latency/allocation impact.

---

## Working method

1. Build a **critical-path cost map** (stage → complexity → measured/estimated cost).
2. Run the perf tests to get real numbers (read-only):
   - `uv run pytest tests/perf/ -q`
   - `uv run pytest tests/acceptance/test_perf_baseline_plumbing.py -q`
3. Inspect the heaviest stages for allocations and structure choices.
4. Classify every proposed optimization for determinism safety **before** recommending it.
5. Optionally measure with `uv run python -X importtime` / `cProfile` on
   `scripts/smoke_pipeline.py` (off-path timing only). Do not modify production code.
6. Cross-check findings against the owning skill's **Not shipped** sections before filing P0 on absent features.

---

## Output format (strict)

Write the audit report to `docs/audits/performance_audit_YYYY-MM-DD.md` with these sections:

1. **Executive summary** (≤15 bullets): top latency wins that are determinism-safe.
2. **Critical-path cost map** (markdown table: stage, complexity, cost, hot?).
3. **Allocation & GC audit**.
4. **Data-structure audit**.
5. **Determinism-safety classification** (every proposed optimization tagged safe/forbidden
   — this section gates all others).
6. **Perf-baseline audit** (what's pinned, drift detection, ≤5% budget).
7. **Test gap matrix** + proposed benchmarks.
8. **Prioritized backlog** (P0/P1/P2, effort S/M/L, each tagged determinism-safe).

Use code citations as `path:line` for every non-trivial claim.
Give measured numbers where you ran the perf suite; label estimates as estimates.

---

## Quality bar

- **Determinism beats speed, always.** Any optimization that risks Inv-5 is forbidden, not
  "P0 with caveats" — say so plainly.
- Prefer **measured** statements ("aggregator rebuilds a 50-key dict per quote → N
  allocations/sec at measured rate") over "this looks slow."
- No wall-clock on the decision path; timing belongs in the off-path harness.
- Stay read-only; propose, don't optimize, in this pass.

---

## Optional follow-ups (paste after the audit)

- *"After the report, draft determinism-safe P1 fixes only for hot-path allocation in the
  aggregator as a follow-up PR plan."*
- *"Profile `scripts/smoke_pipeline.py` with cProfile and attach the top-20 by cumulative
  time — measurement only, no code changes."*
- *"Classify every proposed optimization as determinism-safe or forbidden in a standalone
  table — audit commentary only."*
