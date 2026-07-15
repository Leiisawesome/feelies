---
name: research-workflow
description: >
  Reproducible experiments and notebook-to-alpha handoff. Use for hypothesis tracking and artifact promotion.
---

# Research Workflow — Experiment Lifecycle

Bridge the gap between exploratory research (notebooks, ad-hoc analysis) and
the production pipeline (backtest engine, feature engine, live execution).
Every insight that reaches capital must pass through a reproducible,
auditable path — no exceptions.

## Core Invariants

Inherits platform invariants 5 (deterministic replay → experiment reproducibility),
8 (layer separation → research/production boundary), 13 (provenance → audit trail).
Additionally:

1. **Promotable** — clear, gated path from notebook exploration to backtest-ready artifact
2. **Disposable** — failed experiments are preserved (for learning) but never promoted

---

## Infrastructure Entry Point

Research execution is supported by the orchestrator's
`Orchestrator.run_research(job: Callable[[], None])`:

1. Assert macro state is READY
2. Transition macro: READY → RESEARCH_MODE (`CMD_RESEARCH`)
3. Execute the caller-supplied `job()` callable
4. On success: RESEARCH_MODE → READY (`JOB_COMPLETE`)
5. On exception: RESEARCH_MODE → DEGRADED (trigger `CRITICAL_ERROR:<ExceptionTypeName>` — parameterized with the exception class name)

Research mode does **not** run the micro-state tick pipeline. The `job`
callable has full access to the feature engine, event log, and other
components but does not submit orders or interact with `OrderRouter`.

For deterministic experiment replay, use `SimulatedClock` (`core/clock.py`).
For configuration provenance, use `Configuration.snapshot()`
(`core/config.py`) to capture a frozen copy of all parameters at
experiment time.

## Experiment Lifecycle

```
Hypothesis → Exploration → Formalization → Backtest → Promotion
```

| Phase | Environment | Output | Gate |
|-------|-------------|--------|------|
| Hypothesis | Document (markdown or notebook cell) | Written hypothesis with falsification criteria | Hypothesis registered in experiment log |
| Exploration | Notebooks (Jupyter) | Plots, preliminary statistics, feature prototypes | Evidence justifies proceeding (not confirmation bias) |
| Formalization | Python modules (not notebooks) | Feature definitions, signal logic, parameter specs | Code passes lint, type-check, unit tests |
| Backtest | Backtest engine | PnL curves, integrity checks, sensitivity analysis | All backtest acceptance criteria met (testing-validation skill) |
| Promotion | Promotion pipeline | Versioned strategy artifact | Full promotion gate (testing-validation skill) |

No phase may be skipped. Exploration without a prior hypothesis is
undirected data mining — flag it as such and apply stricter multiple-testing
corrections.

### Step-2 ordering — harness-level IC gate option (backlog 14)

**Not mandated** — operator decision deferred (Lei). Documented
tradeoff from cycle-1 retrospective
(`docs/research/prompt_pack_07_program_retrospective.md` §3).

After census PROCEED, an implementation-independent step 2b
(census-pinned predicate + forward-return extraction via standalone
instruments, before YAML/test investment) is technically possible.
The binding H8 step-2b statistic never executed the alpha YAML
(`scripts/research/dislocation_lambda_validation_extract.py` /
`_stats.py` pattern).

| Ordering | Integrity properties | Cost |
|----------|---------------------|------|
| **A (current):** implement, then step 2 | 2a sign-goldens precede 2b (attribution cleanliness); census-consistency smoke proves tested object = deployable object; implementation scrutiny catches spec defects pre-outcome (H8 D-1 NaN leak at commit 1) | ~8 sunk commits per step-2 death (H8 Tasks 9–10) |
| **B (proposed):** harness-level IC gate before YAML | Same statistic; dies earlier on magnitude/power failures | Attribution cleanliness deferred: harness sign-golden + post-implementation census-consistency smoke become proof obligations; defects like D-1 found post-IC; two-object drift risk until equivalence proved |

Under either ordering, the census-consistency smoke / stage-0
predicate reproduction is the required equivalence proof. Mitigation
under B: freeze the predicate as a shared artifact (census script
already pinned); require harness sign-golden before 2b; require
census-consistency smoke post-implementation with a pre-registered
mismatch consequence (implementation-correction re-run, N unchanged).

Incident: H8 consumed Tasks 9–10 (8 implementation commits) before
dying at step 2b.

---

## Experiment Tracking

### Experiment Log

Every experiment is registered before execution. The shipped dataclass
(`src/feelies/research/experiment.py`; the module docstring notes that
concrete `ExperimentTracker` implementations are future work) is:

```
ExperimentRecord:
  experiment_id: str
  hypothesis_id: str
  config_snapshot: dict[str, Any]
  result_summary: dict[str, Any]
  timestamp_ns: int
  tags: tuple[str, ...] = ()
  metadata: dict[str, Any] = {}
```

**Not shipped:** the richer record below is the target spec — not yet
implemented. Until it lands, the extra fields are carried in
`tags` / `metadata`:

```
ExperimentRecord (target spec):
  author: str
  created: datetime
  status: "proposed" | "exploring" | "formalizing" | "backtesting" | "promoted" | "failed" | "abandoned"
  hypothesis: str (the structural mechanism being tested)
  falsification: str (what would disprove this)
  data_version: str (hash of input data used)
  code_ref: str (git SHA or branch of experiment code)
  notebook_path: str (relative path to primary notebook)
  outcome: "supported" | "falsified" | "inconclusive" | null
  promoted_to: str | null (strategy artifact ID if promoted)
```

### Research-Stage Status Vocabulary (pre-`alpha_id` documents)

Before an `alpha_id` exists in the lifecycle SM, every research doc
(proposal, analysis note, plausibility card) carries exactly one
`Status:` value from this closed set:

| Status | Meaning |
|--------|---------|
| `hypothesis` | Reformalized claim (microstructure-alpha `research-protocol.md` Phase 0/1); no evidence yet |
| `candidate` | Some supporting evidence; validation incomplete |
| `trap-quadrant` | **Statistically valid but execution-invalid** — the edge exists pre-cost/pre-latency and dies under the realistic execution model. Kept, not deleted: it documents a real phenomenon that cannot be harvested |
| `accepted` | Ready to seek RESEARCH→PAPER via `validate_gate(GateId.RESEARCH_TO_PAPER, ...)` with `ResearchAcceptanceEvidence` (alpha-lifecycle skill) |
| `rejected` | Falsified, or noise-ceiling / cost-floor failure; kept for the trial ledger |

Rules:

- **"working" is banned as a status value** — it conflates the two
  validity axes (statistical vs execution) that `trap-quadrant`
  exists to separate.
- This vocabulary is disjoint from `ExperimentRecord.status`
  (per-experiment granularity, target spec above) and from the
  `AlphaLifecycle` states (post-`alpha_id`; alpha-lifecycle skill).
  Do not mix the three.

### Hypothesis Registry

Hypotheses are tracked independently from experiments. Multiple experiments
may test the same hypothesis from different angles.

The shipped dataclass (`src/feelies/research/hypothesis.py`;
`HypothesisRegistry` is a Protocol stub — concrete implementations are
future work) is:

```
Hypothesis:
  hypothesis_id: str
  description: str
  mechanism: str
  falsification_criteria: str
  status: str = "active"
  metadata: dict[str, Any] = {}
```

**Not shipped:** `related_experiments: list[experiment_id]` and
`confidence: float (0–1)` are target-spec extensions — not yet
implemented; carry them in `metadata` until they land.

A hypothesis is falsified when any registered falsification criterion is met.
A hypothesis is supported (never "proven") when multiple independent
experiments fail to falsify it under varied conditions.

---

## Notebook Conventions

### Structure

Every research notebook follows this structure:

| Section | Content |
|---------|---------|
| Header | Experiment ID, hypothesis, date, author, data version |
| Setup | Imports, data loading, parameter definitions |
| Exploration | Analysis, plots, intermediate findings |
| Results | Summary statistics, key plots, conclusion |
| Decision | Proceed / abandon / revise hypothesis — with justification |

### Rules

1. **No production imports (guideline)** — notebooks import from a `research` package, never from `core`, `engine`, or `execution` packages. Today `feelies.research` ships the CPCV/DSR math plus Protocol stubs; the boundary is not yet enforced by an import linter
2. **No hardcoded paths** — data paths resolved via a config or environment variable
3. **Pinned data versions** — the data version hash is recorded in the notebook header
4. **Seed everything** — all random operations use explicit seeds recorded in the header
5. **No side effects** — notebooks do not write to production databases, submit orders, or modify shared state
6. **Narrative flow** — markdown cells explain reasoning, not just code; a reader unfamiliar with the hypothesis should understand the notebook end-to-end

### Naming Convention

Convention to adopt — no `notebooks/` directory exists in the repo yet;
create it with the first committed notebook:

```
notebooks/
  {YYYY-MM-DD}_{experiment_id}_{short_description}.ipynb
```

Example: `notebooks/2026-03-02_exp042_spread_compression_signal.ipynb`

Old notebooks are never deleted. Failed experiments are kept for reference
and marked with outcome in the experiment log.

---

## Notebook-to-Production Handoff

The most dangerous transition in quantitative research is moving from
"it works in a notebook" to "it works in the engine." This boundary is
managed explicitly.

### What Stays in Notebooks

- Exploratory plots and ad-hoc statistics
- One-off data quality investigations
- Hypothesis brainstorming and preliminary feature prototyping
- Post-hoc analysis of backtest results

### What Gets Formalized

When exploration produces a promising signal or feature, it must be
re-implemented as a proper module before backtesting. The proposal
document that accompanies the handoff instantiates the deliverable
template
([microstructure-alpha/proposal-template.md](../microstructure-alpha/proposal-template.md)),
whose sections map onto the YAML fields below:

| Notebook Artifact | Formalized As | Destination |
|------------------|--------------|-------------|
| Feature prototype (pandas/numpy) | `Sensor` protocol implementation registered via `SensorSpec` (incremental `update(event, state, params) -> SensorReading | None`) | Sensor layer (`feelies.sensors.impl`) |
| Signal logic (threshold + condition) | `HorizonSignal.evaluate(snapshot, regime, params) -> Signal | None` declared inline in a schema-1.1 SIGNAL alpha YAML | `alphas/<alpha_id>/<alpha_id>.alpha.yaml` |
| Entry/exit rules | `Signal.direction`, `Signal.strength`, `Signal.edge_estimate_bps`, `Signal.trend_mechanism`, `Signal.expected_half_life_seconds` | Schema-1.1 SIGNAL alpha (G16) |
| Cross-sectional weights | `PortfolioAlpha.construct(ctx, params) -> SizedPositionIntent` declared inline in a `layer: PORTFOLIO` alpha YAML | `alphas/<alpha_id>/<alpha_id>.alpha.yaml` |
| Cost arithmetic | `cost_arithmetic:` block (G12 — `margin_ratio ≥ 1.5`, reconciles ±0.05 absolute; `alpha/cost_arithmetic.py`) | Alpha YAML |
| Trend mechanism declaration (G16) | `trend_mechanism:` block with family + `expected_half_life_seconds` + `l1_signature_sensors` + `failure_signature` | Alpha YAML (default-required since Workstream E) |
| Regime gate | `regime_gate:` AST-DSL block | Alpha YAML |
| Parameter values | `parameters:` block with valid ranges; per-alpha `promotion: { gate_thresholds: ... }` overrides via F-5 | Alpha YAML |

### Handoff Checklist

Before a notebook artifact is considered formalized:

- [ ] Re-implemented as a standalone module (not copy-pasted from notebook)
- [ ] Unit tests written covering normal, edge, and adversarial cases
- [ ] Incremental computation verified (for features): matches full-recompute
- [ ] No pandas in the hot path — formalized code uses the engine's data structures
- [ ] Parameters externalized to config — no magic numbers in code
- [ ] Type-annotated and linted
- [ ] Reviewed by someone who did not write the notebook

---

## Research Artifact Versioning

### What Is Versioned

| Artifact | Versioning Method | Storage |
|----------|------------------|---------|
| Notebooks | Git (committed with experiment ID in filename) | Repository |
| Experiment log | Append-only structured file (JSON lines) — **planned**; today only the `ExperimentTracker` Protocol interface exists | Repository |
| Hypothesis registry | Append-only structured file — **planned**; today only the `HypothesisRegistry` Protocol interface exists | Repository |
| Sensor implementations (formalized) | `sensor_id` + `sensor_version` declared via `SensorSpec` (`feelies.sensors.impl`) — post-D.2, `FeatureDefinition` survives only as test scaffolding | Repository (feature-engine) |
| Strategy configs | Versioned alongside strategy code | Repository |
| Data snapshots (for reproduction) | Content-addressed hash — **planned**; no dedicated research-artefact store exists yet (`fold_pnl_curves_hash` on `CPCVEvidence` is a content-hash pointer only) | Data store (planned) |
| Backtest results | Keyed to `(strategy_version, data_version, engine_version)` — **planned**; no dedicated backtest-results store module exists yet | Storage layer (planned) |

### Provenance Chain

What ships today: promotion provenance is the F-1 promotion ledger
(append-only JSONL, `src/feelies/alpha/promotion_ledger.py`) plus the
F-2 structured-evidence metadata persisted on each ledger entry
(`src/feelies/alpha/promotion_evidence.py`). There is no
`promoted_artifact` type in the codebase.

**Not shipped:** the consolidated chain below is a design target — not yet
implemented; until it lands, record these fields through the ledger
entry's evidence metadata:

```
promoted_artifact (target spec):
  strategy_version: git SHA
  originating_experiment: experiment_id
  originating_hypothesis: hypothesis_id
  data_version: hash of training/validation data
  feature_versions: dict[feature_id, version]
  backtest_run_id: deterministic hash of backtest config + data
  notebook_path: path to the exploratory notebook
  promotion_date: datetime
  promoter: author who approved promotion
```

This chain is immutable. If any input changes, a new artifact is created.

---

## Multiple Testing & Overfitting Controls

Research environments are overfitting factories. Guard against it.

### Mandatory Controls

| Control | Implementation |
|---------|---------------|
| Pre-registration | Hypothesis and falsification criteria registered before data analysis |
| Out-of-sample holdout | Minimum 30% of data reserved; never touched during exploration |
| Walk-forward validation | No single in-sample/out-of-sample split; rolling windows |
| Bonferroni / BH correction | Applied when testing multiple features or signals from the same dataset |
| Living trial-count ledger | See "Living Trial-Count Ledger" below — every variant tried anywhere increments N |
| Stability requirement | Signal must work across ≥ 2 volatility regimes and ≥ 2 spread regimes (manual stratification procedure: microstructure-alpha `research-protocol.md`, Phase 3 test 3) |
| Transaction cost stress | Must survive at 1.5x realistic transaction costs |
| Lottery ticket detection | If signal works only for a narrow parameter range, classify as fragile |

### Living Trial-Count Ledger

The DSR machinery ships (`research/dsr.py`: `expected_max_sharpe`,
`deflated_sharpe`, `build_dsr_evidence`); what it cannot do is count
your trials for you. Discipline (**Not shipped** as tooling — a
per-workflow markdown/JSONL ledger maintained by hand):

- **Every construction, parameter, or filter variant evaluated
  anywhere in the workflow is one trial** and increments the
  workflow's ledger N — including variants that were discarded,
  looked at once, or "didn't count". Features tested (control above)
  are a subset of N, not all of it.
- N is carried into `build_dsr_evidence(trials_count=N)` — the same
  N, not a per-report subset. `validate_dsr` refuses
  `trials_count == 0` (alpha-lifecycle skill), but only the ledger
  makes the count honest.
- Any Sharpe quoted anywhere is stated **alongside its noise
  ceiling** `E[max Sharpe | null, N]`
  (`expected_max_sharpe(n_trials=N, ...)`; asymptotically
  σ·√(2 ln N)). A Sharpe below the ceiling is indistinguishable from
  selection noise regardless of its p-value.
- The ledger is append-only per workflow; resetting N for a "fresh
  look" at the same data is the exact failure mode this exists to
  prevent.

### Red Flags

Reject or flag experiments that exhibit:
- Sharpe ratio that improves monotonically with in-sample optimization
- Signal that works only on a specific date range without structural justification
- Feature importance dominated by a single highly-tuned parameter
- Backtested alpha that vanishes when latency assumptions change by 2x
- "Worked in the notebook" but fails the formalization checklist

---

## Failure Modes

| Failure | Detection | Response |
|---------|-----------|----------|
| Unregistered experiment | Code review; CI check for experiment ID in notebook header (planned — no such CI check exists yet) | Block promotion; register retroactively |
| Data version mismatch | Hash comparison at notebook load | Alert; re-run with correct data or update experiment record |
| Notebook imports production code | Import linter / CI check (planned — no such CI check exists yet) | Block merge; refactor to research package |
| Promoted artifact without provenance | Artifact validation at promotion gate | Block deployment; reconstruct provenance or re-run |
| Hypothesis drift (changing hypothesis after seeing results) | Experiment log audit (hypothesis registered before results) | Flag experiment; apply stricter validation |
| Orphaned notebooks (no experiment record) | Periodic scan of notebook directory vs experiment log | Register or archive |

---

## Integration Points

See [skill index](../README.md). **Non-obvious edges:** notebook → alpha YAML handoff; experiment provenance before promotion gates.