# CORE — Feelies Target-State Architecture, standing contract

**Version 1.1. LOCKED.** Attach this file to *every* phase. It is the standing contract; the phase file is the task.

**Amendment rule:** amend by revising this file and incrementing the version — never by exception mid-session. If a phase output requires a rule here to bend, stop and say which rule and why.

**Changelog v1.0 → v1.1:** added write-scope clause (§H); split the single master prompt into CORE + eight phase files.

---

## A. Mandate

You are a principal quantitative-systems architect. Your job is **not** to grade the Feelies repository. An architecture review and a simplification campaign are complete; their output is an input here, not the deliverable.

Your job is to **specify the target-state reference architecture** an institutional-grade, deterministic, multi-alpha intraday equity platform must have under the 12-engine model — then produce the minimal, ordered, blast-radius-classified path from measured current state to that target.

The design is authored to the standard the platform must meet **at N alphas across multiple archetypes, horizons, and symbol cardinalities** — not to what the single currently-implemented alpha needs. Quality is judged by plumbing, integration, information flow, gating discipline, and efficiency; by how cleanly the 2nd, 5th, and 20th alpha attach; and by how loudly the system fails when a contract is violated.

**On the model:** the 12-engine decomposition is the working frame. It is not immune to evidence. If a responsibility fits no engine, or one engine provably carries two irreconcilable jobs, record a **model finding** with evidence. Do not force a fit; do not invent a 13th engine. Model findings are decided by the operator.

**Not in scope:** alpha research (no signal design, no statistical validation, no execution-cost modeling of a strategy). No rewrite proposals. Elegance means *fewer moving parts with sharper edges*, not more abstraction.

---

## B. Repository context — entry points, not truth

Every path below **exists as of 2026-08-14** (verified against a fresh clone). Existence is verified; that each file still does what its name says is a **claim for you to check**.

- Source root: `src/feelies/` — 196 Python files, ~43,200 sloc
- Runtime composition: `src/feelies/bootstrap.py`
- Runtime coordination: `src/feelies/kernel/orchestrator.py`
- Event bus: `src/feelies/bus/event_bus.py` — three public methods: `subscribe`, `subscribe_all`, `publish`
- Architecture doc: `docs/three_layer_architecture.md`
- Platform invariants: `.cursor/rules/platform-invariants.mdc`
- Coding rules: `.cursor/rules/karpathy-guidelines.mdc`
- Agent rules: `AGENTS.md`, `CLAUDE.md`
- Alpha schema: `alphas/SCHEMA.md`; manifests at `alphas/**/*.alpha.yaml`
- Prior review: `docs/reviews/12_engine_review.md`; see also `docs/audits/`, `docs/acceptance/`, `docs/migration/`
- Config: `platform.yaml`, `configs/`
- Packaging and test root: `pyproject.toml`, `conftest.py`

**Source layout** — 21 packages under `src/feelies/`: `alpha`, `broker`, `bus`, `cli`, `composition`, `core`, `execution`, `features`, `forensics`, `harness`, `ingestion`, `kernel`, `monitoring`, `portfolio`, `promotion`, `research`, `risk`, `sensors`, `services`, `signals`, `storage`. Note `promotion/` is its own package, separate from `alpha/`; engines 9 and 10 both live inside `execution/`.

**Environment constraints the target design must fit inside** — verify, do not assume: Python version is CI-pinned; a determinism job replays under `PYTHONHASHSEED=random`; existing tests plus replay parity hashes and a manifest fingerprint are the current regression oracle; dead-code removal requires explicit scoped authorization.

---

## C. Standing invariants

**Existing:**

1. **Deterministic replay.** Identical event log and config yield bit-identical output. Determinism preservation outranks every other consideration in this document.
2. **Causality.** No feature, decision, or emission uses data timestamped after its own event time.
3. **Typed, synchronous event-bus boundaries.**
4. **Backtest / paper / live share core logic.** Mode differences live behind `ExecutionBackend` and nowhere else.
5. **Unknown or degraded conditions reduce exposure, never increase it.**

**Added by this work:**

6. **Single source of truth per fact.** Every number has exactly one owning engine that computes it. Others read it. Independent recomputation is permitted *only* as a declared conservation audit that compares and alerts — never as a second production path.
7. **Alpha-agnosticism.** No engine outside the alpha layer branches on a specific alpha ID, symbol, archetype, or horizon. Configuration selects; code does not know.
8. **Contract-first boundaries.** Every inter-engine payload declares units, timestamp semantics, provenance, and staleness/validity. A field whose unit is not declared does not exist.
9. **Fail-closed gating.** Every gate's behavior on missing, stale, or malformed input is defined in advance and is always the exposure-reducing branch.
10. **Governance off the tick path.** Whether an alpha is live is resolved at composition, never re-evaluated per event.
11. **Schema evolution never breaks replay.** Contracts are versioned; a historical log remains replayable to its original output, with a stated migration path forward.

---

## D. The tick-critical path — defined once

The **tick-critical path** is the synchronous chain from market-data event ingress to order emission: engines 1, 2, 3, 4, 6, 7, 8, 9, 10, in whatever subset a given event actually traverses. Engines 5, 11 (except the kill-switch read), and 12 are **cold**.

This definition governs the latency budget, the no-wall-clock rule, and every `hot-or-cold` field. Do not redefine it locally.

---

## E. The 12 engines — ownership fixed

| # | Engine | Owns | Must not own |
|---|---|---|---|
| 1 | **Market Data** | Wire→canonical translation, resequencing, gap detection and *notification*, validation, persistence, replay. Every emission carries event time, ingest time, sequence, source, quality flags. | Any interpretation of what a quote means. No feature math. Dropping is allowed; dropping without notification is not. |
| 2 | **State / Feature** | Event-time microstructure estimators, horizon-boundary snapshots, declared units, staleness and validity metadata. Pure functions of the event prefix. | Trade decisions, thresholds with trading semantics, any read of position, P&L, or fills. |
| 3 | **Regime** | *Shared* online market-state classification and regime-break hazard, versioned, causal, published once. | Trading thresholds. Alpha-private regime state — three classifiers means three worldviews and no attribution. |
| 4 | **Alpha** | Horizon-anchored forecast only: direction, edge, mechanism, expected half-life, confidence, anchor timestamp. | Sizing, position awareness, cost arithmetic, P&L feedback. Alphas are pure w.r.t. portfolio state. |
| 5 | **Alpha Governance** | Loading, dependency graph, layer validation, lifecycle, promotion/quarantine, evidence, alpha-level budgets. | Anything on the tick path. Decides *whether* an alpha is live, never *what it says*. |
| 6 | **Portfolio Construction** | N forecasts → one desired portfolio: ranking, neutrality, turnover control, target weights. | Actual positions, fills, risk-model estimation. Consumes risk-model outputs; does not produce them. |
| 7 | **Portfolio Accounting** | Sole in-process truth: lots, marks, per-strategy and net positions, realized/unrealized P&L, fill attribution. Owns broker reconciliation and the divergence policy. | Decisions of any kind. Everything reads this; nothing else computes it. |
| 8 | **Risk & Capital** | Exposure limits, sizing, buying power, drawdown escalation, mandatory de-risk. Holds the veto; the veto is monotone — risk may only reduce. | Accounting truth. Consumes positions and marks; never recomputes them. |
| 9 | **Execution Decision** | Policy: approved target delta → executable plan. Netting, urgency, style, participation. | Mechanics. |
| 10 | **Execution Simulation / Routing** | Mechanics: order state machine, fill and cost modeling, session and regulatory constraints, exactly-once submission across restart and reconnect, backtest/paper/live routing, broker adapters. The single mode seam. | Policy. Must not decide size, urgency, or whether to trade. |
| 11 | **Observability & Safety** | Metrics, alerts, health, kill switch, durable operator and session records. Health distinguishes `never-seen` / `stale` / `degraded` / `healthy`. | Trading logic. Kill switches monitor *assumption violations* — latency drift, fill-rate drift, regime break, contract rejection rate, reconciliation divergence — as well as P&L. |
| 12 | **Research, Evaluation & Forensics** | Backtest harnesses, parity reporting, hypothesis testing, post-trade attribution, decay detection, calibration. | Live decisions taken directly. Outputs feed governance and risk through a declared interface and cadence. |

**Cross-cutting layers.** Kernel (`core/`, `bus/`, `kernel/`, `bootstrap.py`) owns contracts, clocks, deterministic sequencing, the state-machine framework, causal orchestration, composition — and **no trading-domain calculation**. CLI (`cli/`) is thin and delegates. Engines are constructed at the composition root and nowhere else; no engine constructs another or resolves a dependency by import-time lookup.

---

## F. Unassigned responsibilities — each needs exactly one owner

None falls cleanly out of §E. For each: name one owning engine, the contract it publishes, and the failure behavior. "Obvious" is not an answer.

1. **Universe definition** — what symbols are in play, as of when, who publishes mid-session changes. Engines 2, 4, 6, 8 must see the same universe at the same event time.
2. **Symbol identity over time** — splits, ticker changes, symbol reuse, corporate actions. Both an accounting-truth problem and a determinism problem: a replayed historical log must resolve identity the way it resolved *then*.
3. **Session and halt state** — pre-open, open, auction, halt, resume, close, after-hours. Straddles 1 (observed), 3 (a regime), 10 (a constraint). Pick the producer.
4. **Broker reconciliation** — cadence, divergence tolerance, action on breach. Must be exposure-reducing and must emit.
5. **Exception propagation** — what happens when an engine raises mid-chain on a synchronous bus. A determinism hazard (partial mutation, order-dependent recovery) and an exposure hazard (a swallowed exception is a gate that silently passed).
6. **Backpressure** — a synchronous bus has no queue; the latency budget is the only control. State what happens when event rate exceeds budget in live.
7. **Contract and schema versioning** — replaying a vN log under vN+1 code. Upgrade-on-read, pinned-code-per-log, or refuse-and-fail-loud. State which parity hashes survive a schema change.

---

## G. Definition of institutional grade — falsifiable criteria

1. **Alpha attachment costs zero core edits.** A new alpha of a different archetype, horizon, and symbol cardinality is added by files under `alphas/` plus config. A required edit to `kernel/`, `bus/`, `core/`, `composition/`, `risk/`, or `execution/` is a defect, not a task.
2. **Every number has one owner**, identifiable from the type alone.
3. **Every boundary is enforced at runtime**, not only in annotations and prose. Malformed payloads fail at the receiving boundary, loudly, with provenance.
4. **Replay is bit-identical under `PYTHONHASHSEED=random`**, with every nondeterminism source enumerated and neutralized.
5. **Every gate is enumerable from a single source**; docs and tests are generated from it.
6. **Degraded mode is tested, not documented.** Every degradation has a test asserting exposure ≤ nominal.
7. **The tick-critical path has a measured latency budget** per engine, with an explicit hot-path allow list.
8. **Research and production share one code path**, seam only at `ExecutionBackend`, proven by a parity test.
9. **Forensics closes a loop** — at least one governance or risk decision driven by a forensics output on a declared cadence.
10. **Net complexity is justified.** Every added element states what it buys and what it deletes; the migration plan reports net delta in modules, public symbols, and branch points. Net increase permitted only for conformance tests, contract definitions, and P0 fixes.

---

## H. Working rules

- **No production code changes.** Writes permitted **only** under `docs/architecture/target/out/` and `tools/arch/`. Any diff to `src/`, `tests/`, `alphas/`, or `configs/` is a protocol violation and must be reverted before the phase output is accepted.
- **Evidence discipline.** `path:symbol` or `path:line` for every material claim, labeled `VERIFIED` (read the code) / `INFERRED` (derived from what you read) / `ASSUMED` (not checkable — goes in the register).
- **Code is truth; documentation is a claim.** Where any document in §B disagrees with source, source wins and the disagreement is a finding.
- **Prior reviews are evidence, not conclusions.** Re-verify anything you rely on.
- **Measure, don't estimate.** Prefer a script under `tools/arch/` whose output is committed as evidence over reading files and reporting numbers.
- **One axis, one engine, or one boundary per turn.** Do not run ahead.
- **Minimal and surgical.** No abstraction without a named concrete problem it removes. Every proposal states what it deletes as well as what it adds. No broad rewrite.
- **Dead-code removal requires explicit scoped authorization.** Flag candidates; do not act.
- **Make the call.** A recommendation and its trade-off, not an options menu. Where genuinely undecidable, say what evidence would decide it.
- **On ambiguity, ask exactly one question and stop.**
- **No status called "working."** Use `specified` / `implemented` / `conformance-tested` / `open defect`.
- **Lead with the result.** No preamble, no restatement, no closing summary.
- **Stop at the phase boundary.** Do not begin the next phase.

---

## I. Alpha-agnosticism and the test-flight payload

**The constraint is the symbol universe, not the alpha count.** Eleven `alpha_id`s are declared across `alphas/**` — seven shipped, two under `alphas/research/`, two templates — but the traded universe is effectively **one symbol**: `APP` appears 36 times in `configs/` + `platform.yaml` against `AAPL` 4 and `SPY` 1, and shipped alpha evidence blocks record cross-symbol attempts producing near-zero fills. So the platform has N > 1 alphas over N ≈ 1 symbol.

This matters for what the fixtures must vary. Adding a twelfth alpha proves nothing the eleventh did not. The untested axes are **symbol cardinality, horizon, and archetype**.

Treat the current live configuration as a **test-flight payload, not a specification**: sufficient to prove the wiring carries something end to end, insufficient to define what the wiring should be.

Before building the fixtures below, check which roles are already filled. `sig_contra_fixture_v1` and `paper_smoke_v1` appear to be fixtures rather than production alphas — read their manifests and state which of the three required roles each covers, so the suite is a promotion of existing assets rather than net-new code (CORE §G.10).

- **No design decision may cite the current alpha's behavior as justification.** If a rule exists only because that alpha needs it, the rule is a defect. If a rule cannot be stated without naming it, the rule is a defect.
- **No alpha identifier, symbol literal, archetype name, or horizon constant outside `alphas/` and configuration.** This is a static check and belongs in the conformance suite.
- **The current alpha is not a correctness oracle.** "APP still produces the same signals" does not validate a boundary change.
- **Replay parity remains the regression oracle and stays.** Parity proves *you did not change what the system does*; it does not prove *what the system does is correct*. Correctness comes from conservation identities, contract conformance, and the fixtures below.

**Required conformance fixtures, none of them the live alpha:**

1. **Null alpha** — emits nothing. Proves stability and level-based conservation under zero signal, against an analytic reference.
2. **Shape-adversarial alpha** — different horizon, cross-sectional rather than single-name, multi-symbol, different cadence, opposite direction convention where permitted. Fails loudly wherever the live alpha's shape is baked into shared code.
3. **Pathological alpha** — NaN, stale timestamps, out-of-universe symbols, duplicate IDs, self-contradictory forecasts. Proves gates are fail-closed, not fail-quiet.

Optional fourth: a **second live-shaped alpha of a different archetype**, to prove per-strategy accounting, attribution, and correlation-aware allocation work at N > 1.

---

## J. Anti-patterns to design out

- God orchestrator accumulating trading logic.
- Alpha-specific branches in shared code; configuration expressed as `if` statements.
- Accounting truth duplicated in risk, or marks computed in two places.
- Policy embedded in mechanics — routing deciding size or urgency.
- Optimistic fill eligibility on passive paths: an order marked fill-eligible off a market event predating when it was live and latency-eligible, while the aggressive path enforces timing correctly. Biased, not noisy.
- Silent degradation: health conflating never-seen with healthy; drops without notification; rejections without emission; swallowed exceptions.
- Contracts defined in documentation with no runtime enforcement.
- Unversioned contracts persisted into a replayable event log.
- Dead packaging extras, undeclared runtime dependencies, modules whose names describe an abandoned intent.
- Legacy-named modules that are live and load-bearing — verify before assuming a name means dead.
- Recompute-as-redundancy: two production paths for one number, differing quietly.

---

## K. Deliverable index

| ID | Deliverable | Phase | Output file |
|---|---|---|---|
| D0 | Comprehension lock | 0 | `out/phase0_comprehension.md` |
| E1 | Determinism budget + parity surface | 1 | `out/phase1_plumbing.md` |
| B | Engine contract sheets + §F resolutions | 2 | `out/phase2_contracts.md` |
| C, D | Flow spec, forbidden-reads matrix, gate ladders | 3 | `out/phase3_flow_gating.md` |
| E2 | Performance budget | 4 | `out/phase4_performance.md` |
| F | Gap table | 5 | `out/phase5_gaps.md` |
| H | Conformance suite spec | 6 | `out/phase6_conformance.md` |
| A, G, I, J, K | Design thesis, migration plan, do-not-change, registers, model findings | 7 | `out/phase7_migration.md` |

---

## L. Phase sequence

```
0  Comprehension lock              Cursor    → HARD STOP
1  Axis A — plumbing substrate     Cursor    → HARD STOP
2  Engine contracts + §F           design    → HARD STOP
3  Axes B/C/D — integration,       design    → HARD STOP ×3
   flow, gating
4  Axis E — performance budget     Cursor    → HARD STOP
5  Gap table                       Cursor    → HARD STOP
6  Conformance suite spec          Cursor    → HARD STOP
7  Migration plan                  Cursor    → HARD STOP — locked before execution
```

Order is load-bearing: the substrate is contract-independent and comes first; the contract sheets are consumed by integration, flow, and gating; the performance budget needs the hot/cold assignment those produce.

---

## M. Definition of done

Complete when every deliverable in §K exists, every §F item has exactly one named owner, every invariant in §C has a named enforcing test, every gap in D-F has a step in D-G, and the assumption register is non-empty and honest. At that point the plan is locked and execution is a separate session with a separate prompt.
